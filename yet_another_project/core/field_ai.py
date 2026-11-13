"""
core/field_ai.py

Полевой ИИ военных подразделений.

Автономные (не игровые) подразделения выбирают приказы, перемещаются
и создают боестолкновения. Поддерживает наступательные цели
(objective): подразделения с целью движутся к ней, а не к ближайшему
противнику, что моделирует прорыв и выход во фланг и тыл; по пути
атакуются цели в радиусе досягаемости.

Концентрация обеспечивается фокус-целями дивизий (шверпункт):
все юниты дивизии сходятся на одну точку. Боестолкновение
создаётся при контакте без ratio-порогов — от испарения защищают
бюджет потерь в боевой системе и отход при тяжёлых потерях,
а не блокировки вступления в бой, которые приводили к замеранию
фронта. Юнит с целью вблизи противника держит атакующую postura
и не паркуется в отдых/оборону. ИИ работает независимо от LOD.

Перемещение подразделений игрока полевым ИИ не выполняется:
юниты игрока движутся только исполнителем приказов движка
(core.engine._execute_player_orders), чтобы поведение войск
игрока определялось исключительно приказами игрока. Создание
боестолкновений при контакте выполняется для всех сторон.

События модуля записываются в файл operation_ozverin.log в корне
проекта и дублируются в консоль средствами core.log_journal.
"""

from .log_journal import get_logger

logger = get_logger("core.field_ai")

RANGE_BARRAGE = 3
RANGE_MELEE = 1
RECONSIDER_HOURS = 1.0
RESUME_FATIGUE_MAX = 0.4
RESUME_CASUALTIES_MAX = 0.6
ATTACK_FAMILY = {"aggressive_attack", "attack", "cautious_attack"}
RETREAT_FAMILY = {"movement", "forced_march"}
POSTURE_RADIUS = 6


class FieldAI:
    """
    Полевой ИИ военных подразделений.

    Управляет автономными сущностями: выбор приказов, перемещение
    к целям прорыва или к противнику, создание боестолкновений.
    Использует фокус-цели дивизий для концентрации сил и
    utility-функцию для выбора приказов. Перемещение юнитов игрока
    не выполняет — ими управляет исполнитель приказов движка.

    Attributes:
        state: Состояние игрового мира (WorldState).
        ot: Таблица приказов (OrderTable).
        rng: Генератор случайных чисел.
        engine: Ссылка на движок (TickEngine) или None.
        player_ordered: Множество индексов с приказом игрока.
        move_accum: Накопители дробного перемещения.
        focus_targets: Отображение корня дивизии на индекс цели.
        objectives: Словарь индексов на цели прорыва (x, y).
    """

    def __init__(self, state, order_table, rng):
        """
        Инициализирует полевой ИИ.

        Заполняет отображение идентификаторов приказов на индексы,
        инициализирует накопители и фокус-цели. Логирует количество
        сущностей, приказов и целей.

        Args:
            state: Состояние игрового мира (WorldState).
            order_table: Таблица приказов (OrderTable).
            rng: Генератор случайных чисел.
        """
        self.state = state
        self.ot = order_table
        self.rng = rng
        self.engine = None
        self.player_ordered = set()
        self.move_accum = {}
        self.reconsider_accum = 0.0
        self.focus_targets = {}
        self.objectives = getattr(state, "objectives", {}) or {}
        self.id_to_order = {
            o["id"]: i for i, o in enumerate(order_table.orders)
        }
        self._last_dist = float("inf")
        logger.info(
            "Инициализация FieldAI: сущностей=%d, приказов=%d, целей=%d",
            state.count, len(order_table.orders), len(self.objectives),
        )

    def mark_player_ordered(self, idx):
        """
        Помечает сущность как получившую приказ игрока.

        После пометки полевой ИИ не будет автоматически менять
        приказ этой сущности до следующего пересмотра.

        Args:
            idx: Индекс сущности.
        """
        self.player_ordered.add(idx)
        logger.info(
            "Сущность %s помечена как получившая приказ игрока",
            self.state.label_of(idx),
        )

    def _military_indices(self):
        """
        Генератор индексов военных подразделений с сегментом order.

        Yields:
            int: Индекс военной сущности.
        """
        st = self.state
        for i in range(st.count):
            cfg = st.class_configs[st.class_ids[i]]
            if (
                cfg.class_name == "military_unit"
                and "order" in cfg.segment_layout.segments
            ):
                yield i

    def _is_dead(self, idx):
        """
        Проверяет, уничтожена ли сущность.

        Сущность считается уничтоженной, если сегмент condition
        равен 0 или канал U_manpower <= 0.

        Args:
            idx: Индекс сущности.

        Returns:
            bool: True, если сущность уничтожена.
        """
        st = self.state
        cfg = st.class_configs[st.class_ids[idx]]
        if "condition" in cfg.segment_layout.segments:
            if st.read_segment(idx, "condition") == 0:
                return True
        ch = cfg.voltage_layout.channel_index.get("U_manpower")
        if ch is not None and st.read_voltage(idx, "U_manpower") <= 0:
            return True
        return False

    def _safe_order_index(self, order_idx):
        """
        Приводит индекс приказа к допустимому диапазону таблицы.

        При ошибке преобразования или выходе за границы возвращает 0.

        Args:
            order_idx: Индекс приказа (int или приводимое к int).

        Returns:
            int: Корректный индекс приказа.
        """
        n = len(self.ot.orders)
        if n == 0:
            return 0
        try:
            order_idx = int(order_idx)
        except Exception:
            order_idx = 0
        if order_idx < 0 or order_idx >= n:
            return 0
        return order_idx

    def _order_id(self, idx):
        """
        Возвращает строковый id текущего приказа сущности.

        Args:
            idx: Индекс сущности.

        Returns:
            str: Идентификатор приказа.
        """
        order = self._safe_order_index(
            self.state.read_segment(idx, "order")
        )
        return self.ot.orders[order]["id"]

    def _mobility(self, idx):
        """
        Возвращает коэффициент мобильности из боевой модели.

        Args:
            idx: Индекс сущности.

        Returns:
            float: Коэффициент мобильности (по умолчанию 1.0).
        """
        cfg = self.state.class_configs[self.state.class_ids[idx]]
        model = cfg.combat_model or {}
        return float(model.get("mobility", 1.0))

    def _quant(self, idx):
        """
        Вычисляет количественную боевую силу сущности.

        Суммирует произведения значений каналов на веса из
        weapon_weights боевой модели.

        Args:
            idx: Индекс сущности.

        Returns:
            float: Количественная боевая сила.
        """
        st = self.state
        cfg = st.class_configs[st.class_ids[idx]]
        model = cfg.combat_model or {}
        total = 0.0
        for channel, weight in model.get("weapon_weights", {}).items():
            ch = cfg.voltage_layout.channel_index.get(channel)
            if ch is not None:
                total += st.read_voltage(idx, channel) * weight
        return total

    def _casualties(self, idx):
        """
        Возвращает накопленные потери сущности в диапазоне [0, 1].

        Args:
            idx: Индекс сущности.

        Returns:
            float: Уровень потерь.
        """
        st = self.state
        cfg = st.class_configs[st.class_ids[idx]]
        if "U_casualties" in cfg.voltage_layout.channel_index:
            return float(st.read_voltage(idx, "U_casualties"))
        return 0.0

    def _morale_norm(self, idx):
        """
        Возвращает нормированную мораль сущности.

        Args:
            idx: Индекс сущности.

        Returns:
            float: Мораль в диапазоне [0, 1]. По умолчанию 0.5.
        """
        st = self.state
        cfg = st.class_configs[st.class_ids[idx]]
        if "morale" in cfg.segment_layout.segments:
            mx = cfg.segment_layout.max_value("morale")
            if mx > 0:
                return st.read_segment(idx, "morale") / mx
        return 0.5

    def _fatigue_norm(self, idx):
        """
        Возвращает нормированную усталость сущности.

        Args:
            idx: Индекс сущности.

        Returns:
            float: Усталость в диапазоне [0, 1]. По умолчанию 0.0.
        """
        st = self.state
        cfg = st.class_configs[st.class_ids[idx]]
        if "fatigue" in cfg.segment_layout.segments:
            mx = cfg.segment_layout.max_value("fatigue")
            if mx > 0:
                return st.read_segment(idx, "fatigue") / mx
        return 0.0

    def _root_of(self, idx):
        """
        Возвращает индекс корневой сущности (дивизии) для юнита.

        Поднимается по parent_ids до корня или до лимита в 16 шагов.

        Args:
            idx: Индекс сущности.

        Returns:
            int: Индекс корневой сущности.
        """
        st = self.state
        cur = idx
        guard = 0
        while st.parent_ids[cur] != -1 and guard < 16:
            cur = st.parent_ids[cur]
            guard += 1
        return cur

    def _nearest_enemy(self, idx):
        """
        Ищет ближайшего живого противника по чебышевскому расстоянию.

        Args:
            idx: Индекс сущности.

        Returns:
            tuple[int | None, float]: Индекс ближайшего врага и
                расстояние до него. (None, inf) если врагов нет.
        """
        st = self.state
        my_faction = st.factions[idx]
        best = None
        best_dist = float("inf")
        for j in range(st.count):
            if j == idx or st.factions[j] == my_faction:
                continue
            if self._is_dead(j):
                continue
            cfg = st.class_configs[st.class_ids[j]]
            if cfg.class_name != "military_unit":
                continue
            dx = st.coords[j, 0] - st.coords[idx, 0]
            dy = st.coords[j, 1] - st.coords[idx, 1]
            dist = max(abs(dx), abs(dy))
            if dist < best_dist:
                best = j
                best_dist = dist
        return best, best_dist

    def _chosen_enemy(self, idx):
        """
        Выбирает цель для автономного юнита.

        Приоритет отдаётся фокус-цели дивизии (шверпункт), если она
        жива. Иначе возвращается ближайший противник.

        Args:
            idx: Индекс сущности.

        Returns:
            tuple[int | None, float]: Индекс цели и расстояние.
        """
        st = self.state
        focus = self.focus_targets.get(self._root_of(idx))
        if focus is not None and not self._is_dead(focus):
            d = max(
                abs(st.coords[focus, 0] - st.coords[idx, 0]),
                abs(st.coords[focus, 1] - st.coords[idx, 1]),
            )
            return focus, d
        return self._nearest_enemy(idx)

    def _update_focus_targets(self):
        """
        Пересчитывает фокус-цели для каждой дивизии противника.

        Для каждой вражеской дивизии находит ближайшую к её центроиду
        слабую единицу игрока. Все юниты дивизии сходятся на одну
        точку, создавая локальное превосходство вместо разрозненных
        атак. Score = distance + quant_strength / 500.
        """
        st = self.state
        player_faction = st.factions[st.player_idx]
        player_units = [
            j for j in range(st.count)
            if st.factions[j] == player_faction
            and st.class_configs[st.class_ids[j]].class_name == "military_unit"
            and not self._is_dead(j)
        ]
        if not player_units:
            self.focus_targets = {}
            return
        roots = {}
        for i in range(st.count):
            if not self._is_autonomous(i):
                continue
            cfg = st.class_configs[st.class_ids[i]]
            if cfg.class_name != "military_unit":
                continue
            if self._is_dead(i):
                continue
            roots.setdefault(self._root_of(i), []).append(i)
        new_focus = {}
        for root, members in roots.items():
            cx = sum(st.coords[m, 0] for m in members) / len(members)
            cy = sum(st.coords[m, 1] for m in members) / len(members)
            best = None
            best_score = None
            for j in player_units:
                d = max(
                    abs(st.coords[j, 0] - cx), abs(st.coords[j, 1] - cy)
                )
                score = d + self._quant(j) / 500.0
                if best_score is None or score < best_score:
                    best_score = score
                    best = j
            if best is not None:
                new_focus[root] = best
        self.focus_targets = new_focus

    def _is_autonomous(self, idx):
        """
        Проверяет, автономна ли сущность (не фракция игрока).

        Args:
            idx: Индекс сущности.

        Returns:
            bool: True, если сущность автономна.
        """
        st = self.state
        return st.factions[idx] != st.factions[st.player_idx]

    def _order_writable(self, idx, order_idx):
        """
        Проверяет, что движок примет новый приказ без отката.

        Делегирует проверку в engine._order_allowed если доступен.

        Args:
            idx: Индекс сущности.
            order_idx: Индекс нового приказа.

        Returns:
            bool: True, если приказ можно установить.
        """
        if self.engine is None:
            return True
        checker = getattr(self.engine, "_order_allowed", None)
        if checker is None:
            return True
        try:
            return bool(checker(idx, order_idx))
        except Exception:
            return True

    def _choose_order(self, idx, enemy, dist):
        """
        Выполняет utility-выбор приказа автономной сущностью.

        Юнит с наступательной целью вблизи противника и без тяжёлых
        потерь не может выбрать отдых/оборону/отход — держит
        атакующую postura, чтобы давление не выдыхалось.

        Args:
            idx: Индекс сущности.
            enemy: Индекс противника или None.
            dist: Расстояние до противника.

        Returns:
            int | None: Индекс нового приказа или None, если
                текущий приказ оптимален.
        """
        st = self.state
        my_q = self._quant(idx)
        en_q = self._quant(enemy) if enemy is not None else 0.0
        ratio = my_q / (my_q + en_q + 1e-6)
        cas = self._casualties(idx)
        morale = self._morale_norm(idx)
        fatigue = self._fatigue_norm(idx)
        cur_id = self._order_id(idx)
        if (
            self.objectives.get(idx) is not None
            and cur_id in ATTACK_FAMILY
            and cas < 0.45
            and morale > 0.25
        ):
            return None
        scores = {
            "aggressive_attack": (
                ratio * 1.0
                - cas * 1.2
                + morale * 0.15
                + (0.10 if ratio > 0.65 else -0.40)
            ),
            "attack": (
                ratio * 0.8
                - cas * 0.9
                + morale * 0.10
                + (0.05 if ratio > 0.60 else -0.30)
            ),
            "cautious_attack": (
                ratio * 0.6
                - cas * 0.6
                + (0.02 if ratio > 0.55 else -0.15)
            ),
            "defense": 0.35 + cas * 0.8 + (1.0 - ratio) * 1.3,
            "holding_defense": 0.30 + cas * 0.7 + (1.0 - ratio) * 1.1,
            "rest": -0.4 + fatigue * 1.2 + (0.6 if dist > 6 else -0.9),
            "withdrawal": -0.8 + cas * 1.8 + (0.4 if morale < 0.3 else 0.0),
        }
        if (
            self.objectives.get(idx) is not None
            and dist <= POSTURE_RADIUS
            and cas < 0.5
            and fatigue < 0.6
        ):
            for k in ("rest", "defense", "holding_defense", "withdrawal"):
                scores.pop(k, None)
        candidates = {
            k: v for k, v in scores.items() if k in self.id_to_order
        }
        if not candidates:
            return None
        best_id = max(candidates, key=candidates.get)
        if candidates[best_id] <= candidates.get(cur_id, 0.0) + 0.1:
            return None
        return self.id_to_order[best_id]

    def _ensure_engagement(self, idx, enemy):
        """
        Создаёт боестолкновение между сущностями, если оно отсутствует.

        Проверяет существующие engagements в движке и добавляет новое
        только если пара (attacker, defender) ещё не представлена.

        Args:
            idx: Индекс атакующей сущности.
            enemy: Индекс защищающейся сущности.
        """
        if self.engine is None:
            return
        st = self.state
        a_id = st.entity_ids[idx]
        d_id = st.entity_ids[enemy]
        for eng in self.engine.engagements:
            if isinstance(eng, dict):
                if (
                    eng.get("attacker") == a_id
                    and eng.get("defender") == d_id
                ):
                    return
            else:
                try:
                    if eng[0] == a_id and eng[1] == d_id:
                        return
                except Exception:
                    continue
        self.engine.engagements.append({
            "attacker": a_id,
            "defender": d_id,
            "projection": "auto",
            "duration": 2,
        })
        mp = st.read_voltage(idx, "U_manpower")
        st.log_event(
            idx,
            f"{st.label_of(idx)}: контакт с {st.label_of(enemy)}, "
            f"дистанция {int(self._last_dist)} км, л.с. {mp:.0f}",
        )
        logger.info(
            "Создано боестолкновение: %s атакует %s (дистанция %d км)",
            st.label_of(idx), st.label_of(enemy), int(self._last_dist),
        )

    def _move(self, idx, order, enemy, dt_hours):
        """
        Перемещает автономную сущность к точке движения с учётом
        мобильности.

        Использует накопитель дробного перемещения для корректной
        обработки скоростей меньше одной клетки за тик. Обновляет
        пространственный индекс через lod_manager.notify_moved.
        Вызывается только для автономных сущностей: перемещением
        юнитов игрока управляет исполнитель приказов движка.

        Args:
            idx: Индекс сущности.
            order: Индекс текущего приказа.
            enemy: Индекс противника или None.
            dt_hours: Длительность шага в часах.
        """
        st = self.state
        order = self._safe_order_index(order)
        speed = float(self.ot.move_speed[order]) * self._mobility(idx)
        if speed <= 0.0:
            return
        target = self._movement_target(idx, enemy)
        if target is None:
            return
        dx = target[0] - float(st.coords[idx, 0])
        dy = target[1] - float(st.coords[idx, 1])
        self.move_accum[idx] = (
            self.move_accum.get(idx, 0.0) + speed * dt_hours
        )
        steps = int(self.move_accum[idx])
        if steps <= 0:
            return
        self.move_accum[idx] -= steps
        bounds = (256, 256)
        if st.heights is not None:
            bounds = st.heights.shape
        for _ in range(steps):
            if abs(dx) >= abs(dy):
                step_x = 1 if dx > 0 else (-1 if dx < 0 else 0)
                new_x = st.coords[idx, 0] + step_x
                st.coords[idx, 0] = max(0, min(bounds[1] - 1, new_x))
            else:
                step_y = 1 if dy > 0 else (-1 if dy < 0 else 0)
                new_y = st.coords[idx, 1] + step_y
                st.coords[idx, 1] = max(0, min(bounds[0] - 1, new_y))
            dx = target[0] - float(st.coords[idx, 0])
            dy = target[1] - float(st.coords[idx, 1])
        lod_manager = getattr(self.engine, "lod_manager", None)
        if lod_manager is not None and hasattr(lod_manager, "notify_moved"):
            lod_manager.notify_moved(idx)
        logger.debug(
            "Перемещение %s: шагов=%d, приказ=%s",
            st.label_of(idx), steps, self.ot.orders[order]["id"],
        )

    def _movement_target(self, idx, enemy):
        """
        Возвращает точку, к которой движется автономная сущность.

        Логика приоритетов:
        1. При отступлении и наличии врага — точка зеркально
           противоположная врагу относительно текущей позиции.
        2. При наличии objective и атакующем приказе — цель прорыва,
           пока расстояние > 3 клеток.
        3. При наличии врага — позиция врага.
        4. Иначе None (нет цели для движения).

        Args:
            idx: Индекс сущности.
            enemy: Индекс противника или None.

        Returns:
            tuple[float, float] | None: Целевые координаты или None.
        """
        st = self.state
        order_id = self._order_id(idx)
        if order_id in RETREAT_FAMILY and enemy is not None:
            dx = st.coords[enemy, 0] - st.coords[idx, 0]
            dy = st.coords[enemy, 1] - st.coords[idx, 1]
            if max(abs(dx), abs(dy)) <= 6:
                return (
                    float(2 * st.coords[idx, 0] - st.coords[enemy, 0]),
                    float(2 * st.coords[idx, 1] - st.coords[enemy, 1]),
                )
        obj = self.objectives.get(idx)
        if obj is not None and order_id in ATTACK_FAMILY:
            dx = obj[0] - st.coords[idx, 0]
            dy = obj[1] - st.coords[idx, 1]
            if max(abs(dx), abs(dy)) > 3:
                return (float(obj[0]), float(obj[1]))
        if enemy is None:
            return None
        return (
            float(st.coords[enemy, 0]),
            float(st.coords[enemy, 1]),
        )

    def tick(self, dt_hours):
        """
        Выполняет один шаг полевого ИИ.

        Периодически (каждые RECONSIDER_HOURS) пересчитывает
        фокус-цели и пересматривает приказы автономных сущностей.
        Для каждой военной сущности: нормализует приказ, выбирает
        цель, создаёт engagement при контакте. Перемещение
        выполняется только для автономных сущностей; юнитами игрока
        управляет исполнитель приказов движка.

        Args:
            dt_hours: Длительность шага в часах.
        """
        st = self.state
        self.reconsider_accum += dt_hours
        reconsider = self.reconsider_accum >= RECONSIDER_HOURS
        if reconsider:
            self.reconsider_accum = 0.0
            self._update_focus_targets()
        logger.debug(
            "tick FieldAI: dt_hours=%.2f, reconsider=%s",
            dt_hours, reconsider,
        )
        for idx in self._military_indices():
            if self._is_dead(idx):
                continue
            raw_order = st.read_segment(idx, "order")
            order = self._safe_order_index(raw_order)
            if raw_order != order:
                st.write_segment(idx, "order", order)
                logger.info(
                    "%s: некорректный приказ %d приведён к %d",
                    st.label_of(idx), raw_order, order,
                )
            if self._is_autonomous(idx):
                enemy, dist = self._chosen_enemy(idx)
            else:
                enemy, dist = self._nearest_enemy(idx)
            self._last_dist = dist
            if reconsider and self._is_autonomous(idx):
                if enemy is not None:
                    new_order = self._choose_order(idx, enemy, dist)
                    if new_order is not None and new_order != order:
                        if self._order_writable(idx, new_order):
                            st.write_segment(idx, "order", new_order)
                            st.log_event(
                                idx,
                                f"{st.label_of(idx)}: меняю приказ на "
                                f"«{self.ot.orders[new_order]['label']}»",
                            )
                            logger.info(
                                "%s: приказ изменён на «%s»",
                                st.label_of(idx),
                                self.ot.orders[new_order]["label"],
                            )
                            order = new_order
                    elif (
                        new_order is None
                        and self._order_id(idx) in ("rest", "movement")
                        and self.objectives.get(idx) is not None
                        and self._fatigue_norm(idx) < RESUME_FATIGUE_MAX
                        and self._casualties(idx) < RESUME_CASUALTIES_MAX
                    ):
                        resume = self.id_to_order.get("attack")
                        if resume is None:
                            resume = self.id_to_order.get(
                                "cautious_attack"
                            )
                        if (
                            resume is not None
                            and resume != order
                            and self._order_writable(idx, resume)
                        ):
                            st.write_segment(idx, "order", resume)
                            st.log_event(
                                idx,
                                f"{st.label_of(idx)}: перегруппировался, "
                                f"возобновляю наступление",
                            )
                            logger.info(
                                "%s: возобновляет наступление после "
                                "отдыха/отхода",
                                st.label_of(idx),
                            )
                            order = resume
                else:
                    rest_id = self.id_to_order.get("rest")
                    if (
                        rest_id is not None
                        and self._fatigue_norm(idx) > 0.6
                        and order != rest_id
                        and self.objectives.get(idx) is None
                    ):
                        if self._order_writable(idx, rest_id):
                            st.write_segment(idx, "order", rest_id)
                            st.log_event(
                                idx,
                                f"{st.label_of(idx)}: противника нет, "
                                f"отвожу на отдых",
                            )
                            logger.info(
                                "%s: назначен отдых "
                                "(усталость %.2f, противника нет)",
                                st.label_of(idx),
                                self._fatigue_norm(idx),
                            )
                            order = rest_id
            if enemy is not None:
                reach = (
                    RANGE_BARRAGE
                    if self.ot.can_barrage[order]
                    else RANGE_MELEE
                )
                if (
                    dist > reach
                    and self._is_autonomous(idx)
                    and float(self.ot.move_speed[order]) <= 0.0
                ):
                    advance_id = self.id_to_order.get("attack")
                    if advance_id is None:
                        advance_id = self.id_to_order.get("move")
                    if (
                        advance_id is not None
                        and advance_id != order
                        and self._order_writable(idx, advance_id)
                    ):
                        st.write_segment(idx, "order", advance_id)
                        st.log_event(
                            idx,
                            f"{st.label_of(idx)}: цель вне "
                            f"досягаемости, приказ на сближение",
                        )
                        logger.info(
                            "%s: сближение с целью, приказ «%s»",
                            st.label_of(idx),
                            self.ot.orders[advance_id]["label"],
                        )
                        order = advance_id
                        reach = (
                            RANGE_BARRAGE
                            if self.ot.can_barrage[order]
                            else RANGE_MELEE
                        )
                if self.ot.can_fight[order] and dist <= reach:
                    self._ensure_engagement(idx, enemy)
            if self._is_autonomous(idx):
                self._move(idx, order, enemy, dt_hours)