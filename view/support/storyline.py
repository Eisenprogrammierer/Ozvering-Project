import os
import logging
import re

from .config_loader import load_json

_VARIABLE_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

STORYLINES_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "configs", "storylines"
    )
)

LOG_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "operation_ozverin.log"
    )
)


def _build_logger():
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

DEFAULT_LOSS_LIMIT_PERCENT = 45


def loss_limit_percent(storyline, default=DEFAULT_LOSS_LIMIT_PERCENT):
    def find(condition):
        if not isinstance(condition, dict):
            return None
        if condition.get("type") == "manpower_loss_above":
            value = condition.get("value")
            if value is None:
                return None
            try:
                return max(1, int(round(100.0 * float(value))))
            except (TypeError, ValueError):
                return None
        for child in condition.get("conditions", []) or []:
            found = find(child)
            if found is not None:
                return found
        return None

    for condition in (storyline or {}).get("lose_conditions", []) or []:
        found = find(condition)
        if found is not None:
            return found
    return max(1, int(round(float(default))))


def list_storylines():
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
        storylines.append(
            {
                "storyline_id": data.get("storyline_id", f[:-5]),
                "title": data.get("title", f[:-5]),
                "description": data.get("description", ""),
            }
        )
    logger.info("list_storylines: найдено сюжетов: %d", len(storylines))
    return storylines


def load_storyline(storyline_id):
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
        "scenario_path": main_data.get("scenario_path", "scenarios/mvp.json"),
        "campaign_template": main_data.get("campaign_template", ""),
        "strategy_path": main_data.get("strategy_path", ""),
        "world_path": main_data.get("world_path", ""),
        "biography_path": main_data.get("biography_path", ""),
        "campaign_seed": main_data.get("campaign_seed", 7),
        "character_creation": char_data,
        "scenes": scenes_data.get("sequence", []),
        "win_conditions": main_data.get("win_conditions", []),
        "lose_conditions": main_data.get("lose_conditions", []),
        "win_scene": main_data.get("win_scene", {}),
        "lose_scene": main_data.get("lose_scene", {}),
        "adjutant_orders": main_data.get("adjutant_orders", []),
    }


def _unit_alive(state, idx):
    cfg = state.class_configs[state.class_ids[idx]]
    if "condition" in cfg.segment_layout.segments:
        if state.read_segment(idx, "condition") == 0:
            return False
    ch = cfg.voltage_layout.channel_index.get("U_manpower")
    if ch is not None and state.read_voltage(idx, "U_manpower") <= 0.0:
        return False
    return True


def _all_enemies_destroyed(state):
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


def _all_player_units_destroyed(state):
    if state is None or state.count <= 0:
        return False
    player_faction = state.factions[state.player_idx]
    for i in range(state.count):
        cfg = state.class_configs[state.class_ids[i]]
        if cfg.class_name != "military_unit":
            continue
        if state.factions[i] != player_faction:
            continue
        if _unit_alive(state, i):
            return False
    return True


def _player_dead(state):
    if state is None:
        return False
    needs_system = getattr(state, "needs", None)
    if needs_system is None:
        return False
    dead = getattr(needs_system, "player_dead", None)
    if dead is not None:
        return bool(dead)
    commander = getattr(needs_system, "commander", None)
    if commander is None:
        return False
    return bool(getattr(commander, "is_dead", False))


def check_storyline_condition(condition, state, time_system, storyline_state):
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
        elif hasattr(state, "division_loss_percent"):
            threshold = 100.0 * float(condition.get("value", 0.0))
            result = state.division_loss_percent() >= threshold
        else:
            idx = state.player_idx
            current = state.read_voltage(idx, "U_manpower")
            threshold = initial * (1.0 - float(condition.get("value", 0.0)))
            result = current < threshold
    elif t == "player_dead":
        result = _player_dead(state)
    elif t == "all_enemies_destroyed":
        result = _all_enemies_destroyed(state)
    elif t == "all_player_units_destroyed":
        result = _all_player_units_destroyed(state)
    elif t.startswith("world_"):
        snapshot = storyline_state.get("world") or {}
        player = snapshot.get("player") or {}
        resources = player.get("resources") or {}
        if t == "world_outcome":
            result = snapshot.get("outcome") == condition.get("value")
        elif t == "world_day_above":
            result = int(snapshot.get("day", 1)) > int(
                condition.get("value", 0)
            )
        elif t == "world_day_at_least":
            result = int(snapshot.get("day", 1)) >= int(
                condition.get("value", 0)
            )
        elif t == "world_standing_at_least":
            result = float(resources.get("standing", 0.0)) >= float(
                condition.get("value", 0.0)
            )
        elif t in (
            "world_node_stat_at_least",
            "world_node_stat_at_most",
        ):
            node_id = str(condition.get("node") or "")
            stat = str(condition.get("stat") or "")
            nodes = snapshot.get("nodes") or {}
            value = float(
                ((nodes.get(node_id) or {}).get("stats") or {}).get(stat, 0.0)
            )
            threshold = float(condition.get("value", 0.0))
            if t == "world_node_stat_at_least":
                result = value >= threshold
            else:
                result = value <= threshold
        else:
            result = False
    elif t.startswith("strategy_"):
        snapshot = storyline_state.get("strategy") or {}
        resources = snapshot.get("resources") or {}
        if t in (
            "strategy_metric_at_least",
            "strategy_metric_at_most",
        ):
            metric = str(condition.get("metric") or "")
            value = float(resources.get(metric, 0.0))
            threshold = float(condition.get("value", 0.0))
            if t == "strategy_metric_at_least":
                result = value >= threshold
            else:
                result = value <= threshold
        elif t == "strategy_day_above":
            day = int(snapshot.get("day", 1))
            result = day > int(condition.get("value", 0))
        elif t == "strategy_outcome":
            result = snapshot.get("outcome") == condition.get("value")
        else:
            result = False
    else:
        result = False
    logger.debug("check_storyline_condition: тип=%s, результат=%s", t, result)
    return result


class StorylineInterpreter:

    def __init__(self, app, storyline):
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
        self.current_scene_index += 1
        logger.info(
            "advance: индекс сцены теперь %d", self.current_scene_index
        )

    def set_variable(self, key, value):
        self.variables[key] = value
        logger.debug("set_variable: %s = %r", key, value)

    def get_variable(self, key, default=None):
        return self.variables.get(key, default)

    def interpolate(self, text):
        if not isinstance(text, str):
            return text

        def replace(match):
            key = match.group(1)
            if key not in self.variables:
                return match.group(0)
            value = self.variables[key]
            if value is None:
                return ""
            if isinstance(value, (list, tuple)):
                return ", ".join(str(item) for item in value)
            return str(value)

        return _VARIABLE_TOKEN.sub(replace, text)

    def _interpolate_value(self, value):
        if isinstance(value, str):
            return self.interpolate(value)
        if isinstance(value, list):
            return [self._interpolate_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._interpolate_value(item) for item in value)
        if isinstance(value, dict):
            return {
                key: self._interpolate_value(item)
                for key, item in value.items()
            }
        return value

    def resolve_variant(self, scene):
        variant_by = scene.get("variant_by")
        if variant_by is None:
            return self._interpolate_value(scene)
        variants = scene.get("variants", {})
        value = self.variables.get(variant_by)
        if value is not None and value in variants:
            resolved = variants[value]
            if isinstance(resolved, dict):
                logger.debug("resolve_variant: выбран вариант '%s'", value)
                merged = dict(scene)
                merged.update(resolved)
                return self._interpolate_value(merged)
        logger.debug("resolve_variant: вариант не применён")
        return self._interpolate_value(scene)

    def check_win_conditions(self):
        conditions = self.storyline.get("win_conditions", [])
        if not conditions:
            return False
        result = all(
            check_storyline_condition(
                c,
                self.app.engine.state,
                self.app.time_system,
                self.state,
            )
            for c in conditions
        )
        logger.info("check_win_conditions: результат=%s", result)
        return result

    def check_lose_conditions(self):
        conditions = self.storyline.get("lose_conditions", [])
        if not conditions:
            return False
        result = any(
            check_storyline_condition(
                c,
                self.app.engine.state,
                self.app.time_system,
                self.state,
            )
            for c in conditions
        )
        logger.info("check_lose_conditions: результат=%s", result)
        return result

    def get_save_snapshot(self):
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
