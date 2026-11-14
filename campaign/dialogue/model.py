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
    """Правило грамматики: синтаксис плюс шаблон семантики."""

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
    max_discourse_moves: int = 3
    default_style: str = ""
    disclosure: Mapping[str, Any] = field(default_factory=dict)
    lie_probability: float = 0.0


@dataclass(frozen=True)
class StyleSpec:
    """Регистровый профиль как набор признаков, а не список фраз."""

    id: str
    label: str
    description: str = ""
    register: str = "neutral"
    features: Mapping[str, str] = field(default_factory=dict)
    selection: Mapping[str, Any] = field(default_factory=dict)

    def feature(self, name: str, default: str = "neutral") -> str:
        return str(self.features.get(str(name)) or default)


@dataclass(frozen=True)
class FeatureSchema:
    """Схема измерений стиля: допустимые значения и умолчания."""

    dimensions: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )

    def names(self) -> Tuple[str, ...]:
        return tuple(self.dimensions)

    def values(self, name: str) -> Tuple[str, ...]:
        data = self.dimensions.get(str(name)) or {}
        return tuple(str(item) for item in data.get("values") or ())

    def default(self, name: str) -> str:
        data = self.dimensions.get(str(name)) or {}
        return str(data.get("default") or "neutral")

    def defaults(self) -> Mapping[str, str]:
        return {
            name: self.default(name)
            for name in self.dimensions
        }


@dataclass(frozen=True)
class StyleCatalog:
    """Набор стилей и стиль по умолчанию."""

    default: str = "neutral"
    styles: Mapping[str, StyleSpec] = field(default_factory=dict)

    def get(self, style_id: str) -> Any:
        return self.styles.get(str(style_id or ""))

    def ids(self) -> Tuple[str, ...]:
        return tuple(sorted(self.styles))


@dataclass(frozen=True)
class SocialActSpec:
    """Речевое действие как данные: акт, пропозиция, условия, реакции."""

    id: str
    label: str
    match: Mapping[str, Any]
    proposition: Mapping[str, Any] = field(default_factory=dict)
    interaction: str = ""
    validity: Tuple[AtomSpec, ...] = ()
    taboo: Tuple[str, ...] = ()
    reactions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ReactionSpec:
    """Реакция на речевое действие: условия, эффект, конструкция синтеза."""

    id: str
    label: str
    effect: Mapping[str, Any] = field(default_factory=dict)
    conditions: Tuple[AtomSpec, ...] = ()
    priority: int = 0
    construction: str = ""


@dataclass(frozen=True)
class SocialCatalog:
    """Акты, реакции и политика обязательств."""

    acts: Mapping[str, SocialActSpec] = field(default_factory=dict)
    reactions: Mapping[str, ReactionSpec] = field(default_factory=dict)
    commitments: Mapping[str, Any] = field(default_factory=dict)

    def act(self, act_id: str) -> Any:
        return self.acts.get(str(act_id or ""))

    def reaction(self, reaction_id: str) -> Any:
        return self.reactions.get(str(reaction_id or ""))


@dataclass(frozen=True)
class DiscourseMove:
    """Один ход дискурсивного ответа."""

    id: str
    label: str = ""
    act: str = ""
    construction: str = ""
    relation: str = ""
    source: str = ""
    optional: bool = False
    features: Mapping[str, str] = field(default_factory=dict)
    priority: int = 0


@dataclass(frozen=True)
class DiscoursePattern:
    """Какие ходы собираются для какого вида ответа.

    ``topic`` — один ход, который идёт первым как тема, остальные — по
    порядку ``moves``. ``topics`` — список ходов, задающих порядок
    абзаца 4+ ходов: сначала они в указанном порядке, затем остальные
    ``moves``. ``topics`` перекрывает ``topic``; если ``topics``
    пусто, поведение прежнее.
    """

    id: str
    kind: str = ""
    plan_id: str = ""
    moves: Tuple[str, ...] = ()
    topic: str = ""
    topics: Tuple[str, ...] = ()
    priority: int = 0


@dataclass(frozen=True)
class DiscourseAnaphora:
    """Политика анафоры внутри одного ответа.

    ``types`` — типы сущностей, к которым применима замена. ``kinds`` —
    виды ходов, для которых анафора активна. ``pronouns`` — карта
    ``(род, число) → местоимение``, например ``"m:sg" → "он"``.
    ``min_length`` — минимальная длина имени, чтобы не менять короткие
    уникальные слова (например, «Ты»).
    """

    types: Tuple[str, ...] = ()
    kinds: Tuple[str, ...] = ()
    pronouns: Mapping[str, str] = field(default_factory=dict)
    min_length: int = 3
    enabled: bool = False


@dataclass(frozen=True)
class DiscourseCatalog:
    """Ходы, шаблоны, связки и анафора дискурсивного слоя."""

    moves: Mapping[str, DiscourseMove] = field(default_factory=dict)
    patterns: Tuple[DiscoursePattern, ...] = ()
    connectives: Tuple[Mapping[str, Any], ...] = ()
    anaphora: DiscourseAnaphora = field(default_factory=DiscourseAnaphora)

    def move(self, move_id: str) -> Any:
        return self.moves.get(str(move_id or ""))

    def pattern_for(self, kind: str, plan_id: str = "") -> Any:
        candidates = [
            item
            for item in self.patterns
            if item.plan_id and item.plan_id == str(plan_id)
        ]
        if not candidates:
            candidates = [
                item
                for item in self.patterns
                if item.kind and item.kind == str(kind) and not item.plan_id
            ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item.priority, item.id))
        return candidates[0]


@dataclass(frozen=True)
class StyleContextRule:
    """Правило автовыбора регистра по контексту разговора."""

    id: str
    style_id: str
    priority: int = 0
    conditions: Tuple[Mapping[str, Any], ...] = ()
    description: str = ""


@dataclass(frozen=True)
class StyleContextCatalog:
    """Правила автовыбора регистра."""

    rules: Tuple[StyleContextRule, ...] = ()
    enabled: bool = False

    def ordered(self) -> Tuple[StyleContextRule, ...]:
        return tuple(
            sorted(self.rules, key=lambda item: (-item.priority, item.id))
        )


@dataclass(frozen=True)
class ComparisonSpec:
    """Правило сравнения: какое отношение, какие аргументы, конструкции."""

    id: str
    relation: str
    args: Mapping[str, int] = field(default_factory=dict)
    value_arg: int = 2
    key_arg: int = 1
    subject_arg: int = 0
    key_prefix: str = ""
    greater: str = ""
    less: str = ""
    equal: str = ""
    unknown_left: str = ""
    unknown_right: str = ""
    both_unknown: str = ""


@dataclass(frozen=True)
class ComparisonCatalog:
    """Таблица сравнений."""

    comparisons: Mapping[str, ComparisonSpec] = field(
        default_factory=dict
    )

    def get(self, relation: str) -> Any:
        return self.comparisons.get(str(relation or ""))


@dataclass(frozen=True)
class CounterfactualSpec:
    """Правила контрфакта: что подменять, сколько шагов, конструкции."""

    relations: Tuple[str, ...] = ()
    max_steps: int = 2
    outcomes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CounterfactualCatalog:
    """Обёртка для загрузчика: единая точка доступа."""

    spec: CounterfactualSpec = field(default_factory=CounterfactualSpec)


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
    styles: StyleCatalog = field(default_factory=StyleCatalog)
    features: FeatureSchema = field(default_factory=FeatureSchema)
    social: SocialCatalog = field(default_factory=SocialCatalog)
    discourse: DiscourseCatalog = field(default_factory=DiscourseCatalog)
    style_context: StyleContextCatalog = field(
        default_factory=StyleContextCatalog
    )
    comparison: ComparisonCatalog = field(
        default_factory=ComparisonCatalog
    )
    counterfactual: CounterfactualSpec = field(
        default_factory=CounterfactualSpec
    )
    disclosure: Mapping[str, Any] = field(default_factory=dict)
    parsing: Mapping[str, Any] = field(default_factory=dict)
    paraphrases: Mapping[str, Any] = field(default_factory=dict)
    goals: Mapping[str, Any] = field(default_factory=dict)
    actions: Mapping[str, Any] = field(default_factory=dict)
    console: Mapping[str, Any] = field(default_factory=dict)
    world: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)
