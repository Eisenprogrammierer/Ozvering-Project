"""Регистровый слой диалога.

Стиль здесь — набор признаков, а не банк фраз. Реализатор согласует с
этими признаками конструкции и лексемы: формальность, дистанция,
авторитет, аффект, прямота, номинализация. Поэтому новый стиль не
требует новых шаблонов ответа — только новый набор значений признаков.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

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


def normalize_gender(value: Any) -> str:
    """Привести пол к одному из ключей ``m`` / ``f`` / ``n``."""

    text = str(value or "").strip().lower()
    if text in _FEMALE:
        return "f"
    if text in _MALE:
        return "m"
    return "n"


class StyleEngine:
    """Читает регистровые профили и отдаёт их реализатору."""

    def __init__(self, catalog: Any):
        styles = getattr(catalog, "styles", None)
        self.catalog = styles if isinstance(styles, StyleCatalog) else (
            StyleCatalog()
        )
        self.styles: Mapping[str, StyleSpec] = self.catalog.styles

    def specs(self) -> Sequence[StyleSpec]:
        """Стили в порядке объявления в JSON."""

        return tuple(self.styles.values())

    def ids(self) -> tuple:
        return tuple(self.styles)

    def has(self, style_id: Any) -> bool:
        return str(style_id or "") in self.styles

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

    def profile(
        self, style_id: Any = None, persona: Any = None
    ) -> StyleSpec:
        """Вернуть регистровый профиль; неизвестный стиль безопасен."""

        key = self.resolve(style_id, persona)
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