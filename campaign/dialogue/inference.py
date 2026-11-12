"""Детерминированный логический вывод с трассировкой.

Правила живут в ``rules.json``. Движок умеет только унифицировать атомы,
доказывать посылки и возвращать объяснение; никаких предметных знаний в
коде нет.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

from .knowledge import AgentKnowledge, Fact
from .model import AtomSpec, DialogueCatalog, RuleSpec


@dataclass(frozen=True)
class Atom:
    rel: str
    args: Tuple[str, ...] = ()

    def __str__(self) -> str:
        if not self.args:
            return self.rel
        return "%s(%s)" % (self.rel, ", ".join(self.args))

    def key(self) -> Tuple[str, Tuple[str, ...]]:
        return (self.rel, self.args)


@dataclass(frozen=True)
class ProofStep:
    """Один шаг доказательства: факт или применение правила."""

    atom: Atom
    rule: str
    children: Tuple["ProofStep", ...] = ()
    because: str = ""

    def signature(self) -> Tuple:
        return (
            self.atom.key(),
            self.rule,
            tuple(child.signature() for child in self.children),
        )

    def lines(self, depth: int = 0) -> Tuple[str, ...]:
        prefix = "  " * depth
        suffix = " [факт]" if self.rule == "fact" else " [%s]" % self.rule
        result = [prefix + str(self.atom) + suffix]
        for child in self.children:
            result.extend(child.lines(depth + 1))
        return tuple(result)


@dataclass(frozen=True)
class Solution:
    bindings: Mapping[str, str]
    proof: ProofStep


def is_variable(value: str) -> bool:
    return isinstance(value, str) and value.startswith("$")


def resolve_term(term: str, bindings: Mapping[str, str]) -> str:
    """Разрешить цепочку связей ``$x → $y → значение``."""

    seen: set = set()
    current = str(term)
    while is_variable(current) and current in bindings:
        if current in seen:
            break
        seen.add(current)
        current = str(bindings[current])
    return current


def _unify_arg(
    left: str, right: str, bindings: Dict[str, str]
) -> Optional[Dict[str, str]]:
    """Симметричная унификация: переменная может быть с любой стороны."""

    left = resolve_term(left, bindings)
    right = resolve_term(right, bindings)
    if left == right:
        return bindings
    if is_variable(left):
        result = dict(bindings)
        result[left] = right
        return result
    if is_variable(right):
        result = dict(bindings)
        result[right] = left
        return result
    return None


def unify(
    pattern: Tuple[str, ...],
    values: Tuple[str, ...],
    bindings: Mapping[str, str],
) -> Optional[Dict[str, str]]:
    if len(pattern) != len(values):
        return None
    result = dict(bindings)
    for item, value in zip(pattern, values):
        result = _unify_arg(str(item), str(value), result)
        if result is None:
            return None
    return result


def canonical(bindings: Mapping[str, str]) -> Dict[str, str]:
    """Оставить только переменные, связанные с конкретными значениями."""

    result: Dict[str, str] = {}
    for key in bindings:
        value = resolve_term(key, bindings)
        if not is_variable(value):
            result[str(key)] = value
    return result


class InferenceEngine:
    """Обратный вывод по правилам с ограничением глубины и циклов."""

    def __init__(self, catalog: DialogueCatalog, knowledge: AgentKnowledge):
        self.catalog = catalog
        self.knowledge = knowledge
        self.max_depth = max(1, int(catalog.max_depth))
        self.rules = tuple(
            sorted(catalog.rules, key=lambda item: (-item.priority, item.id))
        )
        self._rules_by_rel: Dict[str, List[RuleSpec]] = {}
        for rule in self.rules:
            self._rules_by_rel.setdefault(rule.head.rel, []).append(rule)

    def prove(
        self, relation: str, args: Iterable[str] = ()
    ) -> Tuple[Solution, ...]:
        atom = Atom(str(relation), tuple(str(item) for item in args))
        return tuple(
            Solution(canonical(solution.bindings), solution.proof)
            for solution in self._solve(atom, {}, 0, frozenset())
        )

    def has(self, relation: str, *args: str) -> bool:
        return bool(self.prove(relation, args))

    def first(
        self, relation: str, *args: str
    ) -> Optional[Solution]:
        results = self.prove(relation, args)
        return results[0] if results else None

    def _solve(
        self,
        atom: Atom,
        bindings: Mapping[str, str],
        depth: int,
        stack: frozenset,
    ) -> Tuple[Solution, ...]:
        if depth > self.max_depth:
            return ()
        results: List[Solution] = []
        seen: set = set()

        def emit(solution: Solution, signature: Tuple) -> None:
            if signature in seen:
                return
            seen.add(signature)
            results.append(solution)

        for fact in self.knowledge.facts_for(atom.rel):
            if len(fact.args) != len(atom.args):
                continue
            bound = unify(fact.args, atom.args, bindings)
            if bound is None:
                continue
            step = ProofStep(atom=Atom(fact.rel, fact.args), rule="fact")
            emit(
                Solution(dict(bound), step),
                (
                    tuple(sorted(canonical(bound).items())),
                    step.signature(),
                ),
            )

        for rule in self._rules_by_rel.get(atom.rel, ()):
            head = rule.head
            bound = unify(head.args, atom.args, bindings)
            if bound is None:
                continue
            bound_args = tuple(
                resolve_term(arg, bound) for arg in head.args
            )
            guard = (rule.id, bound_args)
            if guard in stack:
                continue
            for premise_bindings, premise_steps in self._prove_premises(
                rule.premises,
                0,
                bound,
                depth + 1,
                stack | {guard},
            ):
                final = canonical(premise_bindings)
                resolved_head = tuple(
                    resolve_term(arg, premise_bindings)
                    for arg in head.args
                )
                step = ProofStep(
                    atom=Atom(rule.head.rel, resolved_head),
                    rule=rule.id,
                    children=premise_steps,
                    because=rule.because,
                )
                emit(
                    Solution(dict(premise_bindings), step),
                    (tuple(sorted(final.items())), step.signature()),
                )
        return tuple(results)

    def _prove_premises(
        self,
        premises: Tuple[AtomSpec, ...],
        index: int,
        bindings: Mapping[str, str],
        depth: int,
        stack: frozenset,
    ) -> Iterator[Tuple[Mapping[str, str], Tuple[ProofStep, ...]]]:
        if index >= len(premises):
            yield dict(bindings), ()
            return
        premise = premises[index]
        args = tuple(resolve_term(arg, bindings) for arg in premise.args)
        for solution in self._solve(
            Atom(premise.rel, args), bindings, depth, stack
        ):
            for final, steps in self._prove_premises(
                premises,
                index + 1,
                solution.bindings,
                depth,
                stack,
            ):
                yield final, (solution.proof,) + steps


def explain(engine: InferenceEngine, relation: str, args: Iterable[str]) -> str:
    """Текстовая трассировка для отладки; не используется в ответе."""

    solutions = engine.prove(relation, args)
    if not solutions:
        return "доказательство не найдено"
    return "\n".join(solutions[0].proof.lines())
