"""Экран настроек: полный экран, автосохранение, язык, громкости, скорость текста."""

import pygame

from .. import theme, widgets
from ..scene import Scene

ROW_H = 46
COL_W_MAX = 620


class SettingsScene(Scene):
    name = "settings"

    def on_enter(self, **kwargs):
        self.s = self.app.save.settings

    def _toggle_lang(self, _value):
        lang = "en" if self.s.get("language") == "ru" else "ru"
        self.app.save.set_setting("language", lang)
        self.app.refresh()          # перерисовать подписи на новом языке

    def layout(self, w, h):
        self.widgets = []
        col_w = min(COL_W_MAX, w - 2 * theme.EDGE)
        x = (w - col_w) // 2
        y = int(h * 0.20)
        s = self.app.save.settings
        rows = 7                       # 3 тоггла + 4 слайдера
        # Вписываем список строк и кнопку «Назад» в доступную высоту.
        row_h, gap = ROW_H, theme.GAP
        avail = (h - theme.EDGE) - y - (theme.GAP * 2 + theme.BTN_H)
        need = rows * row_h + (rows - 1) * gap
        if need > avail:
            gap = 6
            row_h = max(30, (avail - (rows - 1) * gap) // rows)

        def add(wdg):
            nonlocal y
            wdg.set_rect((x, y, col_w, row_h))
            self.widgets.append(wdg)
            y += row_h + gap

        add(widgets.Toggle(
            self.app.t("Полный экран", "Fullscreen"), s.get("fullscreen", False),
            lambda v: self.app.set_fullscreen(v)))
        add(widgets.Toggle(
            self.app.t("Автосохранение", "Autosave"), s.get("autosave", True),
            lambda v: self.app.save.set_setting("autosave", v)))
        add(widgets.Toggle(
            self.app.t("Язык: русский", "Language: English"),
            s.get("language") == "ru", self._toggle_lang))
        add(widgets.Slider(
            self.app.t("Общая громкость", "Master volume"),
            s.get("volume_master", 0.8),
            lambda v: self.app.save.set_setting("volume_master", round(v, 3))))
        add(widgets.Slider(
            self.app.t("Музыка", "Music"), s.get("volume_music", 0.6),
            lambda v: self.app.save.set_setting("volume_music", round(v, 3))))
        add(widgets.Slider(
            self.app.t("Эффекты", "SFX"), s.get("volume_sfx", 0.8),
            lambda v: self.app.save.set_setting("volume_sfx", round(v, 3))))
        add(widgets.Slider(
            self.app.t("Скорость текста", "Text speed"),
            (s.get("text_speed", 1.0) - 0.5) / 2.5,
            lambda v: self.app.save.set_setting("text_speed", round(0.5 + v * 2.5, 2)),
            fmt=lambda v: "x%.1f" % (0.5 + v * 2.5)))

        y += theme.GAP
        bw = min(240, col_w)
        self.widgets.append(widgets.Button(
            self.app.t("Назад", "Back"), self._back,
            ((w - bw) // 2, y, bw, theme.BTN_H)))

    def _back(self):
        self.app.back()

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        theme.draw_title(s, self.app.fonts, self.app.t("Настройки", "Settings"),
                         w // 2, int(h * 0.07))
        theme.text(s, self.app.fonts.font, self.app.t(
            "Значения сохраняются сразу (saves/settings.json).",
            "Values are saved immediately (saves/settings.json)."),
            (w // 2, int(h * 0.15)), theme.TEXT_MUTED, center=True)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
