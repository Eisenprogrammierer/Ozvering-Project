"""D7.4: нарративный слой поверх истории кампании.

``Narrator`` читает ``story_events``, ``log`` работ и прочие ``events``
кампании и собирает из них хронологическое описание. Данные
``narrator.json`` задают лимиты, порядок источников, шаблоны, подписи
форм и исходов. Мир не меняется: модуль только читает списки.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

_DEFAULT_KIND = "{text}"
_SOURCE_DEFAULTS = {"story": 0, "log": 1, "events": 2}


class _Fields(dict):
    """Словарь для ``format_map``: неизвестный ключ даёт пустую строку."""

    def __missing__(self, key):
        return ""


def safe_format(template: str, values: Mapping[str, Any]) -> str:
    """Подставить значения в шаблон, не падая на пропусках."""

    try:
        return string.Formatter().vformat(
            str(template), (), _Fields(values)
        )
    except (KeyError, IndexError, ValueError, AttributeError):
        return str(template)


@dataclass(frozen=True)
class NarrationEntry:
    """Одна строка описания с источником и ходом."""

    kind: str
    turn: int
    source: str
    text: str

    def snapshot(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "turn": self.turn,
            "source": self.source,
            "text": self.text,
        }


@dataclass(frozen=True)
class Narration:
    """Готовое описание мира и истории кампании."""

    ok: bool
    text: str
    header: str = ""
    lines: Tuple[str, ...] = ()
    entries: Tuple[NarrationEntry, ...] = ()
    reason: str = ""

    def snapshot(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "text": self.text,
            "header": self.header,
            "lines": list(self.lines),
            "entries": [entry.snapshot() for entry in self.entries],
        }


class Narrator:
    """Детерминированный сборщик описания без изменения кампании."""

    def __init__(self, catalog: Any, campaign: Any = None):
        self.catalog = catalog
        self.campaign = campaign
        self.spec: Mapping[str, Any] = getattr(catalog, "narrator", None) or {}

    def message(self, key: str, default: str = "") -> str:
        return str((self.spec.get("messages") or {}).get(key) or default)

    def _int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _limit(self, limit: Optional[int]) -> int:
        maximum = max(1, self._int(self.spec.get("max_limit"), 20))
        fallback = max(1, self._int(self.spec.get("limit"), 5))
        value = fallback if limit is None else self._int(limit, fallback)
        return max(1, min(value, maximum))

    def _priority(self, source: str) -> int:
        sources = self.spec.get("sources") or {}
        return self._int(
            sources.get(source), _SOURCE_DEFAULTS.get(source, 9)
        )

    def _label(self, mapping: Any, key: Any, default: str = "") -> str:
        if not isinstance(mapping, Mapping):
            return default
        value = mapping.get(key)
        return default if value in (None, "") else str(value)

    def _severity_label(self, value: Any) -> str:
        bands = self.spec.get("severity_bands") or ()
        try:
            severity = float(value)
        except (TypeError, ValueError):
            severity = None
        fallback = ""
        for band in bands:
            if not isinstance(band, Mapping):
                continue
            maximum = band.get("max")
            label = str(band.get("label") or "")
            if maximum is None:
                fallback = fallback or label
                continue
            try:
                bound = float(maximum)
            except (TypeError, ValueError):
                continue
            if severity is not None and severity <= bound:
                return label
        return fallback

    def _template(self, kind: str) -> str:
        kinds = self.spec.get("kinds") or {}
        entry = kinds.get(kind)
        template = self._label(entry, "template")
        if template:
            return template
        fallback = self.spec.get("fallback") or {}
        template = self._label(fallback, "template")
        return template or _DEFAULT_KIND

    def _form_label(self, value: Any) -> str:
        key = str(value or "work")
        return self._label(self.spec.get("forms"), key, key)

    def _outcome_label(self, success: Any) -> str:
        key = "success" if bool(success) else "failure"
        return self._label(self.spec.get("outcomes"), key, key)

    def _story_records(self) -> list:
        visible_only = bool(self.spec.get("visible_only", True))
        records = []
        for index, entry in enumerate(
            getattr(self.campaign, "story_events", None) or ()
        ):
            if not isinstance(entry, Mapping):
                continue
            if visible_only and entry.get("visible") is False:
                continue
            turn = self._int(entry.get("turn"))
            values = {
                "turn": turn,
                "kind": "story",
                "category": str(entry.get("category") or ""),
                "title": str(entry.get("title") or ""),
                "text": str(entry.get("text") or ""),
                "severity": entry.get("severity"),
                "severity_label": self._severity_label(
                    entry.get("severity")
                ),
            }
            line = safe_format(self._template("story"), values)
            records.append(
                (
                    turn,
                    self._priority("story"),
                    index,
                    "story",
                    "story",
                    line,
                )
            )
        return records

    def _work_records(self) -> list:
        records = []
        for index, entry in enumerate(
            getattr(self.campaign, "log", None) or ()
        ):
            if not isinstance(entry, Mapping):
                continue
            turn = self._int(entry.get("turn"))
            success = entry.get("success")
            if success is None:
                success = entry.get("ok")
            values = {
                "turn": turn,
                "kind": "work",
                "actor": str(
                    entry.get("actor_name") or entry.get("actor") or ""
                ),
                "target": str(
                    entry.get("target_name") or entry.get("target") or ""
                ),
                "label": str(entry.get("label") or ""),
                "form": str(entry.get("form") or "work"),
                "form_label": self._form_label(entry.get("form")),
                "outcome": self._outcome_label(success),
                "chance": entry.get("chance"),
                "roll": entry.get("roll"),
                "text": str(entry.get("text") or ""),
            }
            line = safe_format(self._template("work"), values)
            records.append(
                (
                    turn,
                    self._priority("log"),
                    index,
                    "work",
                    "log",
                    line,
                )
            )
        return records

    def _event_records(self) -> list:
        records = []
        for index, entry in enumerate(
            getattr(self.campaign, "events", None) or ()
        ):
            if not isinstance(entry, Mapping):
                continue
            kind = str(entry.get("kind") or "event")
            if kind == "work":
                # Работа уже описана богаче через ``log``.
                continue
            turn = self._int(entry.get("turn"))
            values = {
                "turn": turn,
                "kind": kind,
                "side": str(entry.get("side") or ""),
                "actor": str(entry.get("actor") or ""),
                "text": str(entry.get("text") or ""),
            }
            line = safe_format(self._template(kind), values)
            records.append(
                (
                    turn,
                    self._priority("events"),
                    index,
                    kind,
                    "events",
                    line,
                )
            )
        return records

    def describe(self, limit: Optional[int] = None) -> Narration:
        """Собрать последние ``limit`` событий в хронологическом тексте."""

        if self.campaign is None:
            return Narration(
                ok=False,
                reason="no_campaign",
                text=self.message(
                    "no_campaign", "Нет кампании: нечего наблюдать."
                ),
            )
        value = self._limit(limit)
        records = (
            self._story_records()
            + self._work_records()
            + self._event_records()
        )
        records.sort(key=lambda item: (item[0], item[1], item[2]))
        selected = records[-value:]
        prefix = str(self.spec.get("line_prefix") or "")
        lines = tuple(prefix + item[5] for item in selected)
        entries = tuple(
            NarrationEntry(
                kind=item[3], turn=item[0], source=item[4], text=item[5]
            )
            for item in selected
        )
        if not lines:
            return Narration(
                ok=True,
                reason="",
                text=self.message(
                    "empty", "Пока ничего не происходит."
                ),
                entries=entries,
            )
        header = self.message("header", "Что видно:")
        body = "\n".join(lines)
        text = "%s\n%s" % (header, body) if header else body
        return Narration(
            ok=True,
            reason="",
            text=text,
            header=header,
            lines=lines,
            entries=entries,
        )
