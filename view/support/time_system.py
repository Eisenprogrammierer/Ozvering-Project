"""Игровое время UI-каркаса.

Это упрощённая замена легаси-``GameTimeSystem``: она ведёт часы, выполняет
действия из ``configs/content/time_actions.json`` и раз в 30 игровых минут
продвигает войсковой такт ``warfare``. Никакой отдельной математической
модели времени здесь нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config_loader import load_json
from .log_journal import get_logger

logger = get_logger("view.time")
ROOT = Path(__file__).resolve().parents[2]
TICK_SECONDS = 1800


@dataclass
class ActionDefinition:
    id: str
    label: str
    duration_seconds: int
    category: str = "wait"
    interruptible: bool = True
    cancellable: bool = True
    repeatable: bool = True
    memory_seconds: int = 1800
    thresholds: list | None = None


class CampaignTimeSystem:
    """Часы кампании и очередь действий игрока."""

    def __init__(self, state, engine=None, app=None):
        self.state = state
        self.engine = engine if engine is not None else getattr(
            state, "engine", None
        )
        self.app = app
        settings = load_json(ROOT / "configs/content/time_settings.json", {}) or {}
        self.day_start_seconds = int(settings.get("day_start_seconds", 25200))
        self.day_end_seconds = int(settings.get("day_end_seconds", 79200))
        self.evening_start_seconds = int(settings.get(
            "evening_start_seconds", self.day_end_seconds - 3600
        ))
        self.day = 1
        self.seconds_of_day = self.day_start_seconds
        self.pending_mandatory_scene = None
        self._evening_done = False
        self.active_action = None
        self.actions = {}
        self._load_actions()
        self._combat_accum = 0
        self._order_actions = {}

    def _load_actions(self):
        raw = load_json(ROOT / "configs/content/time_actions.json", {}) or {}
        for item in raw.get("actions", []):
            action = ActionDefinition(
                id=item.get("id", "?"),
                label=item.get("label", item.get("id", "?")),
                duration_seconds=int(item.get("duration_seconds", 300)),
                category=item.get("category", "wait"),
                interruptible=bool(item.get("interruptible", True)),
                cancellable=bool(item.get("cancellable", True)),
                repeatable=bool(item.get("repeatable", True)),
                memory_seconds=int(item.get("memory_seconds", 1800)),
                thresholds=item.get("thresholds"),
            )
            self.actions[action.id] = action
        for action_id, label, duration in (
            ("radio_contact", "Связь по рации", 300),
            ("issue_order", "Постановка приказа", 1800),
        ):
            if action_id not in self.actions:
                self.actions[action_id] = ActionDefinition(
                    action_id, label, duration, category="orders"
                )

    # --- время -----------------------------------------------------------
    def get_time_string(self):
        minutes = int(self.seconds_of_day) // 60
        return "День %d · %02d:%02d" % (
            self.day, (minutes // 60) % 24, minutes % 60
        )

    def get_fatigue(self):
        det = self.state.det_at(self.state.player_idx)
        if det is None or not det.characters:
            return 0.0
        return sum(c.needs.get("fatigue", 0.0) for c in det.characters) / len(
            det.characters
        )

    def advance(self, seconds):
        remaining = max(0, int(seconds))
        while remaining > 0:
            step = min(remaining, TICK_SECONDS)
            self.seconds_of_day += step
            self._combat_accum += step
            remaining -= step
            if (not self._evening_done and
                    self.seconds_of_day >= self.evening_start_seconds):
                self._evening_done = True
                self.pending_mandatory_scene = "evening_inspection"
            if self.seconds_of_day >= self.day_end_seconds:
                self.seconds_of_day = self.day_start_seconds
                self.day += 1
                self._evening_done = False
                if self.app is not None and hasattr(
                        self.app, "check_storyline_end_of_day"):
                    self.app.check_storyline_end_of_day()
                self.pending_mandatory_scene = "morning_inspection"
            if self._combat_accum >= TICK_SECONDS:
                self._combat_accum = 0
                if self.engine is not None:
                    self.engine.tick()
        return True

    def wait(self, seconds):
        return self.advance(seconds)

    # --- действия --------------------------------------------------------
    def get_available_actions(self):
        return list(self.actions.values())

    def register_order_planning_action(self, planned=1):
        key = self._order_actions.get(planned)
        if key is None:
            key = "plan_orders_%d" % planned
            self.actions[key] = ActionDefinition(
                key,
                "Планирование приказов (%d)" % planned,
                max(TICK_SECONDS, 300 * max(1, int(planned))),
                category="orders",
            )
            self._order_actions[planned] = key
        return key

    def execute_action(self, action_id):
        if self.pending_mandatory_scene is not None:
            return {
                "status": "blocked",
                "reason": "mandatory_scene_pending",
                "mandatory_scene": self.pending_mandatory_scene,
            }
        definition = self.actions.get(action_id)
        if definition is None:
            logger.warning("Неизвестное действие: %s", action_id)
            return {"status": "completed"}
        logger.info("Действие %s: %.0f сек.", action_id,
                    definition.duration_seconds)
        self.advance(definition.duration_seconds)
        return {"status": "completed"}

    def cancel_active_action(self):
        self.active_action = None

    def complete_mandatory_scene(self, scene_id=None):
        self.pending_mandatory_scene = None
        if scene_id:
            self.state.log_event(
                self.state.player_idx,
                "Обязательная сцена завершена: %s" % scene_id,
            )
        if (scene_id == "morning_inspection" and
                getattr(self.state, "needs", None) is not None):
            self.state.needs.camp_morning()

    def choose_night_duty(self, value):
        self.state.log_event(
            self.state.player_idx,
            "Ночное дежурство: %s" % ("да" if value else "нет"),
        )
        if getattr(self.state, "needs", None) is not None:
            self.state.needs.camp_night(slept=not value)
        # Ночь проходит до утра: следующий экран — утренний осмотр лагеря.
        seconds_to_morning = max(
            0, self.day_end_seconds - int(self.seconds_of_day)
        )
        if seconds_to_morning:
            self.advance(seconds_to_morning)

    def accept_interrupt(self, interrupt_id):
        self.state.log_event(
            self.state.player_idx, "Прерывание принято: %s" % interrupt_id
        )

    def ignore_interrupt(self, interrupt_id):
        self.state.log_event(
            self.state.player_idx, "Прерывание отложено: %s" % interrupt_id
        )

    # --- сохранение ------------------------------------------------------
    def get_save_snapshot(self):
        return {
            "day": self.day,
            "seconds_of_day": self.seconds_of_day,
            "pending_mandatory_scene": self.pending_mandatory_scene,
            "evening_done": self._evening_done,
            "order_actions": dict(self._order_actions),
        }

    def load_from_snapshot(self, snapshot):
        if not snapshot:
            return
        self.day = int(snapshot.get("day", self.day))
        self.seconds_of_day = int(snapshot.get(
            "seconds_of_day", self.seconds_of_day))
        self.pending_mandatory_scene = snapshot.get(
            "pending_mandatory_scene")
        if "evening_done" in snapshot:
            self._evening_done = bool(snapshot.get("evening_done"))
        else:
            # Старые сохранения: если уже вечер, повторный осмотр не нужен.
            self._evening_done = (
                self.seconds_of_day >= self.evening_start_seconds
            )
        for planned, action_id in (snapshot.get("order_actions") or {}).items():
            self._order_actions[int(planned)] = action_id
            if action_id not in self.actions:
                self.actions[action_id] = ActionDefinition(
                    action_id, "Планирование приказов", TICK_SECONDS,
                    category="orders",
                )
