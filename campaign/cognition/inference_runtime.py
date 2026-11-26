"""Исполнение логического вывода в Soar через SML.

Soar получает факты на ``input-link`` и строит прямое замыкание правил
из ``configs/soar/inference.soar``. Python не выводит факты: он только
выбирает из готового замыкания решения, упорядочивает их как легаси и
отсекает доказательства с повтором ``(правило, аргументы)`` на пути.

Глубина ограничена продукциями (``^height``), поэтому рекурсивные
правила вроде ``war_symmetric`` завершаются. Трассировка — те же
``ProofStep``, что и у ``InferenceEngine``: Soar создаёт узлы с
``^rule`` и ``^childN``, Python разворачивает их в дерево.
"""

from __future__ import annotations

import itertools
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .errors import BackendError, SoarError
from .inference_compiler import (
    DEFAULT_DIALOGUE_DIR,
    DEFAULT_SOAR_DIR,
    EMPTY_SYMBOL,
    INFERENCE_NAME,
    POLICY_NAME,
    InferenceModel,
    load_model,
)
from .soar_runtime import _kernel, production_blocks, soar_available

_AGENT_NAMES = itertools.count(1)
_ARG = re.compile(r"^arg(\d+)$")
_CHILD = re.compile(r"^child(\d+)$")


@dataclass(frozen=True)
class ProofNode:
    """Узел замыкания: факт или применение правила."""

    rel: str
    args: Tuple[str, ...]
    rule: str
    children: Tuple["ProofNode", ...] = ()
    order: int = 0
    height: int = 0


def _decode(value: str) -> str:
    return "" if value == EMPTY_SYMBOL else str(value)


def _encoded(value: str) -> str:
    return EMPTY_SYMBOL if value == "" else str(value)


def _child_signature(node: ProofNode) -> Tuple:
    return (
        node.rel,
        node.args,
        node.rule,
        tuple(_child_signature(child) for child in node.children),
    )


class SoarInference:
    """Прямое замыкание правил в Soar с выборкой решений в Python."""

    def __init__(
        self,
        catalog: Any,
        knowledge: Any,
        *,
        model: Optional[InferenceModel] = None,
        path: Optional[Path] = None,
        source_dir: Path = DEFAULT_SOAR_DIR,
        timeout_ms: Optional[float] = None,
        node_limit: Optional[int] = None,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.model = model or load_model(Path(source_dir) / INFERENCE_NAME)
        self.path = Path(path) if path else Path(source_dir) / POLICY_NAME
        try:
            self.text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BackendError(
                "нет сгенерированного вывода Soar: %s. "
                "Запустите python -m campaign.cognition.inference_compiler "
                "--write" % self.path
            ) from exc
        self.timeout_ms = max(
            0.0,
            float(
                self.model.timeout_ms
                if timeout_ms is None
                else timeout_ms
            ),
        )
        self.node_limit = int(
            self.model.node_limit if node_limit is None else node_limit
        )
        if self.node_limit < 1:
            raise BackendError("node_limit должен быть >= 1")
        self.max_depth = max(1, int(catalog.max_depth))
        self.rules = tuple(
            sorted(catalog.rules, key=lambda rule: (-rule.priority, rule.id))
        )
        self._rules_by_id = {rule.id: rule for rule in self.rules}
        self._rules_by_rel: Dict[str, List[Any]] = {}
        for rule in self.rules:
            self._rules_by_rel.setdefault(rule.head.rel, []).append(rule)
        self._rule_order = {
            rule.id: index
            for rules in self._rules_by_rel.values()
            for index, rule in enumerate(rules)
        }
        self._nodes: Tuple[ProofNode, ...] = ()
        self._by_rel: Dict[str, Tuple[ProofNode, ...]] = {}
        self._rank: Dict[int, Tuple] = {}
        self._proof: Dict[int, Any] = {}
        self._cache: Dict[Tuple[str, Tuple[str, ...]], Tuple[Any, ...]] = {}
        self._built = False
        self._failure: Optional[BaseException] = None
        self.last_elapsed_ms = 0.0
        self.queries = 0
        self.cache_hits = 0

    # --- построение замыкания --------------------------------------

    def _agent(self) -> Any:
        kernel = _kernel()
        agent = kernel.CreateAgent("inference_%d" % next(_AGENT_NAMES))
        if agent is None:
            raise SoarError("Soar не создал агента")
        return agent

    def _prepare(self, agent: Any) -> None:
        for command in self.model.commands():
            agent.ExecuteCommandLine(command)
        blocks = production_blocks(self.text)
        if not blocks:
            raise SoarError("в inference.soar нет продукций")
        for block in blocks:
            result = agent.ExecuteCommandLine(block)
            if str(result or "").strip() != "*":
                raise SoarError(
                    "Soar отклонил продукцию: %s" % (result,)
                )

    def _check_budget(self, started: float) -> None:
        if not self.timeout_ms:
            return
        elapsed = (time.perf_counter() - started) * 1000.0
        if elapsed > self.timeout_ms:
            raise SoarError(
                "Soar превысил бюджет вывода: %.2f мс > %.2f мс"
                % (elapsed, self.timeout_ms)
            )

    def _build(self) -> None:
        started = time.perf_counter()
        agent = self._agent()
        try:
            self._prepare(agent)
            facts = self._insert_facts(agent)
            agent.SynchronizeInputLink()
            for _cycle in range(self.model.run_cycles):
                self._check_budget(started)
                agent.RunSelf(1)
            nodes = self._read_nodes(agent, facts)
        finally:
            _kernel().DestroyAgent(agent)
            self.last_elapsed_ms = (
                time.perf_counter() - started
            ) * 1000.0
        if self.timeout_ms and self.last_elapsed_ms > self.timeout_ms:
            raise SoarError(
                "Soar превысил бюджет вывода: %.2f мс > %.2f мс"
                % (self.last_elapsed_ms, self.timeout_ms)
            )
        if len(nodes) > self.node_limit:
            raise SoarError(
                "Soar построил %d узлов > лимита %d"
                % (len(nodes), self.node_limit)
            )
        annotated = self._dedupe(nodes)
        self._nodes = annotated
        by_rel: Dict[str, List[ProofNode]] = {}
        for node in annotated:
            by_rel.setdefault(node.rel, []).append(node)
        self._by_rel = {
            rel: tuple(items) for rel, items in by_rel.items()
        }
        self._prepare_indexes(annotated)
        self._built = True

    def _insert_facts(
        self, agent: Any
    ) -> Dict[Tuple[str, Tuple[str, ...]], ProofNode]:
        link = agent.GetInputLink()
        facts: Dict[Tuple[str, Tuple[str, ...]], ProofNode] = {}
        order_by_rel: Dict[str, int] = {}
        for fact in self.knowledge.facts:
            order = order_by_rel.get(fact.rel, 0)
            order_by_rel[fact.rel] = order + 1
            identifier = agent.CreateIdWME(link, "node")
            agent.CreateStringWME(identifier, "kind", "fact")
            agent.CreateStringWME(identifier, "rel", fact.rel)
            for index, arg in enumerate(fact.args, 1):
                agent.CreateStringWME(
                    identifier, "arg%d" % index, _encoded(str(arg))
                )
            agent.CreateIntWME(identifier, "height", 0)
            key = (
                str(fact.rel),
                tuple(str(arg) for arg in fact.args),
            )
            facts.setdefault(
                key,
                ProofNode(
                    rel=key[0],
                    args=key[1],
                    rule="fact",
                    children=(),
                    order=order,
                    height=0,
                ),
            )
        return facts

    def _read_nodes(
        self,
        agent: Any,
        facts: Mapping[Tuple[str, Tuple[str, ...]], ProofNode],
    ) -> List[ProofNode]:
        output = agent.GetOutputLink()
        if output is None:
            raise SoarError("Soar не создал output-link")
        by_name: Dict[str, ProofNode] = {}
        nodes: List[ProofNode] = []
        seen = set()
        for index in range(output.GetNumberChildren()):
            child = output.GetChild(index)
            if child.GetAttribute() != "node":
                continue
            name = child.GetValueAsString()
            identifier = child.ConvertToIdentifier()
            node = self._read_node(
                name, identifier, by_name, facts, set()
            )
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            nodes.append(node)
        return nodes

    def _read_node(
        self,
        name: str,
        identifier: Any,
        by_name: Dict[str, ProofNode],
        facts: Mapping[Tuple[str, Tuple[str, ...]], ProofNode],
        path: set,
    ) -> ProofNode:
        if name in by_name:
            return by_name[name]
        if name in path:
            raise SoarError("циклическая ссылка в выводе Soar")
        attrs: Dict[str, str] = {}
        children: Dict[str, Tuple[str, Any]] = {}
        for index in range(identifier.GetNumberChildren()):
            wme = identifier.GetChild(index)
            attribute = wme.GetAttribute()
            if _CHILD.match(attribute):
                children[attribute] = (
                    wme.GetValueAsString(),
                    wme.ConvertToIdentifier(),
                )
            else:
                attrs[attribute] = wme.GetValueAsString()
        kind = attrs.get("kind")
        if kind == "fact":
            arg_keys = sorted(
                (key for key in attrs if _ARG.match(key)),
                key=lambda key: int(_ARG.match(key).group(1)),
            )
            rel = attrs.get("rel", "")
            args = tuple(_decode(attrs[key]) for key in arg_keys)
            node = facts.get((rel, args))
            if node is None:
                raise SoarError(
                    "Soar вернул неизвестный факт %r" % ((rel, args),)
                )
            by_name[name] = node
            return node
        if kind != "derived":
            raise SoarError(
                "неизвестный узел вывода Soar: %r" % (kind,)
            )
        rule_id = attrs.get("rule", "")
        rule = self._rules_by_id.get(rule_id)
        if rule is None:
            raise SoarError(
                "Soar вывел неизвестное правило %r" % (rule_id,)
            )
        rel = attrs.get("rel", "")
        if rel != rule.head.rel:
            raise SoarError(
                "Soar вывел %r по правилу %r с головой %r"
                % (rel, rule_id, rule.head.rel)
            )
        arg_keys = sorted(
            (key for key in attrs if _ARG.match(key)),
            key=lambda key: int(_ARG.match(key).group(1)),
        )
        args = tuple(_decode(attrs[key]) for key in arg_keys)
        if len(args) != len(rule.head.args):
            raise SoarError(
                "Soar вывел %r с %d аргументами вместо %d"
                % (rel, len(args), len(rule.head.args))
            )
        child_keys = sorted(
            (key for key in children if _CHILD.match(key)),
            key=lambda key: int(_CHILD.match(key).group(1)),
        )
        if len(child_keys) != len(rule.premises):
            raise SoarError(
                "Soar вывел %r с %d посылками вместо %d"
                % (rel, len(child_keys), len(rule.premises))
            )
        path.add(name)
        try:
            child_nodes = tuple(
                self._read_node(
                    children[key][0],
                    children[key][1],
                    by_name,
                    facts,
                    path,
                )
                for key in child_keys
            )
        finally:
            path.discard(name)
        try:
            height = int(attrs.get("height", "-1"))
        except (TypeError, ValueError) as exc:
            raise SoarError("Soar вывел узел без высоты") from exc
        expected = 1 + max(
            (child.height for child in child_nodes), default=-1
        )
        if height != expected:
            raise SoarError(
                "Soar вывел %r с высотой %d вместо %d"
                % (rel, height, expected)
            )
        node = ProofNode(
            rel=rel,
            args=args,
            rule=rule_id,
            children=child_nodes,
            height=height,
        )
        by_name[name] = node
        return node

    def _dedupe(self, nodes: Sequence[ProofNode]) -> Tuple[ProofNode, ...]:
        """Убрать повторные узлы, сохранив порядок и все факты.

        Soar может создать один и тот же вывод несколько раз, если
        продукция сработала на разных идентификаторах с одинаковой
        структурой. Факты не дедуплицируются: их порядок задаёт
        ``knowledge.facts``.
        """

        memo: Dict[int, ProofNode] = {}

        def visit(node: ProofNode) -> ProofNode:
            key = id(node)
            if key in memo:
                return memo[key]
            if node.rule == "fact":
                memo[key] = node
                return node
            result = replace(
                node,
                children=tuple(visit(child) for child in node.children),
            )
            memo[key] = result
            return result

        unique: List[ProofNode] = []
        seen = set()
        for node in nodes:
            visited = visit(node)
            if visited.rule == "fact":
                unique.append(visited)
                continue
            signature = _child_signature(visited)
            if signature in seen:
                continue
            seen.add(signature)
            unique.append(visited)
        return tuple(unique)

    def _validate(
        self,
        node: ProofNode,
        bindings: Mapping[str, str],
        guards: frozenset = frozenset(),
    ) -> Optional[Dict[str, str]]:
        """Согласовать наземный узел с правилами и вернуть связывания.

        Правила в ``rules.json`` используют общий набор переменных:
        переменная, связанная в голове, действует и в посылках. Поэтому
        одного совпадения аргументов мало — нужно заново унифицировать
        голову и все посылки, как это делает ``InferenceEngine``.
        Повтор ``(правило, аргументы)`` на пути доказательства означает
        цикл и отсекается.
        """

        from campaign.dialogue.inference import unify

        if node.rule == "fact":
            return dict(bindings)
        key = (node.rule, node.args)
        if key in guards:
            return None
        rule = self._rules_by_id.get(node.rule)
        if rule is None:
            return None
        bound = unify(rule.head.args, node.args, bindings)
        if bound is None:
            return None
        next_guards = guards | {key}
        for premise, child in zip(rule.premises, node.children):
            bound = unify(premise.args, child.args, bound)
            if bound is None:
                return None
            bound = self._validate(child, bound, next_guards)
            if bound is None:
                return None
        return bound

    def _prepare_indexes(self, nodes: Sequence[ProofNode]) -> None:
        rank: Dict[int, Tuple] = {}
        proof: Dict[int, Any] = {}

        def rank_of(node: ProofNode) -> Tuple:
            key = id(node)
            if key in rank:
                return rank[key]
            if node.rule == "fact":
                value: Tuple = (0, node.order)
            else:
                value = (
                    1,
                    self._rule_order[node.rule],
                ) + tuple(rank_of(child) for child in node.children)
            rank[key] = value
            return value

        from campaign.dialogue.inference import Atom, ProofStep

        def proof_of(node: ProofNode) -> Any:
            key = id(node)
            if key in proof:
                return proof[key]
            if node.rule == "fact":
                step = ProofStep(
                    atom=Atom(node.rel, node.args),
                    rule="fact",
                )
            else:
                rule = self._rules_by_id[node.rule]
                step = ProofStep(
                    atom=Atom(node.rel, node.args),
                    rule=node.rule,
                    children=tuple(
                        proof_of(child) for child in node.children
                    ),
                    because=rule.because,
                )
            proof[key] = step
            return step

        for node in nodes:
            rank_of(node)
            proof_of(node)
        self._rank = rank
        self._proof = proof

    def _ensure(self) -> None:
        if self._built:
            return
        if self._failure is not None:
            raise self._failure
        try:
            self._build()
        except BaseException as exc:
            self._failure = exc
            raise

    # --- запросы ---------------------------------------------------

    def prove(
        self, relation: str, args: Sequence[str] = ()
    ) -> Tuple[Any, ...]:
        self._ensure()
        from campaign.dialogue.inference import (
            Solution,
            canonical,
            is_variable,
        )

        rel = str(relation)
        pattern = tuple(str(item) for item in args)
        key = (rel, pattern)
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached
        found: List[Tuple[Tuple, ProofNode, Dict[str, str]]] = []
        for node in self._by_rel.get(rel, ()):
            if node.height > self.max_depth:
                continue
            if len(node.args) != len(pattern):
                continue
            bindings: Dict[str, str] = {}
            matched = True
            for item, value in zip(pattern, node.args):
                if is_variable(item):
                    if item in bindings and bindings[item] != value:
                        matched = False
                        break
                    bindings[item] = value
                elif item != value:
                    matched = False
                    break
            if not matched:
                continue
            bound = self._validate(node, bindings)
            if bound is None:
                continue
            found.append(
                (self._rank[id(node)], node, canonical(bound))
            )
        found.sort(key=lambda item: item[0])
        seen = set()
        result: List[Any] = []
        for _rank, node, bindings in found:
            step = self._proof[id(node)]
            signature = (
                tuple(sorted(bindings.items())),
                step.signature(),
            )
            if signature in seen:
                continue
            seen.add(signature)
            result.append(Solution(dict(bindings), step))
        value = tuple(result)
        self._cache[key] = value
        self.queries += 1
        return value

    def first(
        self, relation: str, *args: str
    ) -> Optional[Any]:
        results = self.prove(relation, args)
        return results[0] if results else None

    def has(self, relation: str, *args: str) -> bool:
        return bool(self.prove(relation, args))

    # --- отчёт -----------------------------------------------------

    @property
    def nodes(self) -> int:
        return len(self._nodes)

    @property
    def derived(self) -> int:
        return sum(1 for node in self._nodes if node.rule != "fact")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": "soar",
            "available": True,
            "ok": self._built,
            "nodes": self.nodes,
            "derived": self.derived,
            "elapsed_ms": round(self.last_elapsed_ms, 3),
            "queries": self.queries,
            "cache_hits": self.cache_hits,
            "max_depth": self.max_depth,
        }


def check_artifacts(
    source_dir: Path = DEFAULT_SOAR_DIR,
    dialogue_dir: Path = DEFAULT_DIALOGUE_DIR,
) -> InferenceModel:
    """Проверить, что ``inference.soar`` совпадает с JSON."""

    from .inference_compiler import check_policy

    return check_policy(source_dir, dialogue_dir)


__all__ = [
    "ProofNode",
    "SoarInference",
    "check_artifacts",
    "soar_available",
]
