import pygame

from .. import content, theme, widgets
from ..scene import Scene


class NarrativeScene(Scene):
    name = "narrative"

    def on_enter(
        self,
        pages=None,
        next_scene="menu",
        next_kwargs=None,
        index=0,
        **kwargs
    ):
        self.pages = list(pages) if pages else list(content.INTRO_PAGES)
        self.next_scene = next_scene
        self.next_kwargs = dict(next_kwargs or {})
        self.index = max(0, min(int(index), len(self.pages) - 1))

    def layout(self, w, h):
        self.widgets = []
        pad = theme.EDGE
        top = int(h * 0.18)
        img_w = int(w * 0.30)
        img_h = int(h * 0.44)
        self.img_rect = pygame.Rect(pad, top, img_w, img_h)
        self.text_x = self.img_rect.right + pad * 2
        self.text_w = w - self.text_x - pad
        self.body_top = top + 60

        bw, bh = 172, theme.BTN_H
        total = bw * 3 + theme.GAP * 2
        x = (w - total) // 2
        y = int(h * 0.74)
        last = self.index >= len(self.pages) - 1
        self.widgets.append(
            widgets.Button(
                self.app.t("Назад", "Back"),
                self._prev,
                (x, y, bw, bh),
                enabled=self.index > 0,
            )
        )
        self.widgets.append(
            widgets.Button(
                (
                    self.app.t("Начать", "Begin")
                    if last
                    else self.app.t("Далее", "Next")
                ),
                self._next,
                (x + bw + theme.GAP, y, bw, bh),
            )
        )
        self.widgets.append(
            widgets.Button(
                self.app.t("Пропустить", "Skip"),
                self._skip,
                (x + 2 * (bw + theme.GAP), y, bw, bh),
            )
        )

    def _prev(self):
        if self.index > 0:
            self.index -= 1
            self.layout(*self.app.size)

    def _next(self):
        if self.index < len(self.pages) - 1:
            self.index += 1
            self.layout(*self.app.size)
        else:
            self._finish()

    def _skip(self):
        self._finish()

    def _finish(self):
        self.app.go(self.next_scene, **self.next_kwargs)

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        page = self.pages[self.index]
        theme.draw_placeholder(
            s,
            self.img_rect,
            page["image"],
            self.app.fonts,
            caption=self.app.t("КАДР", "ART"),
        )
        theme.text(
            s,
            self.app.fonts.font_b,
            self.app.t(*page["title"]),
            (self.text_x, int(h * 0.19)),
            theme.ACCENT,
        )
        max_w = self.text_w
        y = self.body_top
        for line in theme.wrap(
            self.app.fonts.font, self.app.t(*page["body"]), max_w
        ):
            theme.text(
                s, self.app.fonts.font, line, (self.text_x, y), theme.TEXT
            )
            y += self.app.fonts.font.size("Ag")[1] + 4
        indicator = "%d / %d" % (self.index + 1, len(self.pages))
        theme.text(
            s,
            self.app.fonts.font_s,
            indicator,
            (w // 2, int(h * 0.70)),
            theme.TEXT_DIM,
            center=True,
        )
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
