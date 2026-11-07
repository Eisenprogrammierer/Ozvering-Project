"""Фоновая симуляция кампании (вопрос §7 №31, первый срез).

Кампания остаётся дневной: один день — это единица хода мира. Для фонового
прогресса при свёрнутом окне и оффлайн-догрузки вводится только отображение
реального времени в дни. Часы не меняют правила мира и не трогают `F/E/S`:
они лишь решают, сколько раз вызвать `WorldEngine.end_day()`.

Границы первого среза:

- `SECONDS_PER_DAY` — 120 секунд реального времени на день при 1x;
- `MAX_CATCHUP_DAYS` — не больше 7 дней за один догон, лишнее отбрасывается;
- авто-пауза фона на смерти, завершении сюжета, критическом здоровье
  (`HEALTH_CRITICAL`) или критической болезни (`SICKNESS_CRITICAL`);
- полное закрытие игры поддерживается только через сохранённый `saved_at`
  и ограниченный оффлайн-догон при загрузке. Если сейв старый или часы
  переведены назад, догон равен нулю.

Часы также отдают текущий **внутридневной слот** (`slot`, 0..`SLOTS_MAX`).
Экран мира вызывает `WorldEngine.tick(max_slot=clock.slot)` до перехода
суток, поэтому отложенные намерения срабатывают не только на границе дня,
но и по мере накопления реального времени. Политика автономных структур
(узлов) вне кадра остаётся открытой; этот модуль не выдаёт себя за неё.
"""

import time

from core41 import HEALTH_CRITICAL, SICKNESS_CRITICAL

from .planner import SLOTS_MAX

SECONDS_PER_DAY = 120.0
MAX_CATCHUP_DAYS = 7
# Слоты 0..SLOTS_MAX покрывают сутки; слот 0 — граница дня.
SLOTS_PER_DAY = SLOTS_MAX + 1


def normalize_seconds_per_day(value):
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return SECONDS_PER_DAY


def normalize_max_catchup(value):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return MAX_CATCHUP_DAYS


class CampaignClock:
    """Переводит реальные секунды в дни кампании с ограниченным догоном."""

    def __init__(
        self,
        seconds_per_day=SECONDS_PER_DAY,
        max_catchup_days=MAX_CATCHUP_DAYS,
        paused=False,
    ):
        self.seconds_per_day = normalize_seconds_per_day(seconds_per_day)
        self.max_catchup_days = normalize_max_catchup(max_catchup_days)
        self.paused = bool(paused)
        self.acc = 0.0
        self.days = 0
        self.dropped_days = 0

    @property
    def label(self):
        if self.paused:
            return "PAUSE"
        return "%dd" % self.days

    @property
    def slot(self):
        """Текущий внутридневной слот 0..`SLOTS_MAX` по остатку `acc`.

        Слот — не отдельный счётчик, а проекция накопленных секунд внутри
        текущих суток. Повторный вызов с тем же слотом безопасен:
        `WorldEngine.tick()` извлекает исполненные намерения из очереди.
        """
        if self.paused:
            return 0
        fraction = (self.acc % self.seconds_per_day) / self.seconds_per_day
        return min(SLOTS_MAX, int(fraction * SLOTS_PER_DAY))

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def advance(self, dt):
        """Вернуть число дней, которое нужно просимулировать за `dt` секунд."""
        if self.paused or dt <= 0.0:
            return 0
        self.acc += float(dt)
        days = int(self.acc // self.seconds_per_day)
        if days <= 0:
            return 0
        if days > self.max_catchup_days:
            self.dropped_days += days - self.max_catchup_days
            days = self.max_catchup_days
            self.acc = 0.0
        else:
            self.acc -= days * self.seconds_per_day
        self.days += days
        return days

    def reset_counters(self):
        self.acc = 0.0
        self.days = 0
        self.dropped_days = 0

    def reset_accumulator(self):
        """Сбросить накопленные секунды, не трогая счётчик дней.

        Нужно, когда окно снова активно: время, накопленное в фоне, не
        должно «выстрелить» днями при возврате фокуса.
        """
        self.acc = 0.0


def offline_days(saved_at, now=None, clock=None):
    """Сколько дней можно догнать с момента сохранения, с верхним пределом.

    `saved_at` — unix-время сохранения. `None`, мусор и время из будущего
    дают 0: оффлайн-прогресс не должен наказывать за старые сейвы или
    сломанные часы.
    """
    if saved_at is None:
        return 0
    try:
        saved = float(saved_at)
        current = time.time() if now is None else float(now)
    except (TypeError, ValueError):
        return 0
    elapsed = max(0.0, current - saved)
    clock = clock or CampaignClock()
    days = int(elapsed // clock.seconds_per_day)
    return min(clock.max_catchup_days, max(0, days))


def background_pause_reason(engine):
    """Причина не продвигать кампанию в фоне; пустая строка — можно."""
    if engine is None:
        return "no_engine"
    if getattr(engine, "finished", False):
        return "finished"
    if not getattr(engine, "attached", True):
        return "unattached"
    condition = engine.player_condition()
    if not condition.get("alive", True):
        return "dead"
    if float(condition.get("health", 0.0)) <= float(HEALTH_CRITICAL):
        return "health"
    if float(condition.get("sickness", 0.0)) >= float(SICKNESS_CRITICAL):
        return "sickness"
    # Контент может объявить собственные критические события (блок
    # `logging.pause`): журнал — второй, а не единственный источник
    # причины. Ошибка хука не должна ломать фон.
    hook = getattr(engine, "critical_pause_reason", None)
    if callable(hook):
        try:
            reason = hook()
        except Exception:
            reason = ""
        if reason:
            return str(reason)
    return ""


__all__ = [
    "MAX_CATCHUP_DAYS",
    "SECONDS_PER_DAY",
    "SLOTS_PER_DAY",
    "CampaignClock",
    "background_pause_reason",
    "normalize_max_catchup",
    "normalize_seconds_per_day",
    "offline_days",
]
