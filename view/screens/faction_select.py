import os

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import wrap_text
from ..ui.widgets import Button, Panel
from campaign import CampaignPresetGenerator
from view.support.log_journal import get_logger
from view.support.storyline import load_storyline

logger = get_logger("view.faction_select")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

TEXT = (224, 229, 238)
MUTED = (150, 162, 180)
DIM = (108, 120, 138)
ACCENT = (80, 150, 220)

LIST_X = 80
LIST_Y = 180
LIST_W = 300
ROW_H = 70
ROW_GAP = 78
PREVIEW_RECT = (410, 160, 780, 420)


class FactionSelectScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((60, 60, 1160, 600))
        self.role = getattr(app, "selected_role", None)
        self.storyline = None
        if self.role is not None and self.role.storyline_id:
            self.storyline = load_storyline(self.role.storyline_id)
        seed = app._campaign_seed(self.storyline or {})
        template_path = (self.storyline or {}).get("campaign_template")
        if template_path and not os.path.isabs(template_path):
            template_path = os.path.normpath(
                os.path.join(BASE_DIR, template_path)
            )
        generator = CampaignPresetGenerator(
            catalog=app.role_catalog,
            template_path=template_path or None,
        )
        self.options = generator.faction_options(seed=seed)
        self.option_buttons = {}
        self.empty = not self.options
        self.selected_id = self.options[0]["id"] if self.options else None
        logger.info(
            "Экран выбора фракции: доступно=%d, роль=%s",
            len(self.options),
            getattr(self.role, "id", "—"),
        )
        for index, option in enumerate(self.options[:4]):
            faction_id = option["id"]
            button = Button(
                (
                    LIST_X,
                    LIST_Y + index * ROW_GAP,
                    LIST_W,
                    ROW_H,
                ),
                option["name"],
                app.font_body,
                lambda fid=faction_id: self.select(fid),
            )
            self.option_buttons[faction_id] = button
        self.buttons = list(self.option_buttons.values())
        self.continue_button = Button(
            (1010, 610, 190, 40),
            "Продолжить",
            app.font_body,
            self.continue_to_storyline,
        )
        self.back_button = Button(
            (80, 610, 160, 40),
            "Назад",
            app.font_body,
            app.manager.pop,
        )
        self.buttons.extend((self.continue_button, self.back_button))

    @property
    def current_option(self):
        if self.selected_id is None:
            return None
        return next(
            (
                option
                for option in self.options
                if option["id"] == self.selected_id
            ),
            None,
        )

    def select(self, faction_id):
        if faction_id not in self.option_buttons:
            return
        self.selected_id = faction_id
        logger.info("Выбрана фракция (предпросмотр): %s", faction_id)

    def continue_to_storyline(self):
        if self.storyline is None:
            logger.warning(
                "Сюжет роли не найден: %s",
                getattr(self.role, "storyline_id", ""),
            )
            return
        if self.selected_id is None:
            return
        self.app.selected_faction_id = self.selected_id
        logger.info("Подтверждена фракция: %s", self.selected_id)
        if self.storyline.get("identity_editor"):
            from .identity_editor import IdentityEditorScreen

            self.app.manager.push(
                IdentityEditorScreen(
                    self.app,
                    self.storyline,
                    faction_id=self.selected_id,
                )
            )
            return
        self.app.start_storyline(
            self.storyline, faction_id=self.selected_id
        )

    def handle_event(self, event):
        for button in self.buttons:
            if button.handle_event(event):
                return

    def _draw_option_row(self, screen, index, option):
        rect = pygame.Rect(
            LIST_X,
            LIST_Y + index * ROW_GAP,
            LIST_W,
            ROW_H,
        )
        selected = option["id"] == self.selected_id
        pygame.draw.rect(
            screen,
            (34, 48, 68) if selected else (24, 30, 43),
            rect,
            border_radius=6,
        )
        pygame.draw.rect(
            screen,
            ACCENT if selected else (58, 70, 92),
            rect,
            2,
            border_radius=6,
        )
        screen.blit(
            self.app.font_body.render(option["name"], True, TEXT),
            (rect.x + 12, rect.y + 8),
        )
        meta = "%s · %s" % (
            option["side"].upper(),
            {
                "coalition": "коалиция",
                "consortium": "консорциум",
                "automaton": "автомат",
            }.get(option["kind"], option["kind"]),
        )
        screen.blit(
            self.app.font_tiny.render(meta, True, ACCENT),
            (rect.x + 12, rect.y + 36),
        )
        support = "групп: %d · поддержка %.0f%%" % (
            option.get("groups") or 0,
            100.0 * float(option.get("support") or 0.0),
        )
        screen.blit(
            self.app.font_tiny.render(support, True, DIM),
            (rect.x + 12, rect.y + 51),
        )

    def _draw_preview(self, screen):
        x, y, width, height = PREVIEW_RECT
        pygame.draw.rect(
            screen,
            (16, 21, 31),
            (x, y, width, height),
            border_radius=8,
        )
        pygame.draw.rect(
            screen, (58, 70, 92), (x, y, width, height), 2, border_radius=8
        )
        option = self.current_option
        if option is None:
            return
        screen.blit(
            self.app.font_small.render("ФРАКЦИЯ", True, MUTED),
            (x + 20, y + 16),
        )
        screen.blit(
            self.app.font_body.render(option["name"], True, TEXT),
            (x + 20, y + 42),
        )
        side = (
            "стартовая сторона"
            if option["is_default"]
            else "альтернативная сторона"
        )
        meta = "%s · %s · %s · опора %.0f%%" % (
            option["side"].upper(),
            option.get("kind", "коалиция"),
            side,
            100.0 * float(option.get("support") or 0.0),
        )
        screen.blit(
            self.app.font_tiny.render(meta, True, ACCENT),
            (x + 20, y + 70),
        )
        details = "Организация: %s · Лидер: %s" % (
            option.get("organization_name") or "—",
            option.get("leader_name") or "—",
        )
        screen.blit(
            self.app.font_small.render(details, True, (190, 190, 205)),
            (x + 20, y + 96),
        )
        goals = list(option.get("goals") or ())
        goal_y = y + 130
        screen.blit(
            self.app.font_small.render("Цели фракции", True, MUTED),
            (x + 20, goal_y),
        )
        goal_y += 24
        for goal in goals:
            lines = wrap_text(
                self.app.font_small, "• %s" % goal, width - 44
            )
            for line in lines:
                if goal_y > y + height - 24:
                    break
                screen.blit(
                    self.app.font_small.render(line, True, TEXT),
                    (x + 22, goal_y),
                )
                goal_y += 20
            goal_y += 4
        assets = option.get("assets") or {}
        if assets and goal_y < y + height - 28:
            screen.blit(
                self.app.font_tiny.render(
                    "Активы: "
                    + ", ".join(
                        "%s %.2f" % (key, float(value))
                        for key, value in list(assets.items())[:6]
                    ),
                    True,
                    DIM,
                ),
                (x + 20, y + height - 26),
            )
        if (self.storyline or {}).get("identity_editor"):
            screen.blit(
                self.app.font_tiny.render(
                    "После выбора фракции откроется редактор личности.",
                    True,
                    MUTED,
                ),
                (x + 20, y + height - 48),
            )

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_title.render(
            "Выбор фракции", True, (220, 220, 230)
        )
        screen.blit(title, title.get_rect(center=(640, 94)))
        subtitle = self.app.font_small.render(
            "Выберите, чью коалицию и чей голос вы будете представлять.",
            True,
            MUTED,
        )
        screen.blit(subtitle, subtitle.get_rect(center=(640, 128)))
        if self.empty:
            msg = self.app.font_small.render(
                "В шаблоне кампании нет доступных фракций",
                True,
                (190, 150, 150),
            )
            screen.blit(msg, msg.get_rect(center=(640, 350)))
        for index, option in enumerate(self.options[:4]):
            self._draw_option_row(screen, index, option)
        self._draw_preview(screen)
        note = self.app.font_tiny.render(
            "Выбор меняет сторону, доступных персонажей и текст мандата.",
            True,
            DIM,
        )
        screen.blit(note, note.get_rect(center=(640, 660)))
        self.back_button.draw(screen)
        self.continue_button.draw(screen)


__all__ = ["FactionSelectScreen"]
