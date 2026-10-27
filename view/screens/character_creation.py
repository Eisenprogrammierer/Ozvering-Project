import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from ..ui.text_layout import draw_fitted
from view.support.effects import EffectInterpreter
from view.support.log_journal import get_logger

logger = get_logger("view.character_creation")

TEXT_START_Y = 142
TEXT_MAX_HEIGHT = 292
BUTTON_START_Y = 468
BUTTON_SPACING = 48
BUTTON_HEIGHT = 40
BUTTON_WIDTH = 800
BUTTON_X = 240
COLUMN_WIDTH = 390
COLUMN_X = (240, 650)
TEXT_X = 280
TEXT_MAX_WIDTH = 720
LINE_HEIGHT = 30
PROGRESS_Y = 664
INPUT_RECT = pygame.Rect(280, 420, 720, 52)
INPUT_BUTTON_RECT = pygame.Rect(440, 500, 400, 46)


class CharacterCreationScreen(BaseScreen):

    def __init__(self, app, steps):
        super().__init__(app)
        self.steps = steps
        self.current_step = 0
        self.panel = Panel((240, 100, 800, 580))
        self.buttons = []
        self.input_text = ""
        self.input_key = ""
        self.input_focus = False
        self._skip_to_visible_step()
        self._sync_input()
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

    def _input_config(self, step=None):
        if step is None and self.current_step < len(self.steps):
            step = self._resolve_variant(self.steps[self.current_step])
        if not isinstance(step, dict):
            return None
        value = step.get("input")
        if not value:
            return None
        if value is True:
            return {"key": "name", "max_length": 32}
        if isinstance(value, dict):
            return value
        return None

    def _sync_input(self):
        config = self._input_config()
        if not config:
            self.input_key = ""
            self.input_text = ""
            self.input_focus = False
            return
        self.input_key = str(config.get("key", "name"))
        interp = getattr(self.app, "storyline_interpreter", None)
        current = ""
        if interp is not None:
            current = str(interp.get_variable(self.input_key, "") or "")
        if current:
            self.input_text = current
        self.input_focus = True

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
        if self._input_config(step) is not None:
            self.buttons.append(
                Button(
                    INPUT_BUTTON_RECT,
                    "Продолжить",
                    self.app.font_body,
                    self._submit_input,
                )
            )
            return
        choices = step.get("choices", [])
        columns = 2 if len(choices) > 4 else 1
        rows = min(4, (len(choices) + columns - 1) // columns)
        for index, choice in enumerate(choices[: rows * columns]):
            column = index // rows
            row = index % rows
            width = COLUMN_WIDTH if columns == 2 else BUTTON_WIDTH
            x = COLUMN_X[column] if columns == 2 else BUTTON_X
            y = BUTTON_START_Y + row * BUTTON_SPACING
            self.buttons.append(
                Button(
                    (x, y, width, BUTTON_HEIGHT),
                    choice.get("text", "?"),
                    self.app.font_body,
                    lambda i=index: self.choose(i),
                )
            )
        logger.debug(
            "Шаг %d: построено кнопок выбора=%d",
            self.current_step,
            len(self.buttons),
        )

    def _set_choice_variables(self, choice):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return
        set_var = choice.get("set_variable")
        if set_var:
            interp.set_variable(set_var, choice.get("value"))
            logger.info(
                "Переменная сюжета %s = %r",
                set_var,
                choice.get("value"),
            )
        extra = choice.get("set_variables")
        if isinstance(extra, dict):
            for key, value in extra.items():
                interp.set_variable(key, value)

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
        self._set_choice_variables(choice)
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
        self._advance_step()

    def _submit_input(self):
        config = self._input_config()
        if config is None:
            return
        value = self.input_text.strip()
        if not value:
            value = "Новый герой"
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is not None:
            interp.set_variable(str(config.get("key", "name")), value)
        self._advance_step()

    def _advance_step(self):
        self.current_step += 1
        self._skip_to_visible_step()
        if self.current_step >= len(self.steps):
            self._finish()
        else:
            self._sync_input()
            self._build_buttons()

    def _build_profile(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return None
        storyline = interp.storyline or {}
        if not storyline.get("world_path"):
            return None
        from campaign.world import build_player_profile, load_biography

        path = storyline.get("biography_path") or None
        biography = load_biography(path)
        profile = build_player_profile(
            interp.variables,
            biography=biography,
            seed=self.app._campaign_seed(storyline),
        )
        interp.state["player_profile"] = profile
        interp.set_variable("player_character_name", profile["name"])
        interp.set_variable(
            "player_character_summary",
            " · ".join(
                item
                for item in (
                    profile.get("origin"),
                    profile.get("vocation"),
                    profile.get("reputation"),
                )
                if item
            ),
        )
        self.app.player_profile = profile
        if self.app.state is not None:
            self.app.state.needs.commander.name = str(
                profile.get("name") or "Должностное лицо"
            )
            self.app.state.needs.commander.archetype = "world_actor"
        logger.info(
            "Профиль героя собран: %s, навыков=%d, связей=%d",
            profile.get("name"),
            len(profile.get("skills") or {}),
            len(profile.get("connections") or []),
        )
        return profile

    def _finish(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is not None:
            st = self.app.engine.state if self.app.engine is not None else None
            if st is not None and st.count > 0:
                idx = st.player_idx
                if 0 <= idx < st.count:
                    interp.state["initial_manpower"] = st.read_voltage(
                        idx, "U_manpower"
                    )
                else:
                    interp.state["initial_manpower"] = 0.0
            else:
                interp.state["initial_manpower"] = 0.0
            gender = interp.get_variable("gender", "male")
            if st is not None:
                st.player_gender = gender
            trait = interp.get_variable("trait", None)
            logger.info(
                "Создание завершено: gender=%s, trait=%s, "
                "initial_manpower=%.1f",
                gender,
                trait,
                float(interp.state.get("initial_manpower", 0.0)),
            )
            self._build_profile()
        self.app.manager.pop()
        if interp is not None:
            self.app._play_next_scene()

    def handle_event(self, event):
        config = self._input_config()
        if config is not None:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._submit_input()
                    return
                if event.key == pygame.K_BACKSPACE:
                    self.input_text = self.input_text[:-1]
                    return
                if event.key == pygame.K_ESCAPE:
                    return
                if getattr(event, "unicode", ""):
                    char = event.unicode
                    if char.isprintable():
                        limit = int(config.get("max_length", 32))
                        if len(self.input_text) < limit:
                            self.input_text += char
                    return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if INPUT_RECT.collidepoint(event.pos):
                    self.input_focus = True
                    return
        for b in self.buttons:
            if b.handle_event(event):
                return

    @staticmethod
    def _wrap_text(text, font, max_w):
        lines = []
        line = ""
        for w in str(text).split():
            test = (line + " " + w).strip()
            if font.size(test)[0] > max_w:
                lines.append(line)
                line = w
            else:
                line = test
        lines.append(line)
        return lines

    def _draw_input(self, screen, text):
        draw_fitted(
            screen,
            [self.app.font_body, self.app.font_small, self.app.font_tiny],
            text,
            pygame.Rect(TEXT_X, TEXT_START_Y, TEXT_MAX_WIDTH, 250),
            (220, 220, 230),
        )
        pygame.draw.rect(screen, (18, 22, 32), INPUT_RECT, border_radius=6)
        pygame.draw.rect(
            screen,
            (90, 130, 180) if self.input_focus else (60, 74, 96),
            INPUT_RECT,
            2,
            border_radius=6,
        )
        value = self.input_text
        if value:
            surf = self.app.font_body.render(value, True, (235, 238, 245))
            screen.blit(
                surf,
                (
                    INPUT_RECT.x + 12,
                    INPUT_RECT.centery - surf.get_height() // 2,
                ),
            )
        else:
            hint = self.app.font_small.render(
                "Введите имя...", True, (110, 122, 140)
            )
            screen.blit(
                hint,
                (
                    INPUT_RECT.x + 12,
                    INPUT_RECT.centery - hint.get_height() // 2,
                ),
            )
        if self.input_focus and (pygame.time.get_ticks() // 500) % 2 == 0:
            width = min(
                self.app.font_body.size(value)[0],
                INPUT_RECT.width - 28,
            )
            x = INPUT_RECT.x + 12 + width + 2
            pygame.draw.line(
                screen,
                (180, 210, 240),
                (x, INPUT_RECT.y + 12),
                (x, INPUT_RECT.bottom - 12),
                2,
            )

    def draw(self, screen):
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        if self.current_step >= len(self.steps):
            return
        step = self._resolve_variant(self.steps[self.current_step])
        text = step.get("text", "")
        if self._input_config(step) is not None:
            self._draw_input(screen, text)
        else:
            draw_fitted(
                screen,
                [
                    self.app.font_body,
                    self.app.font_small,
                    self.app.font_tiny,
                ],
                text,
                pygame.Rect(
                    TEXT_X, TEXT_START_Y, TEXT_MAX_WIDTH, TEXT_MAX_HEIGHT
                ),
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
