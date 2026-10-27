import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from ..ui.asset_loader import AssetLoader
from view.support.rules import RuleEngine
from view.support.effects import EffectInterpreter
from view.support.log_journal import get_logger

logger = get_logger("view.aftermath")


class AftermathScreen(BaseScreen):

    def __init__(self, app, unit_idx):
        super().__init__(app)
        self.unit_idx = unit_idx
        st = app.engine.state
        cond = st.read_segment(unit_idx, "condition")
        asset = "scenes/camp_fresh" if cond >= 2 else "scenes/camp_beaten"
        self.bg = AssetLoader.load(asset, (1280, 720))
        self.buttons = [
            Button(
                (480, 560, 320, 45),
                "Диалоги",
                app.font_body,
                self.open_dialogues,
            ),
            Button(
                (480, 615, 320, 45),
                "Решения",
                app.font_body,
                self.open_decisions,
            ),
        ]
        logger.info(
            "Экран последствий открыт: unit_idx=%s condition=%s asset=%s",
            unit_idx,
            cond,
            asset,
        )

    def open_dialogues(self):
        from .dialogue import DialogueScreen

        logger.info("Последствия: открытие диалога aftermath_lt_orlov")
        self.app.manager.push(DialogueScreen(self.app, "aftermath_lt_orlov"))

    def open_decisions(self):
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
            AftermathDecisionScreen(
                self.app, "_aftermath_decisions", self.unit_idx
            )
        )

    def handle_event(self, event):
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        screen.blit(self.bg, (0, 0))
        for b in self.buttons:
            b.draw(screen)


class AftermathDecisionScreen(BaseScreen):

    def __init__(self, app, node_id, unit_idx):
        super().__init__(app)
        self.unit_idx = unit_idx
        node = app.content.dialogues[node_id]
        self.choices = node.get("choices", [])
        self.panel = Panel((140, 330, 1000, 370))
        self.buttons = []
        start_y = 400
        available = self.panel.rect.bottom - 24 - start_y
        step = min(46, max(28, available // max(1, len(self.choices))))
        height = min(42, step - 4)
        y = start_y
        for i, c in enumerate(self.choices):
            self.buttons.append(
                Button(
                    (200, y, 880, height),
                    c["text"],
                    app.font_small,
                    lambda i=i: self.choose(i),
                )
            )
            y += step
        logger.info(
            "Экран решений открыт: node=%s unit_idx=%s решений=%s",
            node_id,
            unit_idx,
            len(self.choices),
        )

    def choose(self, i):
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
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        self.panel.draw(screen)
        sp = self.app.font_body.render("Решения", True, (80, 140, 220))
        screen.blit(sp, (180, 350))
        for b in self.buttons:
            b.draw(screen)
