from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.role_select")

MAX_VISIBLE_ROLES = 3


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


class RoleSelectScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((250, 70, 780, 580))
        self.buttons = []
        self.roles = list(app.role_catalog.available_roles())
        self.empty = not self.roles

        self.step = 140 if len(self.roles) <= 1 else 112
        self.max_lines = 4 if len(self.roles) <= 1 else 2
        logger.info("Экран выбора роли: доступно ролей=%d", len(self.roles))
        y = 210
        for role in self.roles[:MAX_VISIBLE_ROLES]:
            self.buttons.append(
                Button(
                    (340, y, 600, 58),
                    role.label,
                    app.font_body,
                    lambda rid=role.id: self.select(rid),
                )
            )
            y += self.step
        self.buttons.append(
            Button(
                (540, 600, 200, 40),
                "Назад",
                app.font_body,
                app.manager.pop,
            )
        )

    def select(self, role_id):
        role = self.app.role_catalog.select(role_id)
        self.app.selected_role = role
        self.app.selected_faction_id = None
        self.app.campaign_preset = None
        logger.info("Выбрана роль: %s (%s)", role.id, role.label)
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
        for index, role in enumerate(self.roles[:MAX_VISIBLE_ROLES]):
            self.buttons[index].draw(screen)
            top = 278 + index * self.step
            mode = self.app.font_small.render(
                "Режим: %s · фракция: %s"
                % (
                    (
                        "номинальное лидерство"
                        if role.leadership == "nominal"
                        else role.leadership
                    ),
                    (
                        "автомат"
                        if role.faction_kind == "automaton"
                        else role.faction_kind
                    ),
                ),
                True,
                (130, 165, 215),
            )
            screen.blit(mode, (340, top))
            lines = _wrap(self.app.font_small, role.description, 600)
            for line_number, line in enumerate(lines[: self.max_lines]):
                surf = self.app.font_small.render(line, True, (190, 190, 205))
                screen.blit(surf, (340, top + 22 + line_number * 20))
        note = self.app.font_tiny.render(
            "Каталог ролей: configs/roles/roles.json", True, (110, 110, 130)
        )
        screen.blit(note, note.get_rect(center=(640, 560)))
        for button in self.buttons[len(self.roles[:MAX_VISIBLE_ROLES]) :]:
            button.draw(screen)


__all__ = ["RoleSelectScreen"]
