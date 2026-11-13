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
    default_style: str = ""


@dataclass(frozen=True)
class StyleSpec:
    """Регистровый профиль как набор признаков, а не список фраз.

    Стиль не выбирает факты и не заменяет план. Он задаёт значения
    признаков (формальность, дистанция, авторитет, аффект, прямота,
    номинализация и т.п.), с которыми реализатор согласует конструкции
    и лексемы. Новый стиль не требует новых шаблонов ответа.
    """

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
    """Речевое действие как данные: акт, пропозиция, условия, реакции.

    Акт не меняет мир. Он задаёт входную социальную пропозицию, для
    которой ``SocialEngine`` выбирает реакцию по условиям. Новый акт
    добавляется JSON-ом, не правкой Python.
    """

    id: str
    label: str
    match: Mapping[str, Any]
    proposition: Mapping[str, Any] = field(default_factory=dict)
    validity: Tuple[AtomSpec, ...] = ()
    taboo: Tuple[str, ...] = ()
    reactions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ReactionSpec:
    """Реакция на речевое действие: условия, эффект, конструкция синтеза.

    ``effect.type`` — типизированный социальный эффект
    (commitment/refusal/evasion/counter_offer/clarification), не
    произвольный код. Конструкция ссылается на ``synthesis.constructions``
    и согласуется со стилем через общий реализатор.
    """

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
    """Один ход дискурсивного ответа.

    Ход не хранит готовый текст и не добавляет факты. Он говорит, как
    реализовать уже принятый смысл: через речевой акт (``act``), через
    конструкцию синтеза (``construction``), через отношение
    (``relation`` + ``source``) или через готовую строку в данных
    (``source`` без остальных режимов). Три первых способа совпадают с
    механизмами, которые уже есть в реализаторе; четвёртый —
    «озвучить готовую строку».
    """

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

    ``kind`` — вид ``Answer.kind``; ``plan_id`` уточняет конкретный план,
    если одно и то же ``kind`` должно собираться по-разному. Порядок
    ходов в ``moves`` — порядок их реализации в тексте.
    """

    id: str
    kind: str = ""
    plan_id: str = ""
    moves: Tuple[str, ...] = ()
    priority: int = 0


@dataclass(frozen=True)
class DiscourseCatalog:
    """Ходы, шаблоны и связки дискурсивного планировщика.

    Всё содержание — данные. Нет шаблона для вида ответа — нет ходов:
    реализатор возвращает ответ как есть (обратная совместимость и
    байт-в-байт нейтральный путь).
    """

    moves: Mapping[str, DiscourseMove] = field(default_factory=dict)
    patterns: Tuple[DiscoursePattern, ...] = ()
    connectives: Tuple[Mapping[str, Any], ...] = ()

    def move(self, move_id: str) -> Any:
        return self.moves.get(str(move_id or ""))

    def pattern_for(self, kind: str, plan_id: str = "") -> Any:
        """Найти шаблон: сначала по plan_id, затем по kind.

        Порядок фиксирован и объясним: конкретный план важнее общего
        вида ответа, при равенстве — по убыванию приоритета и id.
        """

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
    """Правило автовыбора регистра по контексту разговора.

    Условие — список атомов, объявленных в данных: ``fact`` проверяет
    наличие факта в ``AgentKnowledge`` с подстановкой ``$speaker`` /
    ``$player``, ``field`` сравнивает поле знания с константой или с
    другим полем. Итог — ``style_id``, имя существующего стиля.
    """

    id: str
    style_id: str
    priority: int = 0
    conditions: Tuple[Mapping[str, Any], ...] = ()
    description: str = ""


@dataclass(frozen=True)
class StyleContextCatalog:
    """Правила автовыбора регистра.

    Пустой каталог — валидное состояние: автовыбор отключён, работает
    ручной выбор и ``persona.default_style``. Это сохраняет обратную
    совместимость и «нейтральный путь байт-в-байт».
    """

    rules: Tuple[StyleContextRule, ...] = ()
    enabled: bool = False

    def ordered(self) -> Tuple[StyleContextRule, ...]:
        return tuple(
            sorted(self.rules, key=lambda item: (-item.priority, item.id))
        )


@dataclass(frozen=True)
class ComparisonSpec:
    """Правило сравнения: какое отношение, какие аргументы, конструкции.

    ``greater``/``less``/``equal``/``unknown_left``/``unknown_right``/
    ``both_unknown`` — ключи конструкций в ``synthesis.constructions``.
    ``key_prefix`` — необязательный префикс лексемы ключа, который надо
    снять перед унификацией с фактом (например, ``asset:`` у ``asset``
    хранится в факте без префикса). Никакого ``if a > b`` в коде.
    """

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
    """Таблица сравнений. Пустой каталог — сравнения отключены."""

    comparisons: Mapping[str, ComparisonSpec] = field(
        default_factory=dict
    )

    def get(self, relation: str) -> Any:
        return self.comparisons.get(str(relation or ""))


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
    world: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)