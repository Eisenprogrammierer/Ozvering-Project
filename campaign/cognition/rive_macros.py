"""Object macros RiveScript: морфология, числа, качества и сущности.

Макросы — детерминированные функции над лексиконом. Они не меняют мир
и не обращаются к LLM; RiveScript вызывает их из ответов, а Python
остаётся единственной точкой записи состояния.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Tuple

from campaign.dialogue.morphology import surface

from .errors import RiveError
from .rive_compiler import (
    DEFAULT_DIALOGUE_DIR,
    entry_forms,
    lexicon_substitutions,
    one_token,
)
from .serialization import canonical_digest

LEXICON_NAME = "lexicon.json"
_UNITS = {
    "ноль": 0,
    "нуль": 0,
    "один": 1,
    "одна": 1,
    "одно": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
}
_TENS = {
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
}
_HUNDREDS = {
    "сто": 100,
    "двести": 200,
    "триста": 300,
    "четыреста": 400,
    "пятьсот": 500,
    "шестьсот": 600,
    "семьсот": 700,
    "восемьсот": 800,
    "девятьсот": 900,
}
_QUALITIES = {
    "нет": 0,
    "отсутствует": 0,
    "низкий": 1,
    "низкая": 1,
    "низкое": 1,
    "слабый": 1,
    "мало": 1,
    "средний": 2,
    "средняя": 2,
    "обычный": 2,
    "умеренный": 2,
    "высокий": 3,
    "высокая": 3,
    "сильный": 3,
    "много": 3,
    "максимальный": 4,
    "критический": 4,
}
_MACROS_CACHE: Dict[Tuple[str, int], "RiveMacros"] = {}


def default_lexicon_path() -> Path:
    return DEFAULT_DIALOGUE_DIR / LEXICON_NAME


def parse_number(text: str) -> str:
    """Разобрать русское числительное до 999999; пусто при ошибке."""

    tokens = surface(text).split()
    if not tokens:
        return ""
    total = 0
    current = 0
    for token in tokens:
        if token in _UNITS:
            current += _UNITS[token]
        elif token in _TENS:
            current += _TENS[token]
        elif token in _HUNDREDS:
            current += _HUNDREDS[token]
        elif token in ("тысяча", "тысячи", "тысяч"):
            total += (current or 1) * 1000
            current = 0
        else:
            return ""
    return str(total + current)


def parse_quality(text: str) -> str:
    """Качественный уровень 0–4; пусто, если слово неизвестно."""

    for token in surface(text).split():
        if token in _QUALITIES:
            return str(_QUALITIES[token])
    return ""


@dataclass(frozen=True)
class RiveMacros:
    """Лексиконные функции, доступные из RiveScript."""

    substitutions: Mapping[str, str] = field(default_factory=dict)
    entities: Mapping[str, str] = field(default_factory=dict)
    ambiguous_entities: Tuple[str, ...] = ()

    def morph(self, text: str) -> str:
        tokens = surface(text).split()
        return " ".join(
            self.substitutions.get(token, token) for token in tokens
        )

    def entity(self, text: str) -> str:
        for token in surface(text).split():
            identifier = self.entities.get(token)
            if identifier:
                return identifier
        return ""

    def number(self, text: str) -> str:
        return parse_number(text)

    def quality(self, text: str) -> str:
        return parse_quality(text)

    def digest(self) -> str:
        return canonical_digest(
            {
                "substitutions": dict(self.substitutions),
                "entities": dict(self.entities),
                "ambiguous_entities": list(self.ambiguous_entities),
            }
        )


def build_macros(entries: Iterable[Mapping[str, Any]]) -> RiveMacros:
    items = list(entries)
    substitutions, _ = lexicon_substitutions(items)
    candidates: Dict[str, set] = {}
    for entry in items:
        semantic = entry.get("semantic")
        if not isinstance(semantic, Mapping):
            continue
        if semantic.get("kind") != "entity":
            continue
        identifier = str(semantic.get("id") or "")
        if not identifier:
            continue
        for form in entry_forms(entry):
            token = one_token(form)
            if token:
                candidates.setdefault(token, set()).add(identifier)
    entities = {}
    ambiguous = []
    for token in sorted(candidates):
        identifiers = candidates[token]
        if len(identifiers) == 1:
            entities[token] = next(iter(identifiers))
        else:
            ambiguous.append(token)
    return RiveMacros(
        substitutions=substitutions,
        entities=entities,
        ambiguous_entities=tuple(ambiguous),
    )


def load_macros(path: Path = default_lexicon_path()) -> RiveMacros:
    """Загрузить макросы из лексикона с кешем по mtime."""

    source = Path(path)
    try:
        stamp = source.stat().st_mtime_ns
    except OSError as exc:
        raise RiveError("нет лексикона для макросов: %s" % source) from exc
    key = (str(source), stamp)
    cached = _MACROS_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RiveError("лексикон не является JSON: %s" % source) from exc
    if not isinstance(data, Mapping):
        raise RiveError("лексикон должен быть объектом")
    entries = data.get("entries") or ()
    if not isinstance(entries, (list, tuple)):
        raise RiveError("lexicon.entries должен быть списком")
    macros = build_macros(entries)
    _MACROS_CACHE[key] = macros
    return macros


def register_macros(engine: Any, macros: RiveMacros) -> None:
    """Зарегистрировать ``morph``/``number``/``quality``/``entity``."""

    def joined(args: Any) -> str:
        return " ".join(str(item) for item in (args or ()))

    engine.set_subroutine(
        "morph", lambda rs, args: macros.morph(joined(args))
    )
    engine.set_subroutine(
        "number", lambda rs, args: macros.number(joined(args))
    )
    engine.set_subroutine(
        "quality", lambda rs, args: macros.quality(joined(args))
    )
    engine.set_subroutine(
        "entity", lambda rs, args: macros.entity(joined(args))
    )


__all__ = [
    "RiveMacros",
    "build_macros",
    "default_lexicon_path",
    "load_macros",
    "parse_number",
    "parse_quality",
    "register_macros",
]
