"""
view/screens/aftermath.py

Экран последствий после боя или события.

Отображает фон лагеря, зависящий от сегмента condition подразделения,
и две кнопки: «Диалоги» и «Решения».

Экран решений отображает список решений из контентной конфигурации;
выбор решения вызывает правило метаморфозы и/или применяет эффект
к подразделению, после чего экран закрывается.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль.
"""

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from ..ui.asset_loader import AssetLoader
from view.support.rules import RuleEngine
from view.support.effects import EffectInterpreter
from view.support.log_journal import get_logger

logger = get_logger("view.aftermath")


class AftermathScreen(BaseScreen):
    """
    Экран последствий.

    Отображает фон лагеря, зависящий от сегмента condition
    подразделения, и две кнопки: «Диалоги» и «Решения».

    Attributes:
        unit_idx (int): Индекс подразделения в WorldState.
        bg (pygame.Surface): Фоновое изображение лагеря.
        buttons (list[Button]): Кнопки экрана.
    """

    def __init__(self, app, unit_idx):
        """
        Инициализирует экран последствий.

        Выбирает фон в зависимости от сегмента condition юнита:
        при condition >= 2 используется «свежий» лагерь,
        иначе — «побитый». Создаёт кнопки «Диалоги» и «Решения».

        Args:
            app: Экземпляр приложения (App).
            unit_idx (int): Индекс подразделения в WorldState.
        """
        super().__init__(app)
        self.unit_idx = unit_idx
        st = app.engine.state
        cond = st.read_segment(unit_idx, "condition")
        asset = "scenes/camp_fresh" if cond >= 2 else "scenes/camp_beaten"
        self.bg = AssetLoader.load(asset, (1280, 720))
        self.buttons = [
            Button((480, 560, 320, 45), "Диалоги", app.font_body, self.open_dialogues),
            Button((480, 615, 320, 45), "Решения", app.font_body, self.open_decisions),
        ]
        logger.info(
            "Экран последствий открыт: unit_idx=%s condition=%s asset=%s",
            unit_idx,
            cond,
            asset,
        )

    def open_dialogues(self):
        """
        Открывает диалог, связанный с последствиями.

        Помещает в стек экран DialogueScreen с узлом
        ``aftermath_lt_orlov``.
        """
        from .dialogue import DialogueScreen
        logger.info("Последствия: открытие диалога aftermath_lt_orlov")
        self.app.manager.push(DialogueScreen(self.app, "aftermath_lt_orlov"))

    def open_decisions(self):
        """
        Открывает экран решений для текущего подразделения.

        Формирует временный диалоговый узел ``_aftermath_decisions``
        на основе списка решений из ``app.content.decisions``
        и помещает в стек AftermathDecisionScreen.
        """
        decisions = self.app.content.decisions
        choices = [
            {
                "text": d["label"],
                "rule": d.get("rule"),
                "effect": d.get("effect", {}),
            }
            for d in decisions
        ]
        node = {
            "speaker": "Решения",
            "text": "Что делать с подразделением?",
            "choices": choices,
        }
        self.app.content.dialogues["_aftermath_decisions"] = node
        logger.info(
            "Последствия: открытие экрана решений, решений=%s",
            len(decisions),
        )
        self.app.manager.push(
            AftermathDecisionScreen(self.app, "_aftermath_decisions", self.unit_idx)
        )

    def handle_event(self, event):
        """
        Обрабатывает события pygame для данного экрана.

        Событие последовательно передаётся всем кнопкам экрана.
        Если одна из кнопок обработала событие, дальнейшая обработка
        прекращается.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        """
        Отрисовывает экран последствий.

        Рисует фоновое изображение лагеря и кнопки управления.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        screen.blit(self.bg, (0, 0))
        for b in self.buttons:
            b.draw(screen)


class AftermathDecisionScreen(BaseScreen):
    """
    Экран выбора решений для подразделения.

    Отображает список решений, сформированный на основе
    `app.content.decisions`. При выборе решения может быть
    вызвано правило метаморфозы и/или применён эффект.

    Attributes:
        unit_idx (int): Индекс подразделения в WorldState.
        choices (list[dict]): Список доступных решений.
        panel (Panel): Фоновая панель.
        buttons (list[Button]): Кнопки решений.
    """

    def __init__(self, app, node_id, unit_idx):
        """
        Инициализирует экран решений.

        Читает диалоговый узел по node_id и создаёт кнопку
        для каждого решения из узла.

        Args:
            app: Экземпляр приложения (App).
            node_id (str): Идентификатор диалогового узла.
            unit_idx (int): Индекс подразделения в WorldState.
        """
        super().__init__(app)
        self.unit_idx = unit_idx
        node = app.content.dialogues[node_id]
        self.choices = node.get("choices", [])
        self.panel = Panel((140, 400, 1000, 300))
        self.buttons = []
        y = 500
        for i, c in enumerate(self.choices):
            self.buttons.append(
                Button(
                    (200, y, 880, 42),
                    c["text"],
                    app.font_small,
                    lambda i=i: self.choose(i),
                )
            )
            y += 46
        logger.info(
            "Экран решений открыт: node=%s unit_idx=%s решений=%s",
            node_id,
            unit_idx,
            len(self.choices),
        )

    def choose(self, i):
        """
        Обрабатывает выбор решения.

        Если у решения указан ``rule``, вызывает
        ``RuleEngine.try_decision`` для текущего подразделения.
        Затем применяет эффект решения через ``EffectInterpreter``.
        Если цель эффекта не указана явно, эффект применяется
        к текущему подразделению. После обработки экран закрывается.

        Args:
            i (int): Индекс выбранного решения.
        """
        choice = self.choices[i]
        st = self.app.engine.state
        logger.info("Решение выбрано: %s", choice.get("text"))
        if choice.get("rule"):
            RuleEngine.try_decision(
                st,
                self.unit_idx,
                choice["rule"],
                self.app.engine.rng,
            )
            logger.info("Правило решения применено: %s", choice.get("rule"))
        effect = choice.get("effect") or {}
        if effect:
            effect = dict(effect)
            if "targets" not in effect:
                effect["targets"] = [st.entity_ids[self.unit_idx]]
            EffectInterpreter.apply(st, effect)
            logger.info("Эффект решения применён")
        self.app.manager.pop()

    def handle_event(self, event):
        """
        Обрабатывает события pygame для данного экрана.

        Событие последовательно передаётся всем кнопкам решений.
        Если одна из кнопок обработала событие, дальнейшая обработка
        прекращается.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        """
        Отрисовывает экран решений.

        Рисует панель, заголовок «Решения» и кнопки вариантов.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        Panel((140, 400, 1000, 300)).draw(screen)
        sp = self.app.font_body.render("Решения", True, (80, 140, 220))
        screen.blit(sp, (180, 420))
        for b in self.buttons:
            b.draw(screen)