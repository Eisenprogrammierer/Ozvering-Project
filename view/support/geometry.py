"""Геометрия бригадного боя и историческая модель потерь.

Бой в ``view`` ведётся не «стенка на стенку»: у бригады есть четыре
проекции (фронт, левый фланг, правый фланг и тыл). На каждом направлении
может развернуться ограниченное число рот — *фронт* участка. Поэтому
двукратное общее превосходство противника ещё не даёт троекратного
превосходства в точке соприкосновения, необходимого для прорыва
подготовленной обороны.

Модель потерь намеренно отделена от тактического ядра ``warfare``:
``CampaignEngine`` после каждого пятиминутного такта восстанавливает силу,
которую ядро потратило на «обмен огнём», и начисляет потери по историческим
суточным нормам. Это позволяет сохранить каноническое поведение
``simulation.py`` и ``build_demo_scenario`` и при этом получить правдоподобную
динамику кампании:

* оборона не прорвана — до 4% потерь дивизии в сутки;
* оборона прорвана — 12–15% в сутки;
* после прорыва рота, у которой противник уже в фланге/тылу, теряет
  значительно больше, а организованный отход ограничивает потери;
* пока оборона держится, атакующий теряет больше обороняющегося;
* разные проекции несут разные потери и дают разный вклад силы.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .log_journal import get_logger

logger = get_logger("view.geometry")

SECTORS = ("front", "left", "right", "rear")
SECTOR_LABELS = {
    "front": "ФРОНТ",
    "left": "ЛЕВЫЙ ФЛАНГ",
    "right": "ПРАВЫЙ ФЛАНГ",
    "rear": "ТЫЛ",
}
SECTOR_SHORT = {
    "front": "Ф",
    "left": "Л",
    "right": "П",
    "rear": "Т",
}

# Проекция роты вычисляется из её места в строю относительно **собственного
# фронта** стороны. Фронт — не замороженная метка на отделении, а направление,
# в котором армия развёрнута (её движение/ориентация). Поэтому одна и та же
# рота после манёвра может оказаться на фланге или в тылу.
FLANK_ANGLE = 45.0       # ±45° от фронта — ещё фронт
REAR_ANGLE = 135.0       # дальше ±135° — тыл
SURROUND_MAX_GAP = 100.0  # максимальный разрыв между bearings врагов
SURROUND_MIN_ENEMIES = 4
FACING_MOVE_EPSILON = 0.35  # клеток; меньше — считаем, что армия стоит
FACING_SMOOTHING = 0.55

# Сколько рот реально помещается на каждой проекции. Глубина не исчезает:
# она питает ротацию, но не может разом обрушиться на узкий участок.
SECTOR_CAPACITY = {
    "front": 6,
    "left": 4,
    "right": 4,
    "rear": 2,
}

# Вклад силы в зависимости от того, обороняется рота или наступает.
DEFENDER_PROJECTION = {
    "front": 1.00,
    "left": 0.80,
    "right": 0.80,
    "rear": 0.55,
}
ATTACKER_PROJECTION = {
    "front": 0.85,
    "left": 1.05,
    "right": 1.05,
    "rear": 1.20,
}

# Распределение суточных потерь по проекциям. Сумма потерь дивизии остаётся
# в пределах суточной нормы, но фланги страдают сильнее фронта, а тыл — меньше:
# его берегут как резерв.
DEFENDER_LOSS_WEIGHT = {
    "front": 0.85,
    "left": 1.25,
    "right": 1.25,
    "rear": 0.45,
}
ATTACKER_LOSS_WEIGHT = {
    "front": 1.30,
    "left": 0.95,
    "right": 0.95,
    "rear": 0.35,
}

# Исторические нормы (доля от штатной силы дивизии за сутки).
HOLD_DEFENDER_DAILY = 0.04
HOLD_ATTACKER_DAILY = 0.06
BREACH_DEFENDER_DAILY = 0.13
BREACH_ATTACKER_DAILY = 0.08

# --- контекст прорыва -------------------------------------------------
# Пока линия цела, соседний бой сам по себе не считается охватом: роты
# могут стоять вплотную, но фланги и тыл прикрыты строем. После прорыва
# важна уже не номинальная проекция, а то, где находятся враги относительно
# конкретной роты. Это не новый закон боя, а уточнение контекста, в котором
# канонический автомат отделения несёт потери.
FLANK_THREAT_RADIUS = 3.0       # после прорыва: враг в фланге
REAR_THREAT_RADIUS = 3.5        # после прорыва: враг в тылу
OVERRUN_RADIUS = 2.0            # после прорыва: позиция физически смята
OVERRUN_REAR_RADIUS = 1.5       # до формального прорыва: враг уже за спиной
OVERRUN_FLANK_RADIUS = 1.75     # после прорыва: враг вплотную с фланга
BREACH_HOLD_MULTIPLIER = 2.5    # оставаться на потерянном рубеже
FLANK_LOSS_MULTIPLIER = 3.0
REAR_LOSS_MULTIPLIER = 4.0
OVERRUN_LOSS_MULTIPLIER = 5.5
ORDERLY_RETREAT_MULTIPLIER = 0.55
ORDERLY_RETREAT_DAILY_CAP = 0.10
MAX_UNIT_DAILY_RATE = 0.65
ORDERLY_RETREAT_ORDERS = ("withdrawal", "movement")

# Полное локальное окружение — не просто фланговый охват. Если враг
# окружает роту со всех сторон и имеет перевес, у неё нет коридора отхода:
# суточная норма становится заведомо смертельной, а через час непрерывного
# окружения остатки сдаются. Это не отменяет канонический ``broken``: рота
# снимается с поля тем же флагом, но получает полные потери и признак сдачи.
ENCIRCLE_RADIUS = 2.5
ENCIRCLE_MAX_GAP = 135.0
ENCIRCLE_MIN_ENEMIES = 4
ENCIRCLE_MIN_FORCE_RATIO = 1.25
ENCIRCLE_LOSS_MULTIPLIER = 8.0
MAX_ENCIRCLED_DAILY_RATE = 1.20
ENCIRCLE_SURRENDER_TICKS = 12
ENCIRCLE_COLLAPSE_FRACTION = 0.35

# Прорыв: локальное превосходство и время нажима. 1.8 — это уже больше
# «двукратного», но всё ещё меньше классических 3:1; подготовленная оборона
# держится, пока игрок не оголит участок.
BREACH_RATIO = 1.80
BREACH_PRESSURE_TICKS = 36
RECOVER_RATIO = 1.15
RECOVER_TICKS = 36

# Кампанийный день в ``time_system`` длится с 07:00 до 22:00 (15 часов).
# Ночью бой не идёт, поэтому суточную норму считаем по 180 пятиминутным
# тактам, а не по 288.
DEFAULT_COMBAT_TICKS_PER_DAY = 180


@dataclass
class SectorStatus:
    side: str
    sector: str
    defender_force: float
    attacker_force: float
    ratio: float
    pressure: int
    breached: bool
    defender_daily: float
    attacker_daily: float

    @property
    def label(self):
        return SECTOR_LABELS.get(self.sector, self.sector)

    @property
    def short(self):
        return SECTOR_SHORT.get(self.sector, "?")


@dataclass(frozen=True)
class CombatContext:
    """Локальный контекст роты на прорванном участке.

    Это «сообщение» между геометрией суперсистемы (фронт/проекции/прорыв)
    и автоматом отделения: насколько близко противник подошёл к его флангу
    или тылу и сохраняет ли рота боевой порядок при отходе. Потери начисляет
    по-прежнему ``FrontGeometry``, канонические ``simulation``/``warfare``
    не меняются.
    """

    side: str
    sector: str
    kind: str
    label: str
    breached: bool
    sector_breached: bool
    overrun: bool
    ordered_retreat: bool
    flank_force: float
    rear_force: float
    local_force: float
    multiplier: float
    daily_rate: float
    encircled: bool = False
    encircle_force: float = 0.0
    encircle_gap: float = 360.0
    encircle_ticks: int = 0
    surrender_in: int = 0

    @property
    def routed(self):
        """Позиция смята, а организованного отхода нет.

        Полное окружение считается разгромом даже при приказе на отход:
        коридора для сохранения порядка уже нет.
        """
        return self.overrun and (not self.ordered_retreat or self.encircled)


class FrontGeometry:
    """Четыре проекции бригады, фронтаж и модель истощения."""

    def __init__(self, state):
        self.state = state
        self.player_side = getattr(state, "player_side", "red")
        self.enemy_side = "blue" if self.player_side == "red" else "red"
        self.pressure = {sector: 0 for sector in SECTORS}
        self.recover = {sector: 0 for sector in SECTORS}
        self.breached = set()
        self.ratios = {sector: 0.0 for sector in SECTORS}
        self.engaged_sides = set()
        self.ticks_per_day = DEFAULT_COMBAT_TICKS_PER_DAY
        self._groups = {}
        self._last_tick = -1
        # Непрерывные такты полного окружения по имени роты. Счётчик
        # сбрасывается, как только коридор открылся или рота выбыла.
        self.encircle_ticks = {}
        # Текущий фронт каждой стороны (единичный вектор) и центры строя на
        # прошлом такте. Секторы выводятся из этих данных, а не из ``det.sector``.
        self.facing = {self.player_side: None, self.enemy_side: None}
        self._explicit_facing = {}
        self._last_centers = {}
        self._frames = {}
        self._init_facing()
        self.refresh_sectors()
        self.recompute()

    # --- стороны и проекции ---------------------------------------------
    def is_player(self, side):
        return side == self.player_side

    def is_attacker(self, side):
        return side == self.enemy_side

    def projection(self, det):
        sector = self.sector_of(det)
        table = (DEFENDER_PROJECTION if self.is_player(det.side)
                 else ATTACKER_PROJECTION)
        return table.get(sector, 1.0)

    def loss_weight(self, det):
        sector = self.sector_of(det)
        table = (DEFENDER_LOSS_WEIGHT if self.is_player(det.side)
                 else ATTACKER_LOSS_WEIGHT)
        return table.get(sector, 1.0)

    def projected_force(self, det):
        return max(0.0, float(getattr(det, "force", 0.0))) * self.projection(det)

    def daily_rate(self, side):
        if self.is_player(side):
            return (BREACH_DEFENDER_DAILY if self.breached
                    else HOLD_DEFENDER_DAILY)
        return (BREACH_ATTACKER_DAILY if self.breached
                else HOLD_ATTACKER_DAILY)

    def sector_daily_rate(self, side, sector):
        """Суточная потеря силы на конкретной проекции.

        Общая суточная норма распределяется по проекциям с разными весами,
        поэтому фронт, фланги и тыл теряют неодинаково. Возвращается доля
        силы *этого* участка за сутки.
        """
        table = (DEFENDER_LOSS_WEIGHT if self.is_player(side)
                 else ATTACKER_LOSS_WEIGHT)
        all_units = [
            det for det in self._all_units()
            if det.side == side and self._active(det)
        ]
        if not any(self.sector_of(det) == sector for det in all_units):
            return 0.0
        total_start = sum(
            max(1.0, float(getattr(det, "start_force", det.force)))
            for det in all_units
        )
        weighted_start = sum(
            max(1.0, float(getattr(det, "start_force", det.force))) *
            table.get(self.sector_of(det), 1.0)
            for det in all_units
        )
        average = weighted_start / total_start if total_start else 1.0
        weight = table.get(sector, 1.0)
        return self.daily_rate(side) * weight / max(0.01, average)

    # --- локальный контекст прорыва -------------------------------------
    @staticmethod
    def _ordered_retreat(det):
        """Отход с сохранением порядка, а не паническое бегство."""
        return (
            getattr(det, "ui_order", None) in ORDERLY_RETREAT_ORDERS
            and not bool(getattr(det, "panicked", False))
        )

    @staticmethod
    def _threat_multiplier(max_multiplier, threat_force, local_force):
        """Смягчить множитель, если в охват попала лишь малая часть сил."""
        ratio = float(threat_force) / max(1.0, float(local_force))
        severity = max(0.25, min(1.0, ratio))
        return 1.0 + (max_multiplier - 1.0) * severity

    def _bearing(self, det, enemy, facing):
        """Вернуть проекцию врага относительно роты и дистанцию."""
        dx = float(enemy.position[0]) - float(det.position[0])
        dy = float(enemy.position[1]) - float(det.position[1])
        distance = math.hypot(dx, dy)
        if distance < 1e-6:
            return "rear", 0.0
        right = (-facing[1], facing[0])
        forward = dx * facing[0] + dy * facing[1]
        lateral = dx * right[0] + dy * right[1]
        angle = abs(math.degrees(math.atan2(lateral, forward)))
        if angle <= FLANK_ANGLE:
            return "front", distance
        if angle <= REAR_ANGLE:
            return "flank", distance
        return "rear", distance

    def _encirclement(self, det):
        """Измерить, замкнут ли вокруг роты коридор.

        Окружение — это не «много врагов рядом», а отсутствие свободного
        направления: угловые разрывы между ближайшими врагами не должны
        превышать ``ENCIRCLE_MAX_GAP``. Четыре роты с одной стороны фронта
        такой замер не проходят.
        """
        vectors = []
        for enemy in self._enemy_units(det.side):
            force = float(getattr(enemy, "force", 0.0))
            if force <= 1.0:
                continue
            dx = float(enemy.position[0]) - float(det.position[0])
            dy = float(enemy.position[1]) - float(det.position[1])
            distance = math.hypot(dx, dy)
            if distance > ENCIRCLE_RADIUS:
                continue
            angle = (math.degrees(math.atan2(dy, dx)) % 360.0
                     if distance > 1e-6 else 0.0)
            vectors.append((angle, force))
        if len(vectors) < ENCIRCLE_MIN_ENEMIES:
            return False, sum(force for _, force in vectors), 360.0

        vectors.sort(key=lambda item: item[0])
        angles = [angle for angle, _ in vectors]
        gaps = [
            angles[i + 1] - angles[i] for i in range(len(angles) - 1)
        ]
        gaps.append(angles[0] + 360.0 - angles[-1])
        max_gap = max(gaps)
        encircle_force = sum(force for _, force in vectors)
        ratio = encircle_force / max(1.0, self.projected_force(det))
        encircled = (
            max_gap <= ENCIRCLE_MAX_GAP
            and ratio >= ENCIRCLE_MIN_FORCE_RATIO
        )
        return encircled, encircle_force, max_gap

    def combat_context(self, det):
        """Оценить, чем для роты обернулся прорыв.

        До формального прорыва действует только один локальный сигнал:
        враг уже вплотную за спиной (``OVERRUN_REAR_RADIUS``). После
        прорыва учитываются фланг и тыл в более широком радиусе. Если рота
        отходит по приказу ``withdrawal``, её потери ограничиваются, даже
        когда позиция уже потеряна: она сохраняет боевые порядки, а не
        остаётся на разгром. Исключение — полное локальное окружение: там
        коридора нет, поэтому отход не отменяет капитуляцию.
        """
        sector = self.sector_of(det)
        base = self.sector_daily_rate(det.side, sector)
        if not self.is_player(det.side):
            return CombatContext(
                side=det.side, sector=sector, kind="attacker",
                label="наступление", breached=bool(self.breached),
                sector_breached=sector in self.breached, overrun=False,
                ordered_retreat=False, flank_force=0.0, rear_force=0.0,
                local_force=max(1.0, self.projected_force(det)),
                multiplier=1.0, daily_rate=base,
            )

        local_force = max(1.0, self.projected_force(det))
        facing = self.facing_of(det.side)
        encircled, encircle_force, encircle_gap = self._encirclement(det)
        encircle_ticks = int(self.encircle_ticks.get(det.name, 0))
        flank_force = 0.0
        rear_force = 0.0
        overrun_force = 0.0
        flank_radius = FLANK_THREAT_RADIUS if self.breached else 0.0
        rear_radius = (REAR_THREAT_RADIUS if self.breached
                       else OVERRUN_REAR_RADIUS)
        for enemy in self._enemy_units(det.side):
            if float(getattr(enemy, "force", 0.0)) <= 1.0:
                continue
            bearing, distance = self._bearing(det, enemy, facing)
            if bearing == "front":
                continue
            force = max(0.0, float(getattr(enemy, "force", 0.0)))
            if bearing == "rear" and distance <= rear_radius:
                rear_force += force
            elif bearing == "flank" and distance <= flank_radius:
                flank_force += force
            if bearing == "rear" and distance <= (
                    OVERRUN_RADIUS if self.breached
                    else OVERRUN_REAR_RADIUS):
                overrun_force += force
            elif (self.breached and bearing == "flank"
                  and distance <= OVERRUN_FLANK_RADIUS):
                overrun_force += force

        side_breached = bool(self.breached)
        sector_breached = sector in self.breached
        overrun = overrun_force > 0.0 or encircled
        ordered = self._ordered_retreat(det)

        if encircled:
            kind, label = "overrun", "ОКРУЖЕНИЕ: разгром"
            raw_base = max(base, BREACH_DEFENDER_DAILY)
            multiplier = self._threat_multiplier(
                ENCIRCLE_LOSS_MULTIPLIER, encircle_force, local_force
            )
        elif overrun:
            kind, label = "overrun", "РАЗГРОМ: позиция смята"
            raw_base = max(base, BREACH_DEFENDER_DAILY)
            multiplier = self._threat_multiplier(
                OVERRUN_LOSS_MULTIPLIER, overrun_force, local_force
            )
        elif rear_force > 0.0:
            kind, label = "rear", "удар в тыл"
            raw_base = max(base, BREACH_DEFENDER_DAILY)
            multiplier = self._threat_multiplier(
                REAR_LOSS_MULTIPLIER, rear_force, local_force
            )
        elif flank_force > 0.0:
            kind, label = "flank", "охват фланга"
            raw_base = max(base, BREACH_DEFENDER_DAILY)
            multiplier = self._threat_multiplier(
                FLANK_LOSS_MULTIPLIER, flank_force, local_force
            )
        elif side_breached and sector_breached:
            kind, label = "breach_hold", "прорыв: рубеж потерян"
            raw_base = max(base, BREACH_DEFENDER_DAILY)
            multiplier = BREACH_HOLD_MULTIPLIER
        elif side_breached:
            kind, label = "breach_nearby", "прорыв рядом"
            raw_base = max(base, BREACH_DEFENDER_DAILY)
            multiplier = 1.0
        else:
            kind, label = "intact", "фронт цел"
            raw_base = base
            multiplier = 1.0

        raw_rate = raw_base * multiplier
        if ordered and not encircled:
            # Отход — не неуязвимость: арьергардные бои стоят потерь, но
            # не превращаются в разгром окружённой позиции. В полном
            # окружении коридора нет, поэтому этот спасательный множитель
            # не применяется.
            daily = min(
                ORDERLY_RETREAT_DAILY_CAP,
                raw_rate * ORDERLY_RETREAT_MULTIPLIER,
            )
            label = "организованный отход"
            kind = "withdrawal"
        elif encircled:
            daily = min(MAX_ENCIRCLED_DAILY_RATE, raw_rate)
        else:
            daily = min(MAX_UNIT_DAILY_RATE, raw_rate)

        surrender_in = (
            max(0, ENCIRCLE_SURRENDER_TICKS - encircle_ticks)
            if encircled else 0
        )
        return CombatContext(
            side=det.side, sector=sector, kind=kind, label=label,
            breached=side_breached, sector_breached=sector_breached,
            overrun=overrun, ordered_retreat=ordered,
            flank_force=flank_force, rear_force=rear_force,
            local_force=local_force,
            multiplier=(daily / base) if base > 0.0 else 0.0,
            daily_rate=daily,
            encircled=encircled, encircle_force=encircle_force,
            encircle_gap=encircle_gap, encircle_ticks=encircle_ticks,
            surrender_in=surrender_in,
        )

    def unit_daily_rate(self, det):
        """Суточная потеря конкретной роты с учётом контекста прорыва."""
        return self.combat_context(det).daily_rate

    # --- назначение секторов --------------------------------------------
    def _all_units(self):
        sim = getattr(self.state, "sim", None)
        return list(getattr(sim, "all_detachments", []) or [])

    def _side_units(self, side):
        return [
            det for det in self._all_units()
            if det.side == side and self._active(det)
        ]

    @staticmethod
    def _center_of(units):
        if not units:
            return None
        xs = [float(getattr(det, "position", (0, 0))[0]) for det in units]
        ys = [float(getattr(det, "position", (0, 0))[1]) for det in units]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def _enemy_units(self, side):
        other = self.enemy_side if side == self.player_side else self.player_side
        return self._side_units(other)

    @staticmethod
    def _normalize(vector):
        x, y = float(vector[0]), float(vector[1])
        length = math.hypot(x, y)
        if length < 1e-9:
            return None
        return (x / length, y / length)

    def _default_facing(self, side):
        """Фронт по умолчанию — в сторону центра масс противника."""
        own = self._center_of(self._side_units(side))
        enemy = self._center_of(self._enemy_units(side))
        if own is not None and enemy is not None:
            vector = self._normalize((enemy[0] - own[0], enemy[1] - own[1]))
            if vector:
                return vector
        return (1.0, 0.0) if side == "red" else (-1.0, 0.0)

    def _init_facing(self):
        for side in (self.player_side, self.enemy_side):
            self.facing[side] = self._default_facing(side)
            self._last_centers[side] = self._center_of(
                self._side_units(side)
            )

    def set_facing(self, side, vector):
        """Явно задать фронт стороны (для приказов, снимков и тестов).

        В обычной кампании фронт выводится из движения строя; явное значение
        сохраняется, пока его не сбросят через ``clear_facing``.
        """
        normalized = self._normalize(vector)
        if normalized is None:
            return False
        self.facing[side] = normalized
        self._explicit_facing[side] = normalized
        self.refresh_sectors()
        return True

    def clear_facing(self, side=None):
        """Вернуть автоматический вывод фронта из движения."""
        if side is None:
            self._explicit_facing.clear()
        else:
            self._explicit_facing.pop(side, None)
        self._init_facing()
        self.refresh_sectors()

    def facing_of(self, side):
        vector = self.facing.get(side)
        if vector is None:
            vector = self._default_facing(side)
            self.facing[side] = vector
        return vector

    def _update_facing_from_motion(self):
        """Повернуть фронт вслед за перемещением центра строя.

        Пока армия стоит, фронт не меняется. Как только центр сместился
        заметнее ``FACING_MOVE_EPSILON``, направление движения становится
        новым фронтом. Именно поэтому удар с востока по армии, идущей на
        север, считается ударом в правый (восточный) фланг, а не «фронтом».
        """
        for side in (self.player_side, self.enemy_side):
            current = self._center_of(self._side_units(side))
            previous = self._last_centers.get(side)
            if current is not None and previous is not None:
                dx = current[0] - previous[0]
                dy = current[1] - previous[1]
                if math.hypot(dx, dy) >= FACING_MOVE_EPSILON:
                    if side not in self._explicit_facing:
                        desired = self._normalize((dx, dy))
                        old = self.facing.get(side)
                        if desired is not None:
                            if old is None:
                                self.facing[side] = desired
                            else:
                                blended = self._normalize((
                                    old[0] * (1.0 - FACING_SMOOTHING) +
                                    desired[0] * FACING_SMOOTHING,
                                    old[1] * (1.0 - FACING_SMOOTHING) +
                                    desired[1] * FACING_SMOOTHING,
                                ))
                                self.facing[side] = blended or desired
            if current is not None:
                self._last_centers[side] = current
            if self.facing.get(side) is None:
                self.facing[side] = self._default_facing(side)

    def _is_surrounded(self, center, enemies):
        """Проверить, что противник охватил строй по всему кругу.

        Используется максимальный угловой разрыв между направлениями на
        врагов: если он не больше ``SURROUND_MAX_GAP``, свободного выхода
        из кольца нет. Обычная линия фронта даёт разрыв около 180–300°.
        """
        if center is None or len(enemies) < SURROUND_MIN_ENEMIES:
            return False
        angles = []
        for enemy in enemies:
            x, y = getattr(enemy, "position", (0, 0))
            dx = float(x) - center[0]
            dy = float(y) - center[1]
            if math.hypot(dx, dy) < 1e-6:
                continue
            angles.append(math.degrees(math.atan2(dy, dx)) % 360.0)
        if len(angles) < SURROUND_MIN_ENEMIES:
            return False
        angles.sort()
        gaps = [
            angles[i + 1] - angles[i] for i in range(len(angles) - 1)
        ]
        gaps.append(angles[0] + 360.0 - angles[-1])
        return max(gaps) <= SURROUND_MAX_GAP

    def _compute_frame(self, side):
        units = self._side_units(side)
        center = self._center_of(units)
        facing = self.facing_of(side)
        enemies = self._enemy_units(side)
        surrounded = self._is_surrounded(center, enemies)
        max_radius = 0.0
        if center is not None:
            for det in units:
                x, y = getattr(det, "position", (0, 0))
                max_radius = max(
                    max_radius, math.hypot(float(x) - center[0],
                                           float(y) - center[1])
                )
        # Правое плечо в экранных координатах: при фронте на восток это юг.
        right = (-facing[1], facing[0])
        return {
            "center": center,
            "facing": facing,
            "right": right,
            "surrounded": surrounded,
            "max_radius": max_radius,
        }

    def _sector_for(self, det, frame):
        """Определить проекцию роты внутри уже посчитанного строя."""
        center = frame.get("center")
        if center is None:
            return self._infer_sector(det)
        x, y = getattr(det, "position", (center[0], center[1]))
        dx = float(x) - center[0]
        dy = float(y) - center[1]
        radius = math.hypot(dx, dy)

        # В окружении «фронт» — внешнее кольцо, «тыл» — ядро строя. Игрок
        # не может спрятать резерв за спиной: кольцо со всех сторон.
        max_radius = float(frame.get("max_radius") or 0.0)
        if frame.get("surrounded") and max_radius > 1e-6:
            if radius >= 0.72 * max_radius:
                return "front"
            if radius <= 0.38 * max_radius:
                return "rear"

        facing = frame["facing"]
        right = frame["right"]
        forward = dx * facing[0] + dy * facing[1]
        lateral = dx * right[0] + dy * right[1]
        if abs(forward) < 1e-9 and abs(lateral) < 1e-9:
            return "front"
        angle = math.degrees(math.atan2(lateral, forward))
        if -FLANK_ANGLE <= angle <= FLANK_ANGLE:
            return "front"
        if FLANK_ANGLE < angle <= REAR_ANGLE:
            return "right"
        if -REAR_ANGLE <= angle < -FLANK_ANGLE:
            return "left"
        return "rear"

    def _infer_sector(self, det):
        """Осторожная эвристика без строя (пустой снимок/старый сценарий)."""
        x, y = getattr(det, "position", (12, 12))
        if y <= 6:
            return "left"
        if y >= 18:
            return "right"
        if det.side == "red" and x <= 4:
            return "rear"
        if det.side == "blue" and x >= 20:
            return "rear"
        return "front"

    def refresh_sectors(self):
        """Пересчитать проекции всех рот по текущему положению и фронту."""
        self._frames = {
            side: self._compute_frame(side)
            for side in (self.player_side, self.enemy_side)
        }
        for det in self._all_units():
            frame = self._frames.get(det.side)
            if frame is not None and frame.get("center") is not None:
                det.sector = self._sector_for(det, frame)
            else:
                det.sector = self._infer_sector(det)
        return self._frames

    def sector_of(self, det):
        """Проекция роты — всегда производная, а не сохранённая метка."""
        frame = self._frames.get(det.side)
        if frame is None or frame.get("center") is None:
            frame = self._compute_frame(det.side)
            self._frames[det.side] = frame
        sector = self._sector_for(det, frame)
        det.sector = sector
        return sector

    # Совместимость со старым вызовом.
    def _assign_missing_sectors(self):
        self.refresh_sectors()

    def sector_units(self, side, sector):
        groups = self._groups.get(side, {})
        return list(groups.get(sector, ()))

    # --- фронтаж и эффективная сила -------------------------------------
    def _active(self, det):
        return (not getattr(det, "broken", False) and
                float(getattr(det, "force", 0.0)) > 1.0)

    def recompute(self):
        """Пересобрать группы по проекциям и посчитать фронтаж."""
        self._update_facing_from_motion()
        self.refresh_sectors()
        groups = {
            self.player_side: {sector: [] for sector in SECTORS},
            self.enemy_side: {sector: [] for sector in SECTORS},
        }
        for det in getattr(self.state, "sim", None).all_detachments:
            if det.side not in groups or not self._active(det):
                continue
            sector = self.sector_of(det)
            groups[det.side][sector].append(det)
        self._groups = groups
        return groups

    def effective_force(self, side, sector):
        """Сила, которую сторона реально может подать на проекцию.

        Учитывается фронтаж: в глубине могут стоять ещё роты, но на узком
        участке одновременно разворачивается лишь ``SECTOR_CAPACITY``.
        """
        units = self.sector_units(side, sector)
        if not units:
            return 0.0
        capacities = sorted(
            (self.projected_force(det) for det in units), reverse=True
        )
        return sum(capacities[:SECTOR_CAPACITY.get(sector, 2)])

    def local_ratio(self, sector):
        defender = self.effective_force(self.player_side, sector)
        attacker = self.effective_force(self.enemy_side, sector)
        return attacker / max(1.0, defender)

    def statuses(self):
        self.recompute()
        rows = []
        for sector in SECTORS:
            defender = self.effective_force(self.player_side, sector)
            attacker = self.effective_force(self.enemy_side, sector)
            ratio = self.ratios.get(sector, 0.0)
            if ratio <= 0.0 and sector != "rear":
                ratio = attacker / max(1.0, defender)
            rows.append(SectorStatus(
                side=self.player_side,
                sector=sector,
                defender_force=defender,
                attacker_force=attacker,
                ratio=ratio,
                pressure=int(self.pressure.get(sector, 0)),
                breached=sector in self.breached,
                defender_daily=self.sector_daily_rate(
                    self.player_side, sector
                ),
                attacker_daily=self.sector_daily_rate(
                    self.enemy_side, sector
                ),
            ))
        return rows

    # --- прорыв и восстановление ----------------------------------------
    def update(self, engaged_sides=None, tick=None):
        """Обновить давление на проекциях и зафиксировать прорывы.

        Прорыв не случается от одного численного перевеса: нужен устойчивый
        нажим. Это отделяет «бот старается» от «бот мгновенно сломал оборону».
        """
        if tick is None:
            tick = getattr(getattr(self.state, "sim", None), "turn", 0)
        self._last_tick = int(tick)
        self.engaged_sides = set(engaged_sides or ())
        self.recompute()

        for sector in ("front", "left", "right"):
            ratio = self.local_ratio(sector)
            self.ratios[sector] = ratio
            if sector in self.breached:
                if ratio <= RECOVER_RATIO:
                    self.recover[sector] += 1
                    if self.recover[sector] >= RECOVER_TICKS:
                        self.breached.discard(sector)
                        self.recover[sector] = 0
                        self.pressure[sector] = 0
                        self._log(
                            "Прорыв на направлении «%s» ликвидирован" %
                            SECTOR_LABELS[sector]
                        )
                else:
                    self.recover[sector] = 0
                continue

            if ratio >= BREACH_RATIO:
                self.pressure[sector] += 1
            else:
                # Давление спадает, но не мгновенно: противник не отводит
                # все силы за один такт.
                self.pressure[sector] = max(0, self.pressure[sector] - 2)
            if self.pressure[sector] >= BREACH_PRESSURE_TICKS:
                self.breached.add(sector)
                self.recover[sector] = 0
                self._log(
                    "ПРОРЫВ: «%s» — противник вклинился в оборону" %
                    SECTOR_LABELS[sector]
                )

        self.ratios["rear"] = 0.0
        return self.statuses()

    def _log(self, text):
        logger.warning(text)
        state = self.state
        add = getattr(state, "log_event", None)
        if callable(add):
            try:
                add(getattr(state, "player_idx", 0), text)
            except Exception:                      # noqa: BLE001
                logger.debug("Не удалось записать событие геометрии", exc_info=True)

    # --- капитуляция окружённых -----------------------------------------
    def _update_encirclement_clocks(self):
        """Продвинуть часовой механизм полного окружения.

        Счётчик живёт только пока рота активна и кольцо действительно
        замкнуто. Как только появился коридор, значение снимается: это не
        накопительный «штраф за нахождение рядом с врагом».
        """
        if self.player_side not in self.engaged_sides:
            return
        active_names = set()
        for det in self._side_units(self.player_side):
            active_names.add(det.name)
            context = self.combat_context(det)
            if context.encircled:
                self.encircle_ticks[det.name] = (
                    int(self.encircle_ticks.get(det.name, 0)) + 1
                )
            else:
                self.encircle_ticks.pop(det.name, None)
        for name in list(self.encircle_ticks):
            if name not in active_names:
                self.encircle_ticks.pop(name, None)

    def _surrender(self, det, reason):
        """Сдать окружённую роту: полные потери, ``broken`` и флаг сдачи.

        Каноническое ядро не знает о кампанийном окружении, поэтому здесь
        выставляется тот же ``broken``, который оно использует для выбывших
        отделений. Остаток силы переводится в безвозвратные потери, иначе
        сдавшаяся рота выглядела бы в сводке как «живая».
        """
        if getattr(det, "broken", False):
            return False
        start = max(1.0, float(getattr(det, "start_force", det.force)))
        remaining = max(0.0, float(getattr(det, "force", 1.0)) - 1.0)
        cap = max(0.0, start - 1.0)
        det.losses = min(
            cap, float(getattr(det, "losses", 0.0)) + remaining
        )
        det.force = 1.0
        det.broken = True
        det.surrendered = True
        det.retreating = False
        det.panicked = True
        det.morale = min(float(getattr(det, "morale", 0.0)), 5.0)
        self.encircle_ticks.pop(det.name, None)
        lost_percent = 100.0 * det.losses / start
        self._log(
            "%s: окружена и капитулировала (%s, потери %.1f%%)" %
            (det.name, reason, lost_percent)
        )
        return True

    # --- суточные потери --------------------------------------------------
    def apply_attrition(self, force_before, engaged_sides=None):
        """Начислить потери за прошедший такт по историческим нормам.

        Ядро уже потратило часть силы на обмен огнём и вернуло трение
        ``K_EFFECT``. Перед начислением потерь вызывающий код восстанавливает
        силу к началу такта, поэтому здесь учитываются только потери модели:
        так суточная норма не зависит от случайной силы удара.
        """
        if engaged_sides is not None:
            self.engaged_sides = set(engaged_sides)
        if not self.engaged_sides:
            return

        self.recompute()
        self._update_encirclement_clocks()
        ticks = max(1, int(self.ticks_per_day))
        for side in (self.player_side, self.enemy_side):
            if side not in self.engaged_sides:
                continue
            units = [
                det for det in self._all_units()
                if det.side == side and self._active(det)
            ]
            if not units:
                continue

            for det in units:
                before = force_before.get(det.name)
                if before is None:
                    continue
                start = max(1.0, float(getattr(
                    det, "start_force", det.force
                )))
                # ``sector_daily_rate`` уже нормирует потери по проекциям так,
                # что при целом фронте сумма по стороне равна 4%/6% в сутки.
                # Контекст прорыва меняет норму только для тех рот, чьи
                # фланги/тыл действительно оказались под ударом, и не
                # переписывает канонический обмен огнём.
                context = self.combat_context(det)
                if side == self.player_side and context.encircled:
                    ticks_inside = int(self.encircle_ticks.get(det.name, 0))
                    if (
                        ticks_inside >= ENCIRCLE_SURRENDER_TICKS
                        or float(det.force) / start
                        <= ENCIRCLE_COLLAPSE_FRACTION
                    ):
                        self._surrender(
                            det,
                            "кольцо замкнуто %d тактов" % ticks_inside,
                        )
                        continue
                rate = context.daily_rate
                if rate <= 0.0:
                    continue
                # Не даём модели «съесть» последнюю единицу силы: подразделение
                # рассеивается, когда сила доходит до единицы.
                available = max(0.0, float(det.force) - 1.0)
                loss = min(available, start * rate / ticks)
                if loss <= 0.0:
                    continue
                if (
                    side == self.player_side
                    and context.encircled
                    and float(det.force) - loss <= 1.001
                ):
                    # Даже при одношаговом расчёте (например, ``ticks_per_day
                    # = 1``) окружённая рота не должна «тихо рассеяться» без
                    # события о капитуляции и флага сдачи.
                    self._surrender(det, "остаток разбит")
                    continue
                det.force = max(1.0, float(det.force) - loss)
                cap = max(0.0, start - 1.0)
                det.losses = min(
                    cap, float(getattr(det, "losses", 0.0)) + loss
                )
                if det.force <= 1.001:
                    det.broken = True

    # --- сохранение -------------------------------------------------------
    def snapshot(self):
        return {
            "ticks_per_day": self.ticks_per_day,
            "pressure": dict(self.pressure),
            "recover": dict(self.recover),
            "breached": sorted(self.breached),
            "encircle_ticks": {
                name: int(value)
                for name, value in self.encircle_ticks.items()
            },
            # Фронт сохраняется, чтобы после загрузки армия не «забыла», куда
            # была развёрнута. Сами секторы не сохраняются как истина: они
            # пересчитываются из позиций и фронта.
            "facing": {
                side: list(vector)
                for side, vector in self.facing.items()
                if vector is not None
            },
        }

    def load_snapshot(self, snapshot):
        if not snapshot:
            return
        self.ticks_per_day = int(snapshot.get(
            "ticks_per_day", self.ticks_per_day
        ))
        for sector in SECTORS:
            self.pressure[sector] = int(
                (snapshot.get("pressure") or {}).get(sector, 0)
            )
            self.recover[sector] = int(
                (snapshot.get("recover") or {}).get(sector, 0)
            )
        self.breached = {
            sector for sector in snapshot.get("breached", [])
            if sector in SECTORS
        }
        self.encircle_ticks = {
            str(name): int(value)
            for name, value in (snapshot.get("encircle_ticks") or {}).items()
        }
        facing = snapshot.get("facing") or {}
        for side, vector in facing.items():
            normalized = self._normalize(vector)
            if normalized is not None:
                # Сохранённый фронт — стартовое направление после загрузки,
                # а не вечная блокировка: дальнейшее движение центра строя
                # снова может повернуть армию.
                self.facing[side] = normalized
                self._explicit_facing.pop(side, None)
        self._last_centers = {
            side: self._center_of(self._side_units(side))
            for side in (self.player_side, self.enemy_side)
        }
        self.recompute()
