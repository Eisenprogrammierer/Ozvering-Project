import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")


@pytest.fixture(autouse=True)
def _reset_audio():
    yield
    if pygame.mixer.get_init():
        pygame.mixer.quit()


def _strategy_app():
    from view.app import App
    from view.support.storyline import load_storyline

    app = App()
    app.selected_role = app.role_catalog.select("faction_leader")
    app.start_storyline(load_storyline("faction_leader_demo"), "faction_red")
    app.manager.current.skip()
    app.manager.current.on_finish()
    return app


def test_faction_leader_flow_opens_strategy_not_rts():
    app = _strategy_app()
    from view.screens.strategy_screen import StrategyScreen

    assert isinstance(app.manager.current, StrategyScreen)
    assert app.manager.current.__class__.__name__ != "RTSScreen"
    assert app.strategy is not None
    assert app.campaign_preset.scenario["mode"] == "strategy"
    assert app.state.count == 0


def test_strategy_screen_draws_three_panels_and_actions():
    app = _strategy_app()
    screen = app.manager.current
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    assert screen.engine.entity("press")
    assert screen.engine.entity("charter_commission")
    assert screen._entity_rows()
    screen._select_entity("press")
    ids = [item["id"] for item in screen._action_options()]
    assert "public_address" in ids
    assert screen._action_rows()
    screen._select_action("public_address")
    preview = screen.engine.preview("public_address", "press")
    assert preview["success_text"]
    assert preview["failure_text"]
    assert preview["delayed_text"]
    screen.draw(surface)


def test_strategy_screen_action_and_day_update_storyline_snapshot():
    app = _strategy_app()
    screen = app.manager.current
    screen._select_entity("press")
    screen._select_action("public_address")
    screen._execute_selected()
    snapshot = app.storyline_interpreter.state["strategy"]
    assert snapshot["day"] == 1
    assert snapshot["actions_left"] == 2
    assert screen.last_result is not None
    day = screen.engine.day
    screen._end_day()
    assert screen.engine.day == day + 1
    assert app.storyline_interpreter.state["strategy"]["day"] == day + 1
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)


def test_strategy_screen_accepts_outcome_without_showing_rts():
    app = _strategy_app()
    screen = app.manager.current
    screen.engine.outcome = "win"
    screen.engine.finished = True
    screen._accept_outcome()
    assert app.pending_storyline_outcome == "win"
    assert app.manager.current.__class__.__name__ != "RTSScreen"


def test_strategy_save_load_restores_strategy_screen(tmp_path, monkeypatch):
    import view.support.save_system as saves

    monkeypatch.setattr(saves, "SAVES_DIR", tmp_path)
    app = _strategy_app()
    screen = app.manager.current
    screen._select_entity("press")
    screen._select_action("public_address")
    screen._execute_selected()
    screen._end_day()
    expected = (
        screen.engine.day,
        screen.engine.resource("charter"),
        screen.engine.actions_left,
    )
    assert app.save_game("strategy-slot")

    restored = type(app)()
    assert restored.load_game("strategy-slot")
    assert restored.manager.current.__class__.__name__ == "StrategyScreen"
    assert restored.strategy is not None
    assert (
        restored.strategy.day,
        restored.strategy.resource("charter"),
        restored.strategy.actions_left,
    ) == expected
    assert (
        restored.storyline_interpreter.state["strategy"]["day"] == expected[0]
    )


def test_faction_select_uses_civilian_groups():
    from view.app import App
    from view.screens.faction_select import FactionSelectScreen

    app = App()
    app.selected_role = app.role_catalog.select("faction_leader")
    screen = FactionSelectScreen(app)
    assert [item["groups"] for item in screen.options] == [2, 2]
    assert all(item["companies"] == 0 for item in screen.options)
    assert screen.options[0]["kind"] == "coalition"
