"""D7.0: headless-текстовик над ``DialogueSession`` и ``ActionBridge``.

Тонкая обвязка: история реплик, откат, подсказки и команды. Содержимое
команд, сообщений и лимит истории живут в ``configs/dialogue/console.json``;
фразы-подсказки — в ``actions.json``. Ядро мира не трогается: действие
уходит только через ``DialogueSession.act`` и публичный мост.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ConsoleEntry:
    """Одна реплика текстового интерфейса."""

    kind: str
    text: str
    reply: str
    plan_id: str = ""
    action_id: str = ""
    performed: bool = False
    reason: str = ""

    def snapshot(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "reply": self.reply,
            "plan_id": self.plan_id,
            "action_id": self.action_id,
            "performed": self.performed,
            "reason": self.reason,
        }


class TextGame:
    """Детерминированный текстовый цикл без отрисовки."""

    def __init__(
        self,
        session: Any,
        campaign: Any = None,
        history_limit: Optional[int] = None,
    ):
        self.session = session
        self.campaign = (
            campaign
            if campaign is not None
            else getattr(getattr(session, "bridge", None), "campaign", None)
        )
        spec = getattr(session.catalog, "console", None) or {}
        self.spec: Mapping[str, Any] = spec
        limit = history_limit
        if limit is None:
            try:
                limit = int(spec.get("history_limit") or 50)
            except (TypeError, ValueError):
                limit = 50
        self.history_limit = max(1, int(limit))
        self.entries: List[ConsoleEntry] = []
        self._undo: List[Dict[str, Any]] = []
        self.closed = False

    def _messages(self) -> Mapping[str, Any]:
        return self.spec.get("messages") or {}

    def _message(self, key: str, default: str = "") -> str:
        return str(self._messages().get(key) or default)

    def _state_snapshot(self) -> Dict[str, Any]:
        return {
            "state": copy.deepcopy(self.session.state),
            "campaign": (
                self.campaign.save_snapshot()
                if self.campaign is not None
                else None
            ),
        }

    def _restore(self, snapshot: Mapping[str, Any]) -> None:
        state = snapshot.get("state")
        if state is not None:
            self.session.state = state
            self.session.memory = state.memory
        campaign = snapshot.get("campaign")
        if campaign is not None and self.campaign is not None:
            self.campaign.load_snapshot(campaign)

    def _push_undo(self, snapshot: Mapping[str, Any]) -> None:
        self._undo.append(dict(snapshot))
        if len(self._undo) > self.history_limit:
            del self._undo[: len(self._undo) - self.history_limit]

    def _append(self, entry: ConsoleEntry) -> ConsoleEntry:
        self.entries.append(entry)
        if len(self.entries) > self.history_limit:
            del self.entries[: len(self.entries) - self.history_limit]
        return entry

    def _available(self, action_id: str) -> bool:
        if self.campaign is None:
            return True
        side = getattr(getattr(self.session, "bridge", None), "side", "")
        if not side:
            return True
        try:
            return str(action_id) in self.campaign.available_actions(side)
        except AttributeError:
            return True

    def _label(self, action_id: str) -> str:
        for item in (getattr(self.session.catalog, "actions", {}) or {}).get(
            "actions"
        ) or ():
            if str(item.get("id")) == str(action_id):
                return str(item.get("label") or action_id)
        return str(action_id)

    def submit(self, text: str) -> ConsoleEntry:
        """Обработать строку: команда, действие или обычная реплика."""

        raw = str(text or "")
        value = raw.strip()
        if not value:
            return ConsoleEntry("command", raw, self._message("empty"))
        token = value.split()[0].lower()
        if token.startswith("/"):
            return self._command(token, value)

        snapshot = self._state_snapshot()
        self._push_undo(snapshot)
        found = self.session.intent(value)
        if found is not None and found.action_id:
            result = self.session.act(value)
            label = self._label(result.action_id)
            if result.performed:
                reply = self._message("action_done") % label
            else:
                reason = result.reason or "не выполнено"
                reply = self._message("action_failed") % reason
            return self._append(
                ConsoleEntry(
                    "action",
                    value,
                    reply,
                    action_id=result.action_id,
                    performed=result.performed,
                    reason=result.reason,
                )
            )
        turn = self.session.respond(value)
        return self._append(
            ConsoleEntry(
                "answer",
                value,
                turn.answer.text,
                plan_id=turn.answer.plan_id,
            )
        )

    def _command(self, token: str, text: str) -> ConsoleEntry:
        aliases = self.spec.get("aliases") or {}
        name = str(aliases.get(token) or token.lstrip("/"))
        commands = self.spec.get("commands") or {}
        if name not in commands:
            return ConsoleEntry(
                "command", text, self._message("unknown") % token
            )
        if name == "quit":
            self.closed = True
            return ConsoleEntry("command", text, self._message("quit"))
        if name == "help":
            lines = [
                "/%s — %s" % (key, value)
                for key, value in commands.items()
            ]
            return ConsoleEntry("command", text, "\n".join(lines))
        if name == "history":
            if not self.entries:
                return ConsoleEntry(
                    "command", text, self._message("history_empty")
                )
            lines = [
                "%d. %s" % (index + 1, entry.text)
                for index, entry in enumerate(self.entries)
            ]
            return ConsoleEntry("command", text, "\n".join(lines))
        if name == "undo":
            if not self._undo or not self.entries:
                return ConsoleEntry(
                    "command", text, self._message("undo_empty")
                )
            snapshot = self._undo.pop()
            self._restore(snapshot)
            self.entries.pop()
            return ConsoleEntry(
                "command", text, self._message("undo_done")
            )
        if name == "hint":
            return ConsoleEntry("command", text, self.hint())
        return ConsoleEntry(
            "command", text, self._message("unknown") % token
        )

    def hint(self) -> str:
        """Детерминированные фразы доступных действий из данных."""

        phrases: List[str] = []
        spec = getattr(self.session.catalog, "actions", {}) or {}
        for item in spec.get("actions") or ():
            action_id = str(item.get("id") or "")
            if not action_id or not self._available(action_id):
                continue
            for phrase in item.get("phrases") or ():
                value = str(phrase or "")
                if value:
                    phrases.append(value)
        if not phrases:
            return self._message("hint_empty")
        return self._message("hint_prefix") + "; ".join(phrases)

    def history(self) -> Tuple[ConsoleEntry, ...]:
        return tuple(self.entries)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "closed": self.closed,
            "history": [entry.snapshot() for entry in self.entries],
        }
