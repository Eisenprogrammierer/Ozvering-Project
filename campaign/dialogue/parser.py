"""Детерминированный chart-парсер диалогового слоя.

Грамматика и лексикон приходят из JSON. Парсер не знает русского языка
как такового: он умеет сопоставлять формы, унифицировать признаки и
собирать семантику по шаблонам правил.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .errors import DialogueError
from .morphology import tokenize
from .model import DialogueCatalog, Grammar, GrammarRule, LexEntry, Parse, RuleItem
from .semantics import flatten, substitute

# Признаки отдельной лексемы. Они не наследуются родителем: иначе лемма
# подлежащего столкнётся с леммой сказуемого. Согласование переносит
# только вершинный ребёнок, названный в поле ``head`` правила.
LOCAL_FEATURES = frozenset({"lemma", "entry"})


def merge_features(
    *mappings: Mapping[str, str],
) -> Optional[Dict[str, str]]:
    """Объединить признаки; вернуть ``None`` при конфликте."""

    result: Dict[str, str] = {}
    for mapping in mappings:
        for key, value in (mapping or {}).items():
            key = str(key)
            value = str(value)
            if key in result and result[key] != value:
                return None
            result[key] = value
    return result


def percolate(features: Mapping[str, str]) -> Dict[str, str]:
    """Оставить только признаки, допустимые к наследованию."""

    return {
        str(key): str(value)
        for key, value in (features or {}).items()
        if str(key) not in LOCAL_FEATURES
    }


def features_match(
    actual: Mapping[str, str], required: Mapping[str, str]
) -> bool:
    """Проверить, что фактические признаки удовлетворяют требованию."""

    for key, value in (required or {}).items():
        if str(actual.get(str(key), "")) != str(value):
            return False
    return True


class ChartParser:
    """Разбор фразы по данным лексикона и грамматики."""

    def __init__(self, catalog: DialogueCatalog):
        self.catalog = catalog
        self.grammar: Grammar = catalog.grammar
        self.lexicon: Tuple[LexEntry, ...] = catalog.lexicon

    def parse(self, text: str) -> List[Parse]:
        """Вернуть все полные разборы, отсортированные детерминированно."""

        tokens = tokenize(text)
        if not tokens:
            return []
        chart: Dict[Tuple[str, int, int], Dict[Tuple[Any, ...], Parse]] = (
            defaultdict(dict)
        )
        self._seed(tokens, chart)
        changed = True
        while changed:
            changed = False
            for rule in self.grammar.rules:
                for start in range(len(tokens)):
                    for end in range(start + 1, len(tokens) + 1):
                        for parse in self._apply_rule(
                            rule, chart, tokens, start, end
                        ):
                            bucket = chart[(rule.lhs, start, end)]
                            key = parse.key()
                            if key not in bucket:
                                bucket[key] = parse
                                changed = True
        bucket = chart.get((self.grammar.start, 0, len(tokens)), {})
        result = list(bucket.values())
        result.sort(
            key=lambda item: (
                item.rule,
                repr(item.sem),
                tuple(sorted(item.features.items())),
            )
        )
        return result

    def parse_one(self, text: str) -> Optional[Parse]:
        """Первый (канонический) разбор или ``None``."""

        parses = self.parse(text)
        return parses[0] if parses else None

    def _parse_depth(self, parse: Parse) -> int:
        """Глубина дерева: больше правил — более специфичный разбор."""

        if not parse.children:
            return 0
        return 1 + max(self._parse_depth(child) for child in parse.children)

    def _rank_key(self, parse: Parse, index: int) -> Tuple[Any, ...]:
        """Детерминированный ключ приоритета разбора.

        Никаких вероятностей: порядок видов берётся из
        ``parsing.json``; при равном виде сохраняется канонический
        порядок чарта. ``prefer_depth`` — необязательный data-флаг,
        который поднимает более специфичные деревья.
        """

        spec = self.catalog.parsing or {}
        priority = [str(item) for item in spec.get("kind_priority") or ()]
        kind = (
            str(parse.sem.get("kind") or "")
            if isinstance(parse.sem, Mapping)
            else ""
        )
        try:
            rank = priority.index(kind)
        except ValueError:
            rank = len(priority)
        depth = (
            self._parse_depth(parse)
            if spec.get("prefer_depth", False)
            else 0
        )
        return (rank, -depth, index)

    def parse_beam(self, text: str) -> Tuple[Parse, ...]:
        """Детерминированный beam: лучшие ``beam_width`` разборов."""

        parses = self.parse(text)
        if not parses:
            return ()
        spec = self.catalog.parsing or {}
        try:
            width = int(spec.get("beam_width") or 16)
        except (TypeError, ValueError):
            width = 16
        width = max(1, width)
        ranked = sorted(
            enumerate(parses),
            key=lambda pair: self._rank_key(pair[1], pair[0]),
        )
        return tuple(parse for _, parse in ranked[:width])

    def parse_best(self, text: str) -> Optional[Parse]:
        """Лучший разбор по данным ``parsing.json`` (или канонический)."""

        if not self.catalog.parsing:
            return self.parse_one(text)
        beam = self.parse_beam(text)
        return beam[0] if beam else None

    def _seed(
        self,
        tokens: Sequence[str],
        chart: Dict[Tuple[str, int, int], Dict[Tuple[Any, ...], Parse]],
    ) -> None:
        for start in range(len(tokens)):
            for entry in self.lexicon:
                for form in entry.all_forms():
                    form_tokens = tokenize(form.text)
                    if not form_tokens:
                        continue
                    end = start + len(form_tokens)
                    if end > len(tokens):
                        continue
                    if list(tokens[start:end]) != form_tokens:
                        continue
                    features = merge_features(
                        entry.features,
                        form.features,
                        {"lemma": entry.lemma, "entry": entry.id},
                    )
                    if features is None:
                        continue
                    parse = Parse(
                        cat=entry.cat,
                        start=start,
                        end=end,
                        sem=dict(entry.semantic),
                        features=features,
                        rule="lex:%s" % entry.id,
                        text=" ".join(tokens[start:end]),
                    )
                    chart[(entry.cat, start, end)][parse.key()] = parse

    def _apply_rule(
        self,
        rule: GrammarRule,
        chart: Dict[Tuple[str, int, int], Dict[Tuple[Any, ...], Parse]],
        tokens: Sequence[str],
        start: int,
        end: int,
    ) -> Iterable[Parse]:
        for roles, children in self._match_rhs(
            rule.rhs, chart, start, end, 0, {}, ()
        ):
            inherited: List[Mapping[str, str]] = []
            if rule.head:
                for index, item in enumerate(rule.rhs):
                    role = item.role or str(index + 1)
                    if role == rule.head:
                        inherited.append(percolate(children[index].features))
                        break
            merged = merge_features(rule.features, *inherited)
            if merged is None:
                continue
            try:
                sem = flatten(substitute(rule.sem, roles))
            except DialogueError:
                continue
            yield Parse(
                cat=rule.lhs,
                start=start,
                end=end,
                sem=sem,
                features=merged,
                rule=rule.id,
                children=tuple(children),
                text=" ".join(tokens[start:end]),
            )

    def _match_rhs(
        self,
        rhs: Sequence[RuleItem],
        chart: Dict[Tuple[str, int, int], Dict[Tuple[Any, ...], Parse]],
        start: int,
        end: int,
        index: int,
        roles: Mapping[str, Any],
        children: Tuple[Parse, ...],
    ) -> Iterable[Tuple[Dict[str, Any], Tuple[Parse, ...]]]:
        if index >= len(rhs):
            if start == end:
                yield dict(roles), children
            return
        item = rhs[index]
        for split in range(start, end + 1):
            for parse in chart.get((item.cat, start, split), {}).values():
                if not features_match(parse.features, item.features):
                    continue
                role = item.role or str(index + 1)
                if role in roles:
                    continue
                next_roles = dict(roles)
                next_roles[role] = parse.sem
                yield from self._match_rhs(
                    rhs,
                    chart,
                    split,
                    end,
                    index + 1,
                    next_roles,
                    children + (parse,),
                )
