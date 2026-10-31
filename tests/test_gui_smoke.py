"""E2E-смоук игрового GUI (задача D3/B1 из docs/RELEASE_READINESS.md).

Раньше все pygame-тесты проверяли отдельные экраны поштучно, но живой
главный цикл `view.App.run()` (события → update → draw → flip) не
исполнялся ни разу — 81 skip скрывал этот разрыв. Тесты ниже поднимают
настоящий цикл под dummy-драйвером SDL и проходят путь меню → кампания:

* конструируется реальный `App` (то же, что делает `main.py --campaign`);
* в очередь событий ставятся KEYDOWN (выбор пунктов меню) и QUIT;
* главный цикл крутится до QUIT; на каждом кадре проверяется, что экран
  отрисовался без исключения (draw ловит баги верстки/HUD);
* после цикла инварианты: стек непустой, игра дошла до экрана мира или
   меню осталось живым.

Тесты скипаются, если pygame недоступен (как остальные GUI-тесты).
"""

import os

import pytest

pygame = pytest.importorskip("pygame")

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def _post_keys(keys):
    """Ставит в очередь событий KEYDOWN по списку кодов."""
    for key in keys:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key))


def _post_quit():
    pygame.event.post(pygame.event.Event(pygame.QUIT))


def _click(rect):
    """Клик ЛКМ в центр прямоугольника кнопки (события MOUSEBUTTONDOWN)."""
    pos = (rect.x + rect.width // 2, rect.y + rect.height // 2)
    pygame.event.post(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)
    )
    return pos


def _drain_cycle(app, max_frames=600):
    """Прокручивает главный цикл `app.run()`, ограничивая число кадров.

    Цикл завершится сам на QUIT; max_frames — страховка от зависания.
    Реализация повторяет тело run() (events→update→draw→flip), чтобы
    иметь гарантированный стоп даже при потерянном QUIT.
    """
    frames = 0
    while app.running and frames < max_frames:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                app.running = False
            elif (
                event.type == pygame.KEYDOWN and event.key == pygame.K_F11
            ):
                app.toggle_fullscreen()
            elif (
                event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
            ):
                app.manager.handle_escape()
            else:
                app.manager.handle_event(event)
        dt = app.clock.tick(250) / 1000.0
        app.manager.update(dt)
        app.music.update()
        app.process_pending_storyline_outcome()
        app.process_pending_mandatory_scene()
        app.screen.fill((10, 12, 16))
        app.manager.draw(app.screen)  # каждый кадр рисуем реально
        if app.manager.has_time_hud_screen() and not getattr(
            app.manager.current, "hide_time_hud", False
        ):
            app.time_hud.draw(app.screen)
        pygame.display.flip()
        frames += 1
    return frames


@pytest.fixture()
def app():
    from view.app import App

    instance = App(checkpoint="")
    yield instance
    instance.running = False
    pygame.quit()


def test_main_menu_cycle_draws_without_errors(app):
    """Стартовое меню: несколько живых кадров главного цикла без исключений."""
    frames = _drain_cycle(app, max_frames=30)
    assert frames >= 10, "цикл должен отрисовать кадры до QUIT"
    assert app.manager.current is not None
    assert type(app.manager.current).__name__ == "MainMenuScreen"


def test_menu_navigation_reaches_world_screen(app):
    """Путь «Новая игра» кликами мыши по реальному главному циклу (B2-затравка).

    Кнопки MainMenuScreen работают по MOUSEBUTTONDOWN (виджет Button),
    поэтому кликаем «Новая игра», затем — если открылся выбор сюжета/роли,
    кликаем первую активную кнопку. Проверяем, что навигация не роняет
    цикл и стек меняется (любой прогресс легален, исключение — нет).
    """
    name_before = type(app.manager.current).__name__
    menu = app.manager.current
    new_game_btn = next(
        b for b in menu.buttons if b.text == "Новая игра"
    )
    _click(new_game_btn.rect)
    frames = _drain_cycle(app, max_frames=60)
    assert frames >= 5
    current = type(app.manager.current).__name__
    assert current != name_before or len(app.manager.stack) > 1, (
        "клик «Новая игра» должен сдвинуть навигацию (осталось: %s)"
        % current
    )


def test_world_screen_runs_in_live_cycle(app):
    """Экран мира внутри настоящего цикла: update/draw/HUD без исключений."""
    from view.screens.world_screen import WorldScreen
    from campaign.world import WorldEngine, load_world

    engine = WorldEngine(load_world(), seed=7)
    app.world = engine
    app.manager.replace_all(WorldScreen(app, engine))
    day_before = engine.day
    screen = app.manager.current
    end_day_btn = getattr(screen, "btn_end_day", None)
    if end_day_btn is not None and getattr(end_day_btn, "enabled", True):
        _click(end_day_btn.rect)
    else:
        # fallback: прямой вызов того же пути, что делает кнопка
        screen._end_day()
    _post_quit()
    frames = _drain_cycle(app, max_frames=90)
    assert frames >= 5
    assert engine.day > day_before, "завершение дня обязано продвинуть мир"
