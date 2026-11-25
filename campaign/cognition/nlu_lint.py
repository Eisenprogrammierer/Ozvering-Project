"""Линтер NLU: покрытие лексикона, триггеров и неоднозначностей.

Линтер не меняет контент и не падает на неизвестных словах по
умолчанию: он показывает, какие фразы выйдут за пределы словаря. Это
нужно для пополнения JSON, а не для запрета живого языка.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from campaign.dialogue.morphology import tokenize

from .errors import RiveError
from .rive_compiler import (
    DEFAULT_DIALOGUE_DIR,
    compile_dialogue,
    entry_forms,
)


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


def known_tokens(entries: Any) -> set:
    """Все слова, которые лексикон знает в любой форме."""

    known = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        known.update(tokenize(entry.get("lemma") or ""))
        for form in entry_forms(entry):
            known.update(tokenize(form))
    return known


def collect_phrases(
    dialogue_dir: Path = DEFAULT_DIALOGUE_DIR,
) -> List[Tuple[str, str]]:
    """Пары ``(id, text)`` из парафраз, действий и маркеров."""

    root = Path(dialogue_dir)
    phrases: List[Tuple[str, str]] = []
    data = _read_json(root / "paraphrases.json")
    for item in data.get("phrases") or ():
        if isinstance(item, Mapping):
            phrases.append(
                (
                    str(item.get("id") or ""),
                    str(item.get("text") or ""),
                )
            )
    actions = _read_json(root / "actions.json")
    for item in actions.get("actions") or ():
        if not isinstance(item, Mapping):
            continue
        identifier = str(item.get("id") or "")
        for text in item.get("phrases") or ():
            phrases.append((identifier, str(text or "")))
    for item in actions.get("markers") or ():
        if not isinstance(item, Mapping):
            continue
        identifier = "marker:%s" % (item.get("act") or "")
        for text in item.get("phrases") or ():
            phrases.append((identifier, str(text or "")))
    return phrases


@dataclass(frozen=True)
class LintReport:
    phrases: int
    unknown: Tuple[Tuple[str, Tuple[str, ...]], ...]
    warnings: Tuple[str, ...]
    stats: Mapping[str, Any]

    def ok(self) -> bool:
        return not self.unknown

    def render(self) -> str:
        lines = [
            "NLU lint: %d фраз, %d неизвестных слов"
            % (self.phrases, len(self.unknown)),
            "  лексикон: %s записей, %s замен"
            % (
                self.stats.get("lexicon_entries", 0),
                self.stats.get("lexicon_substitutions", 0),
            ),
            "  триггеры: %s, конфликты: %s"
            % (
                self.stats.get("triggers", 0),
                self.stats.get("lexicon_conflicts", 0),
            ),
        ]
        for token, ids in self.unknown[:20]:
            lines.append(
                "  ? %s: %s" % (token, ", ".join(ids))
            )
        for warning in self.warnings[:10]:
            lines.append("  ! %s" % warning)
        return "\n".join(lines)


def lint_dialogue(
    dialogue_dir: Path = DEFAULT_DIALOGUE_DIR,
) -> LintReport:
    """Собрать отчёт по покрытию без изменения файлов."""

    root = Path(dialogue_dir)
    lexicon = _read_json(root / "lexicon.json")
    entries = lexicon.get("entries") or ()
    if not isinstance(entries, (list, tuple)):
        raise RiveError("lexicon.entries должен быть списком")
    known = known_tokens(entries)
    unknown: Dict[str, List[str]] = {}
    phrases = collect_phrases(root)
    for identifier, text in phrases:
        for token in tokenize(text):
            if token not in known:
                unknown.setdefault(token, []).append(identifier)
    manifest = compile_dialogue(root)
    return LintReport(
        phrases=len(phrases),
        unknown=tuple(
            (token, tuple(sorted(set(unknown[token]))))
            for token in sorted(unknown)
        ),
        warnings=manifest.warnings,
        stats=manifest.stats,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Линтер покрытия диалогового NLU",
    )
    parser.add_argument("--dialogue-dir", default=str(DEFAULT_DIALOGUE_DIR))
    parser.add_argument(
        "--strict",
        action="store_true",
        help="вернуть код 1 при неизвестных словах",
    )
    args = parser.parse_args(argv)
    try:
        report = lint_dialogue(Path(args.dialogue_dir))
    except (RiveError, OSError) as exc:
        print("ошибка: %s" % exc)
        return 1
    print(report.render())
    if args.strict and not report.ok():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LintReport",
    "collect_phrases",
    "known_tokens",
    "lint_dialogue",
    "main",
]
