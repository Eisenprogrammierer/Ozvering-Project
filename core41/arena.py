from __future__ import annotations

import random
from dataclasses import dataclass

from .environment import ArenaEnvironment
from .intel import Intel
from .model import (
    DEFAULT_HEALTH_FACTORS,
    FORCE_FEEDBACK_SHARE,
    HEALTH_FACTOR_MAX,
    HEALTH_MAX,
    OPEN_PRESSURE,
    PRESSURE_PER_WORK,
    RECEIVE_ENERGY_SHARE,
    REST_FORCE,
    REST_REGEN,
    SICKNESS_TREAT_RATE,
    SICKNESS_MAX,
    TREAT_ENERGY_FRACTION,
    WOUND_MAX,
    WOUND_TREAT_RATE,
    INTEL_DAMAGE_BONUS,
    Automaton,
    conversion_report,
    success_probability,
    transmit_sickness,
)
from .types import Action, Observation, Transition, Work, WorkReport

FORMS = ("force", "info")
FRACTIONS = (0.3, 0.7)

CORE_ACTIONS = (
    ("REST", 0.0),
    ("TREAT", TREAT_ENERGY_FRACTION),
    ("force", FRACTIONS[0]),
    ("force", FRACTIONS[1]),
    ("info", FRACTIONS[0]),
    ("info", FRACTIONS[1]),
)

FORCE_WORK_RATIO = 1.0
INFO_COST_FACTOR = 0.60
CHARGE_DAMAGE_BONUS = 0.20
INFO_PRESSURE_PER_WORK = 0.50
PRESSURE_MAX = 30.0

WAIT_ACTION = Action("WAIT", form="wait", duration=1.0)

CAPTURE_RATIO = 1.5
WOUND_HIT_SEVERITY = 0.30
CAPTURE_STREAK = 36
CAPTURE_FRAC = 0.10
L_STEP = 10.0

PROFILE_SKILLS = {
    "CANON": (0.60, 0.00),
    "ZEALOT": (0.68, 0.05),
    "ORTHODOX": (0.55, 0.10),
}

REWARD_ENERGY_COST = 0.6
REWARD_SICKNESS_SELF = 1.0
REWARD_SICKNESS_OPPONENT = 0.5
REWARD_WOUND_SELF = 0.8
REWARD_WOUND_OPPONENT = 0.4
REWARD_TERMINAL_WIN = 1.0
REWARD_TERMINAL_LOSS = -1.0

REWARD_PROFILES = ("legacy", "advantage", "advantage_cost")
REWARD_PROFILE_DEFAULT = "advantage_cost"
REWARD_ADVANTAGE_ENERGY_COST = 0.10


def _energy(agent):
    value = getattr(agent, "energy_pool", None)
    if value is None:
        value = agent.energy
    return float(value)


def _report_dict(report):
    """Привести ``WorkReport``/dict к плоскому dict для арены."""
    if isinstance(report, WorkReport):
        return report.as_dict()
    return dict(report or {})


def _wound_reward(me, before, other, other_before):
    """Вклад устойчивых ран: своя рана — штраф, чужая — награда."""
    if len(before) <= 4 or len(other_before) <= 4:
        return 0.0
    return (
        REWARD_WOUND_SELF
        * (before[4] - me.wound)
        / WOUND_MAX
        + REWARD_WOUND_OPPONENT
        * (other.wound - other_before[4])
        / WOUND_MAX
    )


def _loss(before, now, maximum):
    """Потеря ресурса (только уменьшение, без награды за регенерацию)."""
    return max(0.0, float(before) - float(now)) / max(1.0, maximum)


def reward_delta(me, before, other, other_before, profile=None):
    """Пошаговая награда: F, H, стоимость E, динамика sickness и wound.

    `before`/`other_before` — кортежи
    `(force, energy, health, sickness[, wound])`. Пятый элемент обязателен
    только там, где ведётся учёт острых ран; трёх- и четырёхэлементные
    кортежи легаси-вызовов трактуются как `wound = 0`, поэтому прежняя
    калибровка сохраняется.

    `profile` выбирает семантику (`REWARD_PROFILES`):
    `legacy` — исходная награда; `advantage` — только потери сторон без
    оплаты восстановления; `advantage_cost` — то же плюс цена потраченной
    энергии.
    """
    profile = profile or REWARD_PROFILE_DEFAULT
    if profile not in REWARD_PROFILES:
        raise ValueError("неизвестный профиль награды: %r" % (profile,))
    wound_term = _wound_reward(me, before, other, other_before)
    if profile == "legacy":
        return (
            (me.force - before[0]) / max(1.0, me.max_force)
            + (other_before[0] - other.force) / max(1.0, other.max_force)
            - REWARD_ENERGY_COST
            * (before[1] - _energy(me))
            / max(1.0, me.max_energy)
            + (me.health - before[2]) / max(1.0, me.max_health)
            + (other_before[2] - other.health)
            / max(1.0, other.max_health)
            + REWARD_SICKNESS_SELF
            * (before[3] - me.sickness)
            / SICKNESS_MAX
            + REWARD_SICKNESS_OPPONENT
            * (other.sickness - other_before[3])
            / SICKNESS_MAX
            + wound_term
        )
    reward = (
        _loss(other_before[0], other.force, other.max_force)
        + _loss(other_before[2], other.health, other.max_health)
        - _loss(before[0], me.force, me.max_force)
        - _loss(before[2], me.health, me.max_health)
        + REWARD_SICKNESS_SELF
        * max(0.0, before[3] - me.sickness)
        / SICKNESS_MAX
        + REWARD_SICKNESS_OPPONENT
        * max(0.0, other.sickness - other_before[3])
        / SICKNESS_MAX
    )
    if profile == "advantage_cost":
        reward -= (
            REWARD_ADVANTAGE_ENERGY_COST
            * max(0.0, float(before[1]) - _energy(me))
            / max(1.0, me.max_energy)
        )
    return reward + wound_term


def terminal_reward(winner, side):
    """Терминальный бонус для стороны `rl`/`ai`."""
    if winner in (None, "draw"):
        return 0.0
    won = (winner == "RL" and side == "rl") or (
        winner == "AI" and side == "ai"
    )
    return REWARD_TERMINAL_WIN if won else REWARD_TERMINAL_LOSS


def work_duration(form, fraction):
    """Длительность работы: силовой удар 0.7 — двухтактная подготовка."""
    if str(form) == "force" and float(fraction) >= 0.7:
        return 2.0
    return 1.0


def action_from_index(index):
    name, fraction = CORE_ACTIONS[int(index) % len(CORE_ACTIONS)]
    if name == "REST":
        return Action("REST", form="rest", duration=1.0)
    if name == "TREAT":
        return Action(
            "TREAT",
            form="care",
            fraction=fraction,
            duration=1.0,
        )
    return Action(
        "WORK",
        form=name,
        fraction=fraction,
        duration=work_duration(name, fraction),
    )


def _action_tag(action):
    if action.kind == "WORK":
        return action.form
    if action.kind == "TREAT":
        return "TREAT"
    if action.kind == "WAIT":
        return "WAIT"
    return "REST"


def _default_action(observation):
    return Action("REST", form="rest")


class _RestPolicy:
    def act(self, observation, actions, explore=True):
        return _default_action(observation)

    def observe(self, transition):
        return None

    def state_dict(self):
        return {"kind": "rest"}

    def load_state_dict(self, state):
        return None


def _clamp(value, low, high):
    return max(float(low), min(float(high), float(value)))


def _work_cost_factor(action):
    if action.kind == "WORK" and action.form == "info":
        return INFO_COST_FACTOR
    return 1.0


def work_amount(unit, action):
    """Объём работы с учётом `E`, доли действия и пропускной `F`.

    `F` ограничивает работу за такт; для многотактной подготовки предел
    масштабируется длительностью, потому что работа распределена по тактам.
    """
    if action.kind != "WORK":
        return 0.0
    fraction = _clamp(action.fraction, 0.0, 1.0)
    duration = max(1.0, float(action.duration or 1.0))
    cost_factor = _work_cost_factor(action)
    energy_budget = unit.energy / max(1e-9, cost_factor)
    nominal = fraction * unit.max_energy
    force_budget = max(0.0, unit.force) * duration * FORCE_WORK_RATIO
    return max(0.0, min(energy_budget, nominal, force_budget))


@dataclass
class PendingWork:
    work: Work
    action: Action
    remaining: int


def _unit_delta(before, after):
    return {
        "force": after.force - before.force,
        "energy": after.energy - before.energy,
        "health": after.health - before.health,
        "sickness": after.sickness - before.sickness,
        "wound": after.wound - before.wound,
        "pressure": after.pressure() - before.pressure(),
    }


def _apply_delta(unit, delta):
    unit.force = _clamp(
        unit.force + delta.get("force", 0.0),
        0.0,
        unit.max_force,
    )
    unit.energy = _clamp(
        unit.energy + delta.get("energy", 0.0),
        0.0,
        unit.max_energy,
    )
    unit.health = _clamp(
        unit.health + delta.get("health", 0.0),
        0.0,
        unit.max_health,
    )
    unit.sickness = _clamp(
        unit.sickness + delta.get("sickness", 0.0),
        0.0,
        SICKNESS_MAX,
    )
    unit.wound = _clamp(
        unit.wound + delta.get("wound", 0.0),
        0.0,
        WOUND_MAX,
    )
    unit.state["pressure"] = _clamp(
        unit.pressure() + delta.get("pressure", 0.0),
        0.0,
        PRESSURE_MAX,
    )
    return unit


def _sum_deltas(deltas):
    keys = ("force", "energy", "health", "sickness", "wound", "pressure")
    return {
        key: sum(delta.get(key, 0.0) for delta in deltas)
        for key in keys
    }


def resolve_work(
    attacker_unit,
    defender_unit,
    work,
    rng,
    env_bonus=0.0,
    weak_point=0.0,
    coefficients=None,
):
    """Разрешить работу против снимка защитника, не трогая здоровье атакующего.

    Канонический путь — `_receive_channel(attacker, defender, work,
    world)`: та же функция, что зарегистрирована в `Automaton.handlers`,
    но вызванная явно. `_ResolveWorld` копит изменения, `flush` применяет
    их к клонам, а `resolve_pair` раскладывает дельты по сторонам.
    Обработчик возвращает `WorkReport`, который адаптер переводит в поля,
    ожидаемые `ArenaMatch` (`damage/health/wound/gain/chance/was_open/
    form/revealed/duration/infection`).
    """
    if not defender_unit.can_receive(work.form):
        return {
            "accepted": False,
            "success": False,
            "energy": 0.0,
            "force": 0.0,
            "pressure": 0.0,
        }
    was_open = defender_unit.is_open()
    chance = success_probability(
        attacker_unit,
        defender_unit,
        work,
        was_open,
        env_bonus=env_bonus,
        weak_point=weak_point,
        coefficients=coefficients,
    )
    world = _ResolveWorld(
        rng=rng,
        chance=chance,
        was_open=was_open,
        weak_point=weak_point,
        env_bonus=env_bonus,
        attacker=attacker_unit,
        defender=defender_unit,
        work=work,
    )
    # ``Automaton.receive`` без ``handlers`` (clone_for_tick их стирает)
    # ушёл бы в ``default_receive``. Для резолвера арены канонический
    # обработчик известен явно — ``_receive_channel``. Это тот же путь,
    # что зарегистрирован в ``ArenaAgent.unit.handlers``.
    report = _receive_channel(
        defender_unit, work, attacker_unit, world, work.form
    )
    world.flush(attacker_unit, defender_unit)
    report_dict = _report_dict(report)
    form = work.form
    pressure_rate = (
        INFO_PRESSURE_PER_WORK if form == "info" else PRESSURE_PER_WORK
    )
    pressure = float(report_dict.get("pressure", work.amount * pressure_rate))
    success = bool(report_dict.get("success", False))
    was_info = form == "info"
    return {
        "accepted": bool(report_dict.get("accepted", success)),
        "success": success,
        "energy": float(report_dict.get("energy", 0.0)),
        "force": float(report_dict.get("force", 0.0)),
        "damage": float(
            report_dict.get("damage", report_dict.get("force", 0.0))
        ),
        "health": float(report_dict.get("health", 0.0)),
        "wound": float(report_dict.get("wound", 0.0)),
        "gain": float(report_dict.get("gain", 0.0)),
        "pressure": pressure,
        "chance": chance,
        "was_open": was_open,
        "form": form,
        "revealed": bool(was_info and success),
        "duration": float(work.duration),
        "infection": float(report_dict.get("infection", 0.0)),
    }


class _ResolveWorld:
    """Минимальный `world` для `_receive_channel` из арены.

    Детерминированный обработчик не бросает кубик сам; шанс и бросок
    живут в резолвере. Этот объект передаёт обработчику уже посчитанный
    шанс, открытость окна, `rng` и `work`, а изменения, которые хочет
    внести обработчик (`force`, `damage`, `health`, `wound`, `gain`,
    `infection`, `pressure`), копит и затем применяет к автоматам через
    `flush`, сохраняя прежний контракт `resolve_work` (мутация
    переданных единиц).

    Обработчик **не должен** применять урон к ``target`` напрямую:
    иначе эффект удвоится (один раз — в обработчике, второй — во
    ``flush``). Канонические обработчики ``_receive_channel`` копят
    в ``world``, а ``flush`` применяет.
    """

    def __init__(
        self,
        rng,
        chance,
        was_open,
        weak_point=0.0,
        env_bonus=0.0,
        attacker=None,
        defender=None,
        work=None,
    ):
        self.rng = rng
        self.chance = float(chance)
        self.was_open = bool(was_open)
        self.weak_point = float(weak_point)
        self.env_bonus = float(env_bonus)
        self.attacker = attacker
        self.defender = defender
        self.work = work
        self.force = 0.0
        self.damage = 0.0
        self.health = 0.0
        self.wound = 0.0
        self.gain = 0.0
        self.infection = 0.0
        self.pressure = 0.0
        self.extra = {}

    def set(self, key, value):
        self.extra[key] = value
        return value

    def add_force_damage(self, damage):
        damage = max(0.0, float(damage))
        self.damage += damage
        self.force += damage
        return damage

    def add_gain(self, gain):
        gain = max(0.0, float(gain))
        self.gain += gain
        return gain

    def add_wound(self, severity):
        severity = max(0.0, float(severity))
        if severity > self.wound:
            self.wound = severity
        return self.wound

    def add_infection(self, severity):
        severity = max(0.0, float(severity))
        self.infection = max(self.infection, severity)
        return self.infection

    def add_pressure(self, pressure):
        pressure = max(0.0, float(pressure))
        self.pressure += pressure
        return self.pressure

    def flush(self, attacker_unit, defender_unit):
        if self.force > 0.0:
            _absorbed, _overflow, health_damage = (
                defender_unit.apply_force_damage(self.force)
            )
            self.health += float(health_damage)
        elif self.health > 0.0:
            defender_unit.health = max(
                0.0, defender_unit.health - self.health
            )
        if self.wound > 0.0:
            defender_unit.injure(self.wound)
        if self.infection > 0.0:
            defender_unit.infect(self.infection)
        if self.gain > 0.0:
            attacker_unit.force = min(
                attacker_unit.max_force,
                attacker_unit.force + self.gain,
            )
        if self.pressure > 0.0:
            defender_unit.state["pressure"] = min(
                PRESSURE_MAX,
                defender_unit.pressure() + self.pressure,
            )


def _rest_effect(agent):
    agent.unit.energy = min(
        agent.unit.max_energy,
        agent.unit.energy + REST_REGEN,
    )
    agent.unit.force = min(
        agent.unit.max_force,
        agent.unit.force + REST_FORCE,
    )
    agent.unit.state["pressure"] = agent.unit.pressure() * 0.5
    return {
        "kind": "rest",
        "spent": 0.0,
        "success": True,
        "damage": 0.0,
        "form": "REST",
    }


def _prepare_action(agent, action):
    """Самостоятельная часть действия: оплата, отдых, лечение, подготовка.

    Удар по противнику здесь не разрешается: `resolve_pair` делает это по
    общему снимку такта. Возвращает план с полями `kind`, `action`, `work`,
    `spent`, `resting`, `result`.
    """
    action = action or WAIT_ACTION
    if agent.pending is not None:
        pending = agent.pending
        work = agent.advance_pending()
        agent.last_action = pending.action
        if work is None:
            result = {
                "kind": "wait",
                "spent": 0.0,
                "success": True,
                "damage": 0.0,
                "form": pending.work.form,
                "duration": float(pending.work.duration),
            }
            return {
                "kind": "wait",
                "action": pending.action,
                "work": None,
                "spent": 0.0,
                "resting": False,
                "result": result,
            }
        return {
            "kind": "work",
            "action": pending.action,
            "work": work,
            "spent": float(work.amount),
            "resting": False,
            "result": None,
        }
    agent.last_action = action
    if action.kind == "TREAT":
        amount = min(
            agent.unit.energy,
            _clamp(action.fraction, 0.0, 1.0)
            * agent.unit.max_energy,
        )
        agent.unit.energy = max(0.0, agent.unit.energy - amount)
        if amount > 0.0:
            if agent.unit.sickness > 0.0:
                agent.unit.treat(SICKNESS_TREAT_RATE)
            if agent.unit.wound > 0.0:
                agent.unit.treat_wound(WOUND_TREAT_RATE)
        result = {
            "kind": "treat",
            "spent": amount,
            "success": True,
            "damage": 0.0,
            "form": "care",
            "treated": float(agent.unit.sickness),
            "wound": float(agent.unit.wound),
        }
        return {
            "kind": "treat",
            "action": action,
            "work": None,
            "spent": amount,
            "resting": False,
            "result": result,
        }
    if action.kind == "WAIT":
        return {
            "kind": "wait",
            "action": action,
            "work": None,
            "spent": 0.0,
            "resting": False,
            "result": {
                "kind": "wait",
                "spent": 0.0,
                "success": True,
                "damage": 0.0,
                "form": "wait",
            },
        }
    if action.kind == "REST":
        result = _rest_effect(agent)
        return {
            "kind": "rest",
            "action": action,
            "work": None,
            "spent": 0.0,
            "resting": True,
            "result": result,
        }
    if action.kind != "WORK":
        result = _rest_effect(agent)
        return {
            "kind": "rest",
            "action": action,
            "work": None,
            "spent": 0.0,
            "resting": True,
            "result": result,
        }
    amount = work_amount(agent.unit, action)
    if amount <= 0.0:
        result = _rest_effect(agent)
        return {
            "kind": "rest",
            "action": action,
            "work": None,
            "spent": 0.0,
            "resting": True,
            "result": result,
        }
    cost_factor = _work_cost_factor(action)
    cost = amount * cost_factor
    agent.unit.energy = max(0.0, agent.unit.energy - cost)
    duration = max(
        1.0,
        float(action.duration or 1.0),
        work_duration(action.form, action.fraction),
    )
    work = Work(
        amount=amount,
        form=action.form or "force",
        duration=duration,
    )
    if work.duration > 1.0:
        agent.pending = PendingWork(
            work=work,
            action=action,
            remaining=max(1, int(work.duration) - 1),
        )
        result = {
            "kind": "charge",
            "spent": amount,
            "cost": cost,
            "success": True,
            "damage": 0.0,
            "form": work.form,
            "duration": float(work.duration),
        }
        return {
            "kind": "charge",
            "action": action,
            "work": None,
            "spent": amount,
            "cost": cost,
            "duration": float(work.duration),
            "resting": False,
            "result": result,
        }
    return {
        "kind": "work",
        "action": action,
        "work": work,
        "spent": amount,
        "cost": cost,
        "duration": float(work.duration),
        "resting": False,
        "result": None,
    }


def _plan_events(side, agent, plan, result):
    events = []
    if plan.get("kind") == "charge":
        events.append(
            {
                "kind": "charge",
                "frm": side,
                "form": str(plan["action"].form),
                "duration": float(plan.get("duration", 1.0)),
                "work": float(plan.get("spent", 0.0)),
            }
        )
    elif plan.get("kind") == "work":
        events.extend(_transfer_event(side, agent, result))
    return events


def resolve_pair(left, right, left_action, right_action, rng, env=None):
    """Одновременный такт: оба действия считаются от снимка до разрешения.

    `left`/`right` — `ArenaAgent`. Возвращает планы и результаты сторон.
    Эффекты применяются после того, как оба удара разрешены на клонах,
    поэтому первый ход не даёт преимущества, а убитый успевает ударить.
    """
    snap_left = left.unit.clone_for_tick()
    snap_right = right.unit.clone_for_tick()
    left_plan = _prepare_action(left, left_action)
    right_plan = _prepare_action(right, right_action)

    tick_left = left.unit.clone_for_tick()
    tick_right = right.unit.clone_for_tick()
    tick_left.tick_health(resting=left_plan["resting"])
    tick_right.tick_health(resting=right_plan["resting"])
    left_deltas = [_unit_delta(left.unit, tick_left)]
    right_deltas = [_unit_delta(right.unit, tick_right)]

    env_bonus = 0.0
    if env is not None:
        env_bonus = float(env.work_bonus())

    left_result = left_plan["result"]
    right_result = right_plan["result"]
    left_reveal = False
    right_reveal = False
    for side in ("left", "right"):
        plan = left_plan if side == "left" else right_plan
        work = plan.get("work")
        if work is None:
            continue
        attacker = left if side == "left" else right
        defender = right if side == "left" else left
        attacker_snap = snap_left if side == "left" else snap_right
        defender_snap = snap_right if side == "left" else snap_left
        probe_attacker = attacker_snap.clone_for_tick()
        probe_defender = defender_snap.clone_for_tick()
        result = resolve_work(
            probe_attacker,
            probe_defender,
            work,
            rng,
            env_bonus=env_bonus,
            weak_point=float(attacker.intel.weak_point),
        )
        result["kind"] = "work"
        result["spent"] = float(work.amount)
        result["cost"] = float(plan.get("cost", work.amount))
        result["form"] = work.form
        if side == "left":
            left_result = result
            left_deltas.append(_unit_delta(snap_left, probe_attacker))
            right_deltas.append(_unit_delta(snap_right, probe_defender))
            left_reveal = bool(
                work.form == "info" and result.get("success")
            )
        else:
            right_result = result
            right_deltas.append(_unit_delta(snap_right, probe_attacker))
            left_deltas.append(_unit_delta(snap_left, probe_defender))
            right_reveal = bool(
                work.form == "info" and result.get("success")
            )
        if env is not None:
            env.ingest(work.amount, getattr(work, "form", "force"))

    _apply_delta(left.unit, _sum_deltas(left_deltas))
    _apply_delta(right.unit, _sum_deltas(right_deltas))
    left.unit.decay_pressure()
    right.unit.decay_pressure()

    if left_plan["kind"] == "work":
        if left_plan["work"].form == "info":
            if left_reveal:
                left.intel.reveal(right.unit)
            else:
                left.intel.note_failure()
        elif left_result and left_result.get("success"):
            if left.intel.weak_point > 0.0:
                left.intel.consume_weak_point()
    if right_plan["kind"] == "work":
        if right_plan["work"].form == "info":
            if right_reveal:
                right.intel.reveal(left.unit)
            else:
                right.intel.note_failure()
        elif right_result and right_result.get("success"):
            if right.intel.weak_point > 0.0:
                right.intel.consume_weak_point()

    for agent, plan in ((left, left_plan), (right, right_plan)):
        was_info = (
            plan.get("kind") == "work"
            and plan.get("work") is not None
            and plan["work"].form == "info"
        )
        if not was_info:
            agent.intel.decay()

    for agent, plan, result in (
        (left, left_plan, left_result),
        (right, right_plan, right_result),
    ):
        if result is None:
            result = {
                "kind": plan["kind"],
                "spent": 0.0,
                "success": False,
                "damage": 0.0,
            }
        agent.last_action = plan["action"]
        agent.last_act = _action_tag(plan["action"])
        agent.last_work = float(result.get("spent", 0.0))
        agent.rest_units = max(
            0.0, agent.rest_ceiling - agent.force
        )
    return left_plan, right_plan, left_result, right_result


from .arena_runtime import (  # noqa: E402
    ArenaAgent,
    ArenaMatch,
    _receive_channel,
    _transfer_event,
    check_capture,
    run_duel_tick,
)
