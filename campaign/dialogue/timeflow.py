"""D7.3: время и темп через текст.

Данные ``time.json`` задают длительность короткого ожидания, фазы
суток, разрешённые направления темпа и сообщения. Кампанию двигает
только ``TimeGuide`` при ``allow_actions=True``; в read-only режиме
он показывает план и не трогает ``AutomataCampaign``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TimeResult:
    """Результат ожидания или смены темпа."""

    ok: bool
    performed: bool
    reason: str = ""
    kind: str = ""
    direction: str = ""
    target: str = ""
    seconds: float = 0.0
    real_seconds: float = 0.0
    speed: int = 0
    time: str = ""
    text: str = ""

    def snapshot(self) -> dict:
        return {
            "ok": self.ok,
            "performed": self.performed,
            "reason": self.reason,
            "kind": self.kind,
            "direction": self.direction,
            "target": self.target,
            "seconds": self.seconds,
            "real_seconds": self.real_seconds,
            "speed": self.speed,
            "time": self.time,
            "text": self.text,
        }


class TimeGuide:
    """Детерминированное управление временем одной кампании."""

    def __init__(
        self,
        catalog: Any,
        knowledge: Any,
        campaign: Any = None,
        allow_actions: bool = False,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.campaign = campaign
        self.allow_actions = bool(allow_actions)
        self.spec: Mapping[str, Any] = getattr(catalog, "time", None) or {}

    def message(self, key: str, default: str = "", *args: Any) -> str:
        template = str(
            (self.spec.get("messages") or {}).get(key) or default
        )
        if not args:
            return template
        try:
            return template % args
        except (TypeError, ValueError):
            return template

    def _time_label(self) -> str:
        hook = getattr(self.campaign, "time_label", None)
        if callable(hook):
            try:
                return str(hook())
            except (TypeError, ValueError):
                pass
        elapsed = float(getattr(self.campaign, "elapsed", 0.0) or 0.0)
        total = max(0, int(elapsed))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "%02d:%02d:%02d" % (hours, minutes, seconds)

    def _speed_value(self) -> int:
        try:
            return max(1, int(getattr(self.campaign, "speed", 1) or 1))
        except (TypeError, ValueError):
            return 1

    def _speed_label(self) -> str:
        value = self._speed_value()
        return "×%d" % value

    def _duration_label(self, seconds: float) -> str:
        value = int(round(float(seconds)))
        return "%d с" % value

    def _phase_delta(self, entry: Mapping[str, Any]) -> float:
        try:
            hour = float(entry.get("hour"))
        except (TypeError, ValueError):
            return 0.0
        try:
            cycle = float(self.spec.get("cycle_seconds") or 86400.0)
        except (TypeError, ValueError):
            cycle = 86400.0
        if cycle <= 0.0:
            cycle = 86400.0
        current = float(getattr(self.campaign, "elapsed", 0.0) or 0.0)
        base = (current // cycle) * cycle
        target = base + hour * 3600.0
        if target <= current + 1e-9:
            target += cycle
        return max(0.0, target - current)

    def wait(self, entity_id: str = "") -> TimeResult:
        """Подождать фиксированное время или до фазы суток."""

        target = str(entity_id or "")
        entry = None
        if target:
            entry = (self.spec.get("phases") or {}).get(target)
            if not isinstance(entry, Mapping):
                name = str(
                    getattr(self.knowledge, "name", lambda item: item)(
                        target
                    )
                )
                return TimeResult(
                    ok=False,
                    performed=False,
                    reason="unknown_phase",
                    kind="wait",
                    target=target,
                    text=self.message(
                        "unknown_phase",
                        "Не знаю такой фазы: %s.",
                        name,
                    ),
                )
        if self.campaign is None:
            return TimeResult(
                ok=False,
                performed=False,
                reason="no_campaign",
                kind="wait",
                target=target,
                text=self.message(
                    "no_campaign", "Нет кампании: время не идёт."
                ),
            )
        if bool(getattr(self.campaign, "finished", False)):
            return TimeResult(
                ok=False,
                performed=False,
                reason="finished",
                kind="wait",
                target=target,
                speed=self._speed_value(),
                time=self._time_label(),
                text=self.message(
                    "finished", "Кампания завершена: время стоит."
                ),
            )
        speed = self._speed_value()
        if entry is not None:
            seconds = self._phase_delta(entry)
            label = str(entry.get("label") or target)
        else:
            try:
                seconds = float(self.spec.get("wait_seconds") or 0.0)
            except (TypeError, ValueError):
                seconds = 0.0
            label = self._duration_label(seconds)
        if seconds <= 0.0:
            return TimeResult(
                ok=False,
                performed=False,
                reason="no_duration",
                kind="wait",
                target=target,
                speed=speed,
                time=self._time_label(),
                text=self.message(
                    "not_time", "Это не команда времени."
                ),
            )
        real_seconds = seconds / float(speed)
        if not self.allow_actions:
            key = "planned_phase" if entry is not None else "planned_wait"
            if entry is not None:
                text = self.message(
                    key,
                    "Можно дождаться: %s. Сейчас %s.",
                    label,
                    self._time_label(),
                )
            else:
                text = self.message(
                    key,
                    "Можно подождать %s. Сейчас %s, темп %s.",
                    label,
                    self._time_label(),
                    self._speed_label(),
                )
            return TimeResult(
                ok=False,
                performed=False,
                reason="actions_disabled",
                kind="wait",
                target=target,
                seconds=seconds,
                real_seconds=real_seconds,
                speed=speed,
                time=self._time_label(),
                text=text,
            )
        self.campaign.advance_time(real_seconds)
        time_label = self._time_label()
        if bool(getattr(self.campaign, "finished", False)):
            outcome = str(getattr(self.campaign, "outcome", "") or "")
            return TimeResult(
                ok=True,
                performed=True,
                reason="finished_during",
                kind="wait",
                target=target,
                seconds=seconds,
                real_seconds=real_seconds,
                speed=self._speed_value(),
                time=time_label,
                text=self.message(
                    "finished_during",
                    "Время шло, но кампания завершилась: %s.",
                    outcome,
                ),
            )
        if entry is not None:
            text = self.message(
                "arrived",
                "Вы дождались: %s. Сейчас %s.",
                label,
                time_label,
            )
        else:
            text = self.message(
                "waited",
                "Вы ждали %s. Сейчас %s, темп %s.",
                label,
                time_label,
                self._speed_label(),
            )
        return TimeResult(
            ok=True,
            performed=True,
            kind="wait",
            target=target,
            seconds=seconds,
            real_seconds=real_seconds,
            speed=self._speed_value(),
            time=time_label,
            text=text,
        )

    def speed(self, direction: str) -> TimeResult:
        """Ускорить, замедлить или сбросить темп кампании."""

        key = str(direction or "")
        entry = (self.spec.get("speeds") or {}).get(key)
        if not isinstance(entry, Mapping):
            return TimeResult(
                ok=False,
                performed=False,
                reason="unknown_direction",
                kind="speed",
                direction=key,
                text=self.message(
                    "not_time", "Это не команда времени."
                ),
            )
        label = str(entry.get("label") or key)
        if self.campaign is None:
            return TimeResult(
                ok=False,
                performed=False,
                reason="no_campaign",
                kind="speed",
                direction=key,
                text=self.message(
                    "no_campaign", "Нет кампании: время не идёт."
                ),
            )
        if bool(getattr(self.campaign, "finished", False)):
            return TimeResult(
                ok=False,
                performed=False,
                reason="finished",
                kind="speed",
                direction=key,
                speed=self._speed_value(),
                time=self._time_label(),
                text=self.message(
                    "finished", "Кампания завершена: время стоит."
                ),
            )
        if not self.allow_actions:
            return TimeResult(
                ok=False,
                performed=False,
                reason="actions_disabled",
                kind="speed",
                direction=key,
                speed=self._speed_value(),
                time=self._time_label(),
                text=self.message(
                    "speed_planned",
                    "Можно изменить темп: %s. Сейчас %s.",
                    label,
                    self._time_label(),
                ),
            )
        methods = {
            "up": "speed_up",
            "down": "slow_down",
            "reset": "reset_speed",
        }
        method = getattr(self.campaign, methods.get(key, ""), None)
        if not callable(method):
            return TimeResult(
                ok=False,
                performed=False,
                reason="unsupported",
                kind="speed",
                direction=key,
                speed=self._speed_value(),
                time=self._time_label(),
                text=self.message(
                    "not_time", "Это не команда времени."
                ),
            )
        before = self._speed_value()
        method()
        after = self._speed_value()
        time_label = self._time_label()
        speed_label = self._speed_label()
        if after == before:
            reason = "speed_limit"
            base = str(entry.get("limit") or "")
            key_msg = "speed_limit"
        else:
            reason = ""
            base = str(entry.get("done") or "")
            key_msg = "speed_done"
        try:
            base_text = base % speed_label if base else label
        except (TypeError, ValueError):
            base_text = base or label
        return TimeResult(
            ok=True,
            performed=reason == "",
            reason=reason,
            kind="speed",
            direction=key,
            speed=after,
            time=time_label,
            text=self.message(
                key_msg,
                "%s Сейчас %s, темп %s.",
                base_text,
                time_label,
                speed_label,
            ),
        )
