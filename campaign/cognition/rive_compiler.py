"""Компилятор диалогового JSON в RiveScript и манифест.

JSON остаётся источником истины. Компилятор читает лексикон, грамматику,
парафразы и действия, строит детерминированный ``.rive`` и манифест, а
``--check`` доказывает, что артефакты не разошлись с источником.

Phase 1 компилирует то, что можно проверить без движка: нормализацию
лексикона (``! sub``), точные триггеры парафраз, действий и маркеров.
Грамматика пока попадает в манифест как покрытие, а не как триггеры.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from campaign.dialogue.morphology import tokenize

from .errors import RiveError
from .serialization import canonical_digest, pretty_json

COMPILER_VERSION = 1
MANIFEST_VERSION = 1
TRIGGER_SOURCES = ("paraphrase", "action", "marker")
_SOURCE_ORDER = {"action": 0, "paraphrase": 1, "marker": 2}
_QUOTES = frozenset(("«", "»", '"'))
DEFAULT_DIALOGUE_DIR = (
    Path(__file__).resolve().parents[2] / "configs" / "dialogue"
)
DEFAULT_RIVE_DIR = Path(__file__).resolve().parents[2] / "configs" / "rive"
RIVE_NAME = "dialogue.rive"
MANIFEST_NAME = "manifest.json"


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RiveError("не удалось прочитать %s" % path) from exc
    except ValueError as exc:
        raise RiveError("%s не является JSON" % path) from exc
    if not isinstance(data, Mapping):
        raise RiveError("%s должен содержать объект" % path)
    return data


def _tokens(text: Any) -> Tuple[str, ...]:
    return tuple(
        token for token in tokenize(str(text or ""))
        if token not in _QUOTES
    )


def one_token(text: Any) -> str:
    tokens = _tokens(text)
    return tokens[0] if len(tokens) == 1 else ""


def _mapping(value: Any, name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RiveError("%s должен быть объектом" % name)
    return {str(key): item for key, item in value.items()}


def entry_forms(entry: Mapping[str, Any]) -> List[str]:
    forms = entry.get("forms")
    values: List[str] = []
    if isinstance(forms, Mapping):
        for items in forms.values():
            if isinstance(items, (list, tuple)):
                values.extend(str(item) for item in items)
    elif isinstance(forms, (list, tuple)):
        values.extend(str(item) for item in forms)
    aliases = entry.get("aliases")
    if isinstance(aliases, (list, tuple)):
        values.extend(str(item) for item in aliases)
    return values


def lexicon_substitutions(
    entries: Iterable[Mapping[str, Any]],
) -> Tuple[Dict[str, str], Tuple[str, ...]]:
    """Однозначные замены «форма → лемма» и список конфликтов."""

    candidates: Dict[str, set] = {}
    for entry in entries:
        lemma = one_token(entry.get("lemma"))
        if not lemma:
            continue
        for form in entry_forms(entry):
            token = one_token(form)
            if not token or token == lemma:
                continue
            candidates.setdefault(token, set()).add(lemma)
    substitutions = {}
    conflicts = []
    for token in sorted(candidates):
        lemmas = candidates[token]
        if len(lemmas) == 1:
            substitutions[token] = next(iter(lemmas))
        else:
            conflicts.append(token)
    return substitutions, tuple(conflicts)


def _apply_substitutions(
    tokens: Iterable[str],
    substitutions: Mapping[str, str],
) -> str:
    return " ".join(substitutions.get(token, token) for token in tokens)


def _trigger_text(
    text: Any,
    substitutions: Mapping[str, str],
) -> str:
    return _apply_substitutions(_tokens(text), substitutions)


@dataclass(frozen=True)
class RiveTrigger:
    """Один точный триггер и его смысловая нагрузка."""

    id: str
    trigger: str
    source: str
    text: str = ""
    kind: str = ""
    action_id: str = ""
    expect: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not str(self.id or "").strip():
            raise RiveError("id триггера обязателен")
        if not str(self.trigger or "").strip():
            raise RiveError("trigger триггера обязателен")
        if self.source not in TRIGGER_SOURCES:
            raise RiveError(
                "источник триггера %r не поддерживается" % (self.source,)
            )
        if not isinstance(self.expect, Mapping):
            raise RiveError("expect триггера должен быть объектом")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "source": self.source,
            "text": self.text,
            "kind": self.kind,
            "action_id": self.action_id,
            "expect": dict(self.expect),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RiveTrigger":
        if not isinstance(data, Mapping):
            raise RiveError("триггер должен быть объектом")
        return cls(
            id=str(data.get("id") or ""),
            trigger=str(data.get("trigger") or ""),
            source=str(data.get("source") or ""),
            text=str(data.get("text") or ""),
            kind=str(data.get("kind") or ""),
            action_id=str(data.get("action_id") or ""),
            expect=_mapping(data.get("expect"), "expect"),
        )


@dataclass(frozen=True)
class RiveManifest:
    """Проверяемое описание сгенерированного RiveScript."""

    source_digest: str
    triggers: Tuple[RiveTrigger, ...]
    substitutions: Mapping[str, str] = field(default_factory=dict)
    stats: Mapping[str, Any] = field(default_factory=dict)
    warnings: Tuple[str, ...] = ()
    version: int = MANIFEST_VERSION

    def __post_init__(self):
        if self.version != MANIFEST_VERSION:
            raise RiveError(
                "версия манифеста %r не поддерживается" % (self.version,)
            )
        if not str(self.source_digest or "").strip():
            raise RiveError("source_digest манифеста обязателен")
        if not isinstance(self.triggers, tuple):
            raise RiveError("triggers манифеста должен быть кортежем")
        if not isinstance(self.substitutions, Mapping):
            raise RiveError("substitutions манифеста должен быть объектом")
        if not isinstance(self.stats, Mapping):
            raise RiveError("stats манифеста должен быть объектом")
        if not isinstance(self.warnings, tuple) or not all(
            isinstance(item, str) for item in self.warnings
        ):
            raise RiveError("warnings манифеста должен быть кортежем строк")

    def get(self, trigger_id: str) -> Optional[RiveTrigger]:
        for trigger in self.triggers:
            if trigger.id == trigger_id:
                return trigger
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "source_digest": self.source_digest,
            "triggers": [item.to_dict() for item in self.triggers],
            "substitutions": dict(self.substitutions),
            "stats": dict(self.stats),
            "warnings": list(self.warnings),
        }

    def digest(self) -> str:
        return canonical_digest(self.to_dict())

    def save(self, path: Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(pretty_json(self.to_dict()), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: Path) -> "RiveManifest":
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RiveError(
                "не удалось прочитать манифест: %s" % source
            ) from exc
        except ValueError as exc:
            raise RiveError(
                "манифест не является JSON: %s" % source
            ) from exc
        if not isinstance(data, Mapping):
            raise RiveError("манифест должен быть объектом")
        triggers = data.get("triggers") or ()
        if not isinstance(triggers, (list, tuple)):
            raise RiveError("triggers манифеста должен быть списком")
        substitutions = _mapping(
            data.get("substitutions"), "substitutions"
        )
        try:
            version = int(data.get("version", MANIFEST_VERSION))
        except (TypeError, ValueError) as exc:
            raise RiveError("версия манифеста должна быть целой") from exc
        return cls(
            source_digest=str(data.get("source_digest") or ""),
            triggers=tuple(
                RiveTrigger.from_dict(item) for item in triggers
            ),
            substitutions={
                str(key): str(value)
                for key, value in substitutions.items()
            },
            stats=_mapping(data.get("stats"), "stats"),
            warnings=tuple(
                str(item) for item in (data.get("warnings") or ())
            ),
            version=version,
        )


def _add_trigger(
    candidates: List[RiveTrigger],
    warnings: List[str],
    trigger: RiveTrigger,
) -> None:
    if trigger.trigger:
        candidates.append(trigger)
    else:
        warnings.append("пустой триггер: %s" % trigger.id)


def compile_dialogue(
    dialogue_dir: Path = DEFAULT_DIALOGUE_DIR,
) -> RiveManifest:
    """Собрать манифест из JSON-источников диалога."""

    root = Path(dialogue_dir)
    paraphrases = _read_json(root / "paraphrases.json")
    actions = _read_json(root / "actions.json")
    lexicon = _read_json(root / "lexicon.json")
    grammar = _read_json(root / "grammar.json")

    entries = lexicon.get("entries") or ()
    if not isinstance(entries, (list, tuple)):
        raise RiveError("lexicon.entries должен быть списком")
    substitutions, conflicts = lexicon_substitutions(entries)
    warnings: List[str] = []
    if conflicts:
        warnings.append(
            "лексикон: %d неоднозначных форм оставлены парсеру"
            % len(conflicts)
        )

    candidates: List[RiveTrigger] = []
    phrases = paraphrases.get("phrases") or ()
    if not isinstance(phrases, (list, tuple)):
        raise RiveError("paraphrases.phrases должен быть списком")
    for phrase in phrases:
        data = _mapping(phrase, "парафраз")
        identifier = str(data.get("id") or "")
        text = str(data.get("text") or "")
        _add_trigger(
            candidates,
            warnings,
            RiveTrigger(
                id="p:%s" % identifier,
                trigger=_trigger_text(text, substitutions),
                source="paraphrase",
                text=text,
                kind=str(data.get("kind") or ""),
                expect=_mapping(data.get("expect"), "expect"),
            ),
        )

    action_items = actions.get("actions") or ()
    if not isinstance(action_items, (list, tuple)):
        raise RiveError("actions.actions должен быть списком")
    for action in action_items:
        data = _mapping(action, "действие")
        identifier = str(data.get("id") or "")
        for index, phrase in enumerate(data.get("phrases") or ()):
            text = str(phrase or "")
            _add_trigger(
                candidates,
                warnings,
                RiveTrigger(
                    id="a:%s:%d" % (identifier, index),
                    trigger=_trigger_text(text, substitutions),
                    source="action",
                    text=text,
                    action_id=identifier,
                ),
            )

    markers = actions.get("markers") or ()
    if not isinstance(markers, (list, tuple)):
        raise RiveError("actions.markers должен быть списком")
    for marker in markers:
        data = _mapping(marker, "маркер")
        act = str(data.get("act") or "")
        for index, phrase in enumerate(data.get("phrases") or ()):
            text = str(phrase or "")
            _add_trigger(
                candidates,
                warnings,
                RiveTrigger(
                    id="m:%s:%d" % (act, index),
                    trigger=_trigger_text(text, substitutions),
                    source="marker",
                    text=text,
                    kind=act,
                ),
            )

    candidates.sort(
        key=lambda item: (
            item.trigger,
            _SOURCE_ORDER[item.source],
            item.id,
        )
    )
    seen: Dict[str, RiveTrigger] = {}
    for item in candidates:
        if item.trigger in seen:
            warnings.append(
                "дубликат триггера %r: %s и %s"
                % (item.trigger, seen[item.trigger].id, item.id)
            )
            continue
        seen[item.trigger] = item
    triggers = tuple(seen[key] for key in sorted(seen))

    rules = grammar.get("rules") or ()
    if not isinstance(rules, (list, tuple)):
        raise RiveError("grammar.rules должен быть списком")
    source_digest = canonical_digest(
        {
            "paraphrases": paraphrases,
            "actions": actions,
            "lexicon": lexicon,
            "grammar": grammar,
        }
    )
    stats = {
        "compiler_version": COMPILER_VERSION,
        "lexicon_entries": len(entries),
        "lexicon_substitutions": len(substitutions),
        "lexicon_conflicts": len(conflicts),
        "grammar_rules": len(rules),
        "paraphrases": len(phrases),
        "actions": len(action_items),
        "markers": len(markers),
        "triggers": len(triggers),
    }
    return RiveManifest(
        source_digest=source_digest,
        triggers=triggers,
        substitutions=substitutions,
        stats=stats,
        warnings=tuple(warnings),
    )


def render_rive(manifest: RiveManifest) -> str:
    """Отрисовать детерминированный ``.rive`` из манифеста."""

    lines = [
        "// Сгенерировано campaign.cognition.rive_compiler.",
        "// Не редактировать вручную: источник — configs/dialogue.",
        "// source_digest: %s" % manifest.source_digest,
        "",
        "! version = 2.0",
        "",
        "// Лексикон: поверхностная форма → лемма.",
    ]
    for form, lemma in sorted(manifest.substitutions.items()):
        lines.append("! sub %s = %s" % (form, lemma))
    lines.extend(("", "// Точные триггеры."))
    for trigger in manifest.triggers:
        lines.append("+ %s" % trigger.trigger)
        lines.append("- <call>nlu %s</call>" % trigger.id)
    lines.extend(
        (
            "",
            "// Всё остальное уходит в legacy-разбор.",
            "+ *",
            "- <call>nlu __fallback__</call>",
            "",
        )
    )
    return "\n".join(lines)


def write_artifacts(
    dialogue_dir: Path = DEFAULT_DIALOGUE_DIR,
    rive_dir: Path = DEFAULT_RIVE_DIR,
) -> RiveManifest:
    """Перегенерировать ``.rive`` и манифест."""

    manifest = compile_dialogue(dialogue_dir)
    target = Path(rive_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / RIVE_NAME).write_text(
        render_rive(manifest), encoding="utf-8"
    )
    manifest.save(target / MANIFEST_NAME)
    return manifest


def check_artifacts(
    dialogue_dir: Path = DEFAULT_DIALOGUE_DIR,
    rive_dir: Path = DEFAULT_RIVE_DIR,
) -> RiveManifest:
    """Проверить, что артефакты совпадают с JSON-источником."""

    manifest = compile_dialogue(dialogue_dir)
    target = Path(rive_dir)
    problems = []
    rive_path = target / RIVE_NAME
    if not rive_path.is_file():
        problems.append("нет файла %s" % rive_path)
    else:
        expected = render_rive(manifest)
        actual = rive_path.read_text(encoding="utf-8")
        if actual != expected:
            problems.append("%s устарел" % rive_path)
    manifest_path = target / MANIFEST_NAME
    if not manifest_path.is_file():
        problems.append("нет файла %s" % manifest_path)
    else:
        try:
            actual_manifest = RiveManifest.load(manifest_path)
        except RiveError as exc:
            problems.append(str(exc))
        else:
            if actual_manifest.to_dict() != manifest.to_dict():
                problems.append("%s устарел" % manifest_path)
    if problems:
        raise RiveError(
            "; ".join(problems)
            + ". Запустите python -m campaign.cognition.rive_compiler --write"
        )
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Компилятор диалогового JSON в RiveScript",
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dialogue-dir", default=str(DEFAULT_DIALOGUE_DIR))
    parser.add_argument("--rive-dir", default=str(DEFAULT_RIVE_DIR))
    args = parser.parse_args(argv)
    if not args.check and not args.write:
        args.check = True
    try:
        if args.write:
            manifest = write_artifacts(
                Path(args.dialogue_dir), Path(args.rive_dir)
            )
            print(
                "RiveScript обновлён: %d триггеров, %d замен"
                % (
                    len(manifest.triggers),
                    len(manifest.substitutions),
                )
            )
        else:
            manifest = check_artifacts(
                Path(args.dialogue_dir), Path(args.rive_dir)
            )
            print(
                "RiveScript в порядке: %d триггеров, %d замен"
                % (
                    len(manifest.triggers),
                    len(manifest.substitutions),
                )
            )
    except (RiveError, OSError) as exc:
        print("ошибка: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COMPILER_VERSION",
    "DEFAULT_DIALOGUE_DIR",
    "DEFAULT_RIVE_DIR",
    "MANIFEST_NAME",
    "MANIFEST_VERSION",
    "RIVE_NAME",
    "RiveError",
    "RiveManifest",
    "RiveTrigger",
    "check_artifacts",
    "compile_dialogue",
    "entry_forms",
    "lexicon_substitutions",
    "main",
    "one_token",
    "render_rive",
    "write_artifacts",
]
