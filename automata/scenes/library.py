from __future__ import annotations

import pygame

from ui import theme, widgets
from ui.scene import Scene

from .. import ui
from ..storage import StoreError
from ..ui import ListRow, ToolButton, draw_empty

ROW_H = 68
ROW_GAP = 8


class LibraryScene(Scene):
    name = "library"

    def on_enter(self, message="", **kwargs):
        self.app.set_title(None)
        self.status = message or "Выберите автомат или создайте новый."
        self.scroll = 0
        self.entries = self.app.store.list_entries()

    def refresh(self, message=None):
        if message is not None:
            self.status = message
        self.entries = self.app.store.list_entries()
        self.scroll = min(self.scroll, self._max_scroll())
        self.layout(*self.app.size)

    def _max_scroll(self):
        if not hasattr(self, "list_rect"):
            return 0
        content = len(self.entries) * (ROW_H + ROW_GAP) - ROW_GAP
        return max(0, content - self.list_rect.height)

    def layout(self, w, h):
        self.widgets = []
        self.list_widgets = []
        col_w = min(1060, w - 2 * theme.EDGE)
        x = (w - col_w) // 2
        self.list_rect = pygame.Rect(x, 104, col_w, max(80, h - 104 - 42))

        button_y = 24
        new_w, help_w, quit_w = 180, 110, 100
        bx = x + col_w - new_w
        self.widgets.append(
            ToolButton(
                "+ Новый автомат",
                self.app.new_automaton,
                (bx, button_y, new_w, 34),
                accent=True,
            )
        )
        bx -= help_w + theme.GAP
        self.widgets.append(
            widgets.Button(
                "Справка", self.app.push_help, (bx, button_y, help_w, 34)
            )
        )
        bx -= quit_w + theme.GAP
        self.widgets.append(
            widgets.Button("Выход", self.app.quit, (bx, button_y, quit_w, 34))
        )

        if not self.entries:
            return

        self.scroll = min(self.scroll, self._max_scroll())
        btn_w = 94
        for index, entry in enumerate(self.entries):
            y = self.list_rect.top + index * (ROW_H + ROW_GAP) - self.scroll
            row = pygame.Rect(x, y, col_w, ROW_H)
            if (
                row.bottom <= self.list_rect.top
                or row.top >= self.list_rect.bottom
            ):
                continue
            self.list_widgets.append(ListRow(entry, row))
            buttons = [
                (
                    "Открыть",
                    lambda slug=entry["slug"]: self._open(slug),
                    not entry.get("error"),
                ),
                (
                    "Копия",
                    lambda slug=entry["slug"]: self._duplicate(slug),
                    not entry.get("error"),
                ),
                (
                    "Удалить",
                    lambda slug=entry["slug"]: self._delete(slug),
                    True,
                ),
            ]
            bx = row.right - 12
            for label, callback, enabled in reversed(buttons):
                bx -= btn_w
                self.list_widgets.append(
                    widgets.Button(
                        label,
                        callback,
                        (bx, row.top + 17, btn_w, 34),
                        enabled=enabled,
                    )
                )
                bx -= theme.GAP
        self.widgets.extend(self.list_widgets)

    def _open(self, slug):
        self.app.open_automaton(slug)

    def _duplicate(self, slug):
        try:
            new_slug = self.app.store.duplicate(slug)
        except (StoreError, OSError) as exc:
            self.status = str(exc)
            return
        self.refresh("Создана копия: %s.json" % new_slug)

    def _delete(self, slug):
        entry = next(
            (item for item in self.entries if item["slug"] == slug), None
        )
        name = (entry or {}).get("name") or slug
        self.app.push(
            "confirm",
            title="Удалить автомат?",
            message="Файл «%s» (%s.json) будет удалён." % (name, slug),
            danger=True,
            actions=[
                ("Удалить", lambda: self._do_delete(slug)),
                ("Отмена", None),
            ],
        )

    def _do_delete(self, slug):
        try:
            self.app.store.delete(slug)
        except StoreError as exc:
            self.status = str(exc)
            return
        self.refresh("Удалён файл %s.json" % slug)

    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            if self.list_rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll = max(
                    0, min(self._max_scroll(), self.scroll - event.y * 48)
                )
                self.layout(*self.app.size)
                return True
        return super().handle_event(event)

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        theme.text(
            s,
            self.app.fonts.font_b,
            "АВТОМАТЫ",
            (theme.EDGE, 18),
            theme.ACCENT,
        )
        theme.text(
            s,
            self.app.fonts.font_s,
            "configs/automata · структурный редактор",
            (theme.EDGE, 50),
            theme.TEXT_MUTED,
        )
        count = len(self.entries)
        theme.text(
            s,
            self.app.fonts.font_s,
            "файлов: %d" % count,
            (theme.EDGE, 70),
            theme.TEXT_MUTED,
        )

        for widget in self.widgets:
            if widget in self.list_widgets:
                continue
            widget.draw(s, self.app.fonts)

        if not self.entries:
            empty = self.list_rect.inflate(-40, -40)
            draw_empty(
                s,
                self.app.fonts,
                empty,
                "Пока нет автоматов",
                "Нажмите «+ Новый автомат» — файл появится в configs/automata",
            )
        else:
            old_clip = s.get_clip()
            s.set_clip(self.list_rect)
            for widget in self.list_widgets:
                widget.draw(s, self.app.fonts)
            s.set_clip(old_clip)

            if self._max_scroll() > 0:
                track = pygame.Rect(
                    self.list_rect.right - 8,
                    self.list_rect.top,
                    4,
                    self.list_rect.height,
                )
                pygame.draw.rect(s, theme.BG_ALT, track, border_radius=2)
                content = len(self.entries) * (ROW_H + ROW_GAP) - ROW_GAP
                ratio = self.list_rect.height / float(content)
                knob_h = max(24, int(track.height * ratio))
                max_scroll = self._max_scroll()
                progress = self.scroll / float(max_scroll) if max_scroll else 0
                knob = pygame.Rect(
                    track.left,
                    track.top + int((track.height - knob_h) * progress),
                    track.width,
                    knob_h,
                )
                pygame.draw.rect(s, theme.BORDER, knob, border_radius=2)

        pygame.draw.line(
            s, theme.BORDER, (theme.EDGE, h - 32), (w - theme.EDGE, h - 32), 1
        )
        status = ui.ellipsis(
            self.app.fonts.font_s,
            self.status,
            max(160, w // 2 - 2 * theme.EDGE),
        )
        theme.text(
            s,
            self.app.fonts.font_s,
            status,
            (theme.EDGE, h - 24),
            theme.TEXT_DIM,
        )
        theme.text(
            s,
            self.app.fonts.font_s,
            "JSON · UTF-8 · сохраняется на диск",
            (w - theme.EDGE, h - 24),
            theme.TEXT_MUTED,
            right=True,
        )
