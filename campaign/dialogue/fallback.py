"""Мостик от свободной формулировки к канонической логической форме.

Парсер и фрагменты ``state.json`` покрывают литературные вопросы. Живой
игрок формулирует иначе: «Что нового?», «С кем ты воюешь?», «Расскажи
про противника». Раньше такие фразы падали в ``unknown``, хотя ответ у
агента был.

Правила фолбэка лежат в ``fallback.json``. Python здесь не угадывает
смысл: он проверяет группы токенов, подставляет известные поля картины
мира и отдаёт готовую логическую форму обычному планировщику. Поэтому
новый вопрос — это запись данных, а не новая ветка разбора.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Tuple

from .morphology import tokenize

Texts = Mapping[str, str]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


class FallbackEngine:
    """Сопоставить свободный текст с логической формой из данных."""

    def __init__(
        self,
        catalog: Any,
        knowledge: Any,
        entities: Any = None,
        focus: Any = None,
    ):
        spec = getattr(catalog, "fallback", None)
        self.spec = spec if isinstance(spec, Mapping) else {}
        self.knowledge = knowledge
        self.entities = entities
        self.focus = focus
        raw_rules = list(self.spec.get("rules") or ())
        self.rules = tuple(
            sorted(
                (rule for rule in raw_rules if isinstance(rule, Mapping)),
                key=lambda item: -int(item.get("priority") or 0),
            )
        )

    @property
    def texts(self) -> Texts:
        return _mapping(self.spec.get("texts"))

    def interpret(self, text: str) -> Tuple[Optional[Any], str]:
        """Вернуть ``(sem, rule_id)`` или ``(None, "")``."""

        tokens = tokenize(str(text or ""))
        if not tokens:
            return None, ""
        # Фолбэк — мостик для вопросов и просьб. Утверждения без вопроса
        # должны разбираться грамматикой или оставаться неизвестными,
        # а не подменяться шаблоном.
        if not self._addressed(text, tokens):
            return None, ""
        for rule in self.rules:
            minimum = int(rule.get("min_tokens") or 0)
            if minimum and len(tokens) < minimum:
                continue
            if not self._matches(rule.get("when"), tokens):
                continue
            target = ""
            if bool(rule.get("requires_target", False)):
                target = self._find_target(
                    tokens, rule.get("target_types") or ()
                )
                if (
                    not target
                    and bool(rule.get("use_focus", False))
                    and callable(self.focus)
                ):
                    candidate = _text(self.focus())
                    if self._target_allowed(
                        candidate, rule.get("target_types") or ()
                    ):
                        target = candidate
                if not target:
                    target = self._default_target(rule)
                if not target:
                    continue
            values = self._values(target)
            if not values:
                continue
            sem = self._substitute(rule.get("sem"), values)
            if sem is None:
                continue
            return sem, _text(rule.get("id"))
        return None, ""

    def is_question(self, text: str) -> bool:
        """Вопрос ли это по данным ``fallback.addressing``.

        Отличается от ``is_addressed``: просьба без вопросительного
        слова («Расскажи стихотворение.») не обязана превращаться в
        подсказку о темах мира.
        """

        text = str(text or "")
        if "?" in text:
            return True
        gate = _mapping(self.spec.get("addressing"))
        words = {
            _text(item).casefold()
            for item in gate.get("question_words") or ()
            if _text(item)
        }
        if not words:
            return False
        return any(token in words for token in tokenize(text))

    # --- сопоставление ------------------------------------------------

    def _addressed(self, text: str, tokens: Sequence[str]) -> bool:
        """Вопрос это или просьба, а не декларативное утверждение.

        Список слов задан в данных (``addressing``), потому что это
        часть языка, а не логики. Если данных нет, ограничение
        отключается для совместимости со старыми каталогами.
        """

        gate = _mapping(self.spec.get("addressing"))
        if not gate:
            return True
        if "?" in str(text or ""):
            return True
        words = {
            _text(item).casefold()
            for group in ("question_words", "request_words")
            for item in (gate.get(group) or ())
            if _text(item)
        }
        if not words:
            return True
        return any(token in words for token in tokens)

    def _matches(self, when: Any, tokens: Sequence[str]) -> bool:
        if isinstance(when, Mapping):
            groups = when.get("all") or ()
            any_groups = when.get("any") or ()
        else:
            groups = when or ()
            any_groups = ()
        for group in groups:
            if not self._group(group, tokens):
                return False
        if any_groups:
            return any(
                self._group(group, tokens) for group in any_groups
            )
        return bool(groups) or bool(any_groups)

    @staticmethod
    def _group(group: Any, tokens: Sequence[str]) -> bool:
        alternatives = {
            _text(item).casefold()
            for item in (group or ())
            if _text(item)
        }
        if not alternatives:
            return False
        return any(
            token in alternatives
            or (
                len(token) >= 4
                and any(
                    len(alt) >= 4
                    and (
                        token.startswith(alt)
                        or alt.startswith(token)
                    )
                    for alt in alternatives
                )
            )
            for token in tokens
        )

    # --- подстановка --------------------------------------------------

    _NOT_TARGET = (
        "noun:",
        "verb:",
        "wh:",
        "prep:",
        "pron:",
        "part:",
        "neg:",
        "conj:",
        "det:",
        "adj:",
        "greeting:",
        "farewell:",
    )

    def _find_target(
        self, tokens: Sequence[str], types: Sequence[str] = ()
    ) -> str:
        entities = self.entities
        if entities is None:
            return ""
        for index in range(len(tokens)):
            found = entities.resolve(tokens, index, "entity")
            if found is None:
                continue
            identifier, _span = found
            if self._target_allowed(identifier, types):
                return _text(identifier)
        return ""

    def _target_allowed(
        self, identifier: str, types: Sequence[str] = ()
    ) -> bool:
        identifier = _text(identifier)
        if not identifier:
            return False
        if identifier.startswith(self._NOT_TARGET):
            return False
        entities = self.entities
        if entities is None:
            return False
        allowed = {
            _text(item).casefold() for item in types if _text(item)
        }
        type_name = _text(entities.type_of(identifier)).casefold()
        if allowed and type_name not in allowed:
            return False
        if getattr(entities, "ignored", lambda value: False)(identifier):
            return False
        return True

    def _default_target(self, rule: Mapping[str, Any]) -> str:
        value = _text(rule.get("default_target"))
        if not value:
            return ""
        if value.startswith("$"):
            return _text(self._values("").get(value))
        return value

    def _values(self, target: str) -> Mapping[str, str]:
        knowledge = self.knowledge
        values = {
            "$target": _text(target),
            "$speaker_faction": _text(
                getattr(knowledge, "faction_id", "")
            ),
            "$player_faction": _text(
                getattr(knowledge, "player_faction", "")
            ),
            "$speaker_id": _text(
                getattr(knowledge, "speaker_id", "")
            ),
            "$player_id": _text(
                getattr(knowledge, "player_id", "")
            ),
            "$side": _text(getattr(knowledge, "side", "")),
        }
        return {
            key: value for key, value in values.items() if value
        }

    def _substitute(self, value: Any, values: Mapping[str, str]):
        if isinstance(value, str):
            if not value.startswith("$"):
                return value
            return values.get(value, "")
        if isinstance(value, list):
            result = []
            for item in value:
                replaced = self._substitute(item, values)
                if replaced is None or replaced == "":
                    return None
                result.append(replaced)
            return result
        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                replaced = self._substitute(item, values)
                if replaced is None:
                    return None
                if replaced == "" and isinstance(item, str):
                    return None
                result[str(key)] = replaced
            return result
        return value
