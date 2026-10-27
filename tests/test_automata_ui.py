from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    pytest.importorskip("pygame")
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    from automata.app import AutomataApp
    from automata.storage import AutomataStore

    root = tmp_path_factory.mktemp("automata_store")
    instance = AutomataApp(store=AutomataStore(root))
    yield instance
    import game_engine as ge

    ge.quit_pygame()


@pytest.fixture(autouse=True)
def clean(app):
    for path in app.store.root.glob("*.json"):
        path.unlink()
    app.go("library")
    yield


def _frame(app):
    app.manager.update(1.0 / 60.0)
    app.manager.draw(app.screen)


def _click(scene, pos):
    import pygame

    for event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        scene.handle_event(pygame.event.Event(event_type, pos=pos, button=1))


def _editor(app):
    app.new_automaton()
    assert app.manager.current.name == "editor"
    return app.manager.current


def _center(canvas, state):
    rect = canvas.node_rect(state)
    return rect.center


def test_library_empty_and_with_file(app):
    scene = app.manager.current
    assert scene.name == "library"
    _frame(app)
    assert scene.entries == []

    from automata.model import Automaton

    automaton = Automaton("Файл")
    automaton.add_state("A", initial=True)
    slug = app.store.save(automaton, "file")
    scene.refresh()
    _frame(app)
    assert [entry["slug"] for entry in scene.entries] == [slug]
    assert scene.entries[0]["name"] == "Файл"


def test_new_automaton_opens_editor(app):
    scene = _editor(app)
    assert scene.automaton.counts() == (1, 0)
    state = scene.automaton.states[0]
    assert state.initial is True
    assert scene.canvas.selected_kind == "state"
    assert scene.canvas.selected_id == state.id
    assert scene.slug is None
    assert scene.is_dirty() is True
    _frame(app)
    assert scene.canvas.rect.width > 100


def test_new_document_leave_prompts_without_edits(app):
    scene = _editor(app)
    scene.request_leave()
    assert app.manager.current.name == "confirm"
    assert app.manager.current.title == "Несохранённые изменения"


def test_add_states_and_connect_by_clicks(app):
    scene = _editor(app)
    first = scene.automaton.states[0]
    second = scene.canvas.add_state_at(
        (scene.canvas.rect.centerx + 180, scene.canvas.rect.centery)
    )
    assert scene.automaton.counts() == (2, 0)

    scene._toggle_connect()
    assert scene.canvas.connect_mode is True
    _click(scene, _center(scene.canvas, first))
    assert scene.canvas.pending_source == first.id
    _click(scene, _center(scene.canvas, second))

    assert scene.automaton.counts() == (2, 1)
    transition = scene.automaton.transitions[0]
    assert transition.source == first.id
    assert transition.target == second.id
    assert scene.canvas.selected_kind == "transition"
    _frame(app)


def test_drag_state_creates_one_history_step_and_undo(app):
    import pygame

    scene = _editor(app)
    state = scene.automaton.states[0]
    old = (state.x, state.y)
    start = _center(scene.canvas, state)
    scene.handle_event(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start, button=1)
    )
    scene.handle_event(
        pygame.event.Event(
            pygame.MOUSEMOTION,
            pos=(start[0] + 120, start[1] + 80),
            rel=(120, 80),
            buttons=(1, 0, 0),
        )
    )
    scene.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONUP, pos=(start[0] + 120, start[1] + 80), button=1
        )
    )
    assert (state.x, state.y) != old
    assert scene.history.can_undo is True
    _frame(app)

    scene.undo()
    restored = scene.automaton.states[0]
    assert (restored.x, restored.y) == old
    assert scene.automaton.counts() == (1, 0)
    _frame(app)


def test_inspector_edit_and_save_roundtrip(app):
    from automata.model import Automaton
    from automata.ui import TextInput

    scene = _editor(app)
    state = scene.automaton.states[0]
    inputs = [
        w
        for w in scene.widgets
        if isinstance(w, TextInput) and w.label == "Название"
    ]
    assert len(inputs) == 2
    state_input = inputs[1]
    state_input.start()
    state_input.value = "Готово"
    state_input.caret = len(state_input.value)
    assert state_input.commit() is True
    assert scene.automaton.states[0].name == "Готово"
    assert scene.is_dirty() is True

    assert scene.save() is True
    slug = scene.slug
    assert slug
    assert app.store.exists(slug)
    assert scene.is_dirty() is False
    loaded = app.store.load(slug)
    assert loaded.states[0].name == "Готово"

    scene.automaton.name = "Новый заголовок"
    scene._after_edit("Название изменено")
    assert scene.save() is True
    assert scene.slug == slug
    assert app.store.load(slug).name == "Новый заголовок"
    assert isinstance(
        Automaton.from_dict(app.store.load(slug).to_dict()), Automaton
    )


def test_unsaved_leave_can_save(app):
    scene = _editor(app)
    scene.automaton.states[0].name = "Правка"
    scene._after_edit("Правка")
    assert scene.is_dirty()

    scene.request_leave()
    confirm = app.manager.current
    assert confirm.name == "confirm"
    _frame(app)
    action = next(
        callback for label, callback in confirm.actions if label == "Сохранить"
    )
    confirm._fire(action)

    assert app.manager.current.name == "library"
    assert len(app.store.list_entries()) == 1
    _frame(app)


def test_unsaved_leave_can_discard(app):
    scene = _editor(app)
    scene.automaton.states[0].name = "Правка"
    scene._after_edit("Правка")
    scene.request_leave()
    confirm = app.manager.current
    action = next(
        callback
        for label, callback in confirm.actions
        if label == "Не сохранять"
    )
    confirm._fire(action)
    assert app.manager.current.name == "library"
    assert app.store.list_entries() == []


def test_help_and_confirm_overlay_render(app):
    app.push_help()
    assert app.manager.current.name == "help"
    _frame(app)
    app.pop()
    assert app.manager.current.name == "library"

    app.push(
        "confirm",
        title="Тест",
        message="Удалить?",
        actions=[("Да", None), ("Нет", None)],
        danger=True,
    )
    assert app.manager.current.name == "confirm"
    _frame(app)
    app.pop()


def test_canvas_edge_direction_and_selection(app):
    scene = _editor(app)
    first = scene.automaton.states[0]
    second = scene.canvas.add_state_at(
        (scene.canvas.rect.centerx + 200, scene.canvas.rect.centery)
    )
    transition = scene.automaton.add_transition(first.id, second.id, "go")
    points, label = scene.canvas._edge_geometry(transition)
    assert points[0][0] < points[-1][0]
    assert points[-1][0] <= scene.canvas.node_rect(second).left + 2
    assert label is not None

    scene.canvas.select("transition", transition.id)
    assert scene.canvas.selected_transition() is transition
    assert scene.canvas.delete_selected() is True
    assert scene.automaton.transitions == []


def test_text_input_typing_cancel_and_rejection(app):
    import pygame
    from automata.ui import TextInput

    widget = TextInput(
        "Поле",
        "abc",
        on_commit=lambda value: value != "bad",
        rect=(10, 10, 220, 32),
    )
    widget.draw(app.screen, app.fonts)
    widget.start()
    widget.caret = len(widget.value)
    widget.handle(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x, unicode="x", mod=0)
    )
    assert widget.value == "abcx"
    widget.handle(
        pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0
        )
    )
    assert widget.value == "abc"
    assert widget.editing is False

    widget.start()
    widget.value = "bad"
    assert widget.commit() is False
    assert widget.editing is True
    widget.value = "ok"
    assert widget.commit() is True
    assert widget.editing is False


def test_state_id_rename_rebuilds_inspector_callbacks(app):
    import pygame
    from ui import widgets
    from automata.ui import TextInput

    scene = _editor(app)
    id_input = next(
        w
        for w in scene.widgets
        if isinstance(w, TextInput) and w.label.startswith("ID")
    )
    id_input.start()
    id_input.value = "q0"
    assert id_input.commit() is True
    assert scene.automaton.states[0].id == "q0"
    assert scene.canvas.selected_id == "q0"

    state = scene.automaton.states[0]
    name_input = next(
        w
        for w in scene.widgets
        if isinstance(w, TextInput)
        and w.label == "Название"
        and w.value == state.name
    )
    name_input.start()
    name_input.value = "После переименования"
    assert name_input.commit() is True
    assert scene.automaton.state("q0").name == "После переименования"

    final_toggle = next(
        w
        for w in scene.widgets
        if isinstance(w, widgets.Toggle) and w.label == "Финальное состояние"
    )
    scene.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=final_toggle.rect.center, button=1
        )
    )
    assert scene.automaton.state("q0").final is True


def test_click_from_one_inspector_input_to_another_keeps_focus(app):
    import pygame
    from automata.model import Automaton
    from automata.ui import TextInput

    scene = _editor(app)
    inputs = [
        w
        for w in scene.widgets
        if isinstance(w, TextInput) and w.label == "Название"
    ]
    assert len(inputs) == 2
    doc_input, state_input = inputs
    state = scene.automaton.states[0]

    scene.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=doc_input.rect.center, button=1
        )
    )
    assert doc_input.editing is True
    doc_input.value = "Документ"
    doc_input.caret = len(doc_input.value)

    scene.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=state_input.rect.center, button=1
        )
    )
    assert doc_input.editing is False
    assert scene.automaton.name == "Документ"
    assert state_input.editing is True
    assert state_input in scene.widgets

    scene.handle_event(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x, unicode="x", mod=0)
    )
    assert state_input.value.endswith("x")
    scene.handle_event(
        pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0
        )
    )
    assert state.name.endswith("x")
    assert isinstance(scene.automaton, Automaton)
