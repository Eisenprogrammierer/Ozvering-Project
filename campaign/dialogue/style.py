"""Регистровый слой диалога.

Стиль здесь — набор признаков, а не банк фраз. Реализатор согласует с
этими признаками конструкции и лексемы: формальность, дистанция,
авторитет, аффект, прямота, номинализация. Поэтому новый стиль не
требует новых шаблонов ответа — только новый набор значений признаков.

D5.2 добавляет автовыбор регистра по контексту: правила лежат в
``style_context.json``, условия проверяются по ``AgentKnowledge``
(факты и поля), результат — имя существующего стиля. Это чистые данные:
добавление правила не требует правки Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .model import StyleCatalog, StyleSpec

ANSWER_KINDS = frozenset(
    {
        "yes",
        "no",
        "unknown",
        "clarification",
        "smalltalk",
        "explanation",
        "list",
        "value",
        "entity",
        "description",
        "summary",
    }
)

SELECTION_KEYS = frozenset(
    {
        "avoid_recent",
        "priority",
        "max_moves",
        "connectives",
        "allow_fallback",
    }
)

_FEMALE = frozenset({"f", "female", "woman", "женщина", "ж"})
_MALE = frozenset({"m", "male", "man", "мужчина", "м"})

_SUBJECT_FIELDS = {
    "$speaker_id": "speaker_id",
    "$speaker_name": "speaker_name",
    "$speaker_post": "speaker_post",
    "$speaker_faction": "faction_id",
    "$player_id": "player_id",
    "$player_name": "player_name",
    "$player_post": "player_post",
    "$player_faction": "player_faction_id",
    "$player_faction_name": "player_faction",
    "$player_side": "player_side",
    "$side": "side",
    "$faction_id": "faction_id",
    "$relation_affinity": "relation_affinity",
    "$relation_trust": "relation_trust",
    "$relation_fear": "relation_fear",
    "$relation_respect": "relation_respect",
    "$player_relation_affinity": "player_relation_affinity",
    "$player_relation_trust": "player_relation_trust",
    "$player_relation_fear": "player_relation_fear",
    "$player_relation_respect": "player_relation_respect",
}

_NUMERIC_OPERATORS = frozenset(
    {"gt", "gte", "lt", "lte", ">", ">=", "<", "<="}
)


def normalize_gender(value: Any) -> str:
    """Привести пол к одному из ключей ``m`` / ``f`` / ``n``."""

    text = str(value or "").strip().lower()
    if text in _FEMALE:
        return "f"
    if text in _MALE:
        return "m"
    return "n"


def _substitute(value: Any, knowledge: Any) -> Any:
    """Подставить поля ``AgentKnowledge`` в аргументы условия."""

    text = str(value or "")
    field_name = _SUBJECT_FIELDS.get(text)
    if field_name is None:
        return text
    return str(getattr(knowledge, field_name, "") or "")


@dataclass(frozen=True)
class StyleDecision:
    """Выбранный регистр и объяснимая причина выбора.

    ``source`` — машинный код причины: ``explicit``, ``persona``,
    ``rule``, ``hint`` или ``default``. ``rule_id`` и ``description``
    заполнены только для правил ``style_context.json``; подсказка
    режима тоже несёт ``description``, чтобы интерфейс мог показать
    «почему такой регистр» без знания Python-кода.
    """

    style_id: str
    source: str = "default"
    rule_id: str = ""
    description: str = ""


class StyleEngine:
    """Читает регистровые профили и отдаёт их реализатору."""

    def __init__(self, catalog: Any):
        styles = getattr(catalog, "styles", None)
        self.catalog = styles if isinstance(styles, StyleCatalog) else (
            StyleCatalog()
        )
        self.styles: Mapping[str, StyleSpec] = self.catalog.styles
        self.context = getattr(catalog, "style_context", None)

    def specs(self) -> Sequence[StyleSpec]:
        """Стили в порядке объявления в JSON."""

        return tuple(self.styles.values())

    def ids(self) -> tuple:
        return tuple(self.styles)

    def has(self, style_id: Any) -> bool:
        return str(style_id or "") in self.styles

    @property
    def hint_priority(self) -> int:
        """Приоритет подсказки стиля (данные ``style_context.json``)."""

        return int(getattr(self.context, "hint_priority", 40))

    @property
    def hint_min_weight(self) -> float:
        """Минимальный вес маркера для уверенной подсказки."""

        return float(getattr(self.context, "hint_min_weight", 0.8))

    def resolve(self, style_id: Any = None, persona: Any = None) -> str:
        """Выбрать стиль: явный → персона → стиль по умолчанию."""

        explicit = str(style_id or "")
        if explicit in self.styles:
            return explicit
        default = str(getattr(persona, "default_style", "") or "")
        if default in self.styles:
            return default
        if self.catalog.default in self.styles:
            return self.catalog.default
        return next(iter(self.styles), "")

    def resolve_for_context(
        self,
        style_id: Any = None,
        persona: Any = None,
        knowledge: Any = None,
        *,
        hint_style: Any = "",
        hint_priority: Optional[int] = None,
    ) -> str:
        """Выбрать стиль с учётом контекста разговора."""

        return self.explain_for_context(
            style_id,
            persona,
            knowledge,
            hint_style=hint_style,
            hint_priority=hint_priority,
        ).style_id

    def explain_for_context(
        self,
        style_id: Any = None,
        persona: Any = None,
        knowledge: Any = None,
        *,
        hint_style: Any = "",
        hint_priority: Optional[int] = None,
    ) -> StyleDecision:
        """Выбрать стиль и объяснить причину выбора.

        Порядок строго фиксирован и объясним:

        1. Явный выбор игрока — он побеждает любые правила.
        2. ``persona.default_style`` — дефолт персоны.
        3. Правила ``style_context.json`` и подсказка ``style_hints``
           по убыванию ``priority``; первое совпавшее правило даёт
           стиль. Подсказка — такое же правило, поэтому её приоритет
           (``hint_priority``) задан данными.
        4. ``styles.default`` — нейтральный.

        ``knowledge`` может быть ``None``: тогда правила, которым нужны
        поля/факты, не срабатывают, и работает ручной выбор. Подсказка
        не зависит от знания и применяется, если её приоритет выше
        остальных совпавших правил.
        """

        explicit = str(style_id or "")
        if explicit in self.styles:
            return StyleDecision(explicit, "explicit")
        default = str(getattr(persona, "default_style", "") or "")
        if default in self.styles:
            return StyleDecision(default, "persona")
        context = self.context
        enabled = bool(
            context is not None and getattr(context, "enabled", False)
        )
        hint = str(hint_style or "")
        if hint not in self.styles:
            hint = ""
        candidates = []
        if enabled and knowledge is not None:
            for rule in context.ordered():
                candidates.append(
                    (
                        rule.priority,
                        rule.id,
                        rule.style_id,
                        rule.conditions,
                        rule.description,
                        "rule",
                    )
                )
        if hint:
            if hint_priority is None:
                hint_priority = int(
                    getattr(context, "hint_priority", 40)
                )
            candidates.append(
                (int(hint_priority), "", hint, (), "", "hint")
            )
            candidates.sort(key=lambda item: (-item[0], item[1]))
        for priority, rule_id, style, conditions, description, source in (
            candidates
        ):
            if style not in self.styles:
                continue
            if conditions and not self._conditions_met(
                conditions, knowledge
            ):
                continue
            return StyleDecision(style, source, rule_id, description)
        if self.catalog.default in self.styles:
            return StyleDecision(self.catalog.default, "default")
        return StyleDecision(next(iter(self.styles), ""), "default")

    def _conditions_met(
        self,
        conditions: Sequence[Mapping[str, Any]],
        knowledge: Any,
    ) -> bool:
        for condition in conditions:
            if not self._condition_met(condition, knowledge):
                return False
        return True

    def _condition_met(
        self, condition: Mapping[str, Any], knowledge: Any
    ) -> bool:
        kind = str(condition.get("kind") or "field")
        if kind == "fact":
            rel = str(condition.get("rel") or "")
            args = tuple(
                _substitute(item, knowledge)
                for item in condition.get("args") or ()
            )
            return self._fact_present(knowledge, rel, args)
        if kind == "field":
            return self._field_condition(condition, knowledge)
        return False

    @staticmethod
    def _fact_present(
        knowledge: Any, relation: str, args: Sequence[str]
    ) -> bool:
        if not relation:
            return False
        if any(not str(item) for item in args):
            return False
        getter = getattr(knowledge, "facts_for", None)
        if not callable(getter):
            return False
        for fact in getter(relation):
            fact_args = tuple(getattr(fact, "args", ()) or ())
            if fact_args == tuple(str(item) for item in args):
                return True
        return False

    def _field_condition(
        self, condition: Mapping[str, Any], knowledge: Any
    ) -> bool:
        field_name = str(condition.get("field") or "")
        if not field_name:
            return False
        actual_raw = getattr(knowledge, field_name, "")
        actual = str(actual_raw if actual_raw is not None else "")
        operator = str(condition.get("op") or "eq")
        raw = condition.get("value")
        if isinstance(raw, Mapping):
            other_field = str(raw.get("field") or "")
            expected_raw = getattr(knowledge, other_field, "")
            expected = str(
                expected_raw if expected_raw is not None else ""
            )
        elif isinstance(raw, (list, tuple)):
            expected_list = [
                _substitute(item, knowledge) for item in raw
            ]
            if operator == "in":
                return actual in expected_list
            if operator == "not_in":
                return actual not in expected_list
            return False
        elif raw is None:
            expected = ""
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            expected = raw
        else:
            expected = str(_substitute(raw, knowledge))
        if operator in _NUMERIC_OPERATORS:
            return self._numeric_compare(
                actual_raw, expected, operator
            )
        if operator == "eq":
            return bool(actual) and actual == expected
        if operator == "ne":
            return bool(actual) and actual != expected
        if operator == "exists":
            return bool(actual)
        if operator == "in":
            return actual in (expected,)
        if operator == "not_in":
            return actual not in (expected,)
        return False

    @staticmethod
    def _numeric_compare(actual: Any, expected: Any, operator: str) -> bool:
        """Сравнить два значения как числа; нечисло — не совпало."""

        try:
            left = float(actual)
            right = float(expected)
        except (TypeError, ValueError):
            return False
        if operator in ("gt", ">"):
            return left > right
        if operator in ("gte", ">="):
            return left >= right
        if operator in ("lt", "<"):
            return left < right
        if operator in ("lte", "<="):
            return left <= right
        return False

    def profile(
        self, style_id: Any = None, persona: Any = None
    ) -> StyleSpec:
        """Вернуть регистровый профиль; неизвестный стиль безопасен."""

        key = self.resolve(style_id, persona)
        style = self.styles.get(key)
        if style is not None:
            return style
        return StyleSpec(id="", label="", register="neutral")

    def profile_for_context(
        self,
        style_id: Any = None,
        persona: Any = None,
        knowledge: Any = None,
        *,
        hint_style: Any = "",
        hint_priority: Optional[int] = None,
    ) -> StyleSpec:
        """Профиль с учётом контекста; неизвестный стиль безопасен."""

        key = self.resolve_for_context(
            style_id,
            persona,
            knowledge,
            hint_style=hint_style,
            hint_priority=hint_priority,
        )
        style = self.styles.get(key)
        if style is not None:
            return style
        return StyleSpec(id="", label="", register="neutral")

    @staticmethod
    def features(style: StyleSpec) -> Mapping[str, str]:
        """Признаки стиля, включая регистр как отдельный признак.

        ``register`` — не ещё одно измерение наравне с остальными, а
        ключ профиля. Поэтому он всегда побеждает значение, унаследованное
        из схемы по умолчанию.
        """

        result = dict(style.features or {})
        result["register"] = str(style.register or "neutral")
        return result

    @staticmethod
    def is_neutral(style: StyleSpec) -> bool:
        """Нейтральный профиль сохраняет прежний байт-в-байт путь."""

        return not str(style.id or "") or str(style.id) == "neutral"
