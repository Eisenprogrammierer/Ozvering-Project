from __future__ import annotations

import pygame

from ui import theme
from ui.widgets import Button, Widget

CANVAS_BG = (15, 17, 23)
GRID = (25, 28, 36)
GRID_MAJOR = (34, 38, 49)
NODE = (32, 36, 47)
NODE_HI = (42, 48, 63)
NODE_BORDER = (72, 80, 98)
NODE_TEXT = (228, 228, 232)
NODE_DIM = (145, 151, 165)
EDGE = (112, 124, 148)
EDGE_HI = theme.ACCENT2
EDGE_DIM = (78, 87, 105)
INITIAL = (120, 200, 130)
FINAL = (255, 210, 90)
SELECT = theme.ACCENT2
ERROR = theme.DANGER
WARN = theme.WARN


def draw_label(s, fonts, value, pos, color=theme.TEXT_DIM):
    theme.text(s, fonts.font_s, value, pos, color)


def ellipsis(font, value, width):
    value = str(value)
    if width <= 0:
        return ""
    if font.size(value)[0] <= width:
        return value
    cut = value
    while cut and font.size(cut + "…")[0] > width:
        cut = cut[:-1]
    return (cut + "…") if cut else "…"


def draw_section(s, fonts, title, rect):
    theme.text(
        s, fonts.font_s, title.upper(), (rect.left, rect.top), theme.TEXT_MUTED
    )
    y = rect.top + 18
    pygame.draw.line(s, theme.BORDER, (rect.left, y), (rect.right, y), 1)
    return y + 8


class TextInput(Widget):

    def __init__(
        self,
        label,
        value="",
        on_commit=None,
        rect=None,
        placeholder="",
        max_len=96,
    ):
        super().__init__(rect)
        self.label = label
        self.value = str(value)
        self.original = str(value)
        self.on_commit = on_commit
        self.placeholder = placeholder
        self.max_len = max(1, int(max_len))
        self.editing = False
        self.caret = len(self.value)
        self._scroll = 0
        self._font = None

    def set_value(self, value):
        if not self.editing:
            self.value = str(value)
            self.original = self.value
            self.caret = len(self.value)
            self._scroll = 0

    def start(self):
        self.editing = True
        self.original = self.value
        self.caret = len(self.value)
        self._scroll = 0

    def cancel(self):
        self.value = self.original
        self.caret = len(self.value)
        self._scroll = 0
        self.editing = False

    def commit(self):
        if not self.editing:
            return True
        candidate = self.value.strip()
        if self.on_commit is not None:
            try:
                accepted = self.on_commit(candidate)
            except Exception:
                accepted = False
            if accepted is False:
                self.caret = min(self.caret, len(self.value))
                return False
        self.value = candidate
        self.original = candidate
        self.caret = len(candidate)
        self._scroll = 0
        self.editing = False
        return True

    def _char_width(self, char="M"):
        if self._font is not None:
            return max(1, self._font.size(char)[0])
        return 8

    def _caret_from_x(self, x):
        if self._font is None:
            index = int(
                (x - self.rect.left - 10 + self._scroll) / self._char_width()
            )
            return max(0, min(len(self.value), index))
        best = 0
        best_dist = None
        for index in range(len(self.value) + 1):
            px = (
                self.rect.left
                + 10
                - self._scroll
                + self._font.size(self.value[:index])[0]
            )
            dist = abs(px - x)
            if best_dist is None or dist < best_dist:
                best, best_dist = index, dist
        return best

    def handle(self, e):
        if not (self.visible and self.enabled):
            return False
        if e.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(e.pos)
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.rect.collidepoint(e.pos):
                if not self.editing:
                    self.start()
                self.caret = self._caret_from_x(e.pos[0])
                return True
            if self.editing:

                self.commit()
            return False
        if e.type == pygame.KEYDOWN and self.editing:
            key = e.key
            mods = getattr(e, "mod", 0)
            if mods & (pygame.KMOD_CTRL | pygame.KMOD_META | pygame.KMOD_ALT):
                return False
            if key == pygame.K_ESCAPE:
                self.cancel()
                return True
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB):
                self.commit()
                return True
            if key == pygame.K_BACKSPACE:
                if self.caret > 0:
                    self.value = (
                        self.value[: self.caret - 1] + self.value[self.caret :]
                    )
                    self.caret -= 1
                return True
            if key == pygame.K_DELETE:
                if self.caret < len(self.value):
                    self.value = (
                        self.value[: self.caret] + self.value[self.caret + 1 :]
                    )
                return True
            if key == pygame.K_LEFT:
                self.caret = max(0, self.caret - 1)
                return True
            if key == pygame.K_RIGHT:
                self.caret = min(len(self.value), self.caret + 1)
                return True
            if key == pygame.K_HOME:
                self.caret = 0
                return True
            if key == pygame.K_END:
                self.caret = len(self.value)
                return True
            text = getattr(e, "unicode", "")
            if text and text.isprintable() and len(self.value) < self.max_len:
                self.value = (
                    self.value[: self.caret] + text + self.value[self.caret :]
                )
                self.caret += len(text)
                return True
            return True
        return False

    def draw(self, s, fonts):
        if not self.visible:
            return
        self._font = fonts.font
        if self.label:
            theme.text(
                s,
                fonts.font_s,
                self.label,
                (self.rect.left, self.rect.top - 16),
                theme.TEXT_DIM,
            )
        fill = theme.BG_ALT
        border = theme.BORDER
        if self.editing:
            fill = theme.mix(fill, theme.BG, 0.35)
            border = theme.ACCENT2
        elif self.hover:
            border = theme.mix(border, theme.ACCENT2, 0.55)
        theme.panel(s, self.rect, fill=fill, border=border, radius=5)

        inner = self.rect.inflate(-20, -2)
        raw = self.value if self.value else self.placeholder
        text = raw if self.editing else ellipsis(self._font, raw, inner.width)
        color = theme.TEXT if self.value else theme.TEXT_MUTED

        if self.editing:
            caret_px = self._font.size(self.value[: self.caret])[0]
            room = max(1, inner.width)
            if caret_px - self._scroll > room:
                self._scroll = caret_px - room
            if caret_px - self._scroll < 0:
                self._scroll = max(0, caret_px)
            total = self._font.size(self.value)[0]
            self._scroll = max(0, min(self._scroll, max(0, total - room)))
        else:
            self._scroll = 0

        old_clip = s.get_clip()
        s.set_clip(inner)
        image = self._font.render(text, True, color)
        s.blit(
            image,
            (
                inner.left - self._scroll,
                self.rect.centery - image.get_height() // 2,
            ),
        )
        if self.editing and (pygame.time.get_ticks() // 500) % 2 == 0:
            caret_px = self._font.size(self.value[: self.caret])[0]
            x = inner.left - self._scroll + caret_px
            pygame.draw.line(
                s,
                theme.ACCENT2,
                (x, self.rect.top + 9),
                (x, self.rect.bottom - 9),
                1,
            )
        s.set_clip(old_clip)


class ToolButton(Button):

    def __init__(
        self,
        label,
        callback=None,
        rect=None,
        enabled=True,
        key=None,
        active=False,
        accent=False,
        danger=False,
    ):
        super().__init__(label, callback, rect, enabled, key)
        self.active = bool(active)
        self.accent = bool(accent)
        self.danger = bool(danger)

    def draw(self, s, fonts):
        if not self.visible:
            return
        fill = theme.PANEL_HI if self.enabled else theme.PANEL
        border = theme.BORDER
        color = theme.TEXT if self.enabled else theme.TEXT_MUTED
        if self.active:
            fill = theme.mix(theme.PANEL_HI, theme.ACCENT2, 0.28)
            border = theme.ACCENT2
        if self.accent:
            fill = theme.mix(theme.PANEL_HI, theme.ACCENT, 0.24)
            border = theme.ACCENT
        if self.danger:
            border = theme.DANGER
        if self.enabled and self.hover:
            fill = theme.mix(fill, theme.ACCENT, 0.14)
            if not self.active and not self.accent:
                border = theme.mix(border, theme.ACCENT, 0.55)
        if self.enabled and self._pressed:
            fill = theme.mix(fill, (0, 0, 0), 0.22)
        theme.panel(s, self.rect, fill=fill, border=border, radius=5)
        theme.text(
            s, fonts.font, self.label, self.rect.center, color, center=True
        )


class ListRow(Widget):

    def __init__(self, entry, rect=None):
        super().__init__(rect)
        self.entry = entry

    def draw(self, s, fonts):
        entry = self.entry
        error = entry.get("error")
        fill = (
            theme.BG_ALT
            if not error
            else theme.mix(theme.BG_ALT, theme.DANGER, 0.10)
        )
        border = (
            theme.BORDER
            if not error
            else theme.mix(theme.BORDER, theme.DANGER, 0.55)
        )
        theme.panel(s, self.rect, fill=fill, border=border, radius=5)
        title = entry.get("name") or entry.get("slug")
        title = ellipsis(fonts.font, title, max(80, self.rect.width - 360))
        theme.text(
            s,
            fonts.font,
            title,
            (self.rect.left + 14, self.rect.top + 9),
            theme.TEXT if not error else theme.DANGER,
        )
        if error:
            meta = "ошибка: %s" % error
        else:
            meta = "%d сост. · %d перех. · %s · %s.json" % (
                entry.get("states", 0),
                entry.get("transitions", 0),
                entry.get("updated", ""),
                entry.get("slug", ""),
            )
        meta = ellipsis(fonts.font_s, meta, max(80, self.rect.width - 360))
        theme.text(
            s,
            fonts.font_s,
            meta,
            (self.rect.left + 14, self.rect.top + 36),
            theme.TEXT_MUTED if not error else theme.WARN,
        )


def draw_empty(s, fonts, rect, title, hint=""):
    theme.panel(s, rect, fill=theme.BG_ALT, border=theme.BORDER, radius=8)
    theme.text(
        s, fonts.font, title, rect.center, theme.TEXT_MUTED, center=True
    )
    if hint:
        theme.text(
            s,
            fonts.font_s,
            hint,
            (rect.centerx, rect.centery + 24),
            theme.TEXT_MUTED,
            center=True,
        )
