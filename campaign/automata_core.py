"""Инициализация кампании, фракции, геометрия, часы, скорость и время."""

from __future__ import annotations

from .automata_support import (
    AutomataCampaignError,
    CampaignError,
    DEFAULT_AUTOMATON_INTERACTIONS,
    DEFAULT_CHARACTER_INTERACTIONS,
    DEFAULT_OBLIGATION_KIND,
    FactionRuntime,
    Mapping,
    ORGANIZATION_RUNTIME_DEFAULTS,
    OrganRuntime,
    OrganizationRuntime,
    PHYSICAL_SECONDS_PER_REAL_SECOND,
    PRESET_DEFAULTS,
    StateMachine,
    StateMachineCatalog,
    StateMachineError,
    _as_mapping,
    _build_geometry,
    _build_subfactions,
    _character_from_record,
    _clamp,
    _merged_mapping,
    _number,
    _organization_parameters,
    _relation_model,
    _text,
    asset_keys,
    load_catalog,
    logger,
    math,
    organ_composite,
    relation_axis_labels_from_config,
    validate_organ_network,
)


class AutomataCoreMixin:

    @staticmethod
    def _load_machine_catalog():
        """Прочитать исполняемые автоматы из ``configs/automata``."""
        try:
            return load_catalog()
        except (OSError, StateMachineError, ValueError) as error:
            logger.warning("Автоматы кампании не загружены: %s", error)
            return StateMachineCatalog()

    def _build_machines(self):
        """Создать рантайм автоматов для фракций, подсистем и органов.

        Явная ссылка в данных сильнее общего автомата вида:
        ``faction.automaton`` выбирает автомат фракции, ``automaton_id``
        органа — его собственный, а при его отсутствии используется
        автомат по ``kind``. ``*.default`` остаётся совместимым fallback.
        """
        self.faction_machines = {}
        self.organ_machines = {}
        self.subfaction_machines = {}
        faction_definition = self.machine_catalog.first("faction")
        organ_definition = self.machine_catalog.first("organ")
        subfaction_definition = self.machine_catalog.first("subfaction")
        for side, faction in self.factions.items():
            definition = self.machine_catalog.get(
                str(faction.record.get("automaton") or "")
            )
            definition = definition or faction_definition
            if definition is not None:
                self.faction_machines[side] = StateMachine(definition)
            subs = {}
            for subfaction in faction.subfactions:
                definition = None
                if subfaction.machine_id:
                    definition = self.machine_catalog.get(
                        subfaction.machine_id
                    )
                definition = definition or subfaction_definition
                if definition is not None:
                    subs[subfaction.id] = StateMachine(definition)
            if subs:
                self.subfaction_machines[side] = subs
            if organ_definition is None:
                continue
            machines = {}
            for organ in faction.organs:
                definition = self.machine_catalog.get(
                    str(organ.automaton_id or "")
                )
                if definition is None:
                    definition = self.machine_catalog.get(
                        "organ.%s" % str(organ.kind or "")
                    )
                definition = definition or organ_definition
                machines[str(organ.id)] = StateMachine(definition)
            if machines:
                self.organ_machines[side] = machines

    def _seed_obligations(self):
        """Развернуть стартовые обязательства из постов персонажей.

        Источник — ``post.leverage``/``character_defaults.leverage``:
        каждая запись описывает рычаг, который герой имеет на персонажа.
        По умолчанию кредитор — ``"player"``, должник — сам персонаж.
        Невалидная запись пропускается: контент не должен ломать кампанию.
        """

        for faction in self.factions.values():
            for character in getattr(faction, "characters", ()) or ():
                seeds = getattr(character, "campaign_leverage", ()) or ()
                debtor_default = _text(
                    getattr(character, "campaign_id", "")
                )
                for raw in seeds:
                    if not isinstance(raw, Mapping):
                        continue
                    creditor = _text(raw.get("creditor"), "player")
                    debtor = _text(raw.get("debtor"), debtor_default)
                    kind = _text(
                        raw.get("kind"), DEFAULT_OBLIGATION_KIND
                    )
                    amount = _number(raw.get("amount"), 1.0)
                    note = _text(raw.get("note"))
                    try:
                        self.obligations.add(
                            creditor,
                            debtor,
                            kind,
                            amount,
                            created_day=self.turn,
                            note=note,
                        )
                    except CampaignError as error:
                        logger.warning(
                            "Обязательство %s/%s пропущено: %s",
                            debtor,
                            kind,
                            error,
                        )

    def add_obligation(
        self,
        creditor,
        debtor,
        kind=DEFAULT_OBLIGATION_KIND,
        amount=1.0,
        *,
        due_day=None,
        note="",
    ):
        """Создать обязательство: ``debtor`` должен ``creditor``."""

        return self.obligations.add(
            creditor,
            debtor,
            kind,
            amount,
            created_day=self.turn,
            due_day=due_day,
            note=note,
        ).to_dict()

    def fulfill_obligation(self, obligation_id, day=None):
        """Отметить обязательство исполненным."""

        obligation = self.obligations.fulfill(
            obligation_id,
            self.turn if day is None else day,
        )
        return None if obligation is None else obligation.to_dict()

    def cancel_obligation(self, obligation_id, day=None):
        """Отменить обязательство, не исполняя его."""

        obligation = self.obligations.cancel(
            obligation_id,
            self.turn if day is None else day,
        )
        return None if obligation is None else obligation.to_dict()

    def obligation_view(self, party=None, day=None):
        """Срез журнала обязательств для UI и диалога."""

        day = self.turn if day is None else int(_number(day, self.turn))
        entries = (
            self.obligations.for_party(party)
            if party is not None
            else list(self.obligations)
        )
        return {
            "summary": self.obligations.summary(day),
            "entries": [item.to_dict() for item in entries],
            "due": [
                item.to_dict() for item in self.obligations.due(day)
            ],
            "overdue": [
                item.to_dict() for item in self.obligations.overdue(day)
            ],
        }

    def _machine_context(self, faction, organ=None, subfaction=None):
        character = faction.characters[0] if faction.characters else None
        context = {
            "faction": faction,
            "character": character,
            "turn": self.turn,
        }
        if organ is not None:
            context["organ"] = organ
        if subfaction is not None:
            context["subfaction"] = subfaction
        return context

    def _tick_machines(self):
        """Продвинуть исполняемые автоматы на один тик.

        Переходы читают состояние; эффекты состояний проходят через
        ``campaign/effects.py``. События сюда не попадают.
        """
        for side, machine in self.faction_machines.items():
            faction = self.factions.get(side)
            if faction is None or faction.dissolved:
                continue
            machine.tick(
                self._machine_context(faction), actor=faction
            )
        for side, machines in self.subfaction_machines.items():
            faction = self.factions.get(side)
            if faction is None or faction.dissolved:
                continue
            for subfaction in faction.subfactions:
                machine = machines.get(subfaction.id)
                if machine is None:
                    continue
                machine.tick(
                    self._machine_context(faction, subfaction=subfaction),
                    actor=faction,
                )
        for side, machines in self.organ_machines.items():
            faction = self.factions.get(side)
            if faction is None:
                continue
            for organ in faction.organs:
                machine = machines.get(str(organ.id))
                if machine is None or organ.integrity <= 0.0:
                    continue
                machine.tick(
                    self._machine_context(faction, organ),
                    actor=faction,
                )

    def _build_factions(self, data):
        characters = list(data.get("characters") or ())
        organizations = {
            str(item.get("id")): item
            for item in (data.get("organizations") or ())
            if item.get("id")
        }
        for index, faction in enumerate(data.get("factions") or ()):
            if not isinstance(faction, Mapping):
                continue
            side = str(faction.get("side") or "")
            if not side:
                continue
            faction_id = str(faction.get("id") or side)
            own_records = [
                item for item in characters if item.get("side") == side
            ]
            specs = []
            for record in own_records:
                spec = _character_from_record(
                    record,
                    self.seed + index * 1009 + len(specs) * 17,
                )
                specs.append(spec)
                self._character_index[str(record.get("id"))] = spec
            organization_id = str(faction.get("organization_id") or "")
            organization_record = organizations.get(organization_id, {})
            runtime_cfg = _as_mapping(organization_record.get("runtime"))
            leader = next(
                (
                    item
                    for item in own_records
                    if item.get("is_faction_leader")
                ),
                own_records[0] if own_records else {},
            )
            parameters = _organization_parameters(
                runtime_cfg.get("parameters")
            )
            organization = None
            if specs:
                organization = OrganizationRuntime(
                    name=str(
                        organization_record.get("name")
                        or faction.get("name")
                        or faction_id
                    ),
                    side=side,
                    characters=specs,
                    parameters=parameters,
                    complete_weight=_clamp(
                        runtime_cfg.get(
                            "complete_weight",
                            PRESET_DEFAULTS["organization_complete_weight"],
                        )
                    ),
                    leader_id=str(
                        runtime_cfg.get("leader_id")
                        or leader.get("name")
                        or ""
                    )
                    or None,
                    satisfaction_per_tick=_number(
                        runtime_cfg.get("satisfaction_per_tick"),
                        ORGANIZATION_RUNTIME_DEFAULTS["satisfaction_per_tick"],
                    ),
                    contribution_cost=_number(
                        runtime_cfg.get("contribution_cost"),
                        ORGANIZATION_RUNTIME_DEFAULTS["contribution_cost"],
                    ),
                    coercion_factor=_number(
                        runtime_cfg.get("coercion_factor"),
                        ORGANIZATION_RUNTIME_DEFAULTS["coercion_factor"],
                    ),
                    leader_morale_bonus=_number(
                        runtime_cfg.get("leader_morale_bonus"),
                        ORGANIZATION_RUNTIME_DEFAULTS["leader_morale_bonus"],
                    ),
                    allow_rejoin=bool(
                        runtime_cfg.get(
                            "allow_rejoin",
                            ORGANIZATION_RUNTIME_DEFAULTS["allow_rejoin"],
                        )
                    ),
                    jitter_salt=organization_id or faction_id,
                )
            assets = {
                str(key): _clamp(value)
                for key, value in _as_mapping(faction.get("assets")).items()
            }
            organ_interactions = [
                dict(item)
                for item in (faction.get("organ_interactions") or ())
                if isinstance(item, Mapping) and item.get("id")
            ]
            character_interactions = [
                dict(item)
                for item in (faction.get("character_interactions") or ())
                if isinstance(item, Mapping) and item.get("id")
            ]
            if not character_interactions:
                character_interactions = [
                    dict(item) for item in DEFAULT_CHARACTER_INTERACTIONS
                ]
            automaton_interactions = [
                dict(item)
                for item in (faction.get("automaton_interactions") or ())
                if isinstance(item, Mapping) and item.get("id")
            ]
            if not automaton_interactions:
                automaton_interactions = [
                    dict(item) for item in DEFAULT_AUTOMATON_INTERACTIONS
                ]
            order_model = _merged_mapping(
                self.order_model, faction.get("order_model")
            )
            orders = [
                dict(item)
                for item in (
                    faction.get("orders")
                    or order_model.get("orders")
                    or ()
                )
                if isinstance(item, Mapping) and item.get("id")
            ]
            organs = []
            for organ_record in faction.get("organs") or ():
                if not isinstance(organ_record, Mapping):
                    continue
                organ = OrganRuntime.from_record(
                    organ_record, interactions=organ_interactions
                )
                if organ is not None:
                    organs.append(organ)
            subfactions = _build_subfactions(
                faction, organs, organ_interactions
            )
            geometry = _build_geometry(faction_id, faction, organs)
            network_problems = validate_organ_network(organs)
            if network_problems:
                raise AutomataCampaignError(
                    "%s: %s"
                    % (faction_id, "; ".join(network_problems))
                )
            runtime = FactionRuntime(
                side=side,
                id=faction_id,
                name=str(faction.get("name") or faction_id),
                record=dict(faction),
                characters=specs,
                organization=organization,
                income={
                    str(key): _number(value, 0.0)
                    for key, value in _as_mapping(
                        faction.get("income")
                    ).items()
                },
                score_assets={
                    str(key): _number(value, 0.0)
                    for key, value in _as_mapping(
                        faction.get("score_assets")
                    ).items()
                },
                actions=[
                    dict(item)
                    for item in (faction.get("actions") or ())
                    if isinstance(item, Mapping) and item.get("id")
                ],
                organs=organs,
                subfactions=subfactions,
                course_weight_shift=_number(
                    self.model.get("course_weight_shift"), 0.18
                ),
                geometry=geometry,
                automaton_interactions=automaton_interactions,
                character_interactions=character_interactions,
                orders=orders,
                relations=self.relations,
            )
            # Стартовые значения пресета задают фон, а не отдельный
            # кошелёк: подбираем контекст так, чтобы производные активы
            # начинались с данных шаблона.
            for key in asset_keys(runtime):
                runtime.context.setdefault(str(key), 0.5)
            for key, value in assets.items():
                runtime.set_asset(key, value)
            runtime.baseline_context = dict(runtime.context)
            runtime.baseline_assets = runtime.derived_assets()
            self.factions[side] = runtime

    def faction(self, side):
        return self.factions.get(str(side or ""))

    def relation_view(self, source=None, target=None):
        """Срез отношений для UI и диалога.

        Без аргументов — вся матрица; с ``source`` — исходящие связи
        субъекта; с ``source`` и ``target`` — обе стороны пары.
        """
        model = _relation_model(self.data)
        axes = list(self.relations.axes)
        labels = relation_axis_labels_from_config(
            {"relation_axes": model.get("axes")}, axes
        )
        if source and target:
            return {
                "source": str(source),
                "target": str(target),
                "outgoing": self.relations.axes_for(source, target),
                "incoming": self.relations.axes_for(target, source),
                "axes": axes,
                "labels": labels,
            }
        return {
            "source": str(source or ""),
            "axes": axes,
            "labels": labels,
            "limit": self.relations.limit,
            "matrix": self.relations.view(source),
        }

    def geometry(self, side):
        """Семантическая геометрия стороны или ``None``."""
        faction = self.faction(side)
        if faction is None:
            return None
        return getattr(faction, "geometry", None)

    def geometry_distance(self, side, source, target):
        """Кратчайшее расстояние по сети стороны; ``inf`` без пути."""
        graph = self.geometry(side)
        if graph is None:
            return math.inf
        return graph.distance(source, target)

    def geometry_path(self, side, source, target):
        """Канонический путь стороны или ``None``."""
        graph = self.geometry(side)
        if graph is None:
            return None
        return graph.path(source, target)

    def geometry_angle(self, side, node, source, target):
        """Локальный угол между двумя соседями узла, радианы."""
        graph = self.geometry(side)
        if graph is None:
            raise AutomataCampaignError(
                "у стороны %s нет геометрии" % side
            )
        return graph.angle(node, source, target)

    def geometry_bearing(self, side, observer, source, target):
        """Угол между направлениями на две цели из наблюдателя."""
        graph = self.geometry(side)
        if graph is None:
            raise AutomataCampaignError(
                "у стороны %s нет геометрии" % side
            )
        return graph.angle_between_targets(observer, source, target)

    @property
    def player(self):
        return self.faction(self.player_side)

    @property
    def rival(self):
        return self.faction(self.rival_side)

    def avatar_character(self):
        """``Character`` аватара или ``None``.

        Аватар может не иметь фракции (свободный режим); тогда персонаж
        ищется по всем сторонам. Отсутствие аватара не ошибка: старые
        снимки и сценарии без героя продолжают работать.
        """
        if self.avatar is None:
            return None
        if self.avatar.faction_id:
            faction = self.faction(self.avatar.faction_id)
            if faction is not None:
                found = faction.character(self.avatar.character_id)
                if found is not None:
                    return found
        for faction in self.factions.values():
            found = faction.character(self.avatar.character_id)
            if found is not None:
                return found
        return None

    def assign_avatar_office(self, office_id):
        """Сменить должность аватара; потеря поста — не поражение."""
        if self.avatar is None:
            return None
        office_id = str(office_id or "").strip()
        character = self.avatar_character()
        if character is not None:
            character.campaign_post_id = office_id
            character.campaign_post = office_id
        self.avatar = self.avatar.with_office(office_id)
        return self.avatar

    def move_avatar(self, scene_id):
        """Перевести аватара в сцену. Сцена — данные, а не сторона."""
        if self.avatar is None:
            return None
        scene_id = str(scene_id or "").strip()
        character = self.avatar_character()
        if character is not None:
            character.scene_id = scene_id
        self.avatar = self.avatar.with_scene(scene_id)
        return self.avatar

    def _sync_avatar_state(self):
        """Сделать аватар источником истины для флагов персонажа.

        Снимок хранит аватар отдельно, а ``FactionRuntime`` — записи
        персонажей. После загрузки флаги ``campaign_is_player`` и
        должность/сцена приводятся к аватару, иначе старый сейв мог бы
        оставить игроком лидера.
        """
        if self.avatar is None:
            return
        for faction in self.factions.values():
            for character in faction.characters:
                character.campaign_is_player = (
                    str(getattr(character, "campaign_id", "") or "")
                    == self.avatar.character_id
                )
        character = self.avatar_character()
        if character is None:
            return
        previous_id = str(
            getattr(character, "campaign_post_id", "") or ""
        )
        if previous_id != self.avatar.office_id:
            character.campaign_post = self.avatar.office_id
        character.campaign_post_id = self.avatar.office_id
        character.scene_id = self.avatar.scene_id

    def rival_of(self, side):
        side = str(side or "")
        explicit = self._rivals.get(side)
        if explicit:
            return explicit
        faction = self.faction(side)
        if faction is not None:
            explicit = str(faction.record.get("rival_side") or "")
            if explicit:
                return explicit
        if side == self.rival_side:
            return self.player_side
        return self.rival_side

    def other_sides(self, side):
        return [item for item in self.factions if item != str(side or "")]

    def composite(self, side=None):
        """Составной автомат сети органов стороны.

        Это диагностическое представление (WORLD_CORE_MODEL §2.7):
        `OrganRuntime` остаётся источником истины, а сеть отдаёт
        агрегаты `F/E/S` и распределение работы. ``side`` по умолчанию —
        сторона игрока; неизвестная сторона возвращает ``None``.
        """
        side = str(side or self.player_side)
        faction = self.faction(side)
        if faction is None:
            return None
        return organ_composite(
            faction.organs,
            root_id="%s:faction" % side,
        )

    def _activate_clock(self):
        """Разбудить цикл без построения полного снимка.

        Отделено от :meth:`ensure_clock`, потому что игровой цикл вызывает
        активацию каждый кадр. Полный ``snapshot()`` тяжёлый: он обходит
        персонажей, органы и производные активы, поэтому в горячем пути
        нужен только переход состояния.
        """
        if self.finished:
            return
        if not self._turn_active:
            self._turn_active = True
            if self.turn <= 0:
                self.turn = 1
            self.actions_left = max(
                self.actions_left, self.actions_per_cycle
            )

    def ensure_clock(self):
        """Активировать реальное время, не сдвигая организационный цикл.

        Свободный режим идёт непрерывно: открытие экрана или действие
        игрока не являются TBS-ходом и не должны увеличивать ``turn``.
        Цикл двигают только ``advance_time`` и внутренние таймеры.
        """
        self._activate_clock()
        return self.snapshot()

    def begin_turn(self):
        """Legacy: начать ход, если он ещё не начат.

        Оставлен для старых сейвов, CLI и тестов. Игровые экраны
        используют ``ensure_clock`` и не переключают цикл вручную.
        """
        if self.finished or self._turn_active:
            return self.snapshot()
        self.turn += 1
        self.actions_left = self.actions_per_cycle
        self._turn_active = True
        self.reset_npc_tick_budget()
        return self.snapshot()

    def action_budget(self):
        return {
            "turn": self.turn,
            "actions_per_cycle": self.actions_per_cycle,
            # Совместимый ключ для старых экранов и сюжетных переменных.
            "actions_per_turn": self.actions_per_cycle,
            "actions_left": self.actions_left,
            "active": bool(self._turn_active),
            "finished": bool(self.finished),
        }

    def _interval(self, name):
        """Положительный интервал реального времени из конфига.

        Новый канонический ключ — ``cycle_seconds``; старые снимки и
        шаблоны могли хранить ``turn_seconds``, поэтому чтение откатывается
        к нему, если канонического ключа нет.
        """
        value = self.realtime.get(name)
        if value is None and name == "cycle_seconds":
            value = self.realtime.get("turn_seconds")
        return max(1e-6, _number(value, 1e-6))

    def _snapshot_realtime(self):
        """Снимок интервалов с каноническими и совместимыми ключами."""
        data = dict(self.realtime)
        seconds = self.cycle_seconds
        data["cycle_seconds"] = seconds
        data["turn_seconds"] = seconds
        return data

    @property
    def cycle_seconds(self):
        return self._interval("cycle_seconds")

    @property
    def turn_seconds(self):
        """Совместимый псевдоним ``cycle_seconds``."""
        return self.cycle_seconds

    @property
    def actions_per_turn(self):
        """Совместимый псевдоним ``actions_per_cycle``."""
        return self.actions_per_cycle

    @actions_per_turn.setter
    def actions_per_turn(self, value):
        self.actions_per_cycle = max(1, int(_number(value, 1)))

    @property
    def max_turns(self):
        """Совместимый псевдоним ``cycle_limit``."""
        return self.cycle_limit

    @max_turns.setter
    def max_turns(self, value):
        if value is None:
            self.cycle_limit = None
            return
        try:
            limit = int(value)
        except (TypeError, ValueError):
            limit = 0
        self.cycle_limit = limit if limit > 0 else None

    @property
    def action_interval_seconds(self):
        return self._interval("action_interval_seconds")

    @property
    def ai_interval_seconds(self):
        return self._interval("ai_interval_seconds")

    @property
    def organization_interval_seconds(self):
        return self._interval("organization_interval_seconds")

    @property
    def realtime_scale(self):
        """Сколько игровых секунд проходит за одну реальную секунду.

        Физический инвариант проекта: масштаб всегда ``1:1``. Экран
        вызывает ``advance_realtime(dt)``; ускорение задаётся только
        множителем ``speed``, а не скрытым пересчётом часов. Старый
        контент со значением вроде ``3600`` не может ускорить время:
        при загрузке он нормализуется к ``1.0`` с предупреждением.
        """
        return PHYSICAL_SECONDS_PER_REAL_SECOND

    def time_label(self):
        """Игровое время: ``ЧЧ:ММ:СС``, а с первых суток — ``Д д ЧЧ:ММ:СС``."""
        total = max(0, int(self.elapsed))
        days, remainder = divmod(total, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if days:
            return "%d д %02d:%02d:%02d" % (
                days,
                hours,
                minutes,
                seconds,
            )
        return "%02d:%02d:%02d" % (hours, minutes, seconds)

    def duration_label(self, seconds):
        """Человеческая длительность для UI: минуты, часы, дни, недели."""
        seconds = max(0.0, _number(seconds, 0.0))
        if seconds >= 86400.0:
            return "%.1f дн" % (seconds / 86400.0)
        if seconds >= 3600.0:
            return "%.1f ч" % (seconds / 3600.0)
        if seconds >= 60.0:
            return "%.0f мин" % (seconds / 60.0)
        return "%.0f с" % seconds

    def speed_label(self):
        # Шрифт интерфейса не содержит знака «×», поэтому темп пишется
        # латинской «x»: так подпись читается на всех экранах.
        return "x%d" % int(self.speed)

    def speed_cap(self):
        return int(self.speed_levels[-1])

    def can_speed_up(self):
        return int(self.speed) < self.speed_cap()

    def can_slow_down(self):
        """Можно ли отменить ускорение и вернуться к более медленному темпу."""
        return int(self.speed) > int(self.speed_levels[0])

    def speed_up(self):
        """Ускорить время до следующего разрешённого значения.

        Замедление ниже физической секунды, пауза и откат не
        предусмотрены: минимальная скорость — ``speed_levels[0]`` (обычно
        ``1×``). Ускорение можно отменить методом ``slow_down()``.
        """
        if self.finished:
            return self.speed
        for value in self.speed_levels:
            if value > int(self.speed):
                self.speed = int(value)
                break
        return self.speed

    def slow_down(self):
        """Отменить одно ускорение, но не ниже минимальной скорости."""
        if self.finished:
            return self.speed
        for value in reversed(self.speed_levels):
            if value < int(self.speed):
                self.speed = int(value)
                break
        return self.speed

    def reset_speed(self):
        """Вернуть физический темп ``1×`` (если он есть в конфиге)."""
        self.speed = int(self.speed_levels[0])
        return self.speed

    def set_speed(self, value):
        """Задать любую разрешённую скорость не ниже минимальной.

        ``False`` возвращается для неизвестного значения или попытки
        опуститься ниже физического темпа; пауза и откат не допускаются.
        """
        try:
            requested = int(value)
        except (TypeError, ValueError):
            return False
        minimum = int(self.speed_levels[0])
        if requested < minimum:
            return False
        allowed = [level for level in self.speed_levels if level >= requested]
        if not allowed:
            return False
        self.speed = int(allowed[0])
        return True

    def _advance_seconds(
        self, seconds, *, scale=True, tick_rounds=True, tick_ai=True
    ):
        """Продвинуть состояние без построения снимка.

        ``seconds`` — уже игровые секунды (до умножения на ``speed``).
        Это горячий путь игрового цикла: экран обновляется 60 раз в
        секунду, а ``snapshot()`` обходит всех персонажей и органы.
        Поэтому снимок строится только по явному запросу.

        ``scale=False`` нужен эмуляции: она пропускает выбранный
        интервал игрового времени целиком, не умножая его на скорость.
        ``tick_rounds=False`` и ``tick_ai=False`` тоже нужны эмуляции:
        длинный шаг не должен прогонять полную автономию персонажей и
        все ответы ИИ на каждый игровой день.
        """
        if self.finished:
            return
        if seconds <= 0.0:
            return
        self._activate_clock()
        scaled = seconds * float(self.speed) if scale else float(seconds)
        self.elapsed += scaled
        self._regenerate_actions(scaled)
        if tick_ai:
            self._advance_ai(scaled)
        self._advance_rounds(scaled, tick_rounds=tick_rounds)
        self._advance_story_events(scaled)
        self.dispatch.tick(scaled)
        self._advance_processes(scaled)

    def advance_time(self, dt, *, snapshot=True):
        """Продвинуть кампанию на ``dt`` игровых секунд.

        Это базовый вызов для тестов и legacy-кода. Игровые экраны
        используют ``advance_realtime``, который переводит реальные
        секунды кадра в игровые через ``realtime_scale``. Внутри обеих
        функций время идёт со скоростью ``speed`` (не меньше 1); работа,
        ИИ и организации обновляются непрерывно, без кнопки «завершить
        ход»; пауза, замедление и откат отсутствуют.

        ``snapshot=False`` нужен горячему пути: снимок стоит дороже
        самого шага и не нужен, пока интерфейс не запросит его явно.
        """
        try:
            seconds = float(dt)
        except (TypeError, ValueError):
            seconds = 0.0
        self._advance_seconds(seconds)
        return self.snapshot() if snapshot else None

    def advance_realtime(self, dt, *, snapshot=True):
        """Продвинуть кампанию на ``dt`` реальных секунд из игрового цикла.

        При ``1×`` это ровно ``dt`` игровых секунд; при ``2×`` — ``2·dt``.
        Никакой другой масштаб не применяется: физическое соответствие
        времени — инвариант проекта. Экраны передают ``snapshot=False``,
        чтобы не строить полный снимок каждый кадр.
        """
        try:
            seconds = float(dt)
        except (TypeError, ValueError):
            seconds = 0.0
        self._advance_seconds(seconds * self.realtime_scale)
        return self.snapshot() if snapshot else None

    def advance_simulation(self, seconds, *, snapshot=False, tick=True):
        """Пропустить ровно ``seconds`` игрового времени.

        В отличие от ``advance_time``/``advance_realtime`` множитель
        скорости не применяется: эмуляция принимает шаг в игровых часах
        или днях. Это осознанный пропуск времени, а не ускорение темпа,
        поэтому физический инвариант реального цикла не меняется.

        ``tick=False`` пропускает организационный такт и ответ ИИ:
        месяцы и годы нельзя прогонять полной автономией всех персонажей
        на каждый день. Эмуляция включает такт несколько раз за шаг,
        а работа, события и процессы считаются на всём интервале.
        """
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            seconds = 0.0
        self._advance_seconds(
            seconds, scale=False, tick_rounds=False, tick_ai=bool(tick)
        )
        if tick and not self.finished and seconds > 0.0:
            self._tick_organizations()
            self._check_outcome()
        return self.snapshot() if snapshot else None

    def _regenerate_actions(self, seconds):
        if self.finished:
            return
        if self.actions_left >= self.actions_per_cycle:
            self._action_progress = 0.0
            return
        self._action_progress += seconds
        interval = self.action_interval_seconds
        while (
            self._action_progress >= interval
            and self.actions_left < self.actions_per_cycle
        ):
            self.actions_left += 1
            self._action_progress -= interval
        if self.actions_left >= self.actions_per_cycle:
            self._action_progress = 0.0

    def _history_record(self):
        """Короткая запись хода для истории.

        Полный ``snapshot()`` обходит всех персонажей и органы. История
        нужна только как хронология циклов, поэтому хранит сводку, а не
        тяжёлый снимок мира.
        """
        return {
            "turn": int(self.turn),
            "elapsed": round(float(self.elapsed), 6),
            "outcome": self.outcome,
            "finished": bool(self.finished),
        }

    def _advance_rounds(self, seconds, *, tick_rounds=True):
        if self.finished:
            return
        self._round_progress += seconds
        interval = self.organization_interval_seconds
        if interval <= 0.0:
            return
        steps = int(self._round_progress // interval)
        if steps <= 0:
            return
        self._round_progress -= steps * interval
        if not tick_rounds:
            # Эмуляция: ходы идут, но полный такт организаций будет
            # вызван отдельными «крупными» срезами.
            self.turn += steps
            self.history.append(self._history_record())
            return
        for _ in range(steps):
            if self.finished:
                break
            self.turn += 1
            self._tick_organizations()
            self._check_outcome()
            self.history.append(self._history_record())
