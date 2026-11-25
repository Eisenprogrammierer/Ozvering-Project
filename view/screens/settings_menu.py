from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger
from view.support.settings_store import (
    apply_music,
    save_settings,
)

logger = get_logger("view.settings_menu")


class SettingsMenuScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((340, 90, 600, 540))
        self.settings = dict(getattr(app, "settings", {}) or {})
        self._rebuild()
        logger.info("Экран настроек инициализирован")

    def _label(self, key, text):
        value = self.settings.get(key)
        if isinstance(value, bool):
            return "%s: %s" % (text, "вкл" if value else "выкл")
        if key == "music_volume":
            return "%s: %d%%" % (text, round(float(value or 0.0) * 100))
        if key == "text_speed":
            return "%s: %.2fx" % (text, float(value or 1.0))
        return text

    def _rebuild(self):
        self.buttons = []
        rows = (
            ("sound", "Звук и музыка", self.toggle),
            ("music_volume", "Громкость музыки", self.cycle_volume),
            ("fullscreen", "Полный экран", self.toggle),
            ("animations", "Анимации боя", self.toggle),
            ("text_speed", "Скорость текста", self.cycle_text_speed),
        )
        y = 175
        for key, label, handler in rows:
            self.buttons.append(
                Button(
                    (400, y, 480, 45),
                    self._label(key, label),
                    self.app.font_body,
                    lambda k=key, h=handler: h(k),
                )
            )
            y += 58
        self.buttons.append(
            Button(
                (540, 560, 200, 40),
                "Назад",
                self.app.font_body,
                self.app.manager.pop,
            )
        )

    def _persist(self):
        self.app.settings = save_settings(self.settings)
        self.settings = dict(self.app.settings)
        apply_music(self.settings, getattr(self.app, "music", None))

    def toggle(self, key):
        self.settings[key] = not bool(self.settings.get(key))
        if key == "fullscreen":
            self.app.toggle_fullscreen()
        logger.info(
            "Настройка переключена: %s -> %s",
            key,
            "вкл" if self.settings[key] else "выкл",
        )
        self._persist()
        self._rebuild()

    def cycle_volume(self, key):
        value = float(self.settings.get(key, 0.6) or 0.0)
        value = round(value + 0.2, 2)
        if value > 1.0:
            value = 0.0
        self.settings[key] = value
        logger.info("Громкость музыки: %d%%", round(value * 100))
        self._persist()
        self._rebuild()

    def cycle_text_speed(self, key):
        speeds = (0.5, 0.75, 1.0, 1.5, 2.0)
        value = float(self.settings.get(key, 1.0) or 1.0)
        index = min(
            range(len(speeds)),
            key=lambda i: abs(speeds[i] - value),
        )
        self.settings[key] = speeds[(index + 1) % len(speeds)]
        logger.info("Скорость текста: %.2fx", self.settings[key])
        self._persist()
        self._rebuild()

    def handle_event(self, event):
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_body.render("Настройки", True, (220, 220, 230))
        screen.blit(title, title.get_rect(center=(640, 125)))
        for b in self.buttons:
            b.draw(screen)
