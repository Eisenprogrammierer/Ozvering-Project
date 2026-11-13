"""Контрфакты: временная подмена фактов и сравнение вывода.

D3.2. Движок не мутирует ``AgentKnowledge``: он собирает новый объект
тем же конструктором на основе копии фактов. Кампания и BDI не
затрагиваются. Подменяемые отношения ограничены whitelist-ом из
``counterfactual.json``; правила вывода не подменяются.

Сравнение базы и контрмодели идёт по ``ProofStep.signature()`` и
возвращает ``changed`` / ``unchanged`` / ``unknown``. Исход и число
отличий задаются данными.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Tuple

from .inference import InferenceEngine, Solution
from .knowledge import AgentKnowledge, Fact
from .model import CounterfactualSpec, DialogueCatalog


@dataclass(frozen=True)
class Difference:
    """Одно отличие в доказательстве: атом и правило шага."""

    rel: str
    args: Tuple[str, ...]
    rule: str

    def key(self) -> Tuple[str, Tuple[str, ...], str]:
        return (self.rel, self.args, self.rule)


@dataclass(frozen=True)
class CounterfactualResult:
    """Исход контрфакта: статус, отличия и конструкция синтеза."""

    outcome: str
    construction: str
    differences: Tuple[Difference, ...] = ()
    removed: Tuple[Fact, ...] = ()
    added: Tuple[Fact, ...] = ()
    base_proof: Optional[Solution] = None
    model_proof: Optional[Solution] = None


class CounterfactualEngine:
    """Подмена фактов и сравнение вывода для одного вопроса."""

    def __init__(
        self,
        catalog: DialogueCatalog,
        knowledge: AgentKnowledge,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.spec: Optional[CounterfactualSpec] = getattr(
            catalog, "counterfactual", None
        )
        self.allowed = set(
            getattr(self.spec, "relations", ()) if self.spec else ()
        )
        self.max_steps = int(
            getattr(self.spec, "max_steps", 2) if self.spec else 2
        )

    def enabled(self) -> bool:
        return bool(self.spec and self.allowed)

    def with_facts(
        self,
        remove: Iterable[Fact] = (),
        add: Iterable[Fact] = (),
    ) -> AgentKnowledge:
        """Собрать копию знания с подменёнными фактами.

        ``remove`` и ``add`` фильтруются по whitelist-у: отношение
        вне списка игнорируется. Это защищает от подмены правил и
        служебных фактов. Копия создаётся тем же конструктором, поэтому
        инварианты ``AgentKnowledge`` сохраняются.
        """

        remove_keys = {
            fact.key()
            for fact in remove
            if fact.rel in self.allowed
        }
        add_facts = [
            fact for fact in add if fact.rel in self.allowed
        ]
        add_keys = {fact.key() for fact in add_facts}
        kept: List[Fact] = []
        for fact in self.knowledge.facts:
            if fact.key() in remove_keys:
                continue
            if fact.key() in add_keys:
                continue
            kept.append(fact)
        kept.extend(add_facts)
        return AgentKnowledge(
            self.knowledge.catalog,
            kept,
            self.knowledge.entities,
            side=self.knowledge.side,
            faction_id=self.knowledge.faction_id,
            speaker_id=self.knowledge.speaker_id,
            speaker_name=self.knowledge.speaker_name,
            world=self.knowledge.world,
            clock=self.knowledge.clock,
            run_id=self.knowledge.run_id,
            speaker_post=self.knowledge.speaker_post,
            faction_name=self.knowledge.faction_name,
            player_id=self.knowledge.player_id,
            player_name=self.knowledge.player_name,
            player_post=self.knowledge.player_post,
            player_faction=self.knowledge.player_faction,
            player_side=self.knowledge.player_side,
            player_gender=self.knowledge.player_gender,
        )

    def compare(
        self,
        relation: str,
        args: Iterable[str] = (),
        *,
        remove: Iterable[Fact] = (),
        add: Iterable[Fact] = (),
    ) -> CounterfactualResult:
        """Сравнить базу и контрмодель по цели ``relation(args)``."""

        if not self.enabled():
            return CounterfactualResult(
                outcome="disabled", construction=""
            )
        base_engine = InferenceEngine(self.catalog, self.knowledge)
        model = self.with_facts(remove=remove, add=add)
        model_engine = InferenceEngine(self.catalog, model)
        base = base_engine.first(relation, *args)
        other = model_engine.first(relation, *args)
        differences = self._differences(base, other)
        if base is None and other is None:
            outcome = "unknown"
        elif differences:
            outcome = "changed"
        else:
            outcome = "unchanged"
        construction = ""
        if self.spec is not None:
            construction = str(
                self.spec.outcomes.get(outcome, "") or ""
            )
        removed = tuple(
            fact for fact in remove if fact.rel in self.allowed
        )
        added = tuple(
            fact for fact in add if fact.rel in self.allowed
        )
        return CounterfactualResult(
            outcome=outcome,
            construction=construction,
            differences=differences[: self.max_steps],
            removed=removed,
            added=added,
            base_proof=base,
            model_proof=other,
        )

    def _differences(
        self,
        base: Optional[Solution],
        other: Optional[Solution],
    ) -> Tuple[Difference, ...]:
        """Первый расходящийся шаг сверху вниз, ограниченный ``max_steps``.

        Если одна из сторон не доказана, отличие — голова доказанной
        ветки (один шаг). Иначе обходим базу сверху вниз и берём первый
        шаг, чей ``signature()`` отсутствует в модели; если такого нет,
        берём первый такой шаг модели. Это даёт «вот где разошлось»,
        а не «вся ветка изменилась».
        """

        if base is None and other is None:
            return ()
        if base is None:
            return self._head(other.proof)
        if other is None:
            return self._head(base.proof)
        other_sigs = {
            step.signature() for step in self._walk(other.proof)
        }
        base_sigs = {
            step.signature() for step in self._walk(base.proof)
        }
        for step in self._walk(base.proof):
            if step.signature() not in other_sigs:
                return (
                    Difference(
                        rel=step.atom.rel,
                        args=step.atom.args,
                        rule=step.rule,
                    ),
                )
        for step in self._walk(other.proof):
            if step.signature() not in base_sigs:
                return (
                    Difference(
                        rel=step.atom.rel,
                        args=step.atom.args,
                        rule=step.rule,
                    ),
                )
        return ()

    def _head(
        self, proof: Any
    ) -> Tuple[Difference, ...]:
        if proof is None:
            return ()
        return (
            Difference(
                rel=proof.atom.rel,
                args=proof.atom.args,
                rule=proof.rule,
            ),
        )

    def _walk(self, proof: Any):
        """Детерминированный обход доказательства сверху вниз."""

        if proof is None:
            return
        yield proof
        for child in getattr(proof, "children", ()) or ():
            yield from self._walk(child)