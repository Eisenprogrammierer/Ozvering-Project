"""Быстрая кампания из главного меню (ось B, срез «единый путь запуска»).

`CampaignQuickScreen` — минимальный играбельный цикл поверх `CampaignEnv`:
тот же `WorldEngine`, что и в полном потоке новой игры (`view/app.py::
_start_world_storyline`), но без выбора роли/фракции/сюжетной линии.
Среда обучения и игра используют один мир: действия идут через контракт
`CampaignEnv.step()`, поэтому UI-ход и учебный ход не расходятся.

Экран рисует состояние героя и организации по `CampaignObservation`,
список легальных действий из `legal_actions()` (метки берёт у движка) и
журнал последних событий мира. Служебные действия среды (`END_DAY`,
`TREAT_SELF`, `TREAT_WOUND`) показываются как обычные кнопки.
"""

import pygame

from campaign.env import END_DAY, TREAT_SELF, TREAT_WOUND
from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.campaign_quick")

MAX_LOG_LINES = 6


def _service_label(kind):
    return {
        END_DAY: "Завершить день",
        TREAT_SELF: "Лечить болезнь",
        TREAT_WOUND: "Лечить рану",
    }.get(kind)


class CampaignQuickScreen(BaseScreen):

    escape_action = "pop"

    def __init__(self, app, seed=None):
        super().__init__(app)
        from campaign.env import CampaignEnv

        self.panel = Panel((40, 40, 1200, 640))
        if seed is None:
            seed = getattr(app, "campaign_seed_value", None)
        self.env = CampaignEnv(seed=int(seed) if seed is not None else 7)
        self.observation = self.env.reset()
        self.message = ""
        self._rebuild_buttons()
        logger.info(
            "Быстрая кампания начата: seed=%s, действий=%d",
            self.env.engine.seed,
            len(self.env.legal_actions()),
        )

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    def _action_label(self, action):
        engine = self.env.engine
        label = _service_label(action.kind)
        if label is None:
            label = str(engine.actions.get(action.kind, {}).get("label") or action.kind)
        if action.target:
            label = "%s → %s" % (label, engine.node_label(action.target))
        return label

    def _rebuild_buttons(self):
        buttons = []
        y = 150
        for action in self.env.legal_actions():
            if y > 560:
                break
            buttons.append(
                Button(
                    (60, y, 560, 38),
                    self._action_label(action),
                    self.app.font_small,
                    lambda a=action: self._do(a),
                )
            )
            y += 42
        buttons.append(
            Button((60, 600, 200, 40), "В меню", self.app.font_body, self.app.manager.pop)
        )
        self.buttons = buttons

    def _do(self, action):
        obs, reward, done, truncated, info = self.env.step(action)
        self.observation = obs
        result = info.get("result") or {}
        outcome = str(result.get("outcome") or "")
        self.message = "награда %+.2f · %s" % (reward, outcome or result.get("reason") or "")
        if done or truncated:
            final = obs.outcome or ("горизонт" if truncated else "нейтрально")
            self.message = "Кампания завершена: %s (%s)" % (final, self.message)
            logger.info("Быстрая кампания завершена: %s", final)
        self._rebuild_buttons()

    # ------------------------------------------------------------------
    # Ввод / отрисовка
    # ------------------------------------------------------------------

    def handle_event(self, event):
        if self.env.engine is not None and (
            self.env.engine.finished or self.env._terminal
        ):
            # После финала остаётся только выход в меню.
            self.buttons = self.buttons[-1:]
        for button in self.buttons:
            if button.handle_event(event):
                return

    def _status_lines(self):
        obs = self.observation
        engine = self.env.engine
        lines = [
            "День %d/%d · действий осталось: %d · энергия %.0f%%"
            % (obs.day, obs.total_days, obs.actions_left, 100.0 * obs.energy),
            "Здоровье %.0f%% · болезнь %.0f%% · рана %.0f%%"
            % (obs.health, 100.0 * obs.sickness, 100.0 * obs.wound),
            "Положение %.0f%% · сила узла %.0f%% · связность %.0f%%"
            % (100.0 * obs.standing, 100.0 * obs.power, 100.0 * obs.cohesion),
        ]
        office = engine.player_office()
        if office and office.get("id"):
            lines.insert(
                1,
                "%s · %s" % (office["node_name"], office["title"]),
            )
        return lines

    def _log_lines(self):
        rows = list(self.env.engine.log)[-MAX_LOG_LINES:]
        lines = []
        for row in rows:
            text = str(row.get("text", ""))
            if len(text) > 78:
                text = text[:77] + "…"
            lines.append("д.%s %s" % (row.get("day", "?"), text))
        return lines

    def draw(self, screen):
        screen.fill((18, 20, 28))
        self.panel.draw(screen)
        title = self.app.font_title.render("Быстрая кампания", True, (220, 220, 230))
        screen.blit(title, title.get_rect(center=(640, 70)))
        y = 96
        for line in self._status_lines():
            surf = self.app.font_small.render(line, True, (180, 190, 205))
            screen.blit(surf, (60, y))
            y += 18
        if self.message:
            surf = self.app.font_small.render(self.message, True, (210, 200, 150))
            screen.blit(surf, (60, y + 4))
        for button in self.buttons:
            button.draw(screen)
        header = self.app.font_small.render("Хроника:", True, (160, 160, 170))
        screen.blit(header, (660, 150))
        y = 172
        for line in self._log_lines():
            surf = self.app.font_tiny.render(line, True, (150, 150, 160))
            screen.blit(surf, (660, y))
            y += 16
