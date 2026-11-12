"""Проверка диалоговых JSON: ссылки, категории, роли, покрытие."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Mapping, Set

from .errors import DialogueError
from .loader import DEFAULT_DIR, load_dialogue
from .model import DialogueCatalog, GrammarRule

_REF = re.compile(r"^\$([A-Za-z0-9_]+)(?:\.[A-Za-z0-9_.]+)?$")


def _walk_refs(value, found: Set[str]) -> None:
    if isinstance(value, str):
        match = _REF.match(value)
        if match:
            found.add(match.group(1))
        return
    if isinstance(value, list):
        for item in value:
            _walk_refs(item, found)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _walk_refs(item, found)


def _rule_problems(rule: GrammarRule) -> List[str]:
    problems: List[str] = []
    roles: Set[str] = set()
    for index, item in enumerate(rule.rhs):
        role = item.role or str(index + 1)
        if role in roles:
            problems.append(
                "правило %s: роль %r повторяется" % (rule.id, role)
            )
        roles.add(role)
    if rule.head and rule.head not in roles:
        problems.append(
            "правило %s: head %r не совпадает ни с одной ролью"
            % (rule.id, rule.head)
        )
    refs: Set[str] = set()
    _walk_refs(rule.sem, refs)
    for ref in sorted(refs):
        if ref not in roles:
            problems.append(
                "правило %s: семантика ссылается на неизвестную роль %r"
                % (rule.id, ref)
            )
    return problems


def lint_catalog(catalog: DialogueCatalog) -> List[str]:
    problems: List[str] = []
    lexicon_cats = {entry.cat for entry in catalog.lexicon}
    lhs_cats = {rule.lhs for rule in catalog.grammar.rules}
    known_cats = lexicon_cats | lhs_cats

    if catalog.grammar.start not in lhs_cats:
        problems.append(
            "грамматика: стартовый символ %r не является lhs ни одного "
            "правила" % catalog.grammar.start
        )

    for rule in catalog.grammar.rules:
        problems.extend(_rule_problems(rule))
        for item in rule.rhs:
            if item.cat not in known_cats:
                problems.append(
                    "правило %s: неизвестная категория %r"
                    % (rule.id, item.cat)
                )

    entity_types = set(catalog.ontology.entity_types)
    for entry in catalog.lexicon:
        if not entry.all_forms():
            problems.append(
                "лексема %s: нет ни одной поверхностной формы" % entry.id
            )
        semantic = entry.semantic
        if isinstance(semantic, Mapping):
            kind = semantic.get("kind")
            if kind == "entity":
                entry_type = str(semantic.get("type") or "")
                if entry_type and entry_type not in entity_types:
                    problems.append(
                        "лексема %s: тип %r отсутствует в онтологии"
                        % (entry.id, entry_type)
                    )
    return problems


def lint_directory(directory: Path | str | None = None) -> List[str]:
    root = Path(directory) if directory is not None else DEFAULT_DIR
    try:
        catalog = load_dialogue(root)
    except DialogueError as error:
        return [str(error)]
    return lint_catalog(catalog)


def main() -> int:
    problems = lint_directory()
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print("диалоговые данные в порядке")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
