"""
view/screens/adjutant_orders.py

Экран приказов адъютанту.

Отображает список приказов с пагинацией по PAGE_SIZE записей на страницу.
Список приказов читается из активного сюжетного конфига (поле
adjutant_orders); при отсутствии сюжета или поля используется встроенный
фолбэк-список DEFAULT_ADJUTANT_ORDERS.

Выбор приказа применяет его эффект через EffectInterpreter, записывает
ответ адъютанта в лог мира и журнал, показывает реплику на экране
и тратит игровое время через действие планирования приказов.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль средствами core.log_journal.
"""

import os
import random

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.effects import EffectInterpreter
from view.support.log_journal import get_logger

logger = get_logger("view.adjutant_orders")

PAGE_SIZE = 4

ADJUTANT_ACKS = [
    "Слушаюсь.",
    "Так точно.",
    "Есть.",
    "Будет выполнено.",
    "Приказ понят, передаю.",
]

DEFAULT_ADJUTANT_ORDERS = [
    {
        "id": "hold",
        "label": "Удержать позиции любой ценой",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "set_segments": {"order": "defense"},
            "log": "Приказ адъютанту: удержать позиции.",
        },
    },
    {
        "id": "dig",
        "label": "Окопаться и укрепить позиции",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "set_segments": {"order": "defense"},
            "log": "Приказ адъютанту: окопаться.",
        },
    },
    {
        "id": "rest",
        "label": "Отвести подразделение на отдых",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "set_segments": {"order": "rest"},
            "log": "Приказ адъютанту: отвести на отдых.",
        },
    },
    {
        "id": "recon",
        "label": "Усилить разведку",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "log": "Приказ адъютанту: усилить разведку.",
        },
    },
    {
        "id": "counterattack",
        "label": "Провести контратаку",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "set_segments": {"order": "aggressive_attack"},
            "log": "Приказ адъютанту: контратака.",
        },
    },
    {
        "id": "patrol",
        "label": "Выставить патрули",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "log": "Приказ адъютанту: выставить патрули.",
        },
    },
    {
        "id": "supply",
        "label": "Запросить снабжение",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "add_voltages": {"U_supply": 0.1},
            "log": "Приказ адъютанту: запросить снабжение.",
        },
    },
    {
        "id": "artillery",
        "label": "Запросить артподдержку",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "log": "Приказ адъютанту: запросить артподдержку.",
        },
    },
    {
        "id": "reinforce",
        "label": "Запросить подкрепления",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "add_voltages": {"U_manpower": 50.0},
            "log": "Приказ адъютанту: запросить подкрепления.",
        },
    },
    {
        "id": "regroup",
        "label": "Перегруппироваться",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "set_segments": {"order": "cautious_attack"},
            "log": "Приказ адъютанту: перегруппировка.",
        },
    },
    {
        "id": "evac_wounded",
        "label": "Эвакуировать раненых",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "log": "Приказ адъютанту: эвакуация раненых.",
        },
    },
    {
        "id": "withdraw",
        "label": "Организованный отход",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "set_segments": {"order": "movement"},
            "log": "Приказ адъютанту: организованный отход.",
        },
    },
    {
        "id": "night_ops",
        "label": "Перейти к ночным операциям",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "log": "Приказ адъютанту: ночные операции.",
        },
    },
    {
        "id": "evac_hq",
        "label": "Эвакуировать штаб",
        "duration": 1,
        "effect": {
            "targets": ["player"],
            "log": "Приказ адъютанту: эвакуация штаба.",
        },
    },
]


class AdjutantOrdersScreen(BaseScreen):
    """
    Экран приказов адъютанту с пагинацией.

    Читает список приказов из активного сюжета или использует
    фолбэк-список. При выборе приказа применяет эффект, показывает
    реплику адъютанта и тратит игровое время на планирование.

    Attributes:
        panel (Panel): Фоновая панель экрана.
        orders (list[dict]): Список доступных приказов.
        page (int): Индекс текущей страницы.
        order_buttons (list[Button]): Кнопки приказов текущей страницы.
        prev_btn (Button): Кнопка перехода на предыдущую страницу.
        next_btn (Button): Кнопка перехода на следующую страницу.
        close_btn (Button): Кнопка закрытия экрана.
        issued (bool): Флаг выдачи приказа (режим ответа).
        ack_text (str): Текст реплики адъютанта после выдачи приказа.
        btn_close_after (Button): Кнопка закрытия в режиме ответа.
    """

    def __init__(self, app):
        """
        Инициализирует экран приказов адъютанту.

        Загружает список приказов из сюжета или фолбэка, создаёт
        кнопки навигации и первую страницу приказов.

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app)
        self.panel = Panel((290, 90, 700, 540))
        self.orders = self._resolve_orders()
        self.page = 0
        self.order_buttons = []
        self.prev_btn = Button(
            (320, 560, 140, 40), "< Назад", app.font_small, self.prev_page
        )
        self.next_btn = Button(
            (820, 560, 140, 40), "Вперёд >", app.font_small, self.next_page
        )
        self.close_btn = Button(
            (290 + 700 - 46, 90 + 8, 38, 34), "X", app.font_body, app.manager.pop
        )
        self.issued = False
        self.ack_text = ""
        self.btn_close_after = Button(
            (540, 570, 200, 40), "Закрыть", app.font_body, app.manager.pop
        )
        self._build_buttons()
        logger.info(
            "Экран приказов адъютанту: приказов=%d", len(self.orders)
        )

    def _resolve_orders(self):
        """
        Загружает список приказов из активного сюжета или фолбэка.

        Если storyline_interpreter отсутствует или в сюжете нет
        поля adjutant_orders, возвращает DEFAULT_ADJUTANT_ORDERS.

        Returns:
            list[dict]: Список словарей приказов.
        """
        interp = getattr(self.app, "storyline_interpreter", None)
        orders = None
        if interp is not None and getattr(interp, "storyline", None):
            orders = interp.storyline.get("adjutant_orders")
        if not orders:
            orders = DEFAULT_ADJUTANT_ORDERS
        return orders

    def _page_count(self):
        """
        Возвращает общее число страниц списка приказов.

        Returns:
            int: Число страниц (минимум 1).
        """
        return max(1, (len(self.orders) + PAGE_SIZE - 1) // PAGE_SIZE)

    def _build_buttons(self):
        """
        Строит кнопки приказов для текущей страницы.

        Создаёт до PAGE_SIZE кнопок, начиная с индекса
        page * PAGE_SIZE. Каждая кнопка привязывает замыкание
        к конкретному приказу через параметр по умолчанию.
        """
        self.order_buttons = []
        start = self.page * PAGE_SIZE
        for i, order in enumerate(self.orders[start:start + PAGE_SIZE]):
            self.order_buttons.append(
                Button(
                    (320, 170 + i * 52, 640, 44),
                    order.get("label", "?"),
                    self.app.font_small,
                    lambda o=order: self.issue(o),
                )
            )

    def issue(self, order):
        """
        Применяет выбранный приказ.

        Выполняет эффект приказа через EffectInterpreter, выбирает
        случайную реплику адъютанта, записывает событие в лог мира,
        переводит экран в режим ответа и тратит игровое время
        через действие issue_order (или plan_orders_1 как фолбэк).

        Args:
            order (dict): Словарь приказа с полями effect и label.
        """
        st = self.app.engine.state
        effect = order.get("effect")
        if effect:
            EffectInterpreter.apply(st, effect)
        ack = random.choice(ADJUTANT_ACKS)
        st.log_event(st.player_idx, f"Адъютант: {ack}")
        logger.info(
            "Приказ адъютанту: %s | ответ: %s",
            order.get("label"),
            ack,
        )
        self.issued = True
        self.ack_text = f"Адъютант: «{ack}»"
        ts = getattr(self.app, "time_system", None)
        if ts is not None:
            action_id = "issue_order"
            if action_id not in ts.actions:
                action_id = ts.register_order_planning_action(1)
            self.app.execute_player_action(action_id)

    def prev_page(self):
        """Переключает на предыдущую страницу и перестраивает кнопки."""
        if self.page > 0:
            self.page -= 1
            self._build_buttons()

    def next_page(self):
        """Переключает на следующую страницу и перестраивает кнопки."""
        if self.page < self._page_count() - 1:
            self.page += 1
            self._build_buttons()

    def handle_event(self, event):
        """
        Обрабатывает события pygame для экрана приказов.

        В режиме ответа обрабатывается только кнопка закрытия.
        В обычном режиме обрабатываются кнопки навигации,
        закрытия и выбора приказа.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.issued:
            self.btn_close_after.handle_event(event)
            return
        if self.close_btn.handle_event(event):
            return
        if self.prev_btn.handle_event(event):
            return
        if self.next_btn.handle_event(event):
            return
        for b in self.order_buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        """
        Отрисовывает экран приказов адъютанту.

        В режиме ответа рисует затемнение, панель, заголовок
        «Приказ отдан», центрированную реплику адъютанта и кнопку
        закрытия. В обычном режиме рисует заголовок, кнопки приказов,
        кнопки навигации, номер страницы и кнопку закрытия.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        if self.issued:
            t = self.app.font_body.render(
                "Приказ отдан", True, (220, 220, 230)
            )
            screen.blit(t, (self.panel.rect.x + 20, self.panel.rect.y + 14))
            ack_surf = self.app.font_body.render(
                self.ack_text, True, (180, 220, 180)
            )
            screen.blit(ack_surf, ack_surf.get_rect(center=(640, 360)))
            self.btn_close_after.draw(screen)
            return
        t = self.app.font_body.render(
            "Приказы адъютанту", True, (220, 220, 230)
        )
        screen.blit(t, (self.panel.rect.x + 20, self.panel.rect.y + 14))
        for b in self.order_buttons:
            b.draw(screen)
        self.prev_btn.draw(screen)
        self.next_btn.draw(screen)
        info = f"{self.page + 1} / {self._page_count()}"
        info_surf = self.app.font_small.render(info, True, (150, 150, 160))
        screen.blit(info_surf, (640 - info_surf.get_width() // 2, 570))
        self.close_btn.draw(screen)