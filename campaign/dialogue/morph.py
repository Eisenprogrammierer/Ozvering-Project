"""Детерминированная русская морфология для синтеза.

Модуль — тонкая обёртка над словарным анализатором ``pymorphy3``. Он не
знает предметной области: на вход приходят лемма, падеж, число и род, на
выходе — словоформа. Это даёт авторам контента возможность писать новые
конструкции в JSON, не добавляя вручную каждую словоформу.

Детерминизм: один и тот же вход всегда даёт одну и ту же форму. При
нескольких разборах выбирается первый, который допускает требуемые
граммемы; порядок разборов фиксирован словарём.

Явные исключения и несловарные формы живут в ``synthesis.word_forms``.
Они имеют приоритет над словарём и позволяют автору исправить или
зафиксировать форму без правки Python.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

try:  # pragma: no cover - импорт проверяется тестами окружения
    import pymorphy3
except ImportError as error:  # pragma: no cover
    raise ImportError(
        "для диалогового синтеза нужен pymorphy3; "
        "установите зависимости из requirements.txt"
    ) from error

CASE_GRAMMEMES = {
    "nom": "nomn",
    "gen": "gent",
    "dat": "datv",
    "acc": "accs",
    "ins": "ablt",
    "prep": "loct",
}

NUMBER_GRAMMEMES = {"sg": "sing", "pl": "plur"}

GENDER_GRAMMEMES = {
    "m": "masc",
    "f": "femn",
    "n": "neut",
    "pl": "plur",
    "masc": "masc",
    "femn": "femn",
    "neut": "neut",
    "plur": "plur",
}

_SHORT_GENDER = {"masc": "m", "femn": "f", "neut": "n", "plur": "pl"}


class Morphology:
    """Словарная морфология с детерминированными исключениями."""

    def __init__(self, synthesis: Optional[Mapping[str, Any]] = None):
        data = synthesis or {}
        overrides = data.get("word_forms") or {}
        self._overrides: Dict[str, Mapping[str, str]] = {
            str(key): dict(value)
            for key, value in overrides.items()
            if isinstance(value, Mapping)
        }
        defaults = data.get("morphology") or {}
        self.default_gender = str(defaults.get("gender") or "m")
        self.default_number = str(defaults.get("number") or "sg")
        self._morph = pymorphy3.MorphAnalyzer()
        self._cache: Dict[tuple, str] = {}

    # --- публичный API ----------------------------------------------

    def noun(
        self,
        lemma: str,
        case: str = "nom",
        number: str = "sg",
        entry_id: str = "",
    ) -> str:
        """Просклонять существительное (или именную группу)."""

        case = self._case(case)
        number = self._number(number)
        override = self._override(entry_id, "%s_%s" % (case, number))
        if override:
            return override
        return self._inflect(lemma, case=case, number=number)

    def adjective(
        self,
        lemma: str,
        case: str = "nom",
        number: str = "sg",
        gender: str = "",
        form: str = "long",
        entry_id: str = "",
    ) -> str:
        """Просклонять прилагательное, согласовав его с родом и числом."""

        case = self._case(case)
        number = self._number(number)
        gender = self._gender(gender or self.default_gender)
        if form == "short":
            key = "short_%s" % _SHORT_GENDER.get(gender, "m")
            if number == "pl":
                key = "short_pl"
            override = self._override(entry_id, key)
            if override:
                return override
            return self._inflect(
                lemma,
                adjective=True,
                short=True,
                case=case,
                number=number,
                gender=gender,
            )
        key = "%s_%s" % (
            case,
            "pl" if number == "pl" else _SHORT_GENDER.get(gender, "m"),
        )
        override = self._override(entry_id, key)
        if override:
            return override
        return self._inflect(
            lemma,
            adjective=True,
            case=case,
            number=number,
            gender=gender,
        )

    def verb(
        self,
        lemma: str,
        form: str = "present",
        number: str = "sg",
        gender: str = "",
        person: str = "3",
        entry_id: str = "",
    ) -> str:
        """Проспрягать глагол в настоящем/прошедшем времени или инфинитиве."""

        number = self._number(number)
        key = self._verb_key(form, number, gender, person)
        override = self._override(entry_id, key)
        if override:
            return override
        if form == "infinitive":
            return self._inflect(lemma, infinitive=True)
        if form == "past":
            return self._inflect(
                lemma,
                past=True,
                number=number,
                gender=self._gender(gender or self.default_gender),
            )
        return self._inflect(
            lemma,
            present=True,
            number=number,
            person=str(person or "3"),
        )

    def inflect_phrase(
        self,
        text: str,
        case: str = "nom",
        number: str = "sg",
        gender: str = "",
    ) -> str:
        """Просклонять многословное имя, согласовав прилагательные.

        Для известных сущностей используются курированные формы лексикона;
        этот метод нужен для динамических имён кампании и произвольных
        именных групп из данных.
        """

        text = str(text or "").strip()
        if not text:
            return text
        case = self._case(case)
        number = self._number(number)
        key = ("phrase", text, case, number, self._gender(gender or ""))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        tokens = text.split()
        if len(tokens) == 1:
            result = _match_case(
                tokens[0],
                self._inflect(
                    tokens[0], case=case, number=number, gender=gender
                ),
            )
        else:
            parsed = [self._morph.parse(token)[0] for token in tokens]
            head = self._head_index(parsed)
            personal_name = self._is_name(parsed[0].tag)
            head_gender = self._gender(
                gender
                or self._tag_gender(parsed[head].tag)
                or self.default_gender
            )
            rendered = []
            for index, (token, item) in enumerate(zip(tokens, parsed)):
                pos = self._tag_pos(item.tag)
                if pos in ("ADJF", "PRTF"):
                    inflected = self._inflect(
                        token,
                        adjective=True,
                        case=case,
                        number=number,
                        gender=head_gender,
                    )
                elif pos == "NOUN" and (index == head or personal_name):
                    inflected = self._inflect(
                        token, case=case, number=number, gender=head_gender
                    )
                else:
                    inflected = token
                rendered.append(_match_case(token, inflected))
            result = " ".join(rendered)
        self._cache[key] = result
        return result

    def gender_of(self, text: str) -> str:
        """Род имени: явный признак лексикона или словарный разбор."""

        tokens = str(text or "").split()
        if not tokens:
            return self.default_gender
        parsed = self._morph.parse(tokens[-1])
        if not parsed:
            return self.default_gender
        return self._tag_gender(parsed[0].tag) or self.default_gender

    def number_of(self, text: str) -> str:
        tokens = str(text or "").split()
        if not tokens:
            return self.default_number
        head = tokens[0]
        for token in tokens:
            parsed = self._morph.parse(token)
            if parsed and self._tag_pos(parsed[0].tag) == "NOUN":
                head = token
                break
        parsed = self._morph.parse(head)
        if not parsed:
            return self.default_number
        number = self._tag_number(parsed[0].tag)
        return number or self.default_number

    # --- внутренняя механика ----------------------------------------

    def _override(self, entry_id: str, key: str) -> str:
        if not entry_id:
            return ""
        return str((self._overrides.get(str(entry_id)) or {}).get(key) or "")

    def _inflect(
        self,
        word: str,
        *,
        case: str = "nom",
        number: str = "sg",
        gender: str = "",
        adjective: bool = False,
        short: bool = False,
        present: bool = False,
        past: bool = False,
        infinitive: bool = False,
        person: str = "3",
    ) -> str:
        word = str(word or "").strip()
        if not word:
            return ""
        key = (
            word,
            case,
            number,
            gender,
            adjective,
            short,
            present,
            past,
            infinitive,
            person,
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        grams = self._grammemes(
            case=case,
            number=number,
            gender=gender,
            adjective=adjective,
            short=short,
            present=present,
            past=past,
            infinitive=infinitive,
            person=person,
        )
        result = word
        for parsed in self._morph.parse(word):
            try:
                inflected = parsed.inflect(set(grams))
            except (ValueError, KeyError):
                continue
            if inflected is not None:
                result = inflected.word
                break
        self._cache[key] = result
        return result

    def _grammemes(
        self,
        *,
        case: str,
        number: str,
        gender: str,
        adjective: bool,
        short: bool,
        present: bool,
        past: bool,
        infinitive: bool,
        person: str,
    ) -> set:
        if infinitive:
            return {"INFN"}
        grams = {"sing" if number == "sg" else "plur"}
        if adjective:
            grams.add("ADJS" if short else "ADJF")
            if number == "sg":
                grams.add(GENDER_GRAMMEMES.get(gender, "masc"))
            grams.add(CASE_GRAMMEMES.get(case, "nomn"))
            return grams
        if present:
            grams.update({"VERB", "%sper" % (person or "3")})
            return grams
        if past:
            grams.update({"VERB", "past"})
            if number == "sg":
                grams.add(GENDER_GRAMMEMES.get(gender, "masc"))
            return grams
        grams.add(CASE_GRAMMEMES.get(case, "nomn"))
        return grams

    @staticmethod
    def _head_index(parsed) -> int:
        # В русской именной группе вершина — первое существительное:
        # «Председатель парламента», «Северный совет», «Главная площадь».
        # Последующие существительные обычно зависят от неё и сохраняют
        # свою исходную форму.
        for index, item in enumerate(parsed):
            if Morphology._tag_pos(item.tag) == "NOUN":
                return index
        return len(parsed) - 1

    @staticmethod
    def _tag_pos(tag: Any) -> str:
        try:
            return str(getattr(tag, "POS", "") or "")
        except Exception:
            return ""

    @staticmethod
    def _tag_gender(tag: Any) -> str:
        try:
            value = getattr(tag, "gender", None)
        except Exception:
            return ""
        return str(value or "")

    @staticmethod
    def _tag_number(tag: Any) -> str:
        try:
            value = getattr(tag, "number", None)
        except Exception:
            return ""
        return str(value or "")

    @staticmethod
    def _is_name(tag: Any) -> bool:
        """Личное имя, фамилия или отчество по словарной помете."""

        try:
            return any(
                mark in tag for mark in ("Name", "Surn", "Patr")
            )
        except TypeError:
            return False

    @staticmethod
    def _case(case: str) -> str:
        value = str(case or "nom")
        return value if value in CASE_GRAMMEMES else "nom"

    @staticmethod
    def _number(number: str) -> str:
        value = str(number or "sg")
        return value if value in NUMBER_GRAMMEMES else "sg"

    @staticmethod
    def _gender(gender: str) -> str:
        value = str(gender or "")
        return GENDER_GRAMMEMES.get(value, value or "masc")

    @staticmethod
    def _verb_key(
        form: str, number: str, gender: str, person: str
    ) -> str:
        number_key = "pl" if number == "pl" else "sg"
        if form == "infinitive":
            return "infinitive"
        if form == "past":
            if number_key == "pl":
                return "past_pl"
            return "past_%s" % _SHORT_GENDER.get(
                GENDER_GRAMMEMES.get(gender, "masc"), "m"
            )
        return "present_%s%s" % (number_key, str(person or "3"))


def _match_case(original: str, inflected: str) -> str:
    """Сохранить заглавную букву исходного токена."""

    if not inflected:
        return inflected
    if original.isupper() and len(original) > 1:
        return inflected.upper()
    if original[:1].isupper():
        return inflected[:1].upper() + inflected[1:]
    return inflected
