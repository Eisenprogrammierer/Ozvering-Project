"""
core/storyline.py

Интерпретатор сюжетов.

Загружает конфигурации сюжетов из configs/storylines/, проверяет
условия победы и поражения, управляет последовательностью сцен,
разрешает варианты сцен по переменным сюжета и предоставляет
сериализацию состояния для системы сохранений.

Сюжет состоит из трёх файлов: основного (метаданные, условия,
финальные сцены, приказы адъютанту), файла создания персонажа
(шаги с выборами) и файла сцен (последовательность). Сканер
list_storylines показывает в меню выбора только основные файлы;
файлы с суффиксами _char и _scenes считаются вспомогательными.

Условия сюжета интерпретируются только данным модулем и не связаны
с условиями правил (RuleEngine) или боевых фаз (CombatSystem).
Неизвестный тип условия возвращает False. Исходы проверяются
ежедневно на вечерней границе через app.check_storyline_end_of_day.

События загрузки, проверки условий и навигации по сценам
фиксируются в журнале operation_ozverin.log и дублируются в консоль.
"""

import os
import logging

from .config_loader import load_json

STORYLINES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "configs", "storylines")
)

LOG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "operation_ozverin.log")
)


def _build_logger():
    """
    Создаёт и возвращает журнал модуля storyline.

    Файловый обработчик пишет в operation_ozverin.log в корне проекта
    с уровнем DEBUG, консольный выводит сообщения уровня INFO и выше.
    Обработчики добавляются один раз; повторный вызов возвращает
    уже настроенный журнал без дублирования.

    Returns:
        logging.Logger: Настроенный журнал.
    """
    logger = logging.getLogger("core.storyline")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    try:
        file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


logger = _build_logger()


def list_storylines():
    """
    Сканирует директорию сюжетов и возвращает список доступных сюжетов.

    Читает только основные JSON-файлы (без суффиксов _char и _scenes).
    Для каждого файла извлекает storyline_id, title и description.
    Повреждённые файлы пропускаются без исключения.

    Returns:
        list[dict]: Список словарей с полями storyline_id, title,
            description для каждого найденного сюжета.
    """
    storylines = []
    if not os.path.isdir(STORYLINES_DIR):
        logger.warning("Директория сюжетов не найдена: %s", STORYLINES_DIR)
        return storylines
    for f in sorted(os.listdir(STORYLINES_DIR)):
        if not f.endswith(".json"):
            continue
        if "_char" in f or "_scenes" in f:
            continue
        path = os.path.join(STORYLINES_DIR, f)
        data = load_json(path, None)
        if data is None:
            continue
        storylines.append({
            "storyline_id": data.get("storyline_id", f[:-5]),
            "title": data.get("title", f[:-5]),
            "description": data.get("description", ""),
        })
    logger.info("list_storylines: найдено сюжетов: %d", len(storylines))
    return storylines


def load_storyline(storyline_id):
    """
    Загружает полную конфигурацию сюжета по идентификатору.

    Объединяет основной файл сюжета, файл создания персонажа и
    файл сцен в единый словарь. Если основной файл не найден,
    возвращает None. Отсутствие вспомогательных файлов не является
    ошибкой: соответствующие поля загружаются пустыми.

    Args:
        storyline_id: Идентификатор сюжета (имя файла без .json).

    Returns:
        dict | None: Полная конфигурация сюжета или None, если
            основной файл не найден.
    """
    main_path = os.path.join(STORYLINES_DIR, f"{storyline_id}.json")
    main_data = load_json(main_path, None)
    if main_data is None:
        logger.warning(
            "load_storyline: основной файл не найден: %s", main_path
        )
        return None
    char_id = main_data.get("character_creation")
    char_data = {}
    if char_id:
        char_path = os.path.join(STORYLINES_DIR, f"{char_id}.json")
        char_data = load_json(char_path, {}) or {}
    scenes_id = main_data.get("scenes")
    scenes_data = {}
    if scenes_id:
        scenes_path = os.path.join(STORYLINES_DIR, f"{scenes_id}.json")
        scenes_data = load_json(scenes_path, {}) or {}
    logger.info(
        "load_storyline: '%s' загружен, шагов персонажа: %d, сцен: %d",
        storyline_id,
        len(char_data.get("steps", [])),
        len(scenes_data.get("sequence", [])),
    )
    return {
        "storyline_id": storyline_id,
        "title": main_data.get("title", storyline_id),
        "description": main_data.get("description", ""),
        "scenario_path": main_data.get(
            "scenario_path", "scenarios/mvp.json"
        ),
        "character_creation": char_data,
        "scenes": scenes_data.get("sequence", []),
        "win_conditions": main_data.get("win_conditions", []),
        "lose_conditions": main_data.get("lose_conditions", []),
        "win_scene": main_data.get("win_scene", {}),
        "lose_scene": main_data.get("lose_scene", {}),
        "adjutant_orders": main_data.get("adjutant_orders", []),
    }


def _unit_alive(state, idx):
    """
    Проверяет, живо ли подразделение.

    Подразделение считается уничтоженным, если сегмент condition
    равен 0 или канал U_manpower <= 0.

    Args:
        state: Состояние игрового мира (WorldState).
        idx: Индекс сущности.

    Returns:
        bool: True, если подразделение живо.
    """
    cfg = state.class_configs[state.class_ids[idx]]
    if "condition" in cfg.segment_layout.segments:
        if state.read_segment(idx, "condition") == 0:
            return False
    ch = cfg.voltage_layout.channel_index.get("U_manpower")
    if ch is not None and state.read_voltage(idx, "U_manpower") <= 0.0:
        return False
    return True


def _all_enemies_destroyed(state):
    """
    Проверяет, уничтожены ли все вражеские подразделения.

    Врагами считаются военные юниты, чья фракция отличается от
    фракции игрока и не является нейтральной.

    Args:
        state: Состояние игрового мира (WorldState).

    Returns:
        bool: True, если все враги уничтожены или state is None.
    """
    if state is None:
        return False
    player_faction = state.factions[state.player_idx]
    for i in range(state.count):
        cfg = state.class_configs[state.class_ids[i]]
        if cfg.class_name != "military_unit":
            continue
        fac = state.factions[i]
        if fac == player_faction or fac == "neutral":
            continue
        if _unit_alive(state, i):
            return False
    return True


def check_storyline_condition(condition, state, time_system, storyline_state):
    """
    Проверяет одно условие сюжета.

    Поддерживаемые типы: day_at_least, manpower_loss_above,
    all_enemies_destroyed, all_of, any_of. Неизвестный тип
    возвращает False. Пустое или None-условие возвращает False.

    Для manpower_loss_above требуется initial_manpower в
    storyline_state. Если оно равно нулю или отсутствует,
    условие возвращает False.

    Args:
        condition: Словарь условия с полем type.
        state: Состояние игрового мира (WorldState).
        time_system: Система игрового времени (GameTimeSystem).
        storyline_state: Служебное состояние сюжета (dict).

    Returns:
        bool: Результат проверки условия.
    """
    if not condition:
        return False
    t = condition.get("type", "")
    if t == "all_of":
        result = all(
            check_storyline_condition(c, state, time_system, storyline_state)
            for c in condition.get("conditions", [])
        )
    elif t == "any_of":
        result = any(
            check_storyline_condition(c, state, time_system, storyline_state)
            for c in condition.get("conditions", [])
        )
    elif t == "day_at_least":
        if time_system is None:
            result = False
        else:
            result = time_system.day >= int(condition.get("value", 0))
    elif t == "manpower_loss_above":
        initial = float(storyline_state.get("initial_manpower", 0.0))
        if initial <= 0.0:
            result = False
        else:
            idx = state.player_idx
            current = state.read_voltage(idx, "U_manpower")
            threshold = initial * (1.0 - float(condition.get("value", 0.0)))
            result = current < threshold
    elif t == "all_enemies_destroyed":
        result = _all_enemies_destroyed(state)
    else:
        result = False
    logger.debug(
        "check_storyline_condition: тип=%s, результат=%s", t, result
    )
    return result


class StorylineInterpreter:
    """
    Интерпретатор сюжета.

    Управляет последовательностью сцен, переменными сюжета,
    проверкой условий победы/поражения и сериализацией состояния.
    Не содержит захардкоженной сюжетной логики — только
    интерпретацию декларативных конфигов.

    Attributes:
        app: Экземпляр приложения (App).
        storyline: Полная конфигурация сюжета (dict).
        current_scene_index: Индекс текущей сцены в последовательности.
        variables: Переменные сюжета (пол, происхождение и т.д.).
        state: Служебное состояние (initial_manpower и прочее).
        finished: Флаг завершения сюжета.
    """

    def __init__(self, app, storyline):
        """
        Инициализирует интерпретатор сюжета.

        Args:
            app: Экземпляр приложения (App).
            storyline: Полная конфигурация сюжета (dict),
                возвращённая load_storyline.
        """
        self.app = app
        self.storyline = storyline
        self.current_scene_index = 0
        self.variables = {}
        self.state = {}
        self.finished = False
        logger.info(
            "StorylineInterpreter: инициализирован сюжет '%s', сцен: %d",
            storyline.get("storyline_id"),
            len(storyline.get("scenes", [])),
        )

    def get_current_scene(self):
        """
        Возвращает текущую сцену из последовательности.

        Returns:
            dict | None: Словарь сцены или None, если
                последовательность исчерпана.
        """
        scenes = self.storyline.get("scenes", [])
        if self.current_scene_index >= len(scenes):
            logger.debug("get_current_scene: последовательность исчерпана")
            return None
        scene = scenes[self.current_scene_index]
        logger.debug(
            "get_current_scene: индекс=%d, тип=%s",
            self.current_scene_index,
            scene.get("type"),
        )
        return scene

    def advance(self):
        """Продвигает индекс текущей сцены на единицу."""
        self.current_scene_index += 1
        logger.info(
            "advance: индекс сцены теперь %d", self.current_scene_index
        )

    def set_variable(self, key, value):
        """
        Устанавливает переменную сюжета.

        Args:
            key: Имя переменной.
            value: Значение переменной.
        """
        self.variables[key] = value
        logger.debug("set_variable: %s = %r", key, value)

    def get_variable(self, key, default=None):
        """
        Возвращает значение переменной сюжета.

        Args:
            key: Имя переменной.
            default: Значение по умолчанию, если переменная не установлена.

        Returns:
            Значение переменной или default.
        """
        return self.variables.get(key, default)

    def resolve_variant(self, scene):
        """
        Разрешает вариант сцены по переменной сюжета.

        Если сцена содержит поле variant_by, ищет значение
        соответствующей переменной в variants и возвращает
        объединённый словарь. Если переменная не установлена
        или ключ отсутствует, возвращает исходную сцену.

        Args:
            scene: Словарь сцены.

        Returns:
            dict: Разрешённая сцена (исходная или с подставленным вариантом).
        """
        variant_by = scene.get("variant_by")
        if variant_by is None:
            return scene
        variants = scene.get("variants", {})
        value = self.variables.get(variant_by)
        if value is not None and value in variants:
            resolved = variants[value]
            if isinstance(resolved, dict):
                logger.debug("resolve_variant: выбран вариант '%s'", value)
                merged = dict(scene)
                merged.update(resolved)
                return merged
        logger.debug("resolve_variant: вариант не применён")
        return scene

    def check_win_conditions(self):
        """
        Проверяет условия победы.

        Все условия из win_conditions должны быть истинны.
        При пустом списке возвращает False.

        Returns:
            bool: True, если все условия победы выполнены.
        """
        conditions = self.storyline.get("win_conditions", [])
        if not conditions:
            return False
        result = all(
            check_storyline_condition(
                c, self.app.engine.state, self.app.time_system, self.state,
            )
            for c in conditions
        )
        logger.info("check_win_conditions: результат=%s", result)
        return result

    def check_lose_conditions(self):
        """
        Проверяет условия поражения.

        Достаточно любого истинного условия из lose_conditions.
        При пустом списке возвращает False.

        Returns:
            bool: True, если хотя бы одно условие поражения выполнено.
        """
        conditions = self.storyline.get("lose_conditions", [])
        if not conditions:
            return False
        result = any(
            check_storyline_condition(
                c, self.app.engine.state, self.app.time_system, self.state,
            )
            for c in conditions
        )
        logger.info("check_lose_conditions: результат=%s", result)
        return result

    def get_save_snapshot(self):
        """
        Возвращает сериализуемый снимок состояния интерпретатора.

        Включает storyline_id, индекс текущей сцены, переменные,
        служебное состояние и флаг завершения.

        Returns:
            dict: Снимок состояния для сохранения.
        """
        logger.debug(
            "get_save_snapshot: индекс сцены=%d", self.current_scene_index
        )
        return {
            "storyline_id": self.storyline.get("storyline_id"),
            "current_scene_index": self.current_scene_index,
            "variables": dict(self.variables),
            "state": dict(self.state),
            "finished": self.finished,
        }

    def load_from_snapshot(self, snapshot):
        """
        Восстанавливает состояние интерпретатора из снимка.

        Применяет индекс сцены, переменные, служебное состояние
        и флаг завершения. Пустой или None-снимок игнорируется.

        Args:
            snapshot: Словарь снимка из сохранения или None.
        """
        if not snapshot:
            logger.debug(
                "load_from_snapshot: пустой снимок, состояние не изменено"
            )
            return
        self.current_scene_index = int(snapshot.get("current_scene_index", 0))
        self.variables = dict(snapshot.get("variables", {}))
        self.state = dict(snapshot.get("state", {}))
        self.finished = bool(snapshot.get("finished", False))
        logger.info(
            "load_from_snapshot: сюжет '%s', индекс сцены=%d, finished=%s",
            snapshot.get("storyline_id"),
            self.current_scene_index,
            self.finished,
        )