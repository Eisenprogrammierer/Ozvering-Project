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

    def __init__(self, app):
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
            (290 + 700 - 46, 90 + 8, 38, 34),
            "X",
            app.font_body,
            app.manager.pop,
        )
        self.issued = False
        self.ack_text = ""
        self.btn_close_after = Button(
            (540, 570, 200, 40), "Закрыть", app.font_body, app.manager.pop
        )
        self._build_buttons()
        logger.info("Экран приказов адъютанту: приказов=%d", len(self.orders))

    def _resolve_orders(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        orders = None
        if interp is not None and getattr(interp, "storyline", None):
            orders = interp.storyline.get("adjutant_orders")
        if not orders:
            orders = DEFAULT_ADJUTANT_ORDERS
        return orders

    def _page_count(self):
        return max(1, (len(self.orders) + PAGE_SIZE - 1) // PAGE_SIZE)

    def _build_buttons(self):
        self.order_buttons = []
        start = self.page * PAGE_SIZE
        for i, order in enumerate(self.orders[start : start + PAGE_SIZE]):
            self.order_buttons.append(
                Button(
                    (320, 170 + i * 52, 640, 44),
                    order.get("label", "?"),
                    self.app.font_small,
                    lambda o=order: self.issue(o),
                )
            )

    def issue(self, order):
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
        if self.page > 0:
            self.page -= 1
            self._build_buttons()

    def next_page(self):
        if self.page < self._page_count() - 1:
            self.page += 1
            self._build_buttons()

    def handle_event(self, event):
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
