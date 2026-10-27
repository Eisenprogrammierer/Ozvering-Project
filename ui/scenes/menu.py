from .. import content, save, theme
from .base import MenuScene


class MainMenuScene(MenuScene):
    name = "menu"
    hero_key = "menu_hero"

    def on_enter(self, **kwargs):
        self.title = content.TITLE
        self.subtitle = self.app.t(*content.SUBTITLE)
        self.tagline = self.app.t(*content.TAGLINE)
        self.footer = self.app.t(
            "Мышь — выбор; ESC в партии — пауза.",
            "Mouse to choose; ESC in a match - pause.",
        )
        self.has_save = self.app.save.has_autosave()

    def build_buttons(self):
        t = self.app.t
        return [
            (
                t("Поле боя (RTS)", "Battlefield (RTS)"),
                self._battlefield,
                True,
            ),
            (t("Взаимодействие", "Interaction"), self._interaction, True),
            (t("Новая партия", "New game"), self._new_game, True),
            (t("Продолжить", "Continue"), self._continue, self.has_save),
            (
                t("Загрузить", "Load"),
                lambda: self.app.go("saves", mode="load"),
                True,
            ),
            (
                t("Настройки", "Settings"),
                lambda: self.app.go("settings"),
                True,
            ),
            (t("Об игре", "About"), lambda: self.app.go("about"), True),
            (t("Выход", "Quit"), self.app.quit, True),
        ]

    def _battlefield(self):
        self.app.go("battlefield", new=True)

    def _interaction(self):
        self.app.go("interaction")

    def _new_game(self):
        self.app.go(
            "narrative",
            pages=content.INTRO_PAGES,
            next_scene="game",
            next_kwargs={"new": True},
        )

    def _continue(self):
        data = self.app.save.read(save.AUTOSAVE_SLOT)
        self.app.go("game", save_data=data)

    def draw(self, s):
        super().draw(s)
        if getattr(self, "tagline", ""):
            w, h = s.get_size()
            theme.text(
                s,
                self.app.fonts.font_s,
                self.tagline,
                (w // 2, int(h * 0.235)),
                theme.TEXT_MUTED,
                center=True,
            )
