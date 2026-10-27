import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from ..ui.text_layout import draw_fitted
from view.support.effects import EffectInterpreter
from view.support.log_journal import get_logger

logger = get_logger("view.character_creation")

TEXT_START_Y = 150
TEXT_MAX_HEIGHT = 320
BUTTON_START_Y = 500
BUTTON_SPACING = 55
BUTTON_HEIGHT = 45
BUTTON_WIDTH = 800
BUTTON_X = 240
TEXT_X = 280
TEXT_MAX_WIDTH = 720
LINE_HEIGHT = 30
PROGRESS_Y = 660


class CharacterCreationScreen(BaseScreen):

    def __init__(self, app, steps):
        super().__init__(app)
        self.steps = steps
        self.current_step = 0
        self.panel = Panel((240, 100, 800, 580))
        self.buttons = []
        self._skip_to_visible_step()
        self._build_buttons()
        logger.info(
            "Экран создания персонажа инициализирован: шагов=%d",
            len(self.steps),
        )

    def _resolve_variant(self, step):
        variant_by = step.get("variant_by")
        if variant_by is None:
            return step
        variants = step.get("variants", {})
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return step
        value = interp.get_variable(variant_by)
        if value is not None and value in variants:
            resolved = variants[value]
            if isinstance(resolved, dict):
                merged = dict(step)
                merged.update(resolved)
                return merged
        return step

    def _is_step_visible(self, step):
        requires = step.get("requires")
        if not requires:
            return True
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return True
        for key, value in requires.items():
            if interp.get_variable(key) != value:
                return False
        return True

    def _skip_to_visible_step(self):
        while self.current_step < len(self.steps):
            if self._is_step_visible(self.steps[self.current_step]):
                break
            self.current_step += 1

    def _get_text_lines(self, text):
        lines = self._wrap_text(text, self.app.font_body, TEXT_MAX_WIDTH)
        max_lines = TEXT_MAX_HEIGHT // LINE_HEIGHT
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            if lines and not lines[-1].endswith("..."):
                last = lines[-1]
                lines[-1] = (
                    last[:-3] + "..." if len(last) > 3 else last + "..."
                )
        return lines

    def _build_buttons(self):
        self.buttons = []
        self._skip_to_visible_step()
        if self.current_step >= len(self.steps):
            return
        step = self._resolve_variant(self.steps[self.current_step])
        choices = step.get("choices", [])
        y = BUTTON_START_Y
        for i, choice in enumerate(choices):
            self.buttons.append(
                Button(
                    (BUTTON_X, y, BUTTON_WIDTH, BUTTON_HEIGHT),
                    choice.get("text", "?"),
                    self.app.font_body,
                    lambda i=i: self.choose(i),
                )
            )
            y += BUTTON_SPACING
        logger.debug(
            "Шаг %d: построено кнопок выбора=%d",
            self.current_step,
            len(self.buttons),
        )

    def choose(self, i):
        step = self._resolve_variant(self.steps[self.current_step])
        choices = step.get("choices", [])
        if i >= len(choices):
            return
        choice = choices[i]
        logger.info(
            "Шаг %d: выбран вариант %d (%s)",
            self.current_step,
            i,
            choice.get("text", "?"),
        )
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is not None:
            set_var = choice.get("set_variable")
            if set_var:
                interp.set_variable(set_var, choice.get("value"))
                logger.info(
                    "Переменная сюжета %s = %r",
                    set_var,
                    choice.get("value"),
                )
            effect = choice.get("effect")
            if effect and self.app.engine is not None:
                if self.app.engine.state.count == 0:
                    logger.warning(
                        "Пропуск эффекта: состояние мира пусто (0 сущностей). "
                        "Проверьте наличие и корректность файла сценария "
                        "(например, scenarios/mvp.json) "
                        "и наличие в нём секции 'placements'."
                    )
                else:
                    EffectInterpreter.apply(self.app.engine.state, effect)
                    logger.debug(
                        "Шаг %d: применён эффект выбора", self.current_step
                    )
        self.current_step += 1
        self._skip_to_visible_step()
        if self.current_step >= len(self.steps):
            self._finish()
        else:
            self._build_buttons()

    def _finish(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is not None:
            st = self.app.engine.state
            idx = st.player_idx
            if st.count > 0 and 0 <= idx < st.count:
                interp.state["initial_manpower"] = st.read_voltage(
                    idx, "U_manpower"
                )
            else:
                interp.state["initial_manpower"] = 0.0
                logger.warning(
                    "Создание персонажа: мир пуст (count=%d), player_idx=%d. "
                    "initial_manpower установлен в 0.0. "
                    "Проверьте файл сценария.",
                    st.count,
                    idx,
                )
            gender = interp.get_variable("gender", "male")
            st.player_gender = gender
            trait = interp.get_variable("trait", None)
            logger.info(
                "Создание завершено: gender=%s, trait=%s, "
                "initial_manpower=%.1f",
                gender,
                trait,
                interp.state["initial_manpower"],
            )
        self.app.manager.pop()
        if interp is not None:
            self.app._play_next_scene()

    def handle_event(self, event):
        for b in self.buttons:
            if b.handle_event(event):
                return

    @staticmethod
    def _wrap_text(text, font, max_w):
        lines = []
        line = ""
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
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        if self.current_step >= len(self.steps):
            return
        step = self._resolve_variant(self.steps[self.current_step])
        text = step.get("text", "")
        draw_fitted(
            screen,
            [self.app.font_body, self.app.font_small, self.app.font_tiny],
            text,
            pygame.Rect(TEXT_X, TEXT_START_Y, TEXT_MAX_WIDTH, TEXT_MAX_HEIGHT),
            (220, 220, 230),
        )
        for b in self.buttons:
            b.draw(screen)
        visible_count = sum(1 for s in self.steps if self._is_step_visible(s))
        current_visible = sum(
            1
            for j in range(self.current_step + 1)
            if j < len(self.steps) and self._is_step_visible(self.steps[j])
        )
        progress = f"{current_visible} / {visible_count}"
        prog_surf = self.app.font_small.render(progress, True, (150, 150, 160))
        screen.blit(prog_surf, prog_surf.get_rect(center=(640, PROGRESS_Y)))
