"""Экраны (сцены) сценного слоя: меню, настройки, сохранения, нарратив,
игровое поле, пауза, «об игре».

Каждая сцена — наследник ``ui.scene.Scene``; регистрация в
``ui.app.App._register``.
"""

from .about import AboutScene
from .battlefield import BattlefieldScene
from .game import GameScene
from .menu import MainMenuScene
from .narrative import NarrativeScene
from .pause import PauseScene
from .saves import SavesScene
from .settings import SettingsScene

__all__ = [
    "AboutScene", "BattlefieldScene", "GameScene", "MainMenuScene",
    "NarrativeScene", "PauseScene", "SavesScene", "SettingsScene",
]
