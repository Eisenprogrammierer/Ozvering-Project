"""
view/screens/character_creation.py

Экран создания персонажа.

Отображает последовательность шагов создания персонажа,
описанную в конфигурации сюжета. Каждый шаг содержит текст
и варианты выбора. Выбор может устанавливать переменные
сюжета и применять эффекты к создаваемой сущности.

Поддерживает условное отображение шагов через поле requires
и подстановку вариантов текста через поле variant_by.

При завершении создания записывает пол персонажа в
state.player_gender и выбранную черту в переменную trait
для использования в игровой механике.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль средствами core.log_journal.
"""

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
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
    """
    Экран создания персонажа.

    Последовательно отображает шаги создания из конфигурации.
    Каждый шаг содержит текст и варианты выбора. При выборе
    устанавливаются переменные сюжета и применяются эффекты.

    Поддерживает условное отображение шагов через поле requires
    и подстановку вариантов текста через поле variant_by.

    Attributes:
        steps (list[dict]): Список шагов создания персонажа.
        current_step (int): Индекс текущего видимого шага.
        panel (Panel): Фоновая панель экрана.
        buttons (list[Button]): Кнопки вариантов выбора текущего шага.
    """

    def __init__(self, app, steps):
        """
        Инициализирует экран создания персонажа.

        Создаёт фоновую панель, пропускает невидимые шаги в начало
        и строит кнопки для первого видимого шага.

        Args:
            app: Экземпляр приложения (App).
            steps (list[dict]): Список шагов создания персонажа.
                Каждый шаг — словарь с полями text, choices и
                опциональными requires, variant_by, variants.
        """
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
        """
        Подставляет вариант текста шага по переменной сюжета.

        Если шаг содержит поле variant_by, ищет значение переменной
        в variants и возвращает соответствующий вариант, объединённый
        с исходным шагом. Если переменная не установлена или ключ
        отсутствует, возвращает исходный шаг без изменений.

        Args:
            step (dict): Словарь шага из конфигурации.

        Returns:
            dict: Разрешённый шаг с подставленным текстом.
        """
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
        """
        Проверяет, должен ли шаг быть отображён.

        Шаг отображается, если у него нет поля requires,
        или если все условия requires выполнены.
        Условия requires проверяются через storyline_interpreter.

        Args:
            step (dict): Словарь шага из конфигурации.

        Returns:
            bool: True, если шаг должен быть отображён.
        """
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
        """
        Пропускает невидимые шаги вперёд.

        Вызывается при инициализации и после выбора варианта,
        чтобы текущий шаг всегда был видимым. Если все оставшиеся
        шаги невидимы, current_step устанавливается за пределы
        списка шагов.
        """
        while self.current_step < len(self.steps):
            if self._is_step_visible(self.steps[self.current_step]):
                break
            self.current_step += 1

    def _get_text_lines(self, text):
        """
        Разбивает текст на строки с ограничением по высоте.

        Переносит текст по ширине TEXT_MAX_WIDTH и обрезает до
        максимального числа строк, помещающихся в TEXT_MAX_HEIGHT.
        Если текст обрезается, к последней строке добавляется «...».

        Args:
            text (str): Исходный текст шага.

        Returns:
            list[str]: Список строк, умещающихся в TEXT_MAX_HEIGHT.
        """
        lines = self._wrap_text(text, self.app.font_body, TEXT_MAX_WIDTH)
        max_lines = TEXT_MAX_HEIGHT // LINE_HEIGHT
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            if lines and not lines[-1].endswith("..."):
                last = lines[-1]
                lines[-1] = last[:-3] + "..." if len(last) > 3 else last + "..."
        return lines

    def _build_buttons(self):
        """
        Строит кнопки вариантов выбора для текущего шага.

        Если текущий шаг находится за пределами списка шагов,
        кнопки не создаются. Для каждого варианта выбора создаётся
        кнопка с текстом и callback, вызывающим choose(i).
        """
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
        """
        Обрабатывает выбор варианта на текущем шаге.

        Если указано set_variable, устанавливает переменную сюжета
        через storyline_interpreter. Если указан effect и состояние
        мира содержит сущности, применяет эффект через EffectInterpreter.
        Переходит к следующему видимому шагу или завершает создание.

        Args:
            i (int): Индекс выбранного варианта в списке choices.
        """
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
        """
        Завершает создание персонажа.

        Сохраняет начальное значение U_manpower в состоянии сюжета
        для условия manpower_loss_above. Записывает пол персонажа
        в state.player_gender. Закрывает экран и запускает
        следующую сцену последовательности через app._play_next_scene().

        Если мир пуст, initial_manpower устанавливается в 0.0.
        """
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
        """
        Обрабатывает события pygame для данного экрана.

        Событие последовательно передаётся всем кнопкам вариантов
        выбора текущего шага. Если одна из кнопок обработала событие,
        дальнейшая обработка прекращается.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        for b in self.buttons:
            if b.handle_event(event):
                return

    @staticmethod
    def _wrap_text(text, font, max_w):
        """
        Выполняет перенос текста по заданной максимальной ширине.

        Разбивает текст на слова и собирает строки, не превышающие
        max_w пикселей при отрисовке заданным шрифтом.

        Args:
            text (str): Исходный текст.
            font (pygame.font.Font): Шрифт для измерения ширины.
            max_w (int): Максимальная ширина строки в пикселях.

        Returns:
            list[str]: Список перенесённых строк.
        """
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
        """
        Отрисовывает экран создания персонажа.

        Порядок отрисовки:
        1. Полупрозрачное затемнение всего экрана.
        2. Фоновая панель.
        3. Текст текущего шага с переносом по ширине.
        4. Кнопки вариантов выбора.
        5. Индикатор прогресса (текущий видимый шаг / всего видимых).

        Если все шаги пройдены, отрисовка текста и кнопок пропускается.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        if self.current_step >= len(self.steps):
            return
        step = self._resolve_variant(self.steps[self.current_step])
        text = step.get("text", "")
        y = TEXT_START_Y
        for line in self._get_text_lines(text):
            surf = self.app.font_body.render(line, True, (220, 220, 230))
            screen.blit(surf, (TEXT_X, y))
            y += LINE_HEIGHT
        for b in self.buttons:
            b.draw(screen)
        visible_count = sum(
            1 for s in self.steps if self._is_step_visible(s)
        )
        current_visible = sum(
            1
            for j in range(self.current_step + 1)
            if j < len(self.steps) and self._is_step_visible(self.steps[j])
        )
        progress = f"{current_visible} / {visible_count}"
        prog_surf = self.app.font_small.render(
            progress, True, (150, 150, 160)
        )
        screen.blit(prog_surf, prog_surf.get_rect(center=(640, PROGRESS_Y)))