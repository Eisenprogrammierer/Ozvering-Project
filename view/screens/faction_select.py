from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from campaign import CampaignPresetGenerator
from view.support.log_journal import get_logger
from view.support.storyline import load_storyline

logger = get_logger("view.faction_select")


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


class FactionSelectScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((170, 60, 940, 600))
        self.role = getattr(app, "selected_role", None)
        self.storyline = None
        if self.role is not None and self.role.storyline_id:
            self.storyline = load_storyline(self.role.storyline_id)
        seed = app._campaign_seed(self.storyline or {})
        generator = CampaignPresetGenerator(catalog=app.role_catalog)
        self.options = generator.faction_options(seed=seed)
        self.buttons = []
        self.option_buttons = {}
        self.empty = not self.options
        logger.info(
            "Экран выбора фракции: доступно=%d, роль=%s",
            len(self.options),
            getattr(self.role, "id", "—"),
        )
        y = 190
        for option in self.options[:2]:
            faction_id = option["id"]
            self.option_buttons[faction_id] = Button(
                (280, y, 720, 58),
                option["name"],
                app.font_body,
                lambda fid=faction_id: self.select(fid),
            )
            self.buttons.append(self.option_buttons[faction_id])
            y += 150
        self.buttons.append(
            Button(
                (540, 610, 200, 40),
                "Назад",
                app.font_body,
                app.manager.pop,
            )
        )

    def select(self, faction_id):
        if self.storyline is None:
            logger.warning(
                "Сюжет роли не найден: %s",
                getattr(self.role, "storyline_id", ""),
            )
            return
        self.app.selected_faction_id = faction_id
        logger.info("Выбрана фракция: %s", faction_id)
        self.app.start_storyline(self.storyline, faction_id=faction_id)

    def handle_event(self, event):
        for button in self.buttons:
            if button.handle_event(event):
                return

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_title.render(
            "Выбор фракции", True, (220, 220, 230)
        )
        screen.blit(title, title.get_rect(center=(640, 100)))
        subtitle = self.app.font_small.render(
            "Мандат номинального лидера: выберите, чью волю вы будете "
            "представлять.",
            True,
            (150, 150, 170),
        )
        screen.blit(subtitle, subtitle.get_rect(center=(640, 140)))
        if self.empty:
            msg = self.app.font_small.render(
                "В шаблоне кампании нет доступных фракций",
                True,
                (190, 150, 150),
            )
            screen.blit(msg, msg.get_rect(center=(640, 350)))
        for index, option in enumerate(self.options[:2]):
            top = 190 + index * 150
            button = self.option_buttons.get(option["id"])
            if button is not None:
                button.draw(screen)
            side = (
                "стартовая сторона"
                if option["is_default"]
                else "альтернативная сторона"
            )
            meta = self.app.font_small.render(
                "%s · %s · %d рот · %s"
                % (
                    option["side"].upper(),
                    option["kind"],
                    option["companies"],
                    side,
                ),
                True,
                (130, 165, 215),
            )
            screen.blit(meta, (280, top + 66))
            details = "Организация: %s · Лидер: %s" % (
                option["organization_name"] or "—",
                option["leader_name"] or "—",
            )
            screen.blit(
                self.app.font_small.render(details, True, (190, 190, 205)),
                (280, top + 88),
            )
            goals = option["goals"]
            if goals:
                lines = _wrap(
                    self.app.font_small,
                    "Цель: %s" % goals[0],
                    720,
                )
                for line_number, line in enumerate(lines[:2]):
                    screen.blit(
                        self.app.font_small.render(
                            line, True, (170, 170, 185)
                        ),
                        (280, top + 110 + line_number * 18),
                    )
        note = self.app.font_tiny.render(
            "Выбор меняет сторону игрока, состав ростера и текст мандата.",
            True,
            (110, 110, 130),
        )
        screen.blit(note, note.get_rect(center=(640, 565)))
        self.buttons[-1].draw(screen)


__all__ = ["FactionSelectScreen"]
