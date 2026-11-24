# view/screens/role_select.py
import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import draw_fitted
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.role_select")

VISIBLE_ROWS = 7
BUTTON_WIDTH = 330
BUTTON_HEIGHT = 54
ROW_GAP = 66
FIRST_ROW_Y = 172
LIST_X = 90
PREVIEW_RECT = (460, 160, 730, 420)
TEXT = (224, 229, 238)
MUTED = (150, 162, 180)
DIM = (108, 120, 138)
ACCENT = (80, 150, 220)
SCROLL_STEP = 1

MAX_VISIBLE_ROLES = VISIBLE_ROWS

_FILTER_MODES = (
    ("all", "Все"),
    ("character", "Только персонажи"),
    ("lore", "Только лорные"),
    ("street", "Улица"),
    ("school", "Школа"),
    ("temple", "Храм"),
    ("court", "Двор"),
    ("market", "Рынок"),
    ("army", "Армия"),
    ("free", "Свободный"),
)


def _mode_text(role):
    kind = {
        "character": "персонаж",
        "organization": "организация",
        "item": "предмет",
        "place": "место",
    }.get(getattr(role, "entity_kind", "character"), "персонаж")
    layer = getattr(role, "social_layer", "") or "—"
    return "%s · %s" % (kind, layer)


def _filter_roles(roles, mode, lore_storylines):
    if mode == "all":
        return list(roles)
    if mode == "character":
        return [
            role
            for role in roles
            if getattr(role, "entity_kind", "character") == "character"
        ]
    if mode == "lore":
        return [
            role
            for role in roles
            if "lore" in getattr(role, "tags", ())
            or getattr(role, "storyline_id", "") in lore_storylines
        ]
    return [
        role for role in roles
        if getattr(role, "social_layer", "") == mode
    ]


class RoleSelectScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((60, 60, 1160, 600))
        self.buttons = []
        catalog = getattr(app, "role_catalog", None)
        self.all_roles = [] if catalog is None else [
            role
            for role in catalog.available_roles()
            if "legacy" not in role.tags
        ]
        self.lore_storylines = {
            getattr(role, "storyline_id", "")
            for role in self.all_roles
            if getattr(role, "storyline_id", "")
        }
        self.filter_mode = "all"
        self.filter_order = [item[0] for item in _FILTER_MODES]
        self.roles = _filter_roles(
            self.all_roles, self.filter_mode, self.lore_storylines
        )
        self.scroll_offset = 0
        self.empty = not self.roles
        self.selected_id = self.roles[0].id if self.roles else None
        self._rebuild_buttons()
        self.continue_button = Button(
            (1010, 610, 190, 40),
            "Продолжить",
            app.font_body,
            self.continue_to_storyline,
        )
        self.back_button = Button(
            (90, 610, 160, 40),
            "Назад",
            app.font_body,
            app.manager.pop,
        )
        self.filter_button = Button(
            (90, 116, 260, 32),
            "Фильтр: Все",
            app.font_small,
            self.next_filter,
        )
        self.archetype_button = Button(
            (780, 610, 220, 40),
            self._archetype_label(),
            app.font_small,
            self.open_archetypes,
        )
        self.character_button = Button(
            (500, 610, 260, 40),
            self._character_label(),
            app.font_small,
            self.open_characters,
        )
        logger.info(
            "Экран выбора роли: всего=%d, показано=%d, фильтр=%s",
            len(self.all_roles),
            len(self.roles),
            self.filter_mode,
        )

    def _rebuild_buttons(self):
        self.buttons = []
        for index in range(VISIBLE_ROWS):
            self.buttons.append(
                Button(
                    (
                        LIST_X,
                        FIRST_ROW_Y + index * ROW_GAP,
                        BUTTON_WIDTH,
                        BUTTON_HEIGHT,
                    ),
                    "",
                    self.app.font_body,
                    self._make_select_handler(index),
                )
            )

    def _make_select_handler(self, row_index):
        def handler():
            visible = self._visible_roles()
            if row_index < len(visible):
                self.select(visible[row_index].id)
        return handler

    def _visible_roles(self):
        start = self.scroll_offset
        end = start + VISIBLE_ROWS
        return self.roles[start:end]

    @property
    def current_role(self):
        if self.selected_id is None:
            return None
        return next(
            (
                role
                for role in self.roles
                if role.id == self.selected_id
            ),
            None,
        )

    def _clamp_scroll(self):
        max_offset = max(0, len(self.roles) - VISIBLE_ROWS)
        if self.scroll_offset > max_offset:
            self.scroll_offset = max_offset
        if self.scroll_offset < 0:
            self.scroll_offset = 0

    def _scroll_to_selected(self):
        if not self.roles or self.selected_id is None:
            return
        index = next(
            (
                i for i, role in enumerate(self.roles)
                if role.id == self.selected_id
            ),
            None,
        )
        if index is None:
            return
        if index < self.scroll_offset:
            self.scroll_offset = index
        elif index >= self.scroll_offset + VISIBLE_ROWS:
            self.scroll_offset = index - VISIBLE_ROWS + 1
        self._clamp_scroll()

    def next_filter(self):
        if not self.filter_order:
            return
        try:
            index = self.filter_order.index(self.filter_mode)
        except ValueError:
            index = -1
        self.set_filter(
            self.filter_order[(index + 1) % len(self.filter_order)]
        )

    def set_filter(self, mode):
        if mode not in self.filter_order:
            return
        self.filter_mode = mode
        self.roles = _filter_roles(
            self.all_roles, self.filter_mode, self.lore_storylines
        )
        self.scroll_offset = 0
        self.empty = not self.roles
        if not self.roles:
            self.selected_id = None
        elif self.current_role is None:
            self.selected_id = self.roles[0].id
        self._clamp_scroll()
        label = dict(_FILTER_MODES).get(self.filter_mode, self.filter_mode)
        self.filter_button.text = "Фильтр: %s" % label
        logger.info(
            "Фильтр ролей: %s (ролей=%d)",
            self.filter_mode,
            len(self.roles),
        )

    def select(self, role_id):
        if self.app.role_catalog is None:
            logger.warning("Выбор роли недоступен: каталог пуст")
            return
        try:
            role = self.app.role_catalog.select(role_id)
        except Exception as exc:
            logger.error("Роль %s недоступна: %s", role_id, exc)
            return
        self.selected_id = role.id
        self._scroll_to_selected()
        logger.info(
            "Выбрана роль (предпросмотр): %s (%s)",
            role.id,
            role.label,
        )

    def select_previous(self):
        if not self.roles:
            return
        ids = [role.id for role in self.roles]
        try:
            index = ids.index(self.selected_id)
        except ValueError:
            index = 0
        self.select(ids[(index - 1) % len(ids)])

    def select_next(self):
        if not self.roles:
            return
        ids = [role.id for role in self.roles]
        try:
            index = ids.index(self.selected_id)
        except ValueError:
            index = -1
        self.select(ids[(index + 1) % len(ids)])

    def scroll_up(self):
        self.scroll_offset -= SCROLL_STEP
        self._clamp_scroll()

    def scroll_down(self):
        self.scroll_offset += SCROLL_STEP
        self._clamp_scroll()

    def continue_to_storyline(self):
        role = self.current_role
        if role is None:
            logger.warning("Продолжение невозможно: роль не выбрана")
            return
        previous_role = getattr(self.app, "selected_role", None)
        if previous_role is None or previous_role.id != role.id:
            self.app.selected_player_character_id = ""
            self.app.selected_player_character_label = ""
        self.app.selected_role = role
        self.app.selected_faction_id = None
        self.app.campaign_preset = None
        logger.info("Подтверждена роль: %s (%s)", role.id, role.label)
        if role.storyline_id:
            from view.support.storyline import load_storyline

            storyline = load_storyline(role.storyline_id)
            if storyline is None:
                logger.error(
                    "Сюжет роли не найден: %s (роль %s)",
                    role.storyline_id,
                    role.id,
                )
                return
            if storyline.get("identity_editor"):
                from .identity_editor import IdentityEditorScreen

                self.app.manager.push(
                    IdentityEditorScreen(self.app, storyline)
                )
                return
            self.app.start_storyline(storyline)
            return
        if role.faction_choice:
            from .faction_select import FactionSelectScreen

            self.app.manager.push(FactionSelectScreen(self.app))
            return
        from .storyline_select import StorylineSelectScreen

        self.app.manager.push(StorylineSelectScreen(self.app))

    def _archetype_label(self):
        label = str(
            getattr(self.app, "selected_archetype_label", "") or ""
        )
        return "Архетип: %s" % (label or "нет")

    def open_archetypes(self):
        from .archetype_select import ArchetypeSelectScreen

        self.app.manager.push(ArchetypeSelectScreen(self.app))

    def _character_label(self):
        label = str(
            getattr(self.app, "selected_player_character_label", "") or ""
        )
        return "Герой: %s" % (label or "лидер")

    def open_characters(self):
        role = self.current_role
        if role is None:
            logger.warning("Список героев недоступен: роль не выбрана")
            return
        self.app.selected_role = role
        from .character_select import CharacterSelectScreen

        self.app.manager.push(CharacterSelectScreen(self.app))

    def _visible_button_roles(self):
        return self._visible_roles()

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_DOWN, pygame.K_s):
                self.select_next()
                return
            if event.key in (pygame.K_UP, pygame.K_w):
                self.select_previous()
                return
            if event.key in (pygame.K_PAGEDOWN,):
                self.scroll_down()
                return
            if event.key in (pygame.K_PAGEUP,):
                self.scroll_up()
                return
            if event.key == pygame.K_TAB:
                self.next_filter()
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.continue_to_storyline()
                return
            if event.key == pygame.K_ESCAPE:
                self.app.manager.pop()
                return
        if event.type == pygame.MOUSEWHEEL:
            if event.y > 0:
                self.scroll_up()
            elif event.y < 0:
                self.scroll_down()
            return
        if self.filter_button.handle_event(event):
            return
        if self.archetype_button.handle_event(event):
            return
        if self.character_button.handle_event(event):
            return
        visible = self._visible_roles()
        for index, button in enumerate(self.buttons):
            if index >= len(visible):
                continue
            if button.handle_event(event):
                return
        if self.continue_button.handle_event(event):
            return
        if self.back_button.handle_event(event):
            return

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
        role = self.current_role
        if role is None:
            return
        screen.blit(
            self.app.font_small.render("РОЛЬ", True, MUTED), (x + 20, y + 16)
        )
        screen.blit(
            self.app.font_body.render(role.label, True, TEXT),
            (x + 20, y + 42),
        )
        screen.blit(
            self.app.font_tiny.render(_mode_text(role), True, ACCENT),
            (x + 20, y + 70),
        )
        archetype_label = str(
            getattr(self.app, "selected_archetype_label", "") or ""
        )
        if archetype_label:
            screen.blit(
                self.app.font_tiny.render(
                    "Стартовая точка: %s" % archetype_label,
                    True,
                    DIM,
                ),
                (x + 20, y + 88),
            )
        draw_fitted(
            screen,
            [
                self.app.font_body,
                self.app.font_small,
                self.app.font_tiny,
            ],
            role.description,
            (x + 20, y + 104, width - 40, height - 170),
            TEXT,
        )
        meta_y = y + height - 56
        if getattr(role, "start_offices", ()):
            screen.blit(
                self.app.font_tiny.render(
                    "Стартовые работы: %s"
                    % ", ".join(role.start_offices),
                    True,
                    DIM,
                ),
                (x + 20, meta_y),
            )
            meta_y += 18
        if getattr(role, "storyline_tags", ()):
            screen.blit(
                self.app.font_tiny.render(
                    "Теги сюжета: %s" % ", ".join(role.storyline_tags),
                    True,
                    DIM,
                ),
                (x + 20, meta_y),
            )
            meta_y += 18
        if role.tags:
            screen.blit(
                self.app.font_tiny.render(
                    "Теги роли: %s" % ", ".join(role.tags), True, DIM
                ),
                (x + 20, meta_y),
            )

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_title.render("Выбор роли", True, (220, 220, 230))
        screen.blit(title, title.get_rect(center=(640, 94)))
        subtitle = self.app.font_small.render(
            "Кем вы входите в кампанию? TAB — фильтр, ↑/↓ — выбор.",
            True,
            MUTED,
        )
        screen.blit(subtitle, subtitle.get_rect(center=(640, 132)))
        self.filter_button.draw(screen)
        if self.empty:
            msg = self.app.font_small.render(
                "Пока нет доступных ролей", True, (150, 150, 160)
            )
            screen.blit(msg, msg.get_rect(center=(640, 350)))
        visible = self._visible_roles()
        for index, role in enumerate(visible):
            button = self.buttons[index]
            button.text = role.label
            button.draw(screen)
            if role.id == self.selected_id:
                pygame.draw.rect(
                    screen,
                    ACCENT,
                    button.rect.inflate(6, 6),
                    2,
                    border_radius=8,
                )
        self._draw_scrollbar(screen)
        self._draw_preview(screen)
        note = self.app.font_tiny.render(
            "Каталог ролей: configs/roles/*.json · "
            "Архетипы: configs/characters/archetypes.json",
            True,
            DIM,
        )
        screen.blit(note, note.get_rect(center=(640, 660)))
        self.archetype_button.text = self._archetype_label()
        self.character_button.text = self._character_label()
        self.archetype_button.draw(screen)
        self.character_button.draw(screen)
        self.back_button.draw(screen)
        self.continue_button.draw(screen)

    def _draw_scrollbar(self, screen):
        if len(self.roles) <= VISIBLE_ROWS:
            return
        track_x = LIST_X + BUTTON_WIDTH + 12
        track_y = FIRST_ROW_Y
        track_h = VISIBLE_ROWS * ROW_GAP
        pygame.draw.rect(
            screen,
            (40, 48, 64),
            (track_x, track_y, 6, track_h),
            border_radius=3,
        )
        total = len(self.roles)
        thumb_h = max(24, int(track_h * VISIBLE_ROWS / total))
        max_offset = max(1, total - VISIBLE_ROWS)
        thumb_y = track_y + int(
            (track_h - thumb_h) * (self.scroll_offset / max_offset)
        )
        pygame.draw.rect(
            screen,
            ACCENT,
            (track_x, thumb_y, 6, thumb_h),
            border_radius=3,
        )


__all__ = ["RoleSelectScreen", "MAX_VISIBLE_ROLES", "VISIBLE_ROWS"]
