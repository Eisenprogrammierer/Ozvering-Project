"""Проекция каталога действий в реестр диалога (P5/F-13).

Реестр ``configs/dialogue/actions.json`` исторически был ручным списком
имперских действий. Модуль собирает тот же формат из любого каталога
``ActionSpec``: ``id``, ``label``, ``aliases`` и, если автор их задал,
``phrases``. Ручные записи остаются override: действие с тем же ``id``
из проекции не дублируется, а фраза, уже занятая ручной записью, не
перехватывается.

Модуль только читает и нормализует данные. Он не меняет ``load_dialogue``
по умолчанию, поэтому существующие каталоги и тесты с временными копиями
``configs/dialogue`` остаются изолированными.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from campaign.actions import ActionError, normalize_action

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORLD_ACTIONS = ROOT / "configs" / "worlds" / "actions"


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _tuple_text(values: Any) -> Tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return ()
    result: List[str] = []
    for value in values:
        text = _text(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def action_aliases(action: Mapping[str, Any]) -> Tuple[str, ...]:
    """Псевдонимы действия: явные ``aliases``, иначе сам ``id``."""

    aliases = _tuple_text(action.get("aliases"))
    if aliases:
        return aliases
    action_id = _text(action.get("id"))
    return (action_id,) if action_id else ()


def action_phrases(action: Mapping[str, Any]) -> Tuple[str, ...]:
    """Фразы-подсказки. Пусто, если автор их не задал.

    Проекция намеренно не выдумывает императив из ``label``: метка вида
    «Провести демонстрацию силы» не обязана разбираться грамматикой, а
    непроверяемая подсказка хуже её отсутствия.
    """

    return _tuple_text(action.get("phrases"))


def action_phrase(action: Mapping[str, Any]) -> str:
    """Первая фраза для UI, иначе метка, иначе ``id``."""

    phrases = action_phrases(action)
    if phrases:
        return phrases[0]
    return _text(
        action.get("label"),
        _text(action.get("id")),
    )


@dataclass(frozen=True)
class ProjectedAction:
    """Одна запись реестра диалога, полученная из ``ActionSpec``."""

    id: str
    label: str
    aliases: Tuple[str, ...]
    phrases: Tuple[str, ...] = ()
    source: str = ""

    def as_entry(self) -> dict:
        entry = {
            "id": self.id,
            "label": self.label,
            "aliases": list(self.aliases),
        }
        if self.phrases:
            entry["phrases"] = list(self.phrases)
        return entry


def project_action(
    action: Mapping[str, Any],
    forms: Any = None,
    source: str = "",
) -> ProjectedAction:
    """Нормализовать действие и превратить его в запись реестра."""

    data = normalize_action(action, forms=forms)
    action_id = _text(data.get("id"))
    if not action_id:
        raise ActionError("действие: пустой id")
    return ProjectedAction(
        id=action_id,
        label=_text(data.get("label"), action_id),
        aliases=action_aliases(data),
        phrases=action_phrases(data),
        source=_text(source),
    )


def project_actions(
    sources: Iterable[Tuple[str, Any]],
    forms: Any = None,
) -> Tuple[List[dict], List[str]]:
    """Собрать записи из источников ``(label, data)``.

    ``data`` — объект с ``actions`` или список действий. Внутри одного
    источника повтор ``id`` — проблема; между источниками побеждает
    более поздний (как в ``merge_action_catalogs``). Дубликат фразы
    отбрасывается: первая запись сохраняет подсказку.
    """

    entries: List[dict] = []
    problems: List[str] = []
    by_id: dict = {}
    phrase_owner: dict = {}
    for label, data in sources:
        if isinstance(data, Mapping):
            raw_actions = data.get("actions") or ()
        elif isinstance(data, (list, tuple)):
            raw_actions = data
        else:
            problems.append("%s: ожидался объект или список действий" % label)
            continue
        seen = set()
        for item in raw_actions:
            try:
                projected = project_action(
                    item, forms=forms, source=str(label)
                )
            except ActionError as exc:
                problems.append("%s: %s" % (label, exc))
                continue
            action_id = projected.id
            if action_id in seen:
                problems.append(
                    "%s: действие %s объявлено дважды" % (label, action_id)
                )
                continue
            seen.add(action_id)
            entry = projected.as_entry()
            phrases = []
            for phrase in entry.get("phrases") or ():
                owner = phrase_owner.get(phrase)
                if owner and owner != action_id:
                    continue
                phrase_owner[phrase] = action_id
                phrases.append(phrase)
            if phrases:
                entry["phrases"] = phrases
            else:
                entry.pop("phrases", None)
            if action_id in by_id:
                index = by_id[action_id]
                entries[index] = entry
            else:
                by_id[action_id] = len(entries)
                entries.append(entry)
    return entries, problems


def merge_actions(
    manual: Any,
    projected: Sequence[Mapping[str, Any]],
) -> Tuple[List[dict], List[dict]]:
    """Слить ручной реестр и проекцию; ручной реестр — override.

    Возвращает ``(entries, overrides)``. ``overrides`` описывает, какие
    проекции не попали в результат, потому что ``id`` уже объявлен вручную.
    """

    if isinstance(manual, Mapping):
        manual_entries = manual.get("actions") or ()
    elif isinstance(manual, (list, tuple)):
        manual_entries = manual
    else:
        manual_entries = ()
    entries: List[dict] = []
    seen_ids = set()
    phrase_owner = {}
    for item in manual_entries:
        entry = dict(item)
        action_id = _text(entry.get("id"))
        if action_id:
            seen_ids.add(action_id)
        for phrase in entry.get("phrases") or ():
            phrase_owner.setdefault(str(phrase), action_id)
        entries.append(entry)
    overrides: List[dict] = []
    for item in projected:
        entry = dict(item)
        action_id = _text(entry.get("id"))
        if not action_id:
            continue
        if action_id in seen_ids:
            overrides.append({"id": action_id, "reason": "manual"})
            continue
        phrases = []
        for phrase in entry.get("phrases") or ():
            owner = phrase_owner.get(str(phrase))
            if owner and owner != action_id:
                continue
            phrase_owner[str(phrase)] = action_id
            phrases.append(phrase)
        if phrases:
            entry["phrases"] = phrases
        else:
            entry.pop("phrases", None)
        seen_ids.add(action_id)
        entries.append(entry)
    return entries, overrides


def load_action_file(path: Path | str) -> Mapping[str, Any]:
    """Прочитать JSON-каталог действий; ошибка — ``ActionError``."""

    try:
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ActionError("%s: %s" % (path, exc))
    if not isinstance(data, Mapping):
        raise ActionError("%s: ожидался объект" % path)
    return data


def action_sources(
    directory: Path | str = DEFAULT_WORLD_ACTIONS,
) -> List[Tuple[str, Mapping[str, Any]]]:
    """Прочитать все ``*.json`` каталоги действий из каталога мира."""

    root = Path(directory)
    if not root.exists():
        return []
    sources: List[Tuple[str, Mapping[str, Any]]] = []
    for path in sorted(root.glob("*.json")):
        sources.append((path.stem, load_action_file(path)))
    return sources


def projected_registry(
    directory: Path | str = DEFAULT_WORLD_ACTIONS,
    manual: Optional[Mapping[str, Any]] = None,
    forms: Any = None,
) -> Tuple[dict, List[str], List[dict]]:
    """Готовый реестр ``actions.json``: проекция + ручной override."""

    entries, problems = project_actions(
        action_sources(directory), forms=forms
    )
    merged, overrides = merge_actions(manual or {}, entries)
    registry = {
        "schema": 1,
        "description": (
            "Проекция каталога действий мира; ручные записи — override."
        ),
        "actions": merged,
    }
    return registry, problems, overrides
