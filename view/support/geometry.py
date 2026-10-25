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
* пока оборона держится, атакующий теряет больше обороняющегося;
* разные проекции несут разные потери и дают разный вклад силы.
"""

from __future__ import annotations

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
        self._assign_missing_sectors()
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
            det for det in getattr(self.state, "sim", None).all_detachments
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

    # --- назначение секторов --------------------------------------------
    def _assign_missing_sectors(self):
        for det in getattr(self.state, "sim", None).all_detachments:
            if getattr(det, "sector", None) not in SECTORS:
                det.sector = self._infer_sector(det)

    def _infer_sector(self, det):
        """Осторожная эвристика для снимков/старых сценариев."""
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

    def sector_of(self, det):
        sector = getattr(det, "sector", None)
        if sector not in SECTORS:
            sector = self._infer_sector(det)
            det.sector = sector
        return sector

    def sector_units(self, side, sector):
        groups = self._groups.get(side, {})
        return list(groups.get(sector, ()))

    # --- фронтаж и эффективная сила -------------------------------------
    def _active(self, det):
        return (not getattr(det, "broken", False) and
                float(getattr(det, "force", 0.0)) > 1.0)

    def recompute(self):
        """Пересобрать группы по проекциям и посчитать фронтаж."""
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
        ticks = max(1, int(self.ticks_per_day))
        for side in (self.player_side, self.enemy_side):
            if side not in self.engaged_sides:
                continue
            units = [
                det for det in getattr(self.state, "sim", None).all_detachments
                if det.side == side and self._active(det)
            ]
            if not units:
                continue

            total_start = sum(
                max(1.0, float(getattr(det, "start_force", det.force)))
                for det in units
            )
            target = total_start * self.daily_rate(side) / ticks
            weights = [
                max(1.0, float(getattr(det, "start_force", det.force))) *
                self.loss_weight(det)
                for det in units
            ]
            total_weight = sum(weights) or 1.0

            for det, weight in zip(units, weights):
                before = force_before.get(det.name)
                if before is None:
                    continue
                # Не даём модели «съесть» последнюю единицу силы: подразделение
                # рассеивается, когда сила доходит до единицы.
                available = max(0.0, float(det.force) - 1.0)
                loss = min(available, target * weight / total_weight)
                if loss <= 0.0:
                    continue
                det.force = max(1.0, float(det.force) - loss)
                cap = max(0.0, float(getattr(
                    det, "start_force", det.force
                )) - 1.0)
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
        self.recompute()
