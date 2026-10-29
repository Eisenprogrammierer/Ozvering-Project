"""Кампанейная среда поверх `WorldEngine` (проблема №6 готовности к обучению).

`CampaignEnv` — Gym-подобный контракт reset/step над дневным миром
кампании. Ядро остаётся 4-2-1: среда не вводит новых шкал, а проецирует
состояние мира в `CampaignObservation` (здоровье/болезнь персонажа — то же
состояние S/sickness, что и на арене; ресурсы позиции и статистика узла —
легаси-шкалы как проекции канала form). Награда собирается из нормированных
дельт тех же величин, что и `reward_delta()` арены, плюс терминальный бонус
за исход сюжета; объективной победы нет — «win» это лишь порог положения на
момент конца сценария (см. открытые вопросы §7 №30).

Честно о незакрытом (открытые вопросы docs/SOURCE_OF_TRUTH.md §7):
- №28 распад организации: первый срез — организация распадается после
  `COLLAPSE_GRACE_DAYS` дней подряд ниже порога силы/связности; точная
  экономика распада и легитимности ещё не откалибрована;
- №29 увольнение как смена роли: потеря должности больше не `lose` —
  игрок получает другую роль в той же структуре или остаётся вне службы;
  полноценный рынок труда остаётся открытым;
- №30 финалы бесконечного сценария: горизонт `max_days` — усечение
  (truncated), а не поражение; сюжетный горизонт мира больше не даёт
  `win`, нарративный финал задаётся `effects["ending"]`;
- №31 фоновая симуляция/офлайн-прогресс: `campaign.clock` и
  `WorldEngine.advance_days()` дают ограниченный догон при свёрнутом окне
  и после загрузки; реального real-time-планировщика по-прежнему нет.

Среда создана для обучения, поэтому игрок обязан явно передавать действия
(в отличие от UI, где ход завершается кнопкой). Служебное действие
`END_DAY` переводит день: оно всегда легально, пока кампания не завершена.
"""

from core41 import HEALTH_MAX, SICKNESS_MAX
from core41.types import CampaignAction, CampaignObservation

from .world import (
    PLAYER_STATS,
    WorldEngine,
    load_world,
)

# Действие-служебный ход: завершение дня (ход мира + дневной срез).
END_DAY = "END_DAY"
# Лечение себя — адаптер среды, а не действие конфига мира: в кампании
# `treat_player()` существовал только как API. Без него болезнь была
# отложенной смертью без контрмеры, и политика не могла ей научиться.
TREAT_SELF = "TREAT_SELF"
CAMPAIGN_TREAT_AMOUNT = 0.20

# Награды кампании. Единицы — доли максимумов шкал, шаг сравним с ареной.
CAMPAIGN_REWARD_STANDING = 0.5   # положение героя (F-проекция позиции)
CAMPAIGN_REWARD_ORGANIZATION = 0.5  # сила+связность своей организации
CAMPAIGN_REWARD_HEALTH = 1.0     # здоровье персонажа (S)
CAMPAIGN_REWARD_SICKNESS = 1.0   # снятие/наращивание болезни
CAMPAIGN_REWARD_SUCCESS = 0.10   # малый shaping за успешное действие
CAMPAIGN_REWARD_ILLEGAL = 0.05   # штраф за нелегальный ход (ok=False в мире)
CAMPAIGN_TERMINAL_WIN = 1.0
CAMPAIGN_TERMINAL_LOSS = -1.0
CAMPAIGN_TERMINAL_NEUTRAL = 0.0


def _clamp_unit(value):
    return max(-1.0, min(1.0, float(value)))


def campaign_reward(before, after, outcome_delta=0.0, success=False):
    """Пошаговая награда кампании по снимкам `(obs_before, obs_after)`.

    Снимки — словари `_metrics()`. Композиция зеркалит `reward_delta()`
    арены: прирост своих позиций и организаций, здоровье, динамика
    болезни; `outcome_delta` — терминальная часть (добавляется только на
    переходе, завершившем сюжет).
    """
    reward = CAMPAIGN_REWARD_STANDING * (
        after["standing"] - before["standing"]
    )
    organization = (after["power"] + after["cohesion"]) - (
        before["power"] + before["cohesion"]
    )
    reward += 0.5 * CAMPAIGN_REWARD_ORGANIZATION * organization
    reward += CAMPAIGN_REWARD_HEALTH * (
        (after["health"] - before["health"]) / max(1.0, HEALTH_MAX)
    )
    reward -= CAMPAIGN_REWARD_SICKNESS * (
        (after["sickness"] - before["sickness"]) / max(1e-9, SICKNESS_MAX)
    )
    if success:
        reward += CAMPAIGN_REWARD_SUCCESS
    reward += outcome_delta
    return reward


def terminal_campaign_reward(outcome):
    """Терминальный бонус по исходу сюжета (без объективной победы)."""
    if outcome == "win":
        return CAMPAIGN_TERMINAL_WIN
    if outcome == "lose":
        return CAMPAIGN_TERMINAL_LOSS
    return CAMPAIGN_TERMINAL_NEUTRAL


class CampaignEnv:
    """Gym-подобная среда над `WorldEngine` для обучения политиками ядра.

    Параметры:
    - `config` — словарь мира (по умолчанию `load_world()`);
    - `profile`/`node_id`/`office_id` — стартовая позиция героя; по
      умолчанию используется `default_profile` конфига и первый головной
      узел с его головной должностью, чтобы среда была самодостаточной;
    - `seed` — зерно детерминированных бросков `WorldEngine._roll`;
    - `max_days` — жёсткий горизонт усечения (truncated), не поражение.

    Контракт: `reset(seed=None) -> CampaignObservation`;
    `step(action: CampaignAction) -> (obs, reward, done, truncated, info)`;
    `action_space` — кортеж `(kind, target)` пар; `legal_actions()` —
    легальные на текущем ходу пары вместе со служебным `END_DAY`.
    """

    def __init__(
        self,
        config=None,
        profile=None,
        node_id=None,
        office_id=None,
        seed=0,
        max_days=None,
        snapshot=None,
        sickness=0.0,
        target_mode="all",
        career_actions=False,
        engine=None,
    ):
        if target_mode not in ("first", "all"):
            raise ValueError("target_mode должен быть 'first' или 'all'")
        self.target_mode = target_mode
        # Карьера меняет идентичность героя, поэтому по умолчанию
        # исключена из пространства действий. Флаг нужен для калибровки
        # политики, которая сама выбирает повышение/перевод.
        self.career_actions = bool(career_actions)
        self.config = dict(config or load_world())
        self.seed = int(seed)
        self.max_days = (
            int(max_days) if max_days is not None else int(self.config.get("days", 30))
        )
        self._start_profile = profile
        self._start_node = node_id
        self._start_office = office_id
        self._start_snapshot = snapshot
        # Кэш стартовой позиции: `_default_start()` перебирает узлы и
        # пробные движки, поэтому его нельзя повторять на каждом reset().
        # Домен кампании меняет профиль/болезнь, но не узел/должность.
        self._resolved_start = None
        # Стартовая болезнь героя для доменной рандомизации (проблема №7);
        # применяется в _build_engine как переопределение конфига `condition`.
        self._start_sickness = max(0.0, min(1.0, float(sickness)))
        self.engine = None
        self.last_transition = None
        # Терминальность среды: `WorldEngine.finished` не покрывает случай
        # «должность потеряна, замены нет» — для обучения это тоже конец
        # эпизода (нейтральный исход), иначе остаётся зомби-состояние.
        self._terminal = False
        # Одиночный агент (проблема №6): оппонента нет, цикл обучения
        # (`agents.train`) использует для этой среды кампанейный эпизод.
        self.single_agent = True
        if engine is not None:
            # Живая кампания (P0.4): среда оборачивает уже существующий
            # `WorldEngine` экрана, а не строит второй мир. Действия политики
            # меняют тот же движок, который рисует UI и сохраняется в сейв.
            self.attach(engine)
        else:
            self.reset(seed=self.seed)

    def attach(self, engine):
        """Подключить среду к существующему `WorldEngine` без пересоздания.

        Возвращает `CampaignObservation`. Используется live-режимом
        кампании: `WorldScreen` создаёт `CampaignEnv(engine=engine)`, и
        `step()` политики исполняется на том же движке, что и ручные
        действия игрока. Стартовая позиция кэшируется, чтобы последующий
        `reset()` мог восстановить текущий домен.
        """
        if engine is None:
            raise ValueError("CampaignEnv.attach() нужен WorldEngine")
        self.engine = engine
        self.config = dict(engine.config or self.config)
        self.seed = int(engine.seed)
        self.max_days = max(
            int(self.max_days), int(self.config.get("days", self.max_days))
        )
        self._resolved_start = (
            engine.player_node_id or None,
            engine.player_office_id or None,
        )
        self._start_node = engine.player_node_id or None
        self._start_office = engine.player_office_id or None
        self._start_profile = getattr(engine, "profile", None)
        self._start_snapshot = None
        self.last_transition = None
        self._terminal = bool(engine.finished or not engine.attached)
        return self.observe()

    def choose_action(self, policy, explore=False):
        """Выбрать легальное действие политикой в текущем состоянии."""
        actions = self.legal_actions()
        if not actions:
            return CampaignAction(END_DAY)
        return policy.act(self.observe(), actions, explore=explore)

    def advance(self, policy, explore=False):
        """Один шаг политики в живой кампании (тот же контракт, что `step`)."""
        return self.step(self.choose_action(policy, explore=explore))


    def randomize_draw(
        self,
        rng=None,
        skill_jitter=0.0,
        sickness_min=0.0,
        sickness_max=0.6,
    ):
        """Сэмплировать домен кампании (проблема готовности №7).

        Возвращает словарь для `apply_domain`: джиттер навыков профиля
        (`skill_jitter` — относительная величина, 0.25 = ±25%) и стартовая
        болезнь героя. Профиль строится поверх `default_profile` конфига,
        поэтому среда остаётся самодостаточной на любом валидном мире.
        """
        import random as _random

        from .world import SKILL_ORDER

        rng = rng or _random.Random()
        base = dict(self.config.get("default_profile") or {})
        skills = dict(base.get("skills") or {})
        if skill_jitter > 0.0:
            for key in SKILL_ORDER:
                value = float(skills.get(key, 0.08))
                low = max(0.0, value * (1.0 - float(skill_jitter)))
                high = min(1.0, value * (1.0 + float(skill_jitter)))
                skills[key] = round(rng.uniform(low, high), 4)
        base["skills"] = skills
        return {
            "profile": base,
            "sickness": round(
                rng.uniform(
                    max(0.0, float(sickness_min)),
                    max(max(0.0, float(sickness_min)), min(1.0, float(sickness_max))),
                ),
                4,
            ),
        }

    def apply_domain(self, profile=None, sickness=None):
        """Применить домен кампании и пересоздать движок (`reset`)."""
        if profile is not None:
            self._start_profile = dict(profile)
        if sickness is not None:
            self._start_sickness = max(0.0, min(1.0, float(sickness)))
        return self.reset()

    # ------------------------------------------------------------------
    # Построение движка и стартовой позиции
    # ------------------------------------------------------------------

    def _default_start(self):
        """Старт без явного узла: первый корневой узел + его head-должность.

        Пробуем attach по очереди: если `default_profile` не подходит под
        требования первой должности, берём следующий корневой узел. Так
        среда самодостаточна на любом валидном конфиге мира. Результат
        кэшируется: перебор дорогой, а домен кампании меняет только
        профиль/болезнь, не узел и должность.
        """
        if self._resolved_start is not None:
            return self._resolved_start
        probe = WorldEngine(
            dict(self.config),
            profile=self._start_profile,
            seed=self.seed,
        )
        for candidate_id in probe.node_order:
            node = probe.node(candidate_id)
            if node is None or node.get("parent"):
                continue
            templates = probe.office_templates_for_node(node)
            for template in templates:
                trial = WorldEngine(
                    dict(self.config),
                    profile=self._start_profile,
                    seed=self.seed,
                )
                result = trial.attach(candidate_id, template["id"])
                if result.get("ok"):
                    self._resolved_start = (candidate_id, template["id"])
                    return self._resolved_start
        self._resolved_start = (None, None)
        return self._resolved_start

    def _build_engine(self, seed):
        node_id = self._start_node
        office_id = self._start_office
        if not (node_id and office_id) and not self._start_snapshot:
            node_id, office_id = self._default_start()
        config = dict(self.config)
        # Стартовая болезнь героя для доменной рандомизации (проблема №7):
        # переопределяем `condition` конфига, не мутируя исходный словарь.
        if self._start_sickness > 0.0:
            condition = dict(config.get("condition") or {})
            condition["sickness"] = self._start_sickness
            config["condition"] = condition
        return WorldEngine(
            config,
            profile=self._start_profile,
            node_id=node_id,
            office_id=office_id,
            seed=seed,
            snapshot=self._start_snapshot,
        )

    # ------------------------------------------------------------------
    # Наблюдения и метрики
    # ------------------------------------------------------------------

    def _node_stats(self):
        node = self.engine.node(self.engine.player_node_id)
        stats = (node or {}).get("stats") or {}
        return {
            key: float(stats.get(key, 0.0))
            for key in ("power", "wealth", "legitimacy", "cohesion", "reach", "capacity")
        }

    def _metrics(self):
        engine = self.engine
        condition = engine.player_condition()
        stats = self._node_stats()
        metrics = {
            "day": engine.day,
            "actions_left": engine.actions_left,
            "health": condition["health"],
            "sickness": condition["sickness"],
            "alive": condition["alive"],
            "energy": condition.get("energy", 0.0),
            "max_energy": condition.get("max_energy", 0.0),
            "force": condition.get("force", 0.0),
            "max_force": condition.get("max_force", 0.0),
            "authority": float(engine.player_authority),
            "finished": bool(engine.finished),
            "outcome": engine.outcome or "",
            "attached": bool(engine.attached),
            "dismissed": bool(
                getattr(engine, "dismissed", False) and not engine.attached
            ),
            "dismissal_count": int(
                getattr(engine, "dismissal_count", 0)
            ),
            "collapse_days": int(getattr(engine, "collapse_days", 0)),
            "storyline_days": int(getattr(engine, "storyline_days", 0)),
            "ending": str(getattr(engine, "ending", "") or ""),
            "infinite": bool(getattr(engine, "infinite", True)),
            "horizon_passed": bool(
                getattr(engine, "horizon_passed", False)
            ),
            "collapsed": bool(getattr(engine, "collapsed", False)),
        }
        for key in PLAYER_STATS:
            metrics[key] = float(engine.player_resources.get(key, 0.0))
        metrics.update(stats)
        return metrics

    def observe(self):
        """Текущее наблюдение игрока (плоское, нормированное)."""
        engine = self.engine
        metrics = self._metrics()
        return CampaignObservation(
            day=int(metrics["day"]),
            total_days=int(self.max_days),
            actions_left=int(metrics["actions_left"]),
            actions_per_day=int(engine.actions_per_day),
            energy=float(metrics["energy"]),
            max_energy=float(metrics["max_energy"]),
            force=float(metrics["force"]),
            max_force=float(metrics["max_force"]),
            health=float(metrics["health"]),
            max_health=float(HEALTH_MAX),
            sickness=float(metrics["sickness"]),
            alive=bool(metrics["alive"]),
            influence=_clamp_unit(metrics["influence"]),
            favor=_clamp_unit(metrics["favor"]),
            evidence=_clamp_unit(metrics["evidence"]),
            standing=_clamp_unit(metrics["standing"]),
            authority=_clamp_unit(metrics["authority"]),
            power=_clamp_unit(metrics["power"]),
            wealth=_clamp_unit(metrics["wealth"]),
            legitimacy=_clamp_unit(metrics["legitimacy"]),
            cohesion=_clamp_unit(metrics["cohesion"]),
            reach=_clamp_unit(metrics["reach"]),
            capacity=_clamp_unit(metrics["capacity"]),
            attached=bool(metrics["attached"]),
            finished=bool(metrics["finished"] or self._terminal),
            outcome=str(
                metrics["outcome"]
                or ("neutral" if self._terminal and not metrics["attached"] else "")
            ),
            collapsed=bool(metrics["collapsed"]),
            dismissed=bool(metrics["dismissed"]),
            time=float(metrics["day"]),
            extra={
                "seed": engine.seed,
                # §7 №28–31: распад и увольнение больше не сворачиваются в
                # один флаг `outcome`. Наблюдение отдаёт счётчики и вид
                # финала, чтобы политика/логгер могли их различать.
                "ending": metrics["ending"],
                "infinite": metrics["infinite"],
                "horizon_passed": metrics["horizon_passed"],
                "dismissal_count": metrics["dismissal_count"],
                "collapse_days": metrics["collapse_days"],
                "storyline_days": metrics["storyline_days"],
                "terminal": bool(self._terminal),
            },
        )

    # ------------------------------------------------------------------
    # Пространство действий
    # ------------------------------------------------------------------

    def legal_actions(self):
        """Легальные `CampaignAction` + служебные `END_DAY`/`TREAT_SELF`.

        `target_mode="all"` (по умолчанию для обучения) открывает действия
        по всем доступным узлам, а не только по первому союзному: иначе
        агент видит 3 действия из 47 и не может учиться выбирать адресата.
        `target_mode="first"` сохраняет прежний узкий режим для отладки.
        Карьерные действия по умолчанию исключены: они меняют идентичность
        агента и выходят за пространство одной политики (смена роли по
        №29 происходит внутри `WorldEngine`). `career_actions=True` открывает
        их для калибровки карьерной политики.
        """
        engine = self.engine
        actions = [CampaignAction(END_DAY)]
        if engine.finished or self._terminal or not engine.attached:
            return tuple(actions)
        if engine.player_sickness > 0.0 and engine.actions_left > 0:
            actions.append(CampaignAction(TREAT_SELF))
        seen = set()
        for target_id in self._target_ids():
            for action_id in engine.available_actions(target_id):
                action = engine.actions[action_id]
                if action.get("career") and not self.career_actions:
                    continue
                self_target = bool((action.get("target") or {}).get("self"))
                target = "" if self_target else target_id
                key = (action_id, target)
                if key in seen:
                    continue
                seen.add(key)
                actions.append(
                    CampaignAction(action_id, target=target)
                )
        return tuple(actions)

    def _target_ids(self):
        """Узлы-адресаты в детерминированном порядке (свой узел исключён)."""
        if self.target_mode == "first":
            target_id = self._target_id()
            return (target_id,) if target_id else ()
        engine = self.engine
        groups = engine.organization_groups()
        ordered = []
        seen = set()
        for group in ("allied", "neutral", "hostile"):
            for item in groups.get(group, ()):
                node_id = item["id"]
                if node_id == engine.player_node_id or node_id in seen:
                    continue
                seen.add(node_id)
                ordered.append(node_id)
        return tuple(ordered)

    def _target_id(self):
        engine = self.engine
        groups = engine.organization_groups()
        for group in ("allied", "neutral", "hostile"):
            candidates = [
                item["id"]
                for item in groups.get(group, [])
                if item["id"] != engine.player_node_id
            ]
            if candidates:
                return candidates[0]
        return None

    @property
    def action_space(self):
        return self.legal_actions()

    # ------------------------------------------------------------------
    # Core контракт
    # ------------------------------------------------------------------

    def reset(self, seed=None):
        if seed is not None:
            self.seed = int(seed)
        self.engine = self._build_engine(self.seed)
        self.last_transition = None
        self._terminal = False
        return self.observe()

    def _treat_self(self):
        """Лечение себя в кампанейном адаптере (не действие конфига мира).

        Стоит одно действие дня и снимает `CAMPAIGN_TREAT_AMOUNT` болезни.
        В мире пока нет UI-действия самолечения; среда обязана дать
        политике контрмеру, иначе болезнь — детерминированная отложенная
        смерть и обучение ей невозможно.
        """
        engine = self.engine
        if not engine.attached:
            return {"ok": False, "reason": "сначала выберите должность"}
        if engine.player_sickness <= 0.0:
            return {"ok": False, "reason": "герой здоров"}
        if engine.actions_left <= 0:
            return {"ok": False, "reason": "не осталось действий"}
        engine.player.spend_action()
        value = engine.treat_player(CAMPAIGN_TREAT_AMOUNT)
        if value is None:
            return {"ok": False, "reason": "герой мёртв"}
        text = "Помощь себе: болезнь %.2f." % value
        result = {
            "ok": True,
            "action": TREAT_SELF,
            "action_label": "Лечение",
            "target": "",
            "target_label": "своё состояние",
            "outcome": "success",
            "text": text,
            "changes": [("Болезнь", -CAMPAIGN_TREAT_AMOUNT)],
            "sickness": value,
            "day": engine.day,
        }
        engine.last_result = result
        engine.log.append(
            {
                "day": engine.day,
                "kind": "success",
                "text": "Лечение → своё состояние: %s" % text,
            }
        )
        return result

    def step(self, action):
        engine = self.engine
        if engine is None:
            raise RuntimeError("CampaignEnv.step() вызван до reset()")
        if engine.finished or self._terminal:
            raise RuntimeError("CampaignEnv.step() после завершения кампании")
        if isinstance(action, str):
            action = CampaignAction(action)
        before = self._metrics()
        success = False
        if action.kind == END_DAY:
            result = engine.end_day()
        elif action.kind == TREAT_SELF:
            result = self._treat_self()
            success = bool(result.get("ok"))
        else:
            result = engine.execute(action.kind, action.target or None)
            success = bool(result.get("ok")) and result.get("outcome") == "success"
        # Действие вне правил (например, политика выбрала нелегальный ход):
        # WorldEngine вернул ok=False — это не исключение, а нулевой шаг со
        # штрафом за потерянную инициативу; цикл обучения получает корректный
        # Transition и учится не повторять недопустимые действия.
        illegal = not bool(result.get("ok"))
        after = self._metrics()
        # Потеря должности без замены: `WorldEngine` не завершает кампанию
        # (UI может выбрать новую роль), но для обучения это терминальный
        # нейтральный исход. Иначе остаётся зомби-эпизод с одним END_DAY.
        dismissed_terminal = bool(not engine.attached and not engine.finished)
        done = bool(engine.finished or dismissed_terminal)
        horizon = bool(after["day"] > self.max_days)
        truncated = bool(horizon and not done)
        self._terminal = bool(done or truncated)
        outcome = "neutral" if dismissed_terminal else (engine.outcome or "")
        outcome_delta = terminal_campaign_reward(outcome) if done else 0.0
        reward = campaign_reward(before, after, outcome_delta, success)
        if illegal:
            # Малый штраф за нелегальный ход: переход не изменил мир, но
            # политика должна отличать такие шаги (symmetric с REWARD-логикой
            # арены, где недопустимое действие не встречается — там легальность
            # гарантирует среда).
            reward -= CAMPAIGN_REWARD_ILLEGAL
        observation = self.observe()
        info = {
            "result": result,
            "outcome": outcome,
            "ending": after["ending"],
            "dismissed": after["dismissed"],
            "dismissal_count": after["dismissal_count"],
            "collapse_days": after["collapse_days"],
            "infinite": after["infinite"],
            "horizon_passed": after["horizon_passed"],
            "day": engine.day,
            "metrics": after,
            "outcome_delta": outcome_delta,
            "success": success,
            "illegal": illegal,
            "horizon": horizon,
            "terminal_reason": "dismissed" if dismissed_terminal else "",
            "intents": len(getattr(engine, "intents", ()) or ()),
        }
        transition_ready = bool(done or truncated)
        self.last_transition = {
            "observation": observation,
            "reward": reward,
            "done": done,
            "truncated": truncated,
            "info": info,
            "terminal": transition_ready,
        }
        if transition_ready:
            # Горизонт без терминального исхода: помечаем сюжет оконченным
            # для цикла обучения, не трогая состояние движка (вопрос №30).
            pass
        return observation, reward, done, truncated, info

    # ------------------------------------------------------------------
    # Персистентность (для resume и Сейва арены-кампании)
    # ------------------------------------------------------------------

    def state_dict(self):
        return {
            "kind": "campaign_env",
            "version": 1,
            "seed": self.seed,
            "max_days": self.max_days,
            "target_mode": self.target_mode,
            "career_actions": self.career_actions,
            "snapshot": self.engine.to_dict(),
        }

    def load_state_dict(self, state):
        snapshot = dict(state.get("snapshot") or {})
        self.seed = int(state.get("seed", self.seed))
        self.max_days = int(state.get("max_days", self.max_days))
        target_mode = state.get("target_mode", self.target_mode)
        if target_mode in ("first", "all"):
            self.target_mode = target_mode
        self.career_actions = bool(
            state.get("career_actions", self.career_actions)
        )
        self._start_snapshot = snapshot
        self.engine = self._build_engine(self.seed)
        self._terminal = bool(self.engine.finished or not self.engine.attached)
        return self.observe()


__all__ = [
    "CAMPAIGN_REWARD_HEALTH",
    "CAMPAIGN_REWARD_ILLEGAL",
    "CAMPAIGN_REWARD_ORGANIZATION",
    "CAMPAIGN_REWARD_SICKNESS",
    "CAMPAIGN_REWARD_STANDING",
    "CAMPAIGN_REWARD_SUCCESS",
    "CAMPAIGN_TERMINAL_LOSS",
    "CAMPAIGN_TERMINAL_NEUTRAL",
    "CAMPAIGN_TERMINAL_WIN",
    "CAMPAIGN_TREAT_AMOUNT",
    "END_DAY",
    "TREAT_SELF",
    "CampaignEnv",
    "campaign_reward",
    "terminal_campaign_reward",
]
