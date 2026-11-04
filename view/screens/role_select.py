from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.role_select")

MAX_VISIBLE_ROLES = 4
BUTTON_WIDTH = 340
BUTTON_HEIGHT = 56
COLUMN_GAP = 24
ROW_GAP = 160
FIRST_ROW_Y = 200


def _wrap(font, text, max_width):
    words = str(text or "").split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if font.size(candidate)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _grid(count):
    """Колонки и число строк для списка ролей."""
    if count <= 1:
        return 1, max(1, count)
    if count == 2:
        return 1, 2
    return 2, (count + 1) // 2


class RoleSelectScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((250, 70, 780, 580))
        self.buttons = []
        catalog = getattr(app, "role_catalog", None)
        self.roles = [] if catalog is None else [
            role
            for role in catalog.available_roles()
            if "legacy" not in role.tags
        ]
        self.roles = self.roles[:MAX_VISIBLE_ROLES]
        self.empty = not self.roles

        columns, _ = _grid(len(self.roles))
        self.columns = columns
        self.button_width = BUTTON_WIDTH if columns > 1 else 600
        self.max_lines = 3 if columns > 1 else 4
        logger.info(
            "Экран выбора роли: доступно ролей=%d, колонок=%d",
            len(self.roles),
            columns,
        )
        for index, role in enumerate(self.roles):
            x, y = self._slot(index)
            self.buttons.append(
                Button(
                    (x, y, self.button_width, BUTTON_HEIGHT),
                    role.label,
                    app.font_body,
                    lambda rid=role.id: self.select(rid),
                )
            )
        self.buttons.append(
            Button(
                (540, 600, 200, 40),
                "Назад",
                app.font_body,
                app.manager.pop,
            )
        )
        self.back_button = self.buttons[-1]

    def _slot(self, index):
        if self.columns <= 1:
            x = 640 - self.button_width // 2
            return x, FIRST_ROW_Y + index * ROW_GAP
        row, column = divmod(index, self.columns)
        total = self.columns * self.button_width + (self.columns - 1) * COLUMN_GAP
        left = 640 - total // 2
        x = left + column * (self.button_width + COLUMN_GAP)
        y = FIRST_ROW_Y + row * ROW_GAP
        return x, y

    def select(self, role_id):
        if self.app.role_catalog is None:
            logger.warning("Выбор роли недоступен: каталог пуст")
            return
        try:
            role = self.app.role_catalog.select(role_id)
        except Exception as exc:
            logger.error("Роль %s недоступна: %s", role_id, exc)
            return
        self.app.selected_role = role
        self.app.selected_faction_id = None
        self.app.campaign_preset = None
        logger.info("Выбрана роль: %s (%s)", role.id, role.label)
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
            self.app.start_storyline(storyline)
            return
        if role.faction_choice:
            from .faction_select import FactionSelectScreen

            self.app.manager.push(FactionSelectScreen(self.app))
            return
        from .storyline_select import StorylineSelectScreen

        self.app.manager.push(StorylineSelectScreen(self.app))

    def handle_event(self, event):
        for button in self.buttons:
            if button.handle_event(event):
                return

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_title.render("Выбор роли", True, (220, 220, 230))
        screen.blit(title, title.get_rect(center=(640, 110)))
        subtitle = self.app.font_small.render(
            "Кем вы входите в кампанию?", True, (150, 150, 170)
        )
        screen.blit(subtitle, subtitle.get_rect(center=(640, 150)))
        if self.empty:
            msg = self.app.font_small.render(
                "Пока нет доступных ролей", True, (150, 150, 160)
            )
            screen.blit(msg, msg.get_rect(center=(640, 350)))
        for index, role in enumerate(self.roles):
            button = self.buttons[index]
            button.draw(screen)
            x, y = self._slot(index)
            top = y + BUTTON_HEIGHT + 6
            mode = self.app.font_tiny.render(
                "Режим: %s · опора: %s"
                % (
                    {
                        "nominal": "гражданский мандат",
                        "civilian_mandate": "гражданский мандат",
                        "official": "должностное лицо",
                    }.get(role.leadership, role.leadership),
                    {
                        "coalition": "коалиция",
                        "automaton": "автомат",
                    }.get(role.faction_kind, role.faction_kind),
                ),
                True,
                (130, 165, 215),
            )
            screen.blit(mode, (x, top))
            lines = _wrap(
                self.app.font_small, role.description, self.button_width
            )
            for line_number, line in enumerate(lines[: self.max_lines]):
                surf = self.app.font_small.render(line, True, (190, 190, 205))
                screen.blit(surf, (x, top + 18 + line_number * 19))
        note = self.app.font_tiny.render(
            "Каталог ролей: configs/roles/*.json", True, (110, 110, 130)
        )
        screen.blit(note, note.get_rect(center=(640, 565)))
        self.back_button.draw(screen)


__all__ = ["RoleSelectScreen", "MAX_VISIBLE_ROLES"]
