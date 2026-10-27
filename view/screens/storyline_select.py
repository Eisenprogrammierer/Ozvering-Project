from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.storyline import list_storylines
from view.support.log_journal import get_logger

logger = get_logger("view.storyline_select")

MAX_VISIBLE_STORYLINES = 5


class StorylineSelectScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((290, 70, 700, 580))
        self.buttons = []
        storylines = list_storylines()
        self.empty = not storylines
        self.role = getattr(app, "selected_role", None)
        logger.info(
            "Экран выбора сюжета: доступно сюжетов=%d, роль=%s",
            len(storylines),
            getattr(self.role, "id", "—"),
        )
        y = 170
        for entry in storylines[:MAX_VISIBLE_STORYLINES]:
            label = entry["title"]
            self.buttons.append(
                Button(
                    (340, y, 600, 60),
                    label,
                    app.font_body,
                    lambda sid=entry["storyline_id"]: self.select(sid),
                )
            )
            y += 70
        self.buttons.append(
            Button(
                (540, 600, 200, 40),
                "Назад",
                app.font_body,
                app.manager.pop,
            )
        )

    def select(self, storyline_id):
        from view.support.storyline import load_storyline

        logger.info("Выбран сюжет: %s", storyline_id)
        storyline = load_storyline(storyline_id)
        if storyline is None:
            logger.warning("Сюжет не загружен: %s", storyline_id)
            return
        logger.info("Сюжет запущен: %s", storyline_id)
        self.app.start_storyline(storyline)

    def handle_event(self, event):
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_title.render(
            "Выбор сюжета", True, (220, 220, 230)
        )
        screen.blit(title, title.get_rect(center=(640, 110)))
        if self.role is not None:
            role_line = self.app.font_small.render(
                "Роль: %s" % self.role.label, True, (130, 165, 215)
            )
            screen.blit(role_line, role_line.get_rect(center=(640, 142)))
        if self.empty:
            msg = self.app.font_small.render(
                "Пока пусто", True, (150, 150, 160)
            )
            screen.blit(msg, msg.get_rect(center=(640, 350)))
        for b in self.buttons:
            b.draw(screen)
