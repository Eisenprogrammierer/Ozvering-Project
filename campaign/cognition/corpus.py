"""Золотой корпус NLU: ``(seed, snapshot, input) → trace``.

Корпус — JSON-источник истины для parity-тестов. Он версионируется и
не переписывается под результат: изменение ожиданий требует отдельного
ревью, как изменение golden-снимка кампании.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

from .errors import CorpusError
from .serialization import canonical_digest, pretty_json

CORPUS_VERSION = 1
ENTRY_FIELDS = frozenset(
    (
        "id",
        "seed",
        "snapshot",
        "input",
        "topic",
        "category",
        "expected",
        "notes",
    )
)


def _mapping(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CorpusError("%s должен быть объектом" % name)
    return {str(key): item for key, item in value.items()}


@dataclass(frozen=True)
class CorpusEntry:
    """Одна записанная фраза с ожидаемым результатом."""

    id: str
    seed: int
    snapshot: Mapping[str, Any]
    input: str
    topic: str = "default"
    category: str = ""
    expected: Mapping[str, Any] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self):
        if not str(self.id or "").strip():
            raise CorpusError("id записи корпуса обязателен")
        try:
            seed = int(self.seed)
        except (TypeError, ValueError) as exc:
            raise CorpusError("seed записи должен быть целым") from exc
        object.__setattr__(self, "seed", seed)
        if not isinstance(self.snapshot, Mapping):
            raise CorpusError("snapshot записи должен быть объектом")
        if not isinstance(self.input, str):
            raise CorpusError("input записи должен быть строкой")
        if not isinstance(self.expected, Mapping):
            raise CorpusError("expected записи должен быть объектом")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "seed": self.seed,
            "snapshot": dict(self.snapshot),
            "input": self.input,
            "topic": self.topic,
            "category": self.category,
            "expected": dict(self.expected),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CorpusEntry":
        if not isinstance(data, Mapping):
            raise CorpusError("запись корпуса должна быть объектом")
        unknown = sorted(set(data) - ENTRY_FIELDS)
        if unknown:
            raise CorpusError(
                "неизвестные поля записи: %s" % ", ".join(unknown)
            )
        return cls(
            id=str(data.get("id") or ""),
            seed=data.get("seed", 0),
            snapshot=_mapping(data.get("snapshot") or {}, "snapshot"),
            input=str(data.get("input") or ""),
            topic=str(data.get("topic") or "default"),
            category=str(data.get("category") or ""),
            expected=_mapping(data.get("expected") or {}, "expected"),
            notes=str(data.get("notes") or ""),
        )


class GoldenCorpus:
    """Упорядоченный по id набор записей с версией и хешем."""
    def __init__(
        self,
        entries: Tuple[CorpusEntry, ...] = (),
        version: int = CORPUS_VERSION,
    ):
        self.version = int(version)
        if self.version != CORPUS_VERSION:
            raise CorpusError(
                "версия корпуса %r не поддерживается" % (version,)
            )
        self._entries: Dict[str, CorpusEntry] = {}
        for entry in entries:
            self.add(entry)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[CorpusEntry]:
        return iter(self.sorted_entries())

    def add(self, entry: CorpusEntry, *, replace: bool = False) -> None:
        if not isinstance(entry, CorpusEntry):
            raise CorpusError("в корпус можно добавлять только CorpusEntry")
        if entry.id in self._entries and not replace:
            raise CorpusError("запись %r уже есть в корпусе" % entry.id)
        self._entries[entry.id] = entry

    def get(self, entry_id: str) -> Optional[CorpusEntry]:
        return self._entries.get(str(entry_id))

    def sorted_entries(self) -> Tuple[CorpusEntry, ...]:
        return tuple(
            self._entries[key] for key in sorted(self._entries)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "entries": [entry.to_dict() for entry in self.sorted_entries()],
        }

    def digest(self) -> str:
        return canonical_digest(self.to_dict())

    def save(self, path: Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(pretty_json(self.to_dict()), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: Path) -> "GoldenCorpus":
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except OSError as exc:
            raise CorpusError(
                "не удалось прочитать корпус: %s" % source
            ) from exc
        except ValueError as exc:
            raise CorpusError(
                "корпус не является JSON: %s" % source
            ) from exc
        if not isinstance(data, Mapping):
            raise CorpusError("корпус должен быть объектом")
        entries = data.get("entries") or ()
        if not isinstance(entries, (list, tuple)):
            raise CorpusError("entries корпуса должен быть списком")
        try:
            version = int(data.get("version", CORPUS_VERSION))
        except (TypeError, ValueError) as exc:
            raise CorpusError("версия корпуса должна быть целой") from exc
        return cls(
            entries=tuple(
                CorpusEntry.from_dict(item) for item in entries
            ),
            version=version,
        )


def record_corpus(
    session: Any,
    phrases: Tuple[str, ...],
    *,
    seed: int = 0,
    snapshot: Optional[Mapping[str, Any]] = None,
    topic: str = "default",
    category: str = "",
    prefix: str = "",
    flags: Any = None,
) -> GoldenCorpus:
    """Записать фразы в золотой корпус текущим legacy-разбором."""

    from .nlu import LegacyNlu

    engine = LegacyNlu(session, flags)
    corpus = GoldenCorpus()
    stem = prefix or category or "entry"
    for index, phrase in enumerate(phrases):
        result = engine.understand(str(phrase), topic=topic)
        corpus.add(
            CorpusEntry(
                id="%s-%03d" % (stem, index),
                seed=seed,
                snapshot=dict(snapshot or {}),
                input=str(phrase),
                topic=topic,
                category=category,
                expected=result.to_dict(),
            )
        )
    return corpus


__all__ = [
    "CORPUS_VERSION",
    "CorpusEntry",
    "GoldenCorpus",
    "record_corpus",
]
