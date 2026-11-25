"""Арена, сохранения и настройки."""

from __future__ import annotations

from .app_support import (
    _ArenaHostScreen,
    logger,
)


class AppMenuMixin:

    def open_arena(self):
        """Дуэль-арена поверх главного окна (ось B2, единое меню).

        Встраивает существующий движок `game_engine.GameApp` в текущее
        окно pygame (`screen=`) с колбэком возврата в меню. Тяжёлые
        импорты — лениво, чтобы стартовое меню не падало без опций
        арены; при любой ошибке встроенного запуска остаёмся в меню.
        """
        try:
            from game_engine import GameApp

            arena = GameApp(
                screen=self.screen,
                on_escape=self.manager.pop,
                checkpoint=self.checkpoint,
            )
        except Exception as exc:  # pragma: no cover - защитный путь UI
            logger.warning("Арена недоступна: %s", exc)
            return
        self.manager.push(_ArenaHostScreen(self, arena))
        logger.info("Открыта арена (встроенный game_engine)")

    def open_saves(self):
        from .screens.saves_menu import SavesMenuScreen

        self.manager.push(SavesMenuScreen(self))
        logger.debug("Открыто меню сохранений")

    def open_settings(self):
        from .screens.settings_menu import SettingsMenuScreen

        self.manager.push(SettingsMenuScreen(self))
        logger.debug("Открыто меню настроек")

    def open_how_to_play(self):
        from .screens.how_to_play import HowToPlayScreen

        self.manager.push(HowToPlayScreen(self))
        logger.debug("Открыт экран «Как играть»")
