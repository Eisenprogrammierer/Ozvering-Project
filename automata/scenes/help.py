"""Краткая справка редактора: управление и формат файла."""

from __future__ import annotations

import pygame

from ui import theme, widgets
from ui.scene import Scene

CONTROLS = [
    ("ЛКМ", "выбрать состояние или переход; перетащить состояние"),
    ("ПКМ / средняя кнопка", "панорамировать холст"),
    ("Колесо мыши", "масштаб вокруг курсора"),
    ("Двойной клик по пустому месту", "добавить состояние"),
    ("«Связь»", "кликнуть исходное, затем целевое состояние"),
    ("Delete / Backspace", "удалить выбранный элемент"),
    ("Стрелки", "сдвинуть состояние (Shift — крупный шаг)"),
    ("F / G / + / -", "вписать, сетка, масштаб"),
    ("Ctrl+Z / Ctrl+Y", "отменить / повторить"),
    ("Ctrl+S", "сохранить JSON-файл"),
    ("Esc", "снять выбор, выключить режим связи или выйти"),
]

FORMAT = (
    '{\n'
    '  "version": 1,\n'
    '  "name": "Пример",\n'
    '  "description": "",\n'
    '  "states": [\n'
    '    {"id": "s1", "name": "Ожидание", "x": 120, "y": 140,\n'
    '     "initial": true, "final": false}\n'
    '  ],\n'
    '  "transitions": [\n'
    '    {"id": "t1", "source": "s1", "target": "s2",\n'
    '     "event": "старт", "guard": ""}\n'
    '  ]\n'
    '}'
)


class HelpScene(Scene):
    name = "help"

    def layout(self, w, h):
        self.widgets = []
        width = min(760, w - 80)
        self.widgets.append(widgets.Button(
            "Назад", self.app.pop,
            ((w - 180) // 2, h - 58, 180, 36)))

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.pop()
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
            self.app.pop()
            return True
        return super().handle_event(event)

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        theme.text(s, self.app.fonts.font_b, "СПРАВКА",
                   (theme.EDGE, 18), theme.ACCENT)
        theme.text(s, self.app.fonts.font_s,
                   "Редактор не задаёт предметную спецификацию: "
                   "только состояния и переходы.",
                   (theme.EDGE, 50), theme.TEXT_MUTED)

        left_w = min(520, w // 2 - 30)
        key_w = 226
        x = theme.EDGE
        y = 92
        theme.text(s, self.app.fonts.font, "УПРАВЛЕНИЕ",
                   (x, y), theme.TEXT)
        y += 28
        for key, value in CONTROLS:
            theme.text(s, self.app.fonts.font_s, key, (x, y),
                       theme.ACCENT2)
            for line in theme.wrap(self.app.fonts.font_s, value,
                                   left_w - key_w - 4):
                theme.text(s, self.app.fonts.font_s, line,
                           (x + key_w, y), theme.TEXT_DIM)
                y += 16
            y += 8

        x2 = w // 2 + 10
        y2 = 92
        theme.text(s, self.app.fonts.font, "ФОРМАТ ФАЙЛА",
                   (x2, y2), theme.TEXT)
        y2 += 28
        for line in FORMAT.split("\n"):
            theme.text(s, self.app.fonts.font_s, line, (x2, y2),
                       theme.TEXT_MUTED)
            y2 += 15
        y2 += 8
        note = ("Файлы лежат в configs/automata/. Один файл — один автомат. "
                "Координаты — верхний левый угол узла в мировых пикселях.")
        for line in theme.wrap(self.app.fonts.font_s, note,
                               min(420, w - x2 - theme.EDGE)):
            theme.text(s, self.app.fonts.font_s, line, (x2, y2),
                       theme.TEXT_DIM)
            y2 += 16

        theme.text(s, self.app.fonts.font_s, "F1 / Esc — закрыть",
                   (w // 2, h - 80), theme.TEXT_MUTED, center=True)
        for widget in self.widgets:
            widget.draw(s, self.app.fonts)
