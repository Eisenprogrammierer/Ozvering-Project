"""
view/app.py
Главное окно приложения.
Инициализирует pygame, загружает контент, строит мир, запускает движок
и управляет стеком экранов. Передаёт ссылку на себя в time_system
и logistics для доступа к модификаторам черт персонажа.
При запуске новой игры открывает экран выбора сюжета; после создания
персонажа интерпретатор ведёт игрока по последовательности сцен.
Исход сюжета (победа/поражение) отложен: флаг ставится при пересечении
вечерней границы дня, а финальная сцена показывается в главном цикле
через process_pending_storyline_outcome(), чтобы не переключать экраны
изнутри раскрутки времени.
Слайды визуальных новелл (интро, победная и проигрышная сцены)
поддерживают варианты по переменным сюжета на уровне отдельного
слайда через variant_by/variants.
HUD игрового времени отрисовывается только когда в стеке экранов
присутствует экран с show_time_hud == True (HQSceneScreen); в меню,
сюжетах и новеллах HUD скрыт.
События инициализации, загрузки, сохранения и переходов между экранами
записываются в журнал operation_ozverin.log в корне проекта и
дублируются в консоль.
"""
import os
import sys
import logging
import pygame

SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60
BG_COLOR = (15, 15, 25)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.normpath(
    os.path.join(BASE_DIR, "..", "operation_ozverin.log")
)


def _build_logger(name):
    """
    Создаёт и возвращает журнал с файловым и консольным обработчиками.
    Файловый обработчик пишет в operation_ozverin.log в корне проекта
    с уровнем DEBUG, консольный выводит сообщения уровня INFO и выше.
    Обработчики создаются один раз для каждого имени журнала.
    Args:
        name (str): Имя журнала.
    Returns:
        logging.Logger: Настроенный журнал.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.propagate = False
    return logger


logger = _build_logger("view.app")


def _find_first_valid_ttf():
    """
    Ищет первый валидный TTF-шрифт в директории assets/fonts.
    Перебирает файлы с расширением .ttf в алфавитном порядке и
    возвращает путь к первому, который успешно загружается и
    рендерит тестовую строку. Если директория отсутствует или
    валидных шрифтов нет, возвращает None.
    Returns:
        str | None: Абсолютный путь к валидному TTF-шрифту или None.
    """
    fonts_dir = os.path.normpath(
        os.path.join(BASE_DIR, "..", "assets", "fonts")
    )
    if not os.path.isdir(fonts_dir):
        return None
    for filename in sorted(os.listdir(fonts_dir)):
        if filename.lower().endswith(".ttf"):
            path = os.path.join(fonts_dir, filename)
            try:
                font = pygame.font.Font(path, 12)
                if font.render("Test", True, (255, 255, 255)) is not None:
                    return path
            except Exception:
                continue
    return None


# Шрифт ищется до создания App, поэтому подсистему шрифтов нужно поднять явно.
pygame.font.init()
FONT_PATH = _find_first_valid_ttf()


def load_font(size):
    """
    Загружает шрифт заданного размера с фолбэком на встроенный.
    Использует первый валидный TTF, найденный в assets/fonts.
    При ошибке загрузки или отсутствии шрифта возвращает
    встроенный шрифт pygame.
    Args:
        size (int): Размер шрифта в пикселях.
    Returns:
        pygame.font.Font: Загруженный или встроенный шрифт.
    """
    if FONT_PATH:
        try:
            return pygame.font.Font(FONT_PATH, size)
        except Exception:
            pass
    logger.warning("Шрифт не найден или не работает, использую встроенный")
    return pygame.font.Font(None, size)


class App:
    """
    Главное приложение игры.
    Управляет инициализацией pygame, загрузкой контента, построением
    мира, запуском движка и стеком экранов. Передаёт ссылку на себя
    в time_system и logistics для доступа к модификаторам черт.
    Attributes:
        screen (pygame.Surface): Поверхность экрана.
        clock (pygame.time.Clock): Часы для ограничения FPS.
        font_title (pygame.font.Font): Шрифт заголовков.
        font_body (pygame.font.Font): Основной шрифт.
        font_small (pygame.font.Font): Мелкий шрифт.
        font_tiny (pygame.font.Font): Очень мелкий шрифт.
        running (bool): Флаг работы главного цикла.
        scenario_path (str): Путь к текущему сценарию.
        storyline_interpreter (StorylineInterpreter | None): Интерпретатор сюжета.
        pending_storyline_outcome (str | None): Отложенный исход сюжета.
        music (MusicManager): Менеджер фоновой музыки.
        content (Content): Загруженный контент интерфейса.
        engine (TickEngine): Игровой движок.
        player_idx (int): Индекс сущности игрока.
        time_system (GameTimeSystem): Система игрового времени.
        time_hud (TimeHUD): HUD игрового времени.
        manager (ScreenManager): Менеджер стека экранов.
    """

    def __init__(self):
        """
        Инициализирует приложение, pygame, загружает контент и строит мир.
        Создаёт окно, загружает шрифты, контент, строит начальное
        состояние мира, инициализирует движок, систему времени,
        менеджер музыки и стек экранов. Начальный экран — главное меню.
        """
        pygame.init()
        pygame.display.set_caption("Operation Ozverin — MVP")
        self.fullscreen = False
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.font_title = load_font(32)
        self.font_body = load_font(20)
        self.font_small = load_font(15)
        self.font_tiny = load_font(11)
        self.running = True
        self.scenario_path = "scenarios/mvp.json"
        self.storyline_interpreter = None
        self.pending_storyline_outcome = None
        from .ui.music_manager import MusicManager
        self.music = MusicManager(
            os.path.normpath(os.path.join(BASE_DIR, "..", "music"))
        )
        from view.support.content import Content
        from view.support.scenario import build_world
        from view.support.world import CampaignEngine
        from view.support.time_system import CampaignTimeSystem
        self.content = Content()
        state = build_world(content=self.content)
        self.state = state
        self.engine = CampaignEngine(state)
        self.engine.engagements = getattr(state, "engagements", [])
        self.player_idx = state.player_idx
        self.time_system = CampaignTimeSystem(state, engine=self.engine,
                                              app=self)
        self.engine.time_system = self.time_system
        from .ui.time_hud import TimeHUD
        self.time_hud = TimeHUD(self)
        from .ui.screen_manager import ScreenManager
        from .screens.main_menu import MainMenuScreen
        self.manager = ScreenManager()
        self.manager.replace_all(MainMenuScreen(self))
        self.music.request_category("overture")
        logger.info("Приложение инициализировано")

    def check_storyline_end_of_day(self):
        """
        Ежедневная проверка исходов сюжета. Idempotent.
        Вызывается из GameTimeSystem при пересечении вечерней границы.
        Ставит флаг pending_storyline_outcome, но не переключает экраны;
        финальная сцена показывается в главном цикле через
        process_pending_storyline_outcome().
        """
        if self.storyline_interpreter is None:
            return
        if getattr(self.storyline_interpreter, "finished", False):
            return
        lose = False
        win = False
        if hasattr(self.storyline_interpreter, "check_lose_conditions"):
            lose = self.storyline_interpreter.check_lose_conditions()
        if hasattr(self.storyline_interpreter, "check_win_conditions"):
            win = self.storyline_interpreter.check_win_conditions()
        if lose:
            self.pending_storyline_outcome = "lose"
            self.storyline_interpreter.finished = True
        elif win:
            self.pending_storyline_outcome = "win"
            self.storyline_interpreter.finished = True

    def apply_to_player(self, channel, delta):
        """
        Применяет дельту к каналу напряжения игрока.
        Args:
            channel (str): Имя канала напряжения.
            delta (float): Изменение значения канала.
        """
        if self.engine:
            self.engine.state.add_voltage(self.player_idx, channel, delta)

    def toggle_fullscreen(self):
        """Переключает полноэкранный режим."""
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.screen = pygame.display.set_mode(
                (SCREEN_WIDTH, SCREEN_HEIGHT),
                pygame.FULLSCREEN | pygame.SCALED,
            )
        else:
            self.screen = pygame.display.set_mode(
                (SCREEN_WIDTH, SCREEN_HEIGHT)
            )
        logger.info("Полноэкранный режим: %s", self.fullscreen)

    def advance_turn(self):
        """Выполняет один тик движка (старый режим)."""
        if not self.engine:
            return
        self.engine.tick()
        st = self.engine.state
        if 0 <= st.player_idx < st.count:
            st.log_event(
                st.player_idx, f"Ход {self.engine.tick_count} обработан"
            )
        logger.info("Выполнен тик: %d", self.engine.tick_count)

    def open_turn_log(self):
        """Открывает оверлей лога последнего тика."""
        from .ui.overlays import TurnLogOverlay
        self.manager.push(TurnLogOverlay(self))
        logger.debug("Открыт оверлей лога тика")

    def execute_player_action(self, action_id, on_completed=None):
        """
        Выполняет действие игрока через time_system.
        Обрабатывает прерывания, обязательные сцены и завершение.
        При статусе completed вызывает on_completed callback.
        Args:
            action_id (str): ID действия из time_actions.json.
            on_completed (callable | None): Callback при завершении.
        """
        if self.time_system is None:
            return
        result = self.time_system.execute_action(action_id)
        status = result.get("status")
        logger.info("Действие игрока: %s, статус: %s", action_id, status)
        if status == "interrupted":
            interrupt = result.get("interrupt")
            if interrupt is not None:
                from .screens.interrupt_modal import InterruptModal
                self.manager.push(InterruptModal(self, interrupt))
        elif status == "mandatory_scene":
            scene_id = result.get("mandatory_scene")
            if scene_id is not None:
                from .screens.mandatory_screen import MandatorySceneScreen
                self.manager.push(MandatorySceneScreen(self, scene_id))
        elif status == "blocked":
            scene_id = result.get("mandatory_scene")
            if (
                result.get("reason") == "mandatory_scene_pending"
                and scene_id
            ):
                from .screens.mandatory_screen import MandatorySceneScreen
                self.manager.push(MandatorySceneScreen(self, scene_id))
        elif status == "completed":
            if on_completed is not None:
                on_completed()

    def open_action_menu(self):
        """Открывает меню действий игрока."""
        from .screens.action_menu import ActionMenuOverlay
        self.manager.push(ActionMenuOverlay(self))
        logger.debug("Открыто меню действий")

    def new_game(self):
        """Открывает экран выбора сюжета."""
        from .screens.storyline_select import StorylineSelectScreen
        self.manager.push(StorylineSelectScreen(self))
        logger.info("Запрошена новая игра")

    def start_storyline(self, storyline):
        """
        Запускает сюжет: пересобирает мир, инициализирует интерпретатор
        и запускает первую сцену.
        Args:
            storyline (dict): Конфигурация сюжета из load_storyline().
        """
        from view.support.storyline import StorylineInterpreter
        from view.support.scenario import build_world
        from view.support.world import CampaignEngine
        from view.support.time_system import CampaignTimeSystem
        self.scenario_path = storyline.get(
            "scenario_path", "scenarios/mvp.json"
        )
        self.pending_storyline_outcome = None
        state = build_world(scenario_path=self.scenario_path,
                            content=self.content)
        self.state = state
        self.engine = CampaignEngine(state)
        self.engine.engagements = state.engagements
        self.player_idx = state.player_idx
        self.time_system = CampaignTimeSystem(state, engine=self.engine,
                                              app=self)
        self.engine.time_system = self.time_system
        from .ui.time_hud import TimeHUD
        self.time_hud = TimeHUD(self)
        self.storyline_interpreter = StorylineInterpreter(self, storyline)
        logger.info(
            "Сюжет запущен: %s", storyline.get("storyline_id", "?")
        )
        self._play_next_scene()

    def _play_next_scene(self):
        """Запускает следующую сцену из последовательности."""
        interp = self.storyline_interpreter
        if interp is None:
            return
        scene = interp.get_current_scene()
        if scene is None:
            if interp.check_win_conditions():
                self._show_win_scene()
            else:
                self._return_to_menu()
            return
        resolved = interp.resolve_variant(scene)
        self._play_scene(resolved)

    def _resolve_slides(self, block):
        """
        Возвращает слайды блока новеллы с разрешёнными вариантами.
        Каждый слайд прогоняется через resolve_variant интерпретатора,
        поэтому отдельный слайд может содержать variant_by/variants
        (например, выбор изображения по полу персонажа) без
        дублирования всего списка слайдов.
        Args:
            block (dict): Блок сцены с ключом slides.
        Returns:
            list[dict]: Список разрешённых слайдов.
        """
        slides = block.get("slides", []) if isinstance(block, dict) else []
        interp = self.storyline_interpreter
        if interp is None:
            return list(slides)
        return [interp.resolve_variant(s) for s in slides]

    def _play_scene(self, scene):
        """
        Запускает сцену соответствующего типа.
        Неизвестный тип сцены пропускается с переходом к следующей.
        Args:
            scene (dict): Конфигурация сцены.
        """
        scene_type = scene.get("type", "")
        logger.debug("Запуск сцены: %s", scene_type)
        if scene_type == "character_creation":
            self._play_character_creation(scene)
        elif scene_type == "visual_novel":
            self._play_visual_novel(scene)
        elif scene_type == "document":
            self._play_document(scene)
        elif scene_type == "dialogue":
            self._play_dialogue(scene)
        elif scene_type == "mandatory_scene":
            self._play_mandatory_scene(scene)
        elif scene_type == "hq_scene":
            self._play_hq_scene(scene)
        elif scene_type == "gameplay":
            self._play_gameplay(scene)
        else:
            interp = self.storyline_interpreter
            if interp is not None:
                interp.advance()
                self._play_next_scene()

    def _play_character_creation(self, scene):
        """
        Запускает экран создания персонажа.
        Args:
            scene (dict): Конфигурация сцены (не используется напрямую,
                шаги берутся из storyline.character_creation).
        """
        interp = self.storyline_interpreter
        if interp is None:
            return
        self.music.request_category("overture")
        steps = interp.storyline.get("character_creation", {}).get(
            "steps", []
        )
        if not steps:
            interp.advance()
            self._play_next_scene()
            return
        interp.advance()
        from .screens.character_creation import CharacterCreationScreen
        self.manager.replace_all(CharacterCreationScreen(self, steps))

    def _play_visual_novel(self, scene):
        """
        Запускает визуальную новеллу.
        Слайды разрешаются через _resolve_slides, поэтому каждый
        слайд может иметь собственные варианты по переменным сюжета.
        Args:
            scene (dict): Конфигурация сцены с полем slides.
        """
        from .screens.visual_novel import VisualNovelScreen
        self.music.request_category("overture")

        def on_finish():
            interp = self.storyline_interpreter
            if interp is not None:
                interp.advance()
                self._play_next_scene()

        slides = self._resolve_slides(scene)
        self.manager.replace_all(VisualNovelScreen(self, slides, on_finish))

    def _play_document(self, scene):
        """
        Запускает сцену с документом.
        Args:
            scene (dict): Конфигурация сцены с полями title,
                content_stylized, content_plain, hands_asset.
        """
        from .screens.document_intro import DocumentIntroScreen
        self.music.request_category("overture")

        def on_finish():
            interp = self.storyline_interpreter
            if interp is not None:
                interp.advance()
                self._play_next_scene()

        doc_data = {
            "title": scene.get("title", "ПРИКАЗ"),
            "content_stylized": scene.get("content_stylized", ""),
            "content_plain": scene.get("content_plain", ""),
            "hands_asset": scene.get(
                "hands_asset", "items/hands_paper"
            ),
        }
        self.manager.replace_all(
            DocumentIntroScreen(self, doc_data, on_finish_callback=on_finish)
        )

    def _play_dialogue(self, scene):
        """
        Запускает диалог.
        Args:
            scene (dict): Конфигурация сцены с полем node_id.
        """
        from .screens.dialogue import DialogueScreen
        node_id = scene.get("node_id", "")
        if node_id and node_id in self.content.dialogues:
            self.manager.push(DialogueScreen(self, node_id))
        interp = self.storyline_interpreter
        if interp is not None:
            interp.advance()
            self._play_next_scene()

    def _play_mandatory_scene(self, scene):
        """
        Запускает обязательную сцену.
        Args:
            scene (dict): Конфигурация сцены с полем scene_id.
        """
        scene_id = scene.get("scene_id", "")
        if scene_id and self.time_system is not None:
            self.time_system.pending_mandatory_scene = scene_id
        interp = self.storyline_interpreter
        if interp is not None:
            interp.advance()
            self._play_next_scene()

    def _play_hq_scene(self, scene):
        """
        Запускает сцену командного пункта.
        Args:
            scene (dict): Конфигурация сцены (фон выбирается
                внутри HQSceneScreen по полу игрока).
        """
        from .screens.hq_scene import HQSceneScreen
        self.music.request_category("ambient")
        self.manager.replace_all(HQSceneScreen(self))
        interp = self.storyline_interpreter
        if interp is not None:
            interp.advance()

    def _play_gameplay(self, scene):
        """
        Запускает основной геймплей (КП).
        Args:
            scene (dict): Конфигурация сцены (не используется).
        """
        from .screens.hq_scene import HQSceneScreen
        self.music.request_category("ambient")
        self.manager.replace_all(HQSceneScreen(self))

    def _show_win_scene(self):
        """
        Показывает победную сцену.
        Блок win_scene прогоняется через resolve_variant целиком,
        а затем каждый слайд разрешается отдельно, чтобы первый
        слайд мог выбирать изображение по полу персонажа без
        дублирования всего списка слайдов.
        """
        interp = self.storyline_interpreter
        if interp is None:
            self._return_to_menu()
            return
        win_scene = interp.resolve_variant(
            interp.storyline.get("win_scene", {})
        )
        slides = self._resolve_slides(win_scene)
        if not slides:
            self._return_to_menu()
            return
        self.music.request_category("victorious", fade=True)
        from .screens.visual_novel import VisualNovelScreen
        logger.info("Показана победная сцена")
        self.manager.replace_all(
            VisualNovelScreen(self, slides, self._return_to_menu)
        )

    def _show_lose_scene(self):
        """
        Показывает проигрышную сцену.
        Блок lose_scene и каждый слайд прогоняются через
        resolve_variant для симметрии с победной сценой.
        """
        interp = self.storyline_interpreter
        if interp is None:
            self._return_to_menu()
            return
        lose_scene = interp.resolve_variant(
            interp.storyline.get("lose_scene", {})
        )
        slides = self._resolve_slides(lose_scene)
        if not slides:
            self._return_to_menu()
            return
        self.music.request_category("tragic", fade=True)
        from .screens.visual_novel import VisualNovelScreen
        logger.info("Показана проигрышная сцена")
        self.manager.replace_all(
            VisualNovelScreen(self, slides, self._return_to_menu)
        )

    def _return_to_menu(self):
        """Возвращает в главное меню."""
        self.storyline_interpreter = None
        self.pending_storyline_outcome = None
        self.music.request_category("overture")
        from .screens.main_menu import MainMenuScreen
        self.manager.replace_all(MainMenuScreen(self))
        logger.info("Возврат в главное меню")

    def process_pending_storyline_outcome(self):
        """
        Обрабатывает отложенный исход сюжета.
        Вызывается в главном цикле. Если pending_storyline_outcome
        установлен, показывает соответствующую финальную сцену.
        """
        outcome = self.pending_storyline_outcome
        if outcome is None:
            return
        self.pending_storyline_outcome = None
        if outcome == "lose":
            self._show_lose_scene()
        elif outcome == "win":
            self._show_win_scene()

    def process_pending_mandatory_scene(self):
        """
        Обрабатывает отложенную обязательную сцену.
        Показывает обязательную сцену только если в стеке есть
        экран с show_time_hud == True и текущий экран не является
        MandatorySceneScreen или InterruptModal.
        """
        ts = self.time_system
        if ts is None:
            return
        scene_id = ts.pending_mandatory_scene
        if scene_id is None:
            return
        if not self.manager.has_time_hud_screen():
            return
        current = self.manager.current
        if current is None:
            return
        name = type(current).__name__
        if name in ("MandatorySceneScreen", "InterruptModal"):
            return
        from .screens.mandatory_screen import MandatorySceneScreen
        self.manager.push(MandatorySceneScreen(self, scene_id))
        logger.info("Выведена обязательная сцена: %s", scene_id)

    def save_game(self, slot_name):
        """
        Сохраняет игру в указанный слот.
        Args:
            slot_name (str): Имя слота сохранения.
        Returns:
            str | None: Путь к файлу сохранения или None при ошибке.
        """
        if self.engine is None or self.time_system is None:
            return None
        self.engine.state.engagements = list(self.engine.engagements)
        from view.support.save_system import save_game as do_save
        storyline_snapshot = None
        if self.storyline_interpreter is not None:
            storyline_snapshot = self.storyline_interpreter.get_save_snapshot()
        path = do_save(
            self.engine.state,
            self.time_system,
            slot_name,
            scenario_path=self.scenario_path,
            storyline_snapshot=storyline_snapshot,
        )
        logger.info("Сохранение записано: слот=%s", slot_name)
        return path

    def load_game(self, slot_name):
        """
        Загружает игру из указанного слота.
        Мир пересобирается из сценария, поверх применяется снимок.
        Стек экранов заменяется на HQSceneScreen.
        Args:
            slot_name (str): Имя слота сохранения.
        Returns:
            bool: True при успешной загрузке, False при ошибке.
        """
        from view.support.save_system import load_game as do_load
        from view.support.scenario import build_world
        from view.support.world import CampaignEngine
        from view.support.time_system import CampaignTimeSystem
        snapshot = do_load(slot_name)
        if snapshot is None:
            logger.warning("Загрузка не выполнена: слот=%s", slot_name)
            return False
        scenario_path = snapshot.get("scenario_path", "scenarios/mvp.json")
        self.scenario_path = scenario_path
        self.pending_storyline_outcome = None
        state = build_world(
            scenario_path=scenario_path,
            campaign_snapshot=snapshot.get("campaign", {}),
            content=self.content,
        )
        self.state = state
        self.engine = CampaignEngine(state)
        self.engine.engagements = state.engagements
        self.player_idx = state.player_idx
        self.time_system = CampaignTimeSystem(state, engine=self.engine,
                                              app=self)
        self.time_system.load_from_snapshot(snapshot.get("time_system", {}))
        self.engine.time_system = self.time_system
        from .ui.time_hud import TimeHUD
        self.time_hud = TimeHUD(self)
        storyline_snapshot = snapshot.get("storyline", None)
        if storyline_snapshot is not None:
            from view.support.storyline import load_storyline, StorylineInterpreter
            storyline_id = storyline_snapshot.get("storyline_id")
            if storyline_id:
                storyline = load_storyline(storyline_id)
                if storyline is not None:
                    self.storyline_interpreter = StorylineInterpreter(
                        self, storyline
                    )
                    self.storyline_interpreter.load_from_snapshot(
                        storyline_snapshot
                    )
        from .screens.hq_scene import HQSceneScreen
        self.manager.replace_all(HQSceneScreen(self))
        self.music.request_category("ambient")
        logger.info("Загрузка выполнена: слот=%s", slot_name)
        return True

    def continue_game(self):
        """Продолжает последнее сохранение."""
        from view.support.save_system import list_saves
        saves = list_saves()
        if not saves:
            return
        saves.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        self.load_game(saves[0]["name"])

    def open_saves(self):
        """Открывает меню сохранений."""
        from .screens.saves_menu import SavesMenuScreen
        self.manager.push(SavesMenuScreen(self))
        logger.debug("Открыто меню сохранений")

    def open_settings(self):
        """Открывает меню настроек."""
        from .screens.settings_menu import SettingsMenuScreen
        self.manager.push(SettingsMenuScreen(self))
        logger.debug("Открыто меню настроек")

    def quit(self):
        """Завершает приложение."""
        logger.info("Приложение останавливается")
        self.running = False

    def run(self):
        """
        Главный цикл приложения.
        Обрабатывает события pygame, обновляет менеджер экранов
        и музыку, проверяет отложенные исходы сюжета и обязательные
        сцены, отрисовывает стек экранов и HUD (при наличии
        show_time_hud экрана в стеке).
        """
        logger.info("Главный цикл запущен")
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    self.toggle_fullscreen()
                elif (
                    event.type == pygame.KEYDOWN
                    and event.key == pygame.K_ESCAPE
                ):
                    self.manager.handle_escape()
                elif (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_t
                ):
                    self.advance_turn()
                elif (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_l
                ):
                    self.open_turn_log()
                elif (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_a
                ):
                    self.open_action_menu()
                elif (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_F5
                ):
                    self.save_game("quicksave")
                else:
                    self.manager.handle_event(event)
            dt = self.clock.tick(FPS) / 1000.0
            self.manager.update(dt)
            self.music.update()
            self.process_pending_storyline_outcome()
            self.process_pending_mandatory_scene()
            self.screen.fill(BG_COLOR)
            self.manager.draw(self.screen)
            if self.manager.has_time_hud_screen():
                self.time_hud.draw(self.screen)
            pygame.display.flip()
        pygame.quit()
        return 0


def main(argv=None):
    """Точка входа интерфейса ``view`` (``python3 main.py --view``)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    fullscreen = ("--fullscreen" in argv) or ("-f" in argv)
    app = App()
    if fullscreen:
        app.toggle_fullscreen()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
