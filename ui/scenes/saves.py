import pygame

from .. import save, theme, widgets
from ..scene import Scene

ROW_H = 66


class SavesScene(Scene):
    name = "saves"

    def on_enter(self, mode="load", **kwargs):
        self.mode = mode if mode in ("load", "save") else "load"
        self.slots = self.app.save.list_slots()

    def _slot_label(self, slot):
        if slot == save.AUTOSAVE_SLOT:
            return self.app.t("Автосохранение", "Autosave")
        num = slot.split("_")[-1]
        return self.app.t("Слот %s" % num, "Slot %s" % num)

    def _slot_meta(self, data):
        if not data:
            return self.app.t("пусто", "empty")
        winner = data.get("winner")
        if data.get("finished"):
            wname = {
                "RL": "RL",
                "AI": "BDI",
                "UtilityAI": "UtilityAI",
            }.get(winner, "-")
            result = self.app.t("победа: %s" % wname, "winner: %s" % wname)
        else:
            result = self.app.t(
                "такт %s" % data.get("tick", 0),
                "tick %s" % data.get("tick", 0),
            )
        return "%s  |  seed %s" % (result, data.get("seed", 0))

    def layout(self, w, h):
        self.widgets = []
        col_w = min(720, w - 2 * theme.EDGE)
        x = (w - col_w) // 2
        y = int(h * 0.20)
        btn_w = 168
        for entry in self.slots:
            slot, empty, data = entry["slot"], entry["empty"], entry["data"]
            row = pygame.Rect(x, y, col_w, ROW_H)
            self.widgets.append(
                _RowLabel(
                    self._slot_label(slot), self._slot_meta(data), row, empty
                )
            )
            bx = row.right - btn_w - theme.GAP
            if self.mode == "save":
                game = self.app.manager.find("game")
                self.widgets.append(
                    widgets.Button(
                        self.app.t("Сохранить", "Save here"),
                        (lambda s=slot: self._save(s)),
                        (bx, y + 10, btn_w, ROW_H - 20),
                        enabled=game is not None,
                    )
                )
                bx -= btn_w + theme.GAP
            self.widgets.append(
                widgets.Button(
                    self.app.t("Загрузить", "Load"),
                    (lambda s=slot: self._load(s)),
                    (bx, y + 10, btn_w, ROW_H - 20),
                    enabled=not empty,
                )
            )
            bx -= btn_w + theme.GAP
            self.widgets.append(
                widgets.Button(
                    self.app.t("Удалить", "Delete"),
                    (lambda s=slot: self._delete(s)),
                    (bx, y + 10, btn_w, ROW_H - 20),
                    enabled=not empty,
                )
            )
            y += ROW_H + theme.GAP

        bw = min(220, col_w)
        self.widgets.append(
            widgets.Button(
                self.app.t("Назад", "Back"),
                self.app.back,
                ((w - bw) // 2, y + theme.GAP, bw, theme.BTN_H),
            )
        )

    def _load(self, slot):
        data = self.app.save.read(slot)
        if data:
            self.app.go("game", save_data=data)

    def _save(self, slot):
        game = self.app.manager.find("game")
        if game is not None:
            self.app.save.write(slot, game.save_data())
            self.refresh()

    def _delete(self, slot):
        self.app.save.delete(slot)
        self.refresh()

    def refresh(self):
        self.slots = self.app.save.list_slots()
        self.layout(*self.app.size)

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        title = (
            self.app.t("Сохранить партию", "Save a match")
            if self.mode == "save"
            else self.app.t("Загрузить партию", "Load a match")
        )
        theme.draw_title(s, self.app.fonts, title, w // 2, int(h * 0.07))
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)


class _RowLabel(widgets.Widget):

    def __init__(self, title, meta, rect, empty):
        super().__init__(rect)
        self.title = title
        self.meta = meta
        self.empty = empty

    def draw(self, s, fonts):
        fill = (
            theme.BG_ALT
            if self.empty
            else theme.mix(theme.PANEL, theme.PANEL_HI, 0.4)
        )
        theme.panel(s, self.rect, fill=fill, border=theme.BORDER)
        color = theme.TEXT_MUTED if self.empty else theme.TEXT
        theme.text(
            s,
            fonts.font,
            self.title,
            (self.rect.left + 14, self.rect.top + 10),
            color,
        )
        theme.text(
            s,
            fonts.font_s,
            self.meta,
            (self.rect.left + 14, self.rect.top + 36),
            theme.TEXT_DIM,
        )
