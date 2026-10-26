"""
view/screens/mandatory_screen.py

Экран обязательной сцены (утренний/вечерний осмотр).

Фоновые ассеты и тексты берутся из configs/content/mandatory_scenes.json;
при отсутствии файла или отдельных ключей используются встроенные
фолбэки. Утренний осмотр выбирает фон по калькуляции потерь дивизии
относительно порога поражения из сюжета: до 40% лимита — camp_fresh,
до 80% — camp_wounded, дальше — camp_critical. Поэтому все три варианта
остаются достижимыми и при лимите 20%, и при 25%, и при 45%. Вечерний
осмотр использует фон hq_evening с более сильным затемнением. Текст и
кнопки выводятся в полупрозрачной панели внизу экрана, чтобы игрок видел
лагерь и его детали; затемнение фона минимальное.

ESC игнорируется (escape_action = "none").
При открытии создаётся автосейв в слот autosave.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль.
"""

import pygame

from view.support.camp_state import camp_state_for_loss
from view.support.config_loader import load_json
from view.support.log_journal import get_logger
from view.support.storyline import loss_limit_percent
from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button
from ..ui.asset_loader import AssetLoader
from ..ui.text_layout import draw_fitted

logger = get_logger("view.mandatory_screen")

PANEL_RECT = pygame.Rect(100, 470, 1080, 220)
TEXT_RECT = pygame.Rect(130, 528, 1020, 96)
TITLE_POS = (130, 486)
BUTTON_Y = 634
DIM_ALPHA = 70

DEFAULT_SCENES = {
    "morning_inspection": {
        "title": "Утренний осмотр лагеря",
        "backgrounds": {
            "fresh": "scenes/camp_fresh",
            "wounded": "scenes/camp_wounded",
            "critical": "scenes/camp_critical",
        },
        "texts": {
            "fresh": (
                "Вы обходите позиции. Проверяете посты, склады "
                "боеприпасов, связь. Приказы на день уже на столе. "
                "Солдаты занимают места по расписанию. "
                "Потери дивизии: {losses}."
            ),
            "wounded": (
                "Вы обходите позиции. Санчасти переполнены, подбитая "
                "техника стоит в отстойнике. Подразделения обескровлены, "
                "но продолжают держаться. Потери дивизии: {losses}."
            ),
            "critical": (
                "Вы обходите позиции. Лагерь в тяжёлом состоянии: "
                "большие потери, выбитая техника, люди на пределе. "
                "Нужны пополнение и передышка. Потери дивизии: {losses}."
            ),
        },
    },
    "evening_inspection": {
        "title": "Вечерний осмотр лагеря",
        "background": "scenes/hq_evening",
        "text": (
            "День подходит к концу. Вы обходите позиции, проверяете "
            "раненых, уточняете потери. Нужно решить: ночное дежурство "
            "или сон. Потери дивизии: {losses}."
        ),
    },
}


def _load_scenes() -> dict:
    """
    Загружает данные обязательных сцен из конфига.

    Читает configs/content/mandatory_scenes.json. При отсутствии
    файла, ошибке парсинга или неверном типе возвращает пустой
    словарь, и экран работает на встроенных фолбэках.

    Returns:
        dict: Данные сцен по идентификаторам.
    """
    data = load_json("configs/content/mandatory_scenes.json", {}) or {}
    return data if isinstance(data, dict) else {}


class MandatorySceneScreen(BaseScreen):
    """
    Экран обязательной сцены.

    Блокирует действия игрока до завершения сцены. ESC не закрывает
    экран (escape_action = "none"), клики вне кнопок игнорируются.
    Фон и текст зависят от конфига и калькуляции потерь дивизии.

    Attributes:
        scene_id (str): Идентификатор сцены.
        title (str): Заголовок сцены.
        text (str): Текст сцены с подставленными потерями.
        bg (pygame.Surface): Фоновая сцена лагеря.
        camp_state (str | None): Состояние лагеря (fresh/wounded/
            critical) для утренней сцены.
        loss_percent (int): Округлённые потери дивизии в процентах.
        btn_continue (Button | None): Кнопка «Продолжить».
        btn_night_duty (Button | None): Кнопка «Ночное дежурство».
        btn_sleep (Button | None): Кнопка «Спать».
        forced_sleep (bool): Флаг принудительного сна.
    """

    escape_action = "none"

    def __init__(self, app, scene_id):
        """
        Инициализирует экран обязательной сцены.

        Сливает данные конфига с фолбэками, вычисляет потери дивизии,
        выбирает фон и текст, создаёт кнопки и автосейв.

        Args:
            app: Экземпляр приложения (App).
            scene_id (str): Идентификатор сцены
                ("morning_inspection" или "evening_inspection").
        """
        super().__init__(app)
        self.scene_id = scene_id
        cfg = _load_scenes().get(scene_id, {}) or {}
        default = DEFAULT_SCENES.get(
            scene_id, {"title": scene_id, "text": ""}
        )
        self.title = cfg.get("title") or default.get("title", scene_id)
        self.loss_percent = self._player_loss_percent()
        self.loss_limit_percent = self._loss_limit_percent()
        losses_str = f"{self.loss_percent}%"
        self.camp_state = None
        if scene_id == "morning_inspection":
            self.camp_state = camp_state_for_loss(
                self.loss_percent, self.loss_limit_percent
            )
            backgrounds = dict(default.get("backgrounds", {}))
            backgrounds.update(cfg.get("backgrounds", {}) or {})
            texts = dict(default.get("texts", {}))
            texts.update(cfg.get("texts", {}) or {})
            bg_asset = backgrounds.get(self.camp_state, "scenes/camp_fresh")
            self.text = texts.get(self.camp_state, "").replace(
                "{losses}", losses_str
            )
        else:
            bg_asset = cfg.get("background") or default.get(
                "background", "scenes/camp_wounded"
            )
            self.text = (cfg.get("text") or default.get("text", "")).replace(
                "{losses}", losses_str
            )
        self.bg = AssetLoader.load(bg_asset, (1280, 720))
        ts = getattr(app, "time_system", None)
        self.forced_sleep = bool(
            ts is not None
            and (
                getattr(ts, "forced_sleep", False)
                or getattr(ts, "sleep_debt_nights", 0) >= 3
            )
        )
        self.btn_continue = None
        self.btn_night_duty = None
        self.btn_sleep = None
        if scene_id == "evening_inspection":
            if not self.forced_sleep:
                self.btn_night_duty = Button(
                    (300, BUTTON_Y, 320, 44),
                    "Ночное дежурство",
                    app.font_body,
                    self.choose_night_duty,
                )
                self.btn_sleep = Button(
                    (720, BUTTON_Y, 240, 44),
                    "Спать",
                    app.font_body,
                    self.choose_sleep,
                )
            else:
                self.btn_sleep = Button(
                    (520, BUTTON_Y, 240, 44),
                    "Спать",
                    app.font_body,
                    self.choose_sleep,
                )
        else:
            self.btn_continue = Button(
                (520, BUTTON_Y, 240, 44),
                "Продолжить",
                app.font_body,
                self.finish_scene,
            )
        self._autosave()
        logger.info(
            "Открыта обязательная сцена: %s, фон=%s, потери=%d%% "
            "(лимит %d%%), принудительный сон=%s",
            scene_id,
            bg_asset,
            self.loss_percent,
            self.loss_limit_percent,
            self.forced_sleep,
        )

    def _player_loss_percent(self):
        """Потери дивизии игрока в процентах.

        Использует накопленный счётчик ``Detachment.losses``: текущая сила
        может колебаться в бою, поэтому она не годится для отчёта о
        безвозвратных потерях.
        """
        st = self.app.engine.state
        if hasattr(st, "division_loss_percent"):
            return int(round(float(st.division_loss_percent())))
        p = st.player_idx
        return int(round(100.0 * float(st.read_voltage(p, "U_casualties"))))

    def _loss_limit_percent(self):
        """Порог поражения дивизии в процентах из сюжетного конфига."""
        interp = getattr(self.app, "storyline_interpreter", None)
        storyline = getattr(interp, "storyline", {}) if interp else {}
        return loss_limit_percent(storyline)

    def _autosave(self):
        """
        Создаёт автосейв в слот autosave.

        Исключения подавляются, чтобы не прерывать показ сцены.
        """
        try:
            self.app.save_game("autosave")
            logger.info("Автосейв записан в слот autosave")
        except Exception as exc:
            logger.warning("Автосейв не выполнен: %s", exc)

    def finish_scene(self):
        """
        Завершает сцену без дополнительных действий.

        Уведомляет time_system о завершении сцены и закрывает экран.
        """
        ts = getattr(self.app, "time_system", None)
        if ts is not None:
            ts.complete_mandatory_scene(self.scene_id)
        logger.info("Сцена завершена: %s", self.scene_id)
        self.app.manager.pop()

    def choose_night_duty(self):
        """
        Обрабатывает выбор ночного дежурства.

        Завершает сцену, передаёт выбор в time_system и закрывает экран.
        """
        ts = getattr(self.app, "time_system", None)
        if ts is not None:
            ts.complete_mandatory_scene(self.scene_id)
            ts.choose_night_duty(True)
        logger.info("Выбрано ночное дежурство (сцена %s)", self.scene_id)
        self.app.manager.pop()

    def choose_sleep(self):
        """
        Обрабатывает выбор сна.

        Завершает сцену, передаёт отказ от дежурства в time_system
        и закрывает экран.
        """
        ts = getattr(self.app, "time_system", None)
        if ts is not None:
            ts.complete_mandatory_scene(self.scene_id)
            ts.choose_night_duty(False)
        logger.info("Выбран сон (сцена %s)", self.scene_id)
        self.app.manager.pop()

    @staticmethod
    def _wrap_text(text, font, max_width):
        """
        Переносит текст по ширине.

        Args:
            text (str): Исходный текст.
            font (pygame.font.Font): Шрифт для измерения ширины.
            max_width (int): Максимальная ширина строки в пикселях.

        Returns:
            list[str]: Список строк.
        """
        lines, line = [], ""
        for w in text.split():
            test = (line + " " + w).strip()
            if font.size(test)[0] > max_width:
                lines.append(line)
                line = w
            else:
                line = test
        lines.append(line)
        return lines

    def handle_event(self, event):
        """
        Обрабатывает события pygame для данного экрана.

        События передаются только кнопкам сцены; клики вне кнопок
        игнорируются, ESC не закрывает экран.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.btn_continue is not None:
            if self.btn_continue.handle_event(event):
                return
        if self.btn_night_duty is not None:
            if self.btn_night_duty.handle_event(event):
                return
        if self.btn_sleep is not None:
            if self.btn_sleep.handle_event(event):
                return

    def draw(self, screen):
        """
        Отрисовывает экран обязательной сцены.

        Порядок: фоновая сцена лагеря, лёгкое затемнение,
        полупрозрачная панель внизу, заголовок, текст сцены с
        переносом по ширине, кнопки управления.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        screen.blit(self.bg, (0, 0))
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim_alpha = 110 if self.scene_id == "evening_inspection" else DIM_ALPHA
        dim.fill((0, 0, 0, dim_alpha))
        screen.blit(dim, (0, 0))
        panel = pygame.Surface((PANEL_RECT.width, PANEL_RECT.height), pygame.SRCALPHA)
        panel.fill((10, 10, 20, 185))
        screen.blit(panel, PANEL_RECT.topleft)
        pygame.draw.rect(screen, (90, 90, 120), PANEL_RECT, 2, border_radius=8)
        title_surf = self.app.font_body.render(self.title, True, (220, 200, 140))
        screen.blit(title_surf, TITLE_POS)
        draw_fitted(
            screen,
            [self.app.font_small, self.app.font_tiny],
            self.text,
            TEXT_RECT,
            (210, 210, 220),
        )
        if self.btn_continue is not None:
            self.btn_continue.draw(screen)
        if self.btn_night_duty is not None:
            self.btn_night_duty.draw(screen)
        if self.btn_sleep is not None:
            self.btn_sleep.draw(screen)