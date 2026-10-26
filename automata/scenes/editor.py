"""Главный экран редактора: холст, панель инструментов и инспектор."""

from __future__ import annotations

import pygame

from ui import theme, widgets
from ui.scene import Scene

from .. import ui
from ..canvas import AutomatonCanvas
from ..model import Automaton, AutomatonError, History
from ..storage import StoreError
from ..ui import TextInput, ToolButton

PANEL_W = 322
TOOL_H = 48
STATUS_H = 28


def _plural(number, one, few, many):
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


class EditorScene(Scene):
    name = "editor"

    # --- жизненный цикл -------------------------------------------------
    def on_enter(self, automaton=None, slug=None, saved_data=None, **kwargs):
        if automaton is not None:
            self._load_doc(automaton, slug, saved_data)
        elif not hasattr(self, "automaton"):
            self._load_doc(Automaton(), None, None)
        else:
            self.layout(*self.app.size)

    def _load_doc(self, automaton, slug, saved_data=None):
        self.automaton = automaton
        self.slug = slug
        if saved_data is None:
            # Новый документ ещё не сохранён и должен считаться изменённым.
            self.saved_data = automaton.to_dict() if slug else None
        else:
            self.saved_data = saved_data
        self.history = History(self.automaton.to_dict())
        self.status = ("Открыт %s.json" % slug if slug
                       else "Новый автомат — сохраните файл")
        self.canvas = AutomatonCanvas(
            self.automaton,
            on_select=self._on_select,
            on_change=self._on_change,
            on_status=self._set_status,
        )
        self._canvas_ready = False
        self.app.set_title(self.automaton.name)

    def layout(self, w, h):
        top = pygame.Rect(theme.EDGE, theme.EDGE,
                          w - 2 * theme.EDGE, TOOL_H)
        content_top = top.bottom + theme.GAP
        content_bottom = h - STATUS_H - theme.EDGE
        panel = pygame.Rect(w - theme.EDGE - PANEL_W, content_top,
                            PANEL_W, max(120, content_bottom - content_top))
        canvas_rect = pygame.Rect(theme.EDGE, content_top,
                                  max(120, panel.left - theme.GAP
                                      - theme.EDGE),
                                  max(120, content_bottom - content_top))
        self.top_rect = top
        self.panel_rect = panel
        self.canvas_rect = canvas_rect
        self.canvas.set_rect(canvas_rect, fit=not self._canvas_ready)
        self._canvas_ready = True

        self.widgets = []
        self.toolbar_widgets = []
        self.inspector_widgets = []
        self._build_toolbar(top)
        self._build_inspector(panel)
        self.widgets = self.toolbar_widgets + self.inspector_widgets

    # --- панель инструментов -------------------------------------------
    def _build_toolbar(self, top):
        y = top.top + 7
        h = 34
        x = top.left + 8
        specs = [
            ("Библиотека", self.request_leave, 108, False),
            ("+ Состояние", self._add_state, 128, False),
            ("Связь", self._toggle_connect, 84, self.canvas.connect_mode),
            ("Удалить", self.canvas.delete_selected, 92,
             self.canvas.selected_kind is not None),
            ("Отмена", self.undo, 86, self.history.can_undo),
            ("Повтор", self.redo, 84, self.history.can_redo),
            ("Вписать", self._fit, 84, False),
        ]
        for label, callback, width, active_or_enabled in specs:
            active = bool(active_or_enabled) if label == "Связь" else False
            enabled = True
            if label == "Удалить":
                enabled = bool(active_or_enabled)
            elif label in ("Отмена", "Повтор"):
                enabled = bool(active_or_enabled)
            self.toolbar_widgets.append(ToolButton(
                label, callback, (x, y, width, h), enabled=enabled,
                active=active))
            x += width + 8

        save_w, help_w = 124, 34
        hx = top.right - 8 - help_w
        self.toolbar_widgets.append(ToolButton(
            "?", self._open_help, (hx, y, help_w, h)))
        sx = hx - 8 - save_w
        save_label = "Сохранить*" if self.is_dirty() else "Сохранить"
        self.toolbar_widgets.append(ToolButton(
            save_label, self.save, (sx, y, save_w, h), accent=True))

    # --- инспектор ------------------------------------------------------
    def _section(self, title, y):
        self.section_marks.append((title, y))
        return y + 28

    def _add_input(self, label, value, callback, y, max_len=96,
                   placeholder=""):
        rect = pygame.Rect(self._field_x, y + 16, self._field_w, 32)
        widget = TextInput(label, value, callback, rect,
                           placeholder=placeholder, max_len=max_len)
        self.inspector_widgets.append(widget)
        return rect.bottom + 8

    def _build_inspector(self, panel):
        self.section_marks = []
        self.count_y = None
        self.state_meta_y = None
        self.transition_meta_y = None
        self.hint_y = None
        self.validation_y = panel.bottom + 10
        self._field_x = panel.left + 14
        self._field_w = panel.width - 28
        x, w = self._field_x, self._field_w
        y = panel.top + 48

        y = self._section("Автомат", y)
        y = self._add_input("Название", self.automaton.name,
                            self._commit_doc_name, y, max_len=80)
        y = self._add_input("Описание", self.automaton.description,
                            self._commit_description, y, max_len=160)
        self.count_y = y
        y += 26

        state = self.canvas.selected_state()
        transition = self.canvas.selected_transition()
        if state is not None:
            y = self._section("Состояние", y)
            y = self._add_input("ID (латиница)", state.id,
                                lambda value: self._commit_state_id(
                                    state.id, value), y, max_len=40)
            y = self._add_input("Название", state.name,
                                lambda value: self._commit_state_name(
                                    state.id, value), y, max_len=80)
            y = self._add_toggle("Начальное состояние", state.initial,
                                 lambda value: self._toggle_initial(
                                     state.id, value), y)
            y = self._add_toggle("Финальное состояние", state.final,
                                 lambda value: self._toggle_final(
                                     state.id, value), y)
            self.state_meta_y = y
            y += 24
            y = self._add_button(
                "Удалить состояние", self.canvas.delete_selected, y,
                danger=True)
            self.validation_y = y + 8
        elif transition is not None:
            y = self._section("Переход", y)
            source = self.automaton.state(transition.source)
            target = self.automaton.state(transition.target)
            self.transition_source = self._describe_state(source,
                                                          transition.source)
            self.transition_target = self._describe_state(target,
                                                          transition.target)
            self.transition_meta_y = y
            y += 44
            y = self._add_input("Событие / подпись", transition.event,
                                lambda value: self._commit_event(
                                    transition.id, value), y, max_len=80)
            y = self._add_input("Условие (свободный текст)", transition.guard,
                                lambda value: self._commit_guard(
                                    transition.id, value), y, max_len=120)
            y = self._add_button(
                "Удалить переход", self.canvas.delete_selected, y,
                danger=True)
            self.validation_y = y + 8
        else:
            self.hint_y = y
            y += 70
            self.validation_y = y + 8

    def _add_toggle(self, label, value, callback, y):
        rect = pygame.Rect(self._field_x, y, self._field_w, 34)
        self.inspector_widgets.append(widgets.Toggle(
            label, value, callback, rect))
        return rect.bottom + 6

    def _add_button(self, label, callback, y, danger=False):
        rect = pygame.Rect(self._field_x, y, self._field_w, 34)
        self.inspector_widgets.append(ToolButton(
            label, callback, rect, danger=danger))
        return rect.bottom + 8

    def _describe_state(self, state, state_id):
        if state is None:
            return "%s (нет в файле)" % state_id
        if state.name and state.name != state.id:
            return "%s — %s" % (state.id, state.name)
        return state.id

    # --- колбэки холста -------------------------------------------------
    def _on_select(self, kind, item_id):
        self._rebuild()

    def _on_change(self, message, commit=True):
        self.status = message
        if commit:
            self.history.push(self.automaton.to_dict())
            self._rebuild()
        self.app.set_title(self.automaton.name)

    def _set_status(self, message):
        self.status = message

    def _rebuild(self):
        self.layout(*self.app.size)

    # --- операции -------------------------------------------------------
    def _add_state(self):
        self.canvas.add_state_at(self.canvas.rect.center)

    def _toggle_connect(self):
        self.canvas.set_connect_mode(not self.canvas.connect_mode)
        self._rebuild()

    def _fit(self):
        self.canvas.fit()
        self.status = "Автомат вписан в окно"

    def _open_help(self):
        if self._commit_editors():
            self.app.push_help()

    def _commit_doc_name(self, value):
        if not value:
            self.status = "Название автомата не может быть пустым"
            return False
        if value != self.automaton.name:
            self.automaton.name = value
            self._after_edit("Название автомата изменено")
        return True

    def _commit_description(self, value):
        if value != self.automaton.description:
            self.automaton.description = value
            self._after_edit("Описание изменено")
        return True

    def _commit_state_id(self, old_id, value):
        try:
            self.automaton.rename_state(old_id, value)
        except AutomatonError as exc:
            self.status = str(exc)
            return False
        if value != old_id:
            self.canvas.selected_id = value
            self.status = "ID состояния %s → %s" % (old_id, value)
            self.history.push(self.automaton.to_dict())
            # Пересобираем инспектор: его колбэки захватили старый id.
            self._rebuild()
            self.app.set_title(self.automaton.name)
        return True

    def _commit_state_name(self, state_id, value):
        state = self.automaton.state(state_id)
        if state is None:
            return False
        if value != state.name:
            state.name = value
            self._after_edit("Имя состояния изменено")
        return True

    def _commit_event(self, transition_id, value):
        transition = self.automaton.transition(transition_id)
        if transition is None:
            return False
        if value != transition.event:
            transition.event = value
            self._after_edit("Подпись перехода изменена")
        return True

    def _commit_guard(self, transition_id, value):
        transition = self.automaton.transition(transition_id)
        if transition is None:
            return False
        if value != transition.guard:
            transition.guard = value
            self._after_edit("Условие перехода изменено")
        return True

    def _toggle_initial(self, state_id, value):
        self.automaton.set_initial(state_id, value)
        self._after_edit("Начальное состояние: %s" % state_id)

    def _toggle_final(self, state_id, value):
        self.automaton.set_final(state_id, value)
        self._after_edit("Финальное состояние: %s" % state_id)

    def _after_edit(self, message):
        self.status = message
        self.history.push(self.automaton.to_dict())
        # Не пересоздаём поля инспектора: пользователь может продолжать ввод.
        self.app.set_title(self.automaton.name)
        self._refresh_toolbar()

    def _refresh_toolbar(self):
        self.toolbar_widgets = []
        self._build_toolbar(self.top_rect)
        self.widgets = self.toolbar_widgets + self.inspector_widgets

    # --- сохранение/история --------------------------------------------
    def is_dirty(self):
        if self.saved_data is None:
            return True
        return self.automaton.to_dict() != self.saved_data

    def _commit_editors(self):
        for widget in list(self.widgets):
            if isinstance(widget, TextInput) and widget.editing:
                if not widget.commit():
                    self.status = ("Исправьте поле: %s"
                                   % (widget.label or "значение"))
                    return False
        return True

    def save(self):
        if not self._commit_editors():
            return False
        if not self.automaton.name.strip():
            self.automaton.name = "Без названия"
        try:
            if self.slug is None:
                self.slug = self.app.store.save(self.automaton)
            else:
                self.slug = self.app.store.save(self.automaton, self.slug)
        except (StoreError, OSError) as exc:
            self.status = "Ошибка сохранения: %s" % exc
            return False
        self.saved_data = self.automaton.to_dict()
        self.status = "Сохранено: configs/automata/%s.json" % self.slug
        self.app.set_title(self.automaton.name)
        self._refresh_toolbar()
        return True

    def _cancel_editors(self):
        for widget in list(self.widgets):
            if isinstance(widget, TextInput) and widget.editing:
                widget.cancel()

    def undo(self):
        if any(isinstance(w, TextInput) and w.editing for w in self.widgets):
            self.status = "Завершите ввод (Enter) перед отменой"
            return
        snapshot = self.history.undo()
        if snapshot is None:
            self.status = "Отменять нечего"
            return
        self._apply_snapshot(snapshot, "Отменено")

    def redo(self):
        if any(isinstance(w, TextInput) and w.editing for w in self.widgets):
            self.status = "Завершите ввод (Enter) перед повтором"
            return
        snapshot = self.history.redo()
        if snapshot is None:
            self.status = "Повторять нечего"
            return
        self._apply_snapshot(snapshot, "Повторено")

    def _apply_snapshot(self, snapshot, message):
        self.automaton = Automaton.from_dict(snapshot)
        self.canvas.automaton = self.automaton
        self.canvas.selected_kind = None
        self.canvas.selected_id = None
        self.canvas.pending_source = None
        self.status = message
        self.app.set_title(self.automaton.name)
        self._rebuild()

    # --- выход ----------------------------------------------------------
    def request_leave(self):
        if not self.is_dirty():
            self.app.go("library")
            return
        name = self.automaton.name or "Без названия"
        self.app.push(
            "confirm",
            title="Несохранённые изменения",
            message="Сохранить «%s» перед выходом в библиотеку?" % name,
            note="Если не сохранить, правки этой сессии будут потеряны.",
            actions=[
                ("Сохранить", self._save_and_leave),
                ("Не сохранять", lambda: self.app.go("library")),
                ("Отмена", None),
            ],
        )

    def _save_and_leave(self):
        if self.save():
            self.app.go("library",
                        message="Сохранено: %s.json" % self.slug)

    # --- события --------------------------------------------------------
    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and (event.mod & pygame.KMOD_CTRL):
            if event.key == pygame.K_s:
                self.save()
                return True
            if event.key == pygame.K_z:
                if event.mod & pygame.KMOD_SHIFT:
                    self.redo()
                else:
                    self.undo()
                return True
            if event.key == pygame.K_y:
                self.redo()
                return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
            self._open_help()
            return True
        if super().handle_event(event):
            return True
        if self.canvas.handle_event(event):
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.request_leave()
            return True
        return False

    # --- отрисовка ------------------------------------------------------
    def draw(self, s):
        s.fill(theme.BG)
        canvas = self.canvas_rect
        panel = self.panel_rect
        self.canvas.draw(s, self.app.fonts)

        theme.panel(s, self.top_rect, fill=theme.BG_ALT,
                    border=theme.BORDER, radius=6)
        theme.panel(s, panel, fill=theme.BG_ALT, border=theme.BORDER,
                    radius=6)

        # Инспектор: заголовок, секции и пояснения.
        theme.text(s, self.app.fonts.font, "ИНСПЕКТОР",
                   (panel.left + 14, panel.top + 12), theme.TEXT)
        pygame.draw.line(s, theme.BORDER,
                         (panel.left + 14, panel.top + 36),
                         (panel.right - 14, panel.top + 36), 1)
        for title, y in self.section_marks:
            theme.text(s, self.app.fonts.font_s, title.upper(),
                       (panel.left + 14, y), theme.TEXT_MUTED)
            pygame.draw.line(s, theme.BORDER,
                             (panel.left + 14, y + 16),
                             (panel.right - 14, y + 16), 1)

        if self.count_y is not None:
            states, transitions = self.automaton.counts()
            theme.text(s, self.app.fonts.font_s,
                       "%d %s · %d %s" % (
                           states,
                           _plural(states, "состояние", "состояния",
                                   "состояний"),
                           transitions,
                           _plural(transitions, "переход", "перехода",
                                   "переходов")),
                       (panel.left + 14, self.count_y), theme.TEXT_MUTED)
        if self.state_meta_y is not None and self.canvas.selected_state():
            state = self.canvas.selected_state()
            theme.text(s, self.app.fonts.font_s,
                       "Входящие: %d · исходящие: %d" % (
                           len(self.automaton.incoming(state.id)),
                           len(self.automaton.outgoing(state.id))),
                       (panel.left + 14, self.state_meta_y),
                       theme.TEXT_MUTED)
        if (self.transition_meta_y is not None
                and self.canvas.selected_transition()):
            theme.text(s, self.app.fonts.font_s,
                       "Из: %s" % self.transition_source,
                       (panel.left + 14, self.transition_meta_y),
                       theme.TEXT_DIM)
            theme.text(s, self.app.fonts.font_s,
                       "В:  %s" % self.transition_target,
                       (panel.left + 14, self.transition_meta_y + 18),
                       theme.TEXT_DIM)
        if self.hint_y is not None:
            hint = ("Выберите состояние или переход на холсте. "
                    "Двойной клик по пустому месту добавляет состояние.")
            y = self.hint_y
            for line in theme.wrap(self.app.fonts.font_s, hint,
                                   panel.width - 28):
                theme.text(s, self.app.fonts.font_s, line,
                           (panel.left + 14, y), theme.TEXT_MUTED)
                y += 16
        self._draw_validation(s, panel)

        for widget in self.toolbar_widgets:
            widget.draw(s, self.app.fonts)
        for widget in self.inspector_widgets:
            widget.draw(s, self.app.fonts)

        self._draw_status(s)
        # Тонкая рамка холста поверх сетки.
        pygame.draw.rect(s, theme.BORDER, canvas, width=1)

    def _draw_validation(self, s, panel):
        issues = self.automaton.validate()
        x = panel.left + 14
        width = panel.width - 28
        y = self.validation_y
        if y + 22 > panel.bottom:
            return
        theme.text(s, self.app.fonts.font_s, "ПРОВЕРКА", (x, y),
                   theme.TEXT_MUTED)
        y += 18
        if not issues:
            theme.text(s, self.app.fonts.font_s,
                       "Структура корректна.", (x, y), theme.OK)
            return
        errors = [item for item in issues if item.is_error]
        warnings = [item for item in issues if not item.is_error]
        ordered = errors + warnings
        for issue in ordered[:4]:
            if y + 16 > panel.bottom:
                break
            color = theme.DANGER if issue.is_error else theme.WARN
            mark = "!" if issue.is_error else "·"
            lines = theme.wrap(self.app.fonts.font_s, issue.message, width - 14)
            theme.text(s, self.app.fonts.font_s, mark, (x, y), color)
            for line in lines:
                if y + 16 > panel.bottom:
                    break
                theme.text(s, self.app.fonts.font_s, line, (x + 14, y),
                           color if issue.is_error else theme.TEXT_DIM)
                y += 15
            y += 3
        rest = len(ordered) - 4
        if rest > 0 and y + 16 <= panel.bottom:
            theme.text(s, self.app.fonts.font_s,
                       "…и ещё %d" % rest, (x, y), theme.TEXT_MUTED)

    def _draw_status(self, s):
        w, h = s.get_size()
        y = h - STATUS_H - 2
        pygame.draw.line(s, theme.BORDER, (theme.EDGE, y),
                         (w - theme.EDGE, y), 1)
        text_y = y + 7
        status = ui.ellipsis(self.app.fonts.font_s, self.status,
                             max(120, w // 3 - 60))
        theme.text(s, self.app.fonts.font_s, status,
                   (theme.EDGE, text_y), theme.TEXT_DIM)

        if self.canvas.connect_mode:
            if self.canvas.pending_source:
                hint = ("Связь: источник %s — выберите цель · Esc отмена"
                        % self.canvas.pending_source)
            else:
                hint = "Связь: выберите исходное состояние · Esc отмена"
            color = theme.ACCENT2
        else:
            hint = "ЛКМ выбрать · ПКМ панорама · колесо масштаб · F вписать"
            color = theme.TEXT_MUTED
        hint = ui.ellipsis(self.app.fonts.font_s, hint, max(160, w // 3))
        theme.text(s, self.app.fonts.font_s, hint,
                   (w // 2, text_y), color, center=True)

        states, transitions = self.automaton.counts()
        theme.text(s, self.app.fonts.font_s,
                   "%d сост. · %d перех. · %d%%" % (
                       states, transitions, round(self.canvas.zoom * 100)),
                   (w - theme.EDGE, text_y), theme.TEXT_MUTED, right=True)
