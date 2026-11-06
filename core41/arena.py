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
from .types import Action, Observation, Transition, Work

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

# A9: `F` — пропускная способность, а не только запас прочности. Работа за
# такт не может превысить `F * duration`; при полной силе это не связывает
# действие 0.7, а после потери силы — ограничивает удар.
FORCE_WORK_RATIO = 1.0
# A9: разведка дешевле силовой работы при том же объёме.
INFO_COST_FACTOR = 0.60
# A9: сильный удар — двухтактная подготовка. Противник видит её и успевает
# ответить; компенсация — чуть больший урон при завершении.
CHARGE_DAMAGE_BONUS = 0.20
# Разведка давит на цель сильнее обычной работы: она вскрывает стойку.
INFO_PRESSURE_PER_WORK = 0.50
PRESSURE_MAX = 30.0

WAIT_ACTION = Action("WAIT", form="wait", duration=1.0)

CAPTURE_RATIO = 1.5
# A2: доля тяжести раны за каждый процент максимального здоровья,
# выжженного переполнением силы при успешном ударе (максимум WOUND_MAX).
WOUND_HIT_SEVERITY = 0.30
# 36 тактов удержания — калибровка 2026-11-03 (N=200, env on/off):
# дешёвая разведка A9 позволяла слишком быстро накопить энергетическое
# доминирование, поэтому серия удлинена и захват снова вторичен.
CAPTURE_STREAK = 36
CAPTURE_FRAC = 0.10
L_STEP = 10.0

PROFILE_SKILLS = {
    "CANON": (0.60, 0.00),
    "ZEALOT": (0.68, 0.05),
    "ORTHODOX": (0.55, 0.10),
}

# Награда арены. Единицы — доли максимумов соответствующей шкалы, поэтому
# шаг награды сравним между `F`, `E`, `H` и `sickness`.
REWARD_ENERGY_COST = 0.6
REWARD_SICKNESS_SELF = 1.0
REWARD_SICKNESS_OPPONENT = 0.5
REWARD_WOUND_SELF = 0.8
REWARD_WOUND_OPPONENT = 0.4
REWARD_TERMINAL_WIN = 1.0
REWARD_TERMINAL_LOSS = -1.0

# Профили награды. `legacy` — исходная смесь: оплачивает потраченную
# энергию и начисляет за восстановление E/F/H, из-за чего отдых может
# «фармить» награду. `advantage` — только реальный урон/потери сторон,
# без награды за регенерацию. `advantage_cost` дополнительно списывает
# потраченную (не восстановленную) энергию; это профиль по умолчанию.
REWARD_PROFILES = ("legacy", "advantage", "advantage_cost")
REWARD_PROFILE_DEFAULT = "advantage_cost"
REWARD_ADVANTAGE_ENERGY_COST = 0.10


def _energy(agent):
    value = getattr(agent, "energy_pool", None)
    if value is None:
        value = agent.energy
    return float(value)


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
):
    """Разрешить работу против снимка защитника, не трогая здоровье атакующего.

    Функция меняет переданные автоматы (обычно клоны снимка такта):
    энергия/давление/рана цели и прирост силы атакующего. Штраф здоровья
    атакующего (`tick_health`) накладывается отдельно, чтобы оба действия
    такта считались от одного снимка.
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
    )
    form = work.form
    pressure_rate = (
        INFO_PRESSURE_PER_WORK if form == "info" else PRESSURE_PER_WORK
    )
    pressure = work.amount * pressure_rate
    success = rng.random() < chance
    damage = 0.0
    gain = 0.0
    health_damage = 0.0
    wound_severity = 0.0
    infection = 0.0
    if form == "info":
        defender_unit.state["pressure"] = min(
            PRESSURE_MAX,
            defender_unit.pressure() + pressure,
        )
        return {
            "accepted": True,
            "success": bool(success),
            "energy": 0.0,
            "force": 0.0,
            "damage": 0.0,
            "health": 0.0,
            "wound": 0.0,
            "gain": 0.0,
            "pressure": pressure,
            "chance": chance,
            "was_open": was_open,
            "form": form,
            "revealed": bool(success),
            "duration": float(work.duration),
        }
    defender_unit.energy = min(
        defender_unit.max_energy,
        defender_unit.energy + work.amount * 0.12,
    )
    defender_unit.state["pressure"] = min(
        PRESSURE_MAX,
        defender_unit.pressure() + pressure,
    )
    if success:
        charge = 1.0 + CHARGE_DAMAGE_BONUS * max(
            0.0, float(work.duration) - 1.0
        )
        # A9: удар по свежей слабой точке, найденной разведкой, наносит
        # больше урона. Бонус действует только на `force`.
        exploit = 1.0 + INTEL_DAMAGE_BONUS * min(
            1.0, max(0.0, float(weak_point))
        )
        damage = max(
            0.0,
            work.amount
            * (0.55 - 0.30 * defender_unit.resistance(form))
            * charge
            * exploit,
        )
        _absorbed, _overflow, health_damage = (
            defender_unit.apply_force_damage(damage)
        )
        gain = min(
            attacker_unit.max_force - attacker_unit.force,
            damage * 0.20,
        )
        attacker_unit.force += max(0.0, gain)
        if health_damage > 0.0:
            wound_severity = min(
                WOUND_MAX,
                WOUND_HIT_SEVERITY * health_damage
                / max(1.0, defender_unit.max_health),
            )
            if wound_severity > 0.0:
                defender_unit.injure(wound_severity)
        infection = transmit_sickness(
            attacker_unit, defender_unit, rng, form
        )
    return {
        "accepted": True,
        "success": bool(success),
        "energy": work.amount * 0.12,
        "force": damage,
        "damage": damage,
        "health": health_damage,
        "wound": wound_severity,
        "gain": gain,
        "pressure": pressure,
        "chance": chance,
        "was_open": was_open,
        "form": form,
        "revealed": False,
        "duration": float(work.duration),
        "infection": infection,
    }


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

    # A9: без новой разведки знания стареют. Успешная или проваленная
    # разведка уже обновила `age`/`confidence`, поэтому шаг старения к ней
    # не применяется.
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


def _transfer_event(side, agent, result):
    events = []
    if result.get("kind") == "work" and result.get("spent", 0.0) > 0:
        events.append(
            {
                "kind": "transfer",
                "frm": side,
                "work": float(result.get("spent", 0.0)),
                "hit": bool(result.get("success", False)),
                "gained": int(max(0.0, result.get("gain", 0.0))),
                "type": str(result.get("form", agent.defense)),
            }
        )
    infection = float(result.get("infection", 0.0))
    if infection > 0.0:
        events.append(
            {
                "kind": "infection",
                "frm": side,
                "amount": infection,
            }
        )
    return events


class ArenaAgent:
    def __init__(
        self,
        agent_id,
        policy=None,
        profile="CANON",
        seed=0,
        force=100.0,
        energy=100.0,
        max_force=100.0,
        max_energy=100.0,
        health=HEALTH_MAX,
        max_health=HEALTH_MAX,
        health_factors=None,
        sickness=0.0,
        wound=0.0,
        fog=True,
    ):
        self.id = str(agent_id)
        self.profile = str(profile)
        self.seed = int(seed)
        self.rng = random.Random(seed)
        self.policy = policy if policy is not None else _RestPolicy()
        # A9: туман наблюдаемости. `False` — точное знание (легаси-срез и
        # калибровочное плечо без тумана).
        self.fog = bool(fog)
        # A9: знания о скрытом состоянии противника и подготовка.
        self.intel = Intel()
        self.pending = None
        skill, authority = PROFILE_SKILLS.get(
            self.profile, PROFILE_SKILLS["CANON"]
        )
        factors = dict(DEFAULT_HEALTH_FACTORS)
        if health_factors:
            factors.update(health_factors)
        self.unit = Automaton(
            id=self.id,
            force=float(force),
            energy=float(energy),
            max_force=float(max_force),
            max_energy=float(max_energy),
            health=float(health),
            max_health=float(max_health),
            health_factors=factors,
            sickness=max(0.0, min(SICKNESS_MAX, float(sickness))),
            wound=max(0.0, min(WOUND_MAX, float(wound))),
            inputs=FORMS,
            outputs=FORMS,
            skills={
                "force": float(skill),
                "info": max(0.0, 1.0 - float(skill)),
            },
            authority=float(authority),
        )
        self.unit.handlers["force"] = self._force_handler
        self.unit.handlers["info"] = self._info_handler
        self.last_action = Action("REST", form="rest")
        self.last_act = "REST"
        self.last_work = 0.0
        self.rest_units = 0.0
        self.p = 1.0
        self._last_observation = None
        self._last_action = None
        self._last_opponent = None

    @property
    def force(self):
        return float(self.unit.force)

    @force.setter
    def force(self, value):
        self.unit.force = max(0.0, float(value))

    @property
    def energy_pool(self):
        return float(self.unit.energy)

    @energy_pool.setter
    def energy_pool(self, value):
        self.unit.energy = max(0.0, float(value))

    @property
    def rest_ceiling(self):
        return float(self.unit.max_force)

    @property
    def max_force(self):
        return float(self.unit.max_force)

    @property
    def max_energy(self):
        return float(self.unit.max_energy)

    @property
    def energy_ratio(self):
        return self.energy_pool / max(1.0, self.max_energy)

    @property
    def health(self):
        return float(self.unit.health)

    @health.setter
    def health(self, value):
        self.unit.health = max(0.0, min(self.unit.max_health, float(value)))

    @property
    def max_health(self):
        return float(self.unit.max_health)

    @property
    def health_ratio(self):
        return self.unit.health_ratio

    @property
    def is_dead(self):
        return self.unit.is_dead

    @property
    def sickness(self):
        return float(self.unit.sickness)

    @sickness.setter
    def sickness(self, value):
        self.unit.sickness = max(
            0.0, min(SICKNESS_MAX, float(value))
        )

    @property
    def is_sick(self):
        return self.unit.is_sick

    @property
    def wound(self):
        return float(self.unit.wound)

    @wound.setter
    def wound(self, value):
        self.unit.wound = max(0.0, min(WOUND_MAX, float(value)))

    @property
    def is_wounded(self):
        return self.unit.is_wounded

    def infect(self, severity):
        return self.unit.infect(severity)

    def treat(self, amount):
        return self.unit.treat(amount)

    def injure(self, severity):
        return self.unit.injure(severity)

    def treat_wound(self, amount):
        return self.unit.treat_wound(amount)

    def set_health_factor(self, name, value):
        self.unit.health_factors[str(name)] = max(
            0.0, min(HEALTH_FACTOR_MAX, float(value))
        )
        return self.unit.health_factors[str(name)]

    def set_health_factors(self, factors):
        for name, value in dict(factors).items():
            self.set_health_factor(name, value)

    @property
    def regen(self):
        return int(REST_REGEN)

    @property
    def defense(self):
        if self.last_action.kind in ("WORK", "TREAT"):
            return self.last_action.form
        return "force"

    @property
    def in_open(self):
        return bool(self.unit.is_open())

    @property
    def w_adopt(self):
        return float(self.unit.pressure())

    @property
    def open_timer(self):
        return int(max(0.0, self.unit.pressure()))

    def schmitt_on(self):
        return OPEN_PRESSURE

    @property
    def Q(self):
        table = getattr(self.policy, "table", None)
        return table if isinstance(table, dict) else {}

    def set_profile(self, profile):
        profile = str(profile)
        if profile not in PROFILE_SKILLS:
            return False
        self.profile = profile
        skill, authority = PROFILE_SKILLS[profile]
        self.unit.skills = {
            "force": float(skill),
            "info": max(0.0, 1.0 - float(skill)),
        }
        self.unit.authority = float(authority)
        return True

    def reset_state(self, seed=None):
        if seed is not None:
            self.seed = int(seed)
            self.rng = random.Random(self.seed)
        self.unit.force = self.unit.max_force
        self.unit.energy = self.unit.max_energy
        self.unit.health = self.unit.max_health
        self.unit.sickness = 0.0
        self.unit.wound = 0.0
        self.unit.state["pressure"] = 0.0
        self.last_action = Action("REST", form="rest")
        self.last_act = "REST"
        self.last_work = 0.0
        self.rest_units = 0.0
        self.pending = None
        self.intel = Intel()
        self._last_observation = None
        self._last_action = None

    def condition_state(self):
        """Снимок состояния здоровья.

        `wound` включается только когда он ненулевой: легаси-снимки
        `(health, sickness)` остаются каноничными для здоровых агентов,
        а острые раны переносятся между матчами и сохранениями.
        """
        state = {
            "health": float(self.health),
            "sickness": float(self.sickness),
        }
        if self.wound > 0.0:
            state["wound"] = float(self.wound)
        return state

    def load_condition(self, state):
        state = state or {}
        if state.get("health") is not None:
            self.unit.health = max(
                0.0,
                min(self.unit.max_health, float(state["health"])),
            )
        if state.get("sickness") is not None:
            self.sickness = float(state["sickness"])
        if state.get("wound") is not None:
            self.wound = float(state["wound"])
        return self.condition_state()

    def actions(self):
        # A9: пока идёт подготовка, единственное легальное действие —
        # `WAIT`. Это не отдых: подготовка уже оплачена и должна завершиться.
        if self.pending is not None:
            return (WAIT_ACTION,)
        # `REST` — не no-op: он восстанавливает E/F/здоровье и снимает
        # болезнь. Если восстанавливать нечего, действие не предлагается:
        # иначе две полностью отдохнувшие стороны могут бесконечно
        # выбирать REST, и self-play сходится к 100% таймаутов.
        actions = []
        if self.needs_recovery():
            actions.append(action_from_index(0))
        if self.sickness > 0.0 or self.wound > 0.0:
            actions.append(action_from_index(1))
        for index in range(2, len(CORE_ACTIONS)):
            actions.append(action_from_index(index))
        return tuple(actions)

    def needs_recovery(self):
        """Есть ли смысл в REST: неполная энергия/сила/здоровье или болезнь."""
        return bool(
            self.energy_pool < self.max_energy - 1e-9
            or self.force < self.max_force - 1e-9
            or self.health < self.max_health - 1e-9
            or self.sickness > 0.0
            or self.wound > 0.0
        )

    def advance_pending(self):
        """Продвинуть многотактную работу; вернуть `Work` в такт удара."""
        pending = self.pending
        if pending is None:
            return None
        pending.remaining -= 1
        if pending.remaining > 0:
            return None
        self.pending = None
        return pending.work

    def observe(self, opponent):
        other = opponent.unit if hasattr(opponent, "unit") else opponent
        forms = tuple(
            form for form in self.unit.outputs if other.can_receive(form)
        )
        if not forms:
            forms = ("force",)
        # A9: туман скрывает внутреннее состояние (`E/H/sickness/wound`),
        # но не внешнюю стойку: силу, давление, открытость, подготовку.
        if self.fog:
            opponent_energy = self.intel.estimate(
                "energy", other.energy
            )
            opponent_health = self.intel.estimate(
                "health", other.health
            )
            opponent_sickness = self.intel.estimate(
                "sickness", other.sickness
            )
            opponent_wound = self.intel.estimate(
                "wound", other.wound
            )
        else:
            opponent_energy = float(other.energy)
            opponent_health = float(other.health)
            opponent_sickness = float(other.sickness)
            opponent_wound = float(other.wound)
        pending = getattr(opponent, "pending", None)
        pending_action = pending.action if pending is not None else None
        observation = Observation(
            self_force=self.force,
            self_energy=self.energy_pool,
            self_max_force=self.unit.max_force,
            self_max_energy=self.unit.max_energy,
            opponent_force=float(other.force),
            opponent_energy=opponent_energy,
            opponent_max_force=float(other.max_force),
            opponent_max_energy=float(other.max_energy),
            opponent_pressure=float(other.pressure()),
            opponent_open=bool(other.is_open()),
            time=float(getattr(self, "_time", 0.0)),
            forms=forms,
            opponent_defense=(
                getattr(opponent, "defense", "")
                if hasattr(opponent, "defense")
                else ""
            ),
            self_health=self.health,
            self_max_health=self.max_health,
            self_sickness=self.sickness,
            opponent_health=opponent_health,
            opponent_max_health=float(other.max_health),
            opponent_sickness=opponent_sickness,
            self_wound=self.wound,
            opponent_wound=opponent_wound,
            env_pressure=float(getattr(self, "_env_pressure", 0.0)),
            env_season=float(getattr(self, "_env_season", 1.0)),
            env_window=float(getattr(self, "_env_window", 0.0)),
            opponent_confidence=(
                float(self.intel.confidence) if self.fog else 1.0
            ),
            opponent_weak_point=(
                float(self.intel.weak_point) if self.fog else 0.0
            ),
            self_busy=1.0 if self.pending is not None else 0.0,
            opponent_busy=1.0 if pending is not None else 0.0,
            opponent_pending_form=(
                str(pending_action.form) if pending_action else ""
            ),
            opponent_pending_fraction=(
                float(pending_action.fraction) if pending_action else 0.0
            ),
        )
        return observation

    def choose_action(self, opponent, explore=True):
        observation = self.observe(opponent)
        action = self.policy.act(observation, self.actions(), explore=explore)
        self.record_action(action, opponent, observation)
        return action, observation

    def record_action(self, action, opponent=None, observation=None):
        self._last_observation = (
            observation if observation is not None else self.observe(opponent)
        )
        self._last_action = action
        self._last_opponent = opponent
        return action

    def learn(
        self,
        reward,
        next_observation,
        done,
        opponent=None,
        opponent_action=None,
    ):
        if self._last_observation is None or self._last_action is None:
            return
        other = opponent if opponent is not None else self._last_opponent
        next_actions = self.actions()
        if other is not None:
            next_actions = tuple(
                action
                for action in self.actions()
                if action.kind in ("REST", "WAIT")
                or other.unit.can_receive(action.form)
            )
        info = {}
        if opponent_action is not None:
            # A9: модель противника обновляется по действию, которое он
            # реально выбрал в этом такте. Передаётся через `info`, чтобы
            # `Transition` остался неизменным контрактом.
            info["opponent_action"] = opponent_action
        transition = Transition(
            observation=self._last_observation,
            action=self._last_action,
            reward=float(reward),
            next_observation=next_observation,
            done=bool(done),
            next_actions=next_actions,
            info=info,
        )
        self.policy.observe(transition)
        self._last_observation = None
        self._last_action = None
        self._last_opponent = None

    def _force_handler(self, target, work, source, world):
        return self._receive_work(target, work, source, world, "force")

    def _info_handler(self, target, work, source, world):
        return self._receive_work(target, work, source, world, "info")

    def _receive_work(self, target, work, source, world, form):
        if source is None:
            return target.default_receive(work)
        if not target.can_receive(form):
            report = conversion_report(work.amount, form, 0.0, 0.0)
            report.update(
                {
                    "accepted": False,
                    "success": False,
                    "energy": 0.0,
                    "force": 0.0,
                    "pressure": 0.0,
                }
            )
            return report
        was_open = target.is_open()
        # A1: открытое окно среды аддитивно усиливает успех работы обеих
        # сторон (канонный ENV_BONUS). Вне арены с активным env-актором
        # бонус равен 0 — прежняя калибровка дуэлей не меняется.
        env = getattr(world, "env", None)
        env_bonus = 0.0
        if env is not None:
            env_bonus = float(env.work_bonus())
        chance = success_probability(
            source, target, work, was_open, env_bonus=env_bonus
        )
        rng = getattr(world, "rng", self.rng)
        stored = target.add_energy(work.amount * RECEIVE_ENERGY_SHARE)
        pressure = work.amount * PRESSURE_PER_WORK
        target.state["pressure"] = min(
            30.0, target.pressure() + pressure
        )
        # A1: работа сторон доходит до среды (канонный receive_pressure):
        # накопленное давление может открыть окно уязвимости на следующем
        # такте тика среды.
        if env is not None:
            env.ingest(work.amount, getattr(work, "form", "force"))
        success = rng.random() < chance
        damage = 0.0
        gain = 0.0
        health_damage = 0.0
        if success:
            base = 0.55 if form == "force" else 0.30
            scale = 0.30 if form == "force" else 0.15
            damage = max(
                0.0,
                work.amount * (base - scale * target.resistance(form)),
            )
            _absorbed, _overflow, health_damage = target.apply_force_damage(
                damage
            )
            gain = min(
                source.max_force - source.force,
                damage * FORCE_FEEDBACK_SHARE,
            )
            source.force += max(0.0, gain)
        # A2: устойчивая рана в дуэли. Сильный успешный удар с
        # силовым/информационным уроном по здоровью открывает рану —
        # отдельное персистентное состояние (`wound`), а не только
        # разовый урон `H`. Порог грубый и симметричный для обеих форм:
        # точная калибровка вероятности ранения — часть A7 (потолок RL).
        wound_severity = 0.0
        if health_damage > 0.0:
            wound_severity = min(
                WOUND_MAX,
                WOUND_HIT_SEVERITY * health_damage
                / max(1.0, target.max_health),
            )
            if wound_severity > 0.0:
                target.injure(wound_severity)
        report = conversion_report(work.amount, form, stored)
        report.update(
            {
                "accepted": True,
                "success": success,
                "energy": work.amount * RECEIVE_ENERGY_SHARE,
                "force": damage,
                "damage": damage,
                "health": health_damage,
                "wound": wound_severity,
                "gain": gain,
                "pressure": pressure,
                "chance": chance,
                "was_open": was_open,
            }
        )
        return report


class ArenaMatch:
    def __init__(
        self,
        seed=0,
        steps=2000,
        rl_policy=None,
        ai_policy=None,
        profile_rl="CANON",
        profile_ai="CANON",
        health_factors_rl=None,
        health_factors_ai=None,
        sickness_rl=0.0,
        sickness_ai=0.0,
        wound_rl=0.0,
        wound_ai=0.0,
        with_env=False,
        env_plan=None,
        auto_learn=True,
        fog=True,
        reward_profile=REWARD_PROFILE_DEFAULT,
    ):
        self.seed = int(seed)
        self.steps_total = int(steps)
        self.rng = random.Random(self.seed)
        self.with_env = bool(with_env)
        self.auto_learn = bool(auto_learn)
        if reward_profile not in REWARD_PROFILES:
            raise ValueError(
                "неизвестный профиль награды: %r" % (reward_profile,)
            )
        self.reward_profile = str(reward_profile)
        # A9: туман наблюдаемости включён всегда в активной арене. Явный
        # `fog=False` оставлен для калибровочного плеча «точное знание».
        self.fog = bool(fog)
        self.time = 0
        self.step = 0
        self.winner = None
        self.finished = False
        self.events = []
        self.last_rewards = {"rl": 0.0, "ai": 0.0}
        self.rl_hist = []
        self.ai_hist = []
        self.dom_rl = 0
        self.dom_ai = 0
        self.rl_rest_ticks = 0
        self.ai_rest_ticks = 0
        self.last_rl_action = ("REST", 0.0)
        self.last_ai_action = ("REST", 0.0)
        # A6: последний исход среды (goal/collapse) и событие текущего
        # такта. Это состояния фона, а не терминал партии.
        self.env_outcome = None
        self.env_event = None
        self.rl = ArenaAgent(
            "rl",
            policy=rl_policy,
            profile=profile_rl,
            seed=self.seed ^ 0x5EED,
            health_factors=health_factors_rl,
            sickness=sickness_rl,
            wound=wound_rl,
            fog=self.fog,
        )
        self.ai = ArenaAgent(
            "ai",
            policy=ai_policy,
            profile=profile_ai,
            seed=self.seed ^ 0xA11E,
            health_factors=health_factors_ai,
            sickness=sickness_ai,
            wound=wound_ai,
            fog=self.fog,
        )
        # A9: стартовые знания о скрытом состоянии. Без снимка `Intel`
        # подставлял бы точные значения как «оценку», поэтому снимок
        # создаётся сразу после появления бойцов.
        self.rl.intel.reset(self.ai.unit)
        self.ai.intel.reset(self.rl.unit)
        # Актор среды (проблема с мёртвым `with_env`): не воюет, а по
        # фиксированному расписанию добавляет обоим одинаковое внешнее
        # давление/передышку. При `with_env=False` его нет — прежняя
        # калибровка сохраняется.
        self.env = (
            ArenaEnvironment(seed=self.seed ^ 0xE7E7, plan=env_plan)
            if self.with_env
            else None
        )

    def _coerce_action(self, action):
        if isinstance(action, Action):
            return action
        return action_from_index(action)

    def step_tick(self, forced_rl_action=None, forced_ai_action=None):
        if self.finished:
            return
        self.events = []
        self.env_event = None
        rl, ai = self.rl, self.ai

        rl._time = self.time
        ai._time = self.time
        if self.env is not None:
            env_state = self.env.public_state()
            for actor in (rl, ai):
                actor._env_pressure = env_state["strain"]
                actor._env_season = env_state["season_multiplier"]
                # A1: наблюдаемое окно уязвимости (0/1) — сигнал для
                # 22-го признака политик.
                actor._env_window = 1.0 if env_state["window"] else 0.0
        else:
            for actor in (rl, ai):
                actor._env_pressure = 0.0
                actor._env_season = 1.0
                actor._env_window = 0.0
        rl_obs = rl.observe(ai)
        ai_obs = ai.observe(rl)

        if self.env is not None:
            env_events = self.env.tick(rl, ai)
            self.events.extend(env_events)
            for event in env_events:
                if (
                    event.get("kind") == "environment"
                    and event.get("event") in ("goal", "collapse")
                ):
                    self.env_event = event["event"]
                    self.env_outcome = self.env_event
                    break

        if forced_rl_action is None:
            rl_action, _ = rl.choose_action(ai, explore=True)
        else:
            rl_action = self._coerce_action(forced_rl_action)
            rl.record_action(rl_action, ai, rl_obs)

        if forced_ai_action is None:
            ai_action, _ = ai.choose_action(rl, explore=True)
        else:
            ai_action = self._coerce_action(forced_ai_action)
            ai.record_action(ai_action, rl, ai_obs)

        rl_before = (
            rl.force,
            rl.energy_pool,
            rl.health,
            rl.sickness,
            rl.wound,
        )
        ai_before = (
            ai.force,
            ai.energy_pool,
            ai.health,
            ai.sickness,
            ai.wound,
        )

        # A9: одновременный такт. Оба действия считаются от снимка до
        # разрешения, эффекты применяются атомарно.
        rl_plan, ai_plan, rl_result, ai_result = resolve_pair(
            rl,
            ai,
            rl_action,
            ai_action,
            self.rng,
            env=self.env,
        )
        self.time += 1
        self.step += 1

        reward_rl = self._reward(rl, rl_before, ai, ai_before)
        reward_ai = self._reward(ai, ai_before, rl, rl_before)

        terminal = self._check_terminal()
        if not terminal:
            capture_winner, cap = self._check_capture()
            if capture_winner and not self.finished:
                self.events.append(
                    {
                        "kind": "capture",
                        "winner": capture_winner,
                        "cap": cap,
                    }
                )
                self.winner = capture_winner
                self.finished = True
                terminal = True

        if terminal:
            reward_rl += terminal_reward(self.winner, "rl")
            reward_ai += terminal_reward(self.winner, "ai")
        self.last_rewards = {"rl": reward_rl, "ai": reward_ai}

        rl_next = rl.observe(ai)
        ai_next = ai.observe(rl)
        if self.auto_learn:
            rl.learn(
                reward_rl,
                rl_next,
                terminal,
                ai,
                opponent_action=ai_action,
            )
            ai.learn(
                reward_ai,
                ai_next,
                terminal,
                rl,
                opponent_action=rl_action,
            )

        self.events.extend(
            _plan_events("rl", rl, rl_plan, rl_result)
        )
        self.events.extend(
            _plan_events("ai", ai, ai_plan, ai_result)
        )

        self.last_rl_action = (
            rl.last_act,
            float(rl_result.get("spent", 0.0)),
        )
        self.last_ai_action = (
            ai.last_act,
            float(ai_result.get("spent", 0.0)),
        )

        if rl_plan.get("kind") == "rest":
            self.rl_rest_ticks += 1
        if ai_plan.get("kind") == "rest":
            self.ai_rest_ticks += 1

        self.rl.rest_units = max(0.0, rl.rest_ceiling - rl.force)
        self.ai.rest_units = max(0.0, ai.rest_ceiling - ai.force)
        self.rl_hist.append(rl.force)
        self.ai_hist.append(ai.force)

    def _reward(self, me, before, other, other_before):
        return reward_delta(
            me,
            before,
            other,
            other_before,
            profile=self.reward_profile,
        )

    def _check_terminal(self):
        if self.finished:
            return True
        rl, ai = self.rl, self.ai
        if rl.is_dead and ai.is_dead:
            self.winner = "draw"
        elif rl.is_dead:
            self.winner = "AI"
        elif ai.is_dead:
            self.winner = "RL"
        if self.winner is not None:
            self.finished = True
            return True
        if self.step >= self.steps_total:
            # Лимит шагов — усечение, а не победа по остатку силы/здоровья.
            # Раньше здесь присуждался winner по `(force, health)`, из-за
            # чего таймаут попадал в win/loss и давал терминальный ±1.0.
            # Теперь таймаут — ничья; среда отдельно возвращает
            # `truncated=True`, и цикл обучения не считает его терминалом.
            self.finished = True
            self.winner = None
            return True
        return False

    def _check_capture(self):
        winner, self.dom_rl, self.dom_ai, cap = _resolve_capture(
            self.rl, self.ai, self.dom_rl, self.dom_ai
        )
        return winner, cap


def run_duel_tick(
    left,
    left_action,
    right,
    right_action,
    rng=None,
    *,
    left_id="left",
    right_id="right",
):
    """Один одновременный такт дуэли для UI и экспериментов.

    Оба действия считаются от снимка начала такта; результат не зависит от
    порядка сторон. Возвращает события, результат левой и правой стороны.
    """
    left_plan, right_plan, left_result, right_result = resolve_pair(
        left,
        right,
        left_action,
        right_action,
        rng or random.Random(0),
    )
    events = []
    events.extend(_plan_events(left_id, left, left_plan, left_result))
    events.extend(_plan_events(right_id, right, right_plan, right_result))
    return events, left_result, right_result


def _resolve_capture(
    rl, ai, dom_rl=0, dom_ai=0, winner_rl="RL", winner_ai="AI"
):
    dom_rl = (
        dom_rl + 1
        if (
            rl.energy_pool >= CAPTURE_RATIO * ai.energy_pool
            and rl.force > ai.force
        )
        else 0
    )
    dom_ai = (
        dom_ai + 1
        if (
            ai.energy_pool >= CAPTURE_RATIO * rl.energy_pool
            and ai.force > rl.force
        )
        else 0
    )
    if dom_rl >= CAPTURE_STREAK:
        severity = 2.0 if ai.in_open else 1.0
        cap = int(ai.force * min(CAPTURE_FRAC * severity, 0.5))
        ai.force = max(1.0, ai.force - cap)
        ai.rest_units = max(0.0, ai.rest_units - cap / L_STEP)
        rl.force = min(rl.rest_ceiling, rl.force + cap * 0.20)
        return winner_rl, 0, 0, cap
    if dom_ai >= CAPTURE_STREAK:
        severity = 2.0 if rl.in_open else 1.0
        cap = int(rl.force * min(CAPTURE_FRAC * severity, 0.5))
        rl.force = max(1.0, rl.force - cap)
        rl.rest_units = max(0.0, rl.rest_units - cap / L_STEP)
        ai.force = min(ai.rest_ceiling, ai.force + cap * 0.20)
        return winner_ai, 0, 0, cap
    return None, dom_rl, dom_ai, 0


def check_capture(
    rl,
    ai,
    dom_rl=0,
    dom_ai=0,
    winner_rl="RL",
    winner_ai="AI",
):
    winner, dom_rl, dom_ai, _cap = _resolve_capture(
        rl, ai, dom_rl, dom_ai, winner_rl, winner_ai
    )
    return winner, dom_rl, dom_ai


__all__ = [
    "ArenaAgent",
    "ArenaMatch",
    "CAPTURE_FRAC",
    "CAPTURE_RATIO",
    "CAPTURE_STREAK",
    "CORE_ACTIONS",
    "FORCE_WORK_RATIO",
    "FORMS",
    "FRACTIONS",
    "INFO_COST_FACTOR",
    "L_STEP",
    "OPEN_PRESSURE",
    "PendingWork",
    "WAIT_ACTION",
    "action_from_index",
    "check_capture",
    "resolve_pair",
    "resolve_work",
    "run_duel_tick",
    "work_amount",
    "work_duration",
]
