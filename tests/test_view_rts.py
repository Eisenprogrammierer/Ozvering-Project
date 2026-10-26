"""Дымовые тесты RTS-экрана (требуют pygame)."""

import math
import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")


def _app():
    from view.app import App
    return App()


def test_rts_screen_draws_and_selects_units():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    app.manager.replace_all(screen)
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    assert screen.selected
    assert screen._project((0, 0)) != screen._project((1, 0))
    cell = screen._cell_from_mouse(screen._project((6, 6)))
    assert cell == (6, 6)


def test_rts_move_order_and_needs_action():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    app.manager.replace_all(screen)
    idx = screen.selected[0]
    start = screen.state.det_at(idx).position
    screen._issue_ground((5, 5))
    app.time_system.advance(1800)
    assert screen.state.det_at(idx).position != start
    result = screen.state.needs.apply(idx, "feed")
    assert result["ok"]
    assert screen.state.supplies["food"] < 420


def test_text_layout_breaks_long_words():
    from view.ui.text_layout import wrap_text

    font = pygame.font.Font(None, 20)
    lines = wrap_text(font, "A" * 80, 50)
    assert len(lines) > 1
    assert all(font.size(line)[0] <= 50 for line in lines)


def test_rts_tick_spawns_battle_particles():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    for _ in range(4):
        app.time_system.advance(1800)
        screen._after_tick()
    assert screen._particles


def test_rts_update_advances_game_minutes_and_speed():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    app.manager.replace_all(screen)
    start = app.time_system.seconds_of_day
    screen.set_speed(1)
    screen.update(0.36)
    assert app.time_system.seconds_of_day == start + 60
    start = app.time_system.seconds_of_day
    screen.set_speed(4)
    screen.update(0.36)
    assert app.time_system.seconds_of_day == start + 240


def test_rts_overlays_draw_without_errors():
    from view.screens.rts_screen import RTSScreen
    from view.ui.orders_overlay import UnitOrdersOverlay
    from view.ui.needs_overlay import NeedsOverlay
    from view.ui.overlays import LogisticsOverlay, RadioOverlay

    app = _app()
    screen = RTSScreen(app)
    app.manager.replace_all(screen)
    surface = pygame.Surface((1280, 720))
    for cls in (UnitOrdersOverlay, NeedsOverlay):
        overlay = cls(app, screen)
        app.manager.push(overlay)
        overlay.update(0.016)
        overlay.draw(surface)
        app.manager.pop()
    for cls in (LogisticsOverlay, RadioOverlay):
        overlay = cls(app)
        app.manager.push(overlay)
        overlay.update(0.016)
        overlay.draw(surface)
        app.manager.pop()


def test_rts_overlay_controls_stay_inside_panels():
    from view.screens.rts_screen import RTSScreen
    from view.ui.needs_overlay import NeedsOverlay
    from view.ui.overlays import LogisticsOverlay

    app = _app()
    screen = RTSScreen(app)

    needs = NeedsOverlay(app, screen)
    panel = needs.panel.rect
    buttons = [needs.close_btn, needs.logistics_btn]
    buttons += [btn for _action, btn in needs._action_buttons]
    for button in buttons:
        assert panel.contains(button.rect)

    logistics = LogisticsOverlay(app)
    panel = logistics.panel.rect
    target_buttons = [btn for _name, btn in logistics._target_buttons]
    right_buttons = (
        [btn for _op, btn in logistics._op_buttons]
        + [btn for _kind, btn in logistics._convoy_buttons]
        + [logistics.btn_all, logistics.btn_none, logistics.close_btn]
    )
    for button in target_buttons + right_buttons:
        assert panel.contains(button.rect)
    assert max(btn.rect.bottom for btn in target_buttons) < \
        logistics.btn_all.rect.top
    for target in target_buttons:
        for right in right_buttons:
            assert not target.rect.colliderect(right.rect)


def test_unit_orders_overlay_applies_withdrawal():
    from view.screens.rts_screen import RTSScreen
    from view.ui.orders_overlay import UnitOrdersOverlay

    app = _app()
    screen = RTSScreen(app)
    app.manager.replace_all(screen)
    idx = screen.selected[0]
    overlay = UnitOrdersOverlay(app, screen)
    app.manager.push(overlay)
    overlay.apply("withdrawal")
    det = screen.state.det_at(idx)
    assert det.ui_order == "withdrawal"
    assert det.retreating


def test_rts_zoom_roundtrip_and_limits():
    from view.screens.rts_screen import MAX_ZOOM, MIN_ZOOM, RTSScreen

    app = _app()
    screen = RTSScreen(app)
    cell = (6, 6)
    screen.set_zoom(1.5)
    assert screen._cell_from_mouse(screen._project(cell)) == cell
    screen.set_zoom(MAX_ZOOM + 5.0)
    assert screen.zoom == pytest.approx(MAX_ZOOM)
    screen.set_zoom(MIN_ZOOM - 5.0)
    assert screen.zoom == pytest.approx(MIN_ZOOM)
    screen.zoom_reset()
    assert screen.zoom == pytest.approx(1.0)


def test_rts_smooth_movement_between_combat_ticks():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    det = screen.state.det_at(0)
    screen._sync_render_positions(snap=True)
    start_render = screen._render_pos[det.name]
    det.position = (det.position[0] + 1, det.position[1])
    target = screen._project(det.position)
    screen._sync_render_positions(0.1)
    screen._sync_render_positions(0.1)
    moved = screen._render_pos[det.name]
    assert moved != start_render
    assert math.dist(moved, target) < math.dist(start_render, target)


def test_rts_display_positions_separate_overlapping_icons():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    first, second = screen.state.units[:2]
    first.position = (5, 5)
    second.position = (5, 5)
    screen._sync_render_positions(snap=True)
    screen._update_display_positions()
    p0 = screen._display_pos[first.name]
    p1 = screen._display_pos[second.name]
    assert math.dist(p0, p1) >= 29.0


def test_rts_icons_do_not_jump_in_crowded_contact():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    app.manager.replace_all(screen)
    previous = {}
    previous_moving = {}
    worst = 0.0
    static_drift = 0.0
    for _ in range(900):
        screen.update(1 / 60.0)
        for name, point in screen._display_pos.items():
            old = previous.get(name)
            if old is not None:
                step = math.dist(old, point)
                worst = max(worst, step)
                if (not previous_moving.get(name, False) and
                        not screen._moving.get(name, False)):
                    static_drift = max(static_drift, step)
            previous[name] = point
            previous_moving[name] = screen._moving.get(name, False)
    # На границах такта раньше были скачки по 40–60 px из-за пересборки
    # перекрытий. Теперь позиция должна меняться плавно, а покоящиеся
    # жетоны не должны смещаться вовсе.
    assert worst < 2.5
    assert static_drift < 0.05


def test_rts_groups_select_and_apply_common_order():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    group = screen._player_indices()[:3]
    screen.selected = list(group)
    screen.assign_group(3)
    names = [screen.state.det_at(i).name for i in group]
    assert screen.groups[3] == names
    screen.selected = []
    screen.select_group(3)
    assert screen.selected == group
    screen.command_hold()
    assert all(
        screen.state.det_at(i).ui_order == "holding_defense"
        for i in group
    )
    # Клик по чипу выбирает группу, Ctrl+клик записывает в неё выделение.
    screen.selected = []
    chip = next(rect for number, rect in screen._group_rects if number == 3)
    screen.handle_event(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=chip.center,
    ))
    assert screen.selected == group
    chip4 = next(rect for number, rect in screen._group_rects if number == 4)
    screen.handle_event(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=chip4.center,
        mod=pygame.KMOD_CTRL,
    ))
    assert screen.groups[4] == names


def test_rts_contact_line_uses_engagement_midpoints():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    first = screen.state.units[0]
    second = next(
        det for det in screen.state.units if det.side != first.side
    )
    screen.engine.engagements = [
        {"attacker": first.name, "defender": second.name}
    ]
    screen._display_pos[first.name] = (100.0, 100.0)
    screen._display_pos[second.name] = (140.0, 120.0)
    points = screen._contact_frontline_points()
    assert points == [(120.0, 110.0)]
    screen.draw(pygame.Surface((1280, 720)))


def test_focus_fire_assigns_two_attackers_to_one_target():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    state = screen.state
    reds = [
        det for det in state.units
        if det.side == state.player_side and det.role != "barrier"
    ][:2]
    enemy = next(
        det for det in state.units
        if det.side != state.player_side and det.role != "barrier"
    )
    reds[0].position = (5, 6)
    reds[1].position = (6, 5)
    enemy.position = (5, 5)
    for det in state.units:
        if det not in reds and det is not enemy:
            det.retreating = True
    reds[0].force = 4.0
    reds[1].force = 4.0
    enemy.force = 40.0
    state.sim.engage_range = 3
    assert screen.engine.set_focus_target(state.units.index(reds[0]), enemy)
    assert screen.engine.set_focus_target(state.units.index(reds[1]), enemy)
    screen.engine._sync_focus_targets()
    pairs = state.sim._pair_engagements()
    focused = [
        (a.name, b.name) for a, b in pairs
        if a.name in {reds[0].name, reds[1].name} and b.name == enemy.name
    ]
    assert len(focused) == 2


def test_rts_select_all_and_reads_loss_threshold_from_storyline():
    from view.screens.rts_screen import RTSScreen

    class Interpreter:
        storyline = {
            "lose_conditions": [{
                "type": "any_of",
                "conditions": [
                    {"type": "manpower_loss_above", "value": 0.25},
                    {"type": "all_player_units_destroyed"},
                ],
            }],
        }

    app = _app()
    app.storyline_interpreter = Interpreter()
    screen = RTSScreen(app)
    assert screen._loss_limit_percent() == 25
    screen.selected = []
    screen.handle_event(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_a, mod=pygame.KMOD_CTRL,
    ))
    assert screen.selected == screen._player_indices()


def test_battle_outcome_dispatches_win_and_lose():
    from view.screens.rts_screen import RTSScreen

    class Interpreter:
        finished = False

    app = _app()
    screen = RTSScreen(app)
    app.storyline_interpreter = Interpreter()
    screen.state.sim.finished = True
    screen.state.sim.winner = screen.state.player_side
    screen._trigger_battle_outcome()
    assert app.pending_storyline_outcome == "win"

    app = _app()
    screen = RTSScreen(app)
    app.storyline_interpreter = Interpreter()
    screen.state.sim.finished = True
    enemy_side = "blue" if screen.state.player_side == "red" else "red"
    screen.state.sim.winner = enemy_side
    screen._trigger_battle_outcome()
    assert app.pending_storyline_outcome == "lose"


def test_rts_auto_plan_buttons_hotkeys_and_shift_rmb():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    app.manager.replace_all(screen)

    screen.handle_event(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_g, mod=0,
    ))
    assert screen.engine.plan_for().mode == "hold"

    screen.handle_event(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_t, mod=0,
    ))
    assert screen.engine.plan_for().mode == "advance"

    screen.handle_event(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_y, mod=0,
    ))
    assert not screen.engine.plan_for().active

    screen.handle_event(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_g, mod=0,
    ))
    cell = (14, 10)
    screen.handle_event(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=3,
        pos=screen._project(cell), mod=pygame.KMOD_SHIFT,
    ))
    plan = screen.engine.plan_for()
    assert plan.mode == "hold"
    assert plan.target == cell
    assert screen.btn_plan_hold.rect.collidepoint((20, 320))


def test_rts_draws_active_plan_overlay():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    app.manager.replace_all(screen)
    screen.engine.set_auto_plan("advance", target=(18, 12))
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    screen.engine.set_auto_plan("hold", target=(12, 12))
    screen.draw(surface)
    assert screen.engine.plan_for().mode == "hold"
