import pygame

from .. import theme, widgets
from ..scene import Scene


class MenuScene(Scene):

    title = ""
    subtitle = ""
    hero_key = None
    hero_top_frac = 0.27
    hero_h_frac = 0.17
    btn_top_frac = 0.44
    footer = ""

    def __init__(self, app):
        super().__init__(app)
        self.placeholders = []

    def build_buttons(self):
        return []

    def layout(self, w, h):
        self.widgets = []
        self.placeholders = []
        items = self.build_buttons()
        n = len(items)
        footer_h = 26 if self.footer else 0
        bottom = h - theme.EDGE - footer_h
        if self.hero_key is not None:
            hw = min(int(w * 0.56), 640)
            hh = int(h * self.hero_h_frac)
            rect = pygame.Rect(
                (w - hw) // 2, int(h * self.hero_top_frac), hw, hh
            )
            top = rect.bottom + theme.GAP * 2

            if n:
                min_btn = 24
                min_gap = 4
                needed = n * min_btn + (n - 1) * min_gap
                avail = max(1, bottom - top)
                if avail < needed:
                    rect.height = max(24, rect.height - (needed - avail))
                    top = rect.bottom + theme.GAP * 2
            self.placeholders.append(widgets.Placeholder(self.hero_key, rect))
        else:
            top = int(h * self.btn_top_frac)

        gap = theme.GAP
        btn_h = theme.BTN_H
        if n:
            need = n * btn_h + (n - 1) * gap
            avail = max(1, bottom - top)
            if need > avail:
                gap = 6
                btn_h = max(20, (avail - (n - 1) * gap) // n)
        btn_w = min(440, w - 2 * theme.EDGE)
        x = (w - btn_w) // 2
        y = top
        for label, callback, enabled in items:
            self.widgets.append(
                widgets.Button(
                    label, callback, (x, y, btn_w, btn_h), enabled=enabled
                )
            )
            y += btn_h + gap

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        theme.draw_title(s, self.app.fonts, self.title, w // 2, int(h * 0.075))
        if self.subtitle:
            theme.text(
                s,
                self.app.fonts.font,
                self.subtitle,
                (w // 2, int(h * 0.195)),
                theme.TEXT_DIM,
                center=True,
            )
        for ph in self.placeholders:
            ph.draw(s, self.app.fonts)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
        if self.footer:
            theme.draw_footer_hint(s, self.app.fonts, self.footer, w, h)
