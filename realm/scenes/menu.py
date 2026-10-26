"""Главное меню «Престола»."""

from ui import theme
from ui.scenes.base import MenuScene


class MainMenuScene(MenuScene):
    name = "menu"
    hero_key = "menu_hero"
    title = "ПРЕСТОЛ"
    subtitle = "Номинальный лидер фракции"
    footer = "Мышь — выбор · F11 — полный экран"

    def on_enter(self, **kwargs):
        story = self.app.content.story
        self.title = story.get("title", "ПРЕСТОЛ")
        self.subtitle = story.get("subtitle", "Номинальный лидер фракции")
        self.tagline = story.get("tagline", "")
        self.has_save = self.app.save.has_any_save()

    def build_buttons(self):
        return [
            ("Новая партия", self._new_game, True),
            ("Продолжить", self._continue, self.has_save),
            ("Загрузить", lambda: self.app.open_saves("load"), True),
            ("Настройки", self.app.open_settings, True),
            ("Об игре", lambda: self.app.go("about"), True),
            ("Выход", self.app.quit, True),
        ]

    def _new_game(self):
        self.app.go("mandate")

    def _continue(self):
        if not self.app.continue_game():
            self.layout(*self.app.size)

    def draw(self, s):
        super().draw(s)
        w, h = s.get_size()
        if getattr(self, "tagline", ""):
            theme.text(s, self.app.fonts.font_s, self.tagline,
                       (w // 2, int(h * 0.255)), theme.TEXT_MUTED, center=True)
