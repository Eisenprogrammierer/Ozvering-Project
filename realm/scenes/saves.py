"""Сохранения «Престола» (saves/realm/)."""

from __future__ import annotations

import pygame

from ui import theme
from ui.scene import Scene
from ui.widgets import Button, Widget

from .. import ui

ROW_H = 64


class _RowLabel(Widget):
    def __init__(self, title, meta, rect, empty):
        super().__init__(rect)
        self.title = title
        self.meta = meta
        self.empty = empty

    def draw(self, s, fonts):
        fill = theme.BG_ALT if self.empty else theme.mix(
            theme.PANEL, theme.PANEL_HI, 0.4
        )
        theme.panel(s, self.rect, fill=fill, border=theme.BORDER, radius=5)
        color = theme.TEXT_MUTED if self.empty else theme.TEXT
        theme.text(s, fonts.font, self.title,
                   (self.rect.left + 14, self.rect.top + 9), color)
        theme.text(s, fonts.font_s, self.meta,
                   (self.rect.left + 14, self.rect.top + 34), theme.TEXT_DIM)


class SavesScene(Scene):
    name = "saves"

    def on_enter(self, mode="load", **kwargs):
        self.mode = mode if mode in ("load", "save") else "load"
        self.slots = self.app.save.list_slots()

    def _slot_label(self, slot):
        if slot == "autosave":
            return "Автосохранение"
        return "Слот %s" % slot.split("_")[-1]

    def _slot_meta(self, data):
        if not data:
            return "пусто"
        meta = data.get("meta") or {}
        status = {"won": "финал", "lost": "поражение"}.get(
            meta.get("status"), "неделя %s" % meta.get("week", "?"))
        ending = meta.get("ending") or ""
        parts = ["%s · %s" % (status, meta.get("mandate", "—"))]
        if ending:
            parts.append(ending)
        parts.append("seed %s" % meta.get("seed", "?"))
        return " · ".join(parts)

    def layout(self, w, h):
        self.widgets = []
        col_w = min(760, w - 2 * theme.EDGE)
        x = (w - col_w) // 2
        y = int(h * 0.18)
        btn_w = 145
        for entry in self.slots:
            slot, empty, data = entry["slot"], entry["empty"], entry["data"]
            row = pygame.Rect(x, y, col_w, ROW_H)
            self.widgets.append(_RowLabel(
                self._slot_label(slot), self._slot_meta(data), row, empty))
            bx = row.right - btn_w - theme.GAP
            if self.mode == "save":
                self.widgets.append(Button(
                    "Сохранить", (lambda s=slot: self._save(s)),
                    (bx, y + 10, btn_w, ROW_H - 20),
                    enabled=self.app.game is not None))
                bx -= btn_w + theme.GAP
            self.widgets.append(Button(
                "Загрузить", (lambda s=slot: self._load(s)),
                (bx, y + 10, btn_w, ROW_H - 20), enabled=not empty))
            bx -= btn_w + theme.GAP
            self.widgets.append(Button(
                "Удалить", (lambda s=slot: self._delete(s)),
                (bx, y + 10, btn_w, ROW_H - 20), enabled=not empty))
            y += ROW_H + theme.GAP
        bw = 200
        self.widgets.append(Button("Назад", self.app.pop,
                                   ((w - bw) // 2, y + theme.GAP, bw, 42)))

    def _load(self, slot):
        self.app.load_game(slot)

    def _save(self, slot):
        self.app.save_game(slot)
        self.refresh()

    def _delete(self, slot):
        self.app.save.delete(slot)
        self.refresh()

    def refresh(self):
        self.slots = self.app.save.list_slots()
        self.layout(*self.app.size)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.pop()
            return True
        return super().handle_event(event)

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        title = "СОХРАНИТЬ ПАРТИЮ" if self.mode == "save" else "ЗАГРУЗИТЬ ПАРТИЮ"
        theme.text(s, self.app.fonts.font_b, title, (w // 2, int(h * 0.07)),
                   ui.PARCHMENT, center=True)
        theme.text(s, self.app.fonts.font_s, "saves/realm/ · JSON-слоты",
                   (w // 2, int(h * 0.125)), theme.TEXT_MUTED, center=True)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
