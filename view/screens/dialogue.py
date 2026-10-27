import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from ..ui.text_layout import draw_fitted
from view.support.log_journal import get_logger

logger = get_logger("view.dialogue")


class DialogueScreen(BaseScreen):

    def __init__(self, app, node_id):
        super().__init__(app)
        self.node_id = node_id
        node = app.content.dialogues[node_id]
        self.speaker = node.get("speaker", "")
        self.text = node.get("text", "")
        self.choices = node.get("choices", [{"text": "Продолжить"}])
        self.panel = Panel((140, 360, 1000, 340))
        self.buttons = []
        start_y = 540
        available = self.panel.rect.bottom - 20 - start_y
        step = min(46, max(30, available // max(1, len(self.choices))))
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
            "Диалог открыт: узел=%s, говорящий=%s, вариантов=%d",
            node_id,
            self.speaker or "-",
            len(self.choices),
        )

    def choose(self, i):
        choice = self.choices[i]
        from view.support.effects import EffectInterpreter

        EffectInterpreter.apply(
            self.app.engine.state, choice.get("effect", {})
        )
        next_id = choice.get("next")
        logger.info(
            "Диалог %s: выбран вариант %d (%s), переход=%s",
            self.node_id,
            i,
            choice.get("text", ""),
            next_id or "закрытие",
        )
        if next_id:
            self.app.manager.push(DialogueScreen(self.app, next_id))
        else:
            self.app.manager.pop()
        self.app.execute_player_action("dialogue_choice")

    def handle_event(self, event):
        for b in self.buttons:
            if b.handle_event(event):
                return

    def _wrap(self, text, font, max_w):
        lines, line = [], ""
        for w in text.split():
            test = (line + " " + w).strip()
            if font.size(test)[0] > max_w:
                lines.append(line)
                line = w
            else:
                line = test
        lines.append(line)
        return lines

    def draw(self, screen):
        self.panel.draw(screen)
        sp = self.app.font_body.render(self.speaker, True, (80, 140, 220))
        screen.blit(sp, (180, 382))
        draw_fitted(
            screen,
            [self.app.font_body, self.app.font_small, self.app.font_tiny],
            self.text,
            pygame.Rect(180, 416, 920, 104),
            (220, 220, 230),
        )
        for b in self.buttons:
            b.draw(screen)
