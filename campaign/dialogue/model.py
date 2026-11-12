"""Модель данных диалогового слоя.

Все содержательные решения — онтология, лексикон, грамматика, правила —
живут в JSON. Здесь только типы, которые нужны интерпретатору.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple


@dataclass(frozen=True)
class LexForm:
    """Одна поверхностная форма лексемы с морфологическими признаками."""

    text: str
    features: Mapping[str, str] = field(default_factory=dict)

    @property
    def tokens(self) -> Tuple[str, ...]:
        return tuple(self.text.split())


@dataclass(frozen=True)
class LexEntry:
    """Словарная статья: смысл, категория и набор форм."""

    id: str
    type: str
    cat: str
    lemma: str
    semantic: Mapping[str, Any]
    forms: Tuple[LexForm, ...] = ()
    aliases: Tuple[LexForm, ...] = ()
    features: Mapping[str, str] = field(default_factory=dict)

    def all_forms(self) -> Tuple[LexForm, ...]:
        return tuple(self.forms) + tuple(self.aliases)


@dataclass(frozen=True)
class RuleItem:
    """Элемент правой части грамматического правила."""

    cat: str
    role: str = ""
    features: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GrammarRule:
    """Правило грамматики: синтаксис плюс шаблон семантики.

    ``head`` называет роль ребёнка, чьи признаки наследуются родителем
    (вершинное согласование). Пустая строка — родитель берёт только свои
    признаки. Так лексические признаки вроде леммы не сталкиваются при
    сборке фразы.
    """

    id: str
    lhs: str
    rhs: Tuple[RuleItem, ...]
    sem: Any
    features: Mapping[str, str] = field(default_factory=dict)
    head: str = ""


@dataclass(frozen=True)
class Grammar:
    """Каталог правил и стартовый символ."""

    start: str
    rules: Tuple[GrammarRule, ...]


@dataclass(frozen=True)
class Ontology:
    """Типы сущностей, отношений и допустимые роли."""

    entity_types: Mapping[str, Mapping[str, Any]]
    relations: Mapping[str, Mapping[str, Any]]
    question_types: Mapping[str, Mapping[str, Any]]
    roles: Mapping[str, str]
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Parse:
    """Один разбор участка текста."""

    cat: str
    start: int
    end: int
    sem: Any
    features: Mapping[str, str]
    rule: str
    children: Tuple["Parse", ...] = ()
    text: str = ""

    def key(self) -> Tuple[Any, ...]:
        return (
            self.cat,
            self.start,
            self.end,
            repr(self.sem),
            tuple(sorted(self.features.items())),
        )


@dataclass(frozen=True)
class AtomSpec:
    """Атом логики: отношение и аргументы (константы или ``$переменные``)."""

    rel: str
    args: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleSpec:
    """Правило вывода: посылки, голова и объяснение."""

    id: str
    head: AtomSpec
    premises: Tuple[AtomSpec, ...]
    because: str = ""
    priority: int = 0


@dataclass(frozen=True)
class FactSpec:
    """Статический факт из ``facts.json``."""

    rel: str
    args: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanSpec:
    """План ответа: шаблон вопроса и действие над знанием."""

    id: str
    priority: int
    match: Any
    answer: Mapping[str, Any]
    output: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Persona:
    """Речевая политика агента: честность, тон, неизвестность."""

    id: str
    greeting: str = ""
    smalltalk: Mapping[str, str] = field(default_factory=dict)
    unknown: str = ""
    parse_unknown: str = ""
    clarify: Mapping[str, str] = field(default_factory=dict)
    max_list_items: int = 20


@dataclass(frozen=True)
class DialogueCatalog:
    """Полный набор данных диалога."""

    ontology: Ontology
    lexicon: Tuple[LexEntry, ...]
    grammar: Grammar
    rules: Tuple[RuleSpec, ...] = ()
    facts: Tuple[FactSpec, ...] = ()
    max_depth: int = 32
    plans: Tuple[PlanSpec, ...] = ()
    realization: Mapping[str, Any] = field(default_factory=dict)
    synthesis: Mapping[str, Any] = field(default_factory=dict)
    state: Mapping[str, Any] = field(default_factory=dict)
    personas: Mapping[str, Persona] = field(default_factory=dict)
    world: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)
