"""Доклады источников: ролевой слой событий кампании.

Источник — не всеведущий рассказчик, а персонаж с BDI. Он видит актив с
ошибкой, зависящей от дисциплины, любопытства и страха, выбирает тон по
лояльности и амбиции и присылает доклад. Игрок может довериться,
проверить или проигнорировать сообщение.

Инвариант: доклад **не меняет активы**. Выбор игрока живёт в морали,
потребностях, убеждениях и отношениях источника. Следующий доклад
почувствует это.

Данные приходят из секции ``dispatch`` базовых настроек кампании:

    {"dispatch": {"enabled": true, "interval_seconds": 172800.0, ...}}

Очередь докладов входит в снимок кампании и переживает сохранение.
Отдельный поток — городские вести: сводка, цены и слухи улиц без выбора.

Реализация разделена по швам, публичный класс и его API не меняются:

* ``dispatch_core`` — настройки, такт, разбор полос и выборов;
* ``dispatch_news`` — городские вести и лента новостей;
* ``dispatch_reports`` — выпуск доклада и ИИ-выбор;
* ``dispatch_resolve`` — реакция на выбор игрока и память источника;
* ``dispatch_intercepts`` — перехваты, контрмеры и retaliation;
* ``dispatch_briefing`` — сводка штаба и тренды;
* ``dispatch_effects`` — последствия для BDI источника и лидера;
* ``dispatch_queue`` — журнал, обрезка и снимок.
"""

from .dispatch_briefing import BriefingMixin
from .dispatch_core import DispatcherCore
from .dispatch_effects import EffectsMixin
from .dispatch_intercepts import InterceptMixin
from .dispatch_news import NewsMixin
from .dispatch_queue import QueueMixin
from .dispatch_reports import ReportMixin
from .dispatch_resolve import ResolveMixin

__all__ = ["ReportDispatcher"]


class ReportDispatcher(
    DispatcherCore,
    NewsMixin,
    ReportMixin,
    ResolveMixin,
    InterceptMixin,
    BriefingMixin,
    EffectsMixin,
    QueueMixin,
):
    """Очередь докладов и реакции источников на выбор игрока."""
