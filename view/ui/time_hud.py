"""
view/ui/time_hud.py

HUD игрового времени.

Отображает в левом верхнем углу экрана текущее игровое время,
уровень усталости игрока, текущее выполняемое действие с полосой
прогресса и предупреждение об ожидающей обязательной сцене.

События отображения фиксируются в журнале operation_ozverin.log
в корне проекта и дублируются в консоль.
"""

import os
import logging

import pygame


def _get_logger(name):
    """
    Возвращает журнал с файловым и консольным обработчиками.

    Файловый обработчик пишет в operation_ozverin.log в корне проекта,
    консольный выводит сообщения в стандартный поток вывода.
    Обработчики создаются один раз для каждого имени журнала.

    Args:
        name (str): Имя журнала.

    Returns:
        logging.Logger: Настроенный журнал.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        base = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        file_handler = logging.FileHandler(
            os.path.join(base, "operation_ozverin.log"), encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.propagate = False
    return logger


logger = _get_logger("view.ui.time_hud")


class TimeHUD:
    """
    HUD игрового времени.

    Рисует информационную панель в левом верхнем углу экрана.
    Если в приложении отсутствует time_system, отрисовка не выполняется.

    Attributes:
        app: Экземпляр приложения (App).
    """

    def __init__(self, app):
        """
        Инициализирует HUD игрового времени.

        Args:
            app: Экземпляр приложения (App).
        """
        self.app = app
        self._last_time_str = None
        self._last_mandatory = None
        logger.info("TimeHUD инициализирован")

    def draw(self, screen):
        """
        Отрисовывает HUD игрового времени на экране.

        Порядок отрисовки:
        1. Часы (текущее игровое время).
        2. Уровень усталости.
        3. Текущее действие с полосой прогресса (если выполняется).
        4. Предупреждение об обязательной сцене (если ожидает).

        Изменения отображаемого времени и появление обязательной сцены
        фиксируются в журнале.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        ts = getattr(self.app, "time_system", None)
        if ts is None:
            logger.debug("time_system отсутствует, отрисовка пропущена")
            return
        font = self.app.font_small
        time_str = ts.get_time_string()
        if time_str != self._last_time_str:
            logger.info(
                "HUD: время=%s усталость=%.0f%%",
                time_str,
                ts.get_fatigue() * 100,
            )
            self._last_time_str = time_str
        time_surf = font.render(time_str, True, (220, 220, 230))
        bg = pygame.Surface((time_surf.get_width() + 20, 30), pygame.SRCALPHA)
        bg.fill((10, 10, 20, 180))
        screen.blit(bg, (10, 10))
        screen.blit(time_surf, (20, 15))
        fatigue = ts.get_fatigue()
        fatigue_label = f"Усталость: {fatigue:.0%}"
        fatigue_surf = font.render(fatigue_label, True, (200, 180, 140))
        screen.blit(fatigue_surf, (20, 45))
        active = ts.active_action
        if active is not None:
            definition = ts.actions.get(active.definition_id)
            if definition is not None:
                label = definition.label
                progress = active.progress_seconds
                total = definition.duration_seconds
                pct = min(1.0, progress / max(1e-6, total))
                action_text = f"{label}: {pct:.0%}"
                action_surf = font.render(action_text, True, (180, 220, 180))
                bg2 = pygame.Surface(
                    (action_surf.get_width() + 20, 30), pygame.SRCALPHA
                )
                bg2.fill((10, 20, 10, 180))
                screen.blit(bg2, (10, 70))
                screen.blit(action_surf, (20, 75))
                bar_w = 200
                bar_h = 6
                bar_x = 20
                bar_y = 100
                pygame.draw.rect(
                    screen, (60, 60, 60), (bar_x, bar_y, bar_w, bar_h)
                )
                pygame.draw.rect(
                    screen,
                    (80, 200, 80),
                    (bar_x, bar_y, int(bar_w * pct), bar_h),
                )
        if ts.pending_mandatory_scene is not None:
            if ts.pending_mandatory_scene != self._last_mandatory:
                logger.info(
                    "HUD: ожидает обязательная сцена: %s",
                    ts.pending_mandatory_scene,
                )
                self._last_mandatory = ts.pending_mandatory_scene
            scene_label = {
                "morning_inspection": "Утренний осмотр",
                "evening_inspection": "Вечерний осмотр",
            }.get(ts.pending_mandatory_scene, ts.pending_mandatory_scene)
            scene_surf = font.render(
                f"Обязательная сцена: {scene_label}", True, (255, 200, 100)
            )
            screen.blit(scene_surf, (20, 115))
        else:
            self._last_mandatory = None