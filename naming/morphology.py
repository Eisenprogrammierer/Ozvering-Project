from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping

CASES = ("nom", "gen", "dat", "acc", "ins", "prep")
CASE_RU = {
    "nom": "именительный",
    "gen": "родительный",
    "dat": "дательный",
    "acc": "винительный",
    "ins": "творительный",
    "prep": "предложный",
}
GENDERS = ("m", "f", "n", "pl")
_ADJECTIVE_PATTERNS = (
    "hard",
    "soft",
    "stressed",
    "velar",
    "hush",
    "stressed_velar",
    "stressed_hush",
)
_HUSH = ("ж", "ш", "ч", "щ")
_VELAR = ("к", "г", "х")


class MorphologyError(ValueError):
    pass


def normalize_case(case):
    value = str(case or "nom").lower()
    if value in ("nominative", "именительный"):
        value = "nom"
    elif value in ("genitive", "родительный"):
        value = "gen"
    elif value in ("dative", "дательный"):
        value = "dat"
    elif value in ("accusative", "винительный"):
        value = "acc"
    elif value in ("instrumental", "творительный"):
        value = "ins"
    elif value in ("prepositional", "предложный"):
        value = "prep"
    if value not in CASES:
        raise MorphologyError("неизвестный падеж: %r" % (case,))
    return value


def _clean_forms(forms):
    if forms is None:
        return {}
    if not isinstance(forms, Mapping):
        raise MorphologyError("forms должен быть объектом")
    result = {}
    for case, value in forms.items():
        result[normalize_case(case)] = str(value)
    return result


def _require(data, key, label):
    value = str(data.get(key, "") or "").strip()
    if not value:
        raise MorphologyError("%s: пустое поле %s" % (label, key))
    return value


@dataclass(frozen=True)
class Noun:

    id: str
    nom: str
    gen: str
    gender: str = "m"
    animate: bool = False
    number: str = "sg"
    forms: Dict[str, str] = field(default_factory=dict, compare=False)

    def __post_init__(self):
        if self.gender not in GENDERS:
            raise MorphologyError(
                "%s: неизвестный род %r" % (self.id, self.gender)
            )
        if self.number not in ("sg", "pl"):
            raise MorphologyError(
                "%s: неизвестное число %r" % (self.id, self.number)
            )
        object.__setattr__(self, "forms", _clean_forms(self.forms))

    @classmethod
    def from_config(cls, word_id, data):
        if not isinstance(data, Mapping):
            raise MorphologyError("%s: статья должна быть объектом" % word_id)
        return cls(
            id=str(word_id),
            nom=_require(data, "nom", word_id),
            gen=_require(data, "gen", word_id),
            gender=str(data.get("gender", "m")),
            animate=bool(data.get("animate", False)),
            number=str(data.get("number", "sg")),
            forms=data.get("forms") or {},
        )

    def form(self, case):
        case = normalize_case(case)
        if case in self.forms:
            return self.forms[case]
        if case == "nom":
            return self.nom
        if case == "gen":
            return self.gen
        if self.number == "pl":

            return self.forms.get(case, self.nom)
        if case == "acc":
            return self.gen if self.animate else self.nom

        gender = self.gender
        nom = self.nom
        gen = self.gen
        if gender == "f":
            if nom.endswith("а"):
                stem = gen[:-1]
                dat = stem + "е"
                prep = stem + "е"
                ins = stem + ("ей" if stem[-1:] in "жшчщц" else "ой")
                return {"dat": dat, "ins": ins, "prep": prep}[case]
            if nom.endswith("я"):
                stem = gen[:-1]
                if nom.endswith("ия"):
                    dat = gen
                    prep = gen
                else:
                    dat = stem + "е"
                    prep = stem + "е"
                ins = stem + "ей"
                return {"dat": dat, "ins": ins, "prep": prep}[case]
            if nom.endswith("ь"):
                stem = gen[:-1]
                dat = gen
                prep = gen
                ins = stem + "ью"
                return {"dat": dat, "ins": ins, "prep": prep}[case]
        if gender == "m":
            if nom.endswith("й"):
                stem = gen[:-1]
                dat = stem + "ю"
                ins = stem + "ем"
                prep = stem + "е"
                return {"dat": dat, "ins": ins, "prep": prep}[case]
            if nom.endswith("ь"):
                stem = gen[:-1]
                dat = stem + "ю"
                ins = stem + "ем"
                prep = stem + "е"
                return {"dat": dat, "ins": ins, "prep": prep}[case]
            if gen.endswith("а"):
                stem = gen[:-1]
                dat = stem + "у"
                ins = stem + "ом"
                prep = stem + "е"
                return {"dat": dat, "ins": ins, "prep": prep}[case]
        if gender == "n":
            if nom.endswith("о") and gen.endswith("а"):
                stem = gen[:-1]
                dat = stem + "у"
                ins = stem + "ом"
                prep = stem + "е"
                return {"dat": dat, "ins": ins, "prep": prep}[case]
            if nom.endswith("е") and gen.endswith("а"):
                stem = gen[:-1]
                dat = stem + "у"
                ins = stem + "ом"
                prep = stem + "е"
                return {"dat": dat, "ins": ins, "prep": prep}[case]
            if nom.endswith("е") and gen.endswith("я"):
                stem = gen[:-1]
                dat = stem + "ю"
                ins = stem + "ем"
                prep = stem + ("и" if nom.endswith("ие") else "е")
                return {"dat": dat, "ins": ins, "prep": prep}[case]
        raise MorphologyError(
            "не удалось вывести форму %s для %s (%s)" % (case, self.id, nom)
        )


@dataclass(frozen=True)
class Adjective:

    id: str
    nom: str
    forms: Dict[str, str] = field(default_factory=dict, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "forms", _clean_forms(self.forms))
        if not self.nom:
            raise MorphologyError("%s: пустое прилагательное" % self.id)
        self.pattern

    @classmethod
    def from_config(cls, word_id, data):
        if not isinstance(data, Mapping):
            raise MorphologyError("%s: статья должна быть объектом" % word_id)
        return cls(
            id=str(word_id),
            nom=_require(data, "nom", word_id),
            forms=data.get("forms") or {},
        )

    @property
    def pattern(self):
        nom = self.nom
        stem = nom[:-2]
        if nom.endswith("ой"):
            if stem.endswith(_VELAR):
                return "stressed_velar"
            if stem.endswith(_HUSH):
                return "stressed_hush"
            return "stressed"
        if nom.endswith("ий"):
            if stem.endswith(_VELAR):
                return "velar"
            if stem.endswith(_HUSH):
                return "hush"
            return "soft"
        if nom.endswith("ый"):
            return "hard"
        raise MorphologyError(
            "%s: прилагательное должно оканчиваться на -ый/-ий/-ой" % self.id
        )

    def form(self, case, gender="m", animate=False):
        case = normalize_case(case)
        gender = gender if gender in ("m", "f", "n", "pl") else "m"
        custom = self.forms.get("%s:%s" % (case, gender))
        if custom:
            return custom
        if case == "nom" and gender == "m":
            return self.nom
        stem = self.nom[:-2]
        endings = _ADJECTIVE_ENDINGS[self.pattern]
        key = (
            "acc_anim"
            if (case == "acc" and gender == "m" and animate)
            else case
        )
        if gender == "pl" and case == "acc" and animate:
            key = "acc_anim"
        return stem + endings[gender][key]


_ADJECTIVE_ENDINGS = {
    "hard": {
        "m": {
            "nom": "ый",
            "gen": "ого",
            "dat": "ому",
            "acc": "ый",
            "acc_anim": "ого",
            "ins": "ым",
            "prep": "ом",
        },
        "f": {
            "nom": "ая",
            "gen": "ой",
            "dat": "ой",
            "acc": "ую",
            "acc_anim": "ую",
            "ins": "ой",
            "prep": "ой",
        },
        "n": {
            "nom": "ое",
            "gen": "ого",
            "dat": "ому",
            "acc": "ое",
            "acc_anim": "ое",
            "ins": "ым",
            "prep": "ом",
        },
        "pl": {
            "nom": "ые",
            "gen": "ых",
            "dat": "ым",
            "acc": "ые",
            "acc_anim": "ых",
            "ins": "ыми",
            "prep": "ых",
        },
    },
    "soft": {
        "m": {
            "nom": "ий",
            "gen": "его",
            "dat": "ему",
            "acc": "ий",
            "acc_anim": "его",
            "ins": "им",
            "prep": "ем",
        },
        "f": {
            "nom": "яя",
            "gen": "ей",
            "dat": "ей",
            "acc": "юю",
            "acc_anim": "юю",
            "ins": "ей",
            "prep": "ей",
        },
        "n": {
            "nom": "ее",
            "gen": "его",
            "dat": "ему",
            "acc": "ее",
            "acc_anim": "ее",
            "ins": "им",
            "prep": "ем",
        },
        "pl": {
            "nom": "ие",
            "gen": "их",
            "dat": "им",
            "acc": "ие",
            "acc_anim": "их",
            "ins": "ими",
            "prep": "их",
        },
    },
    "stressed": {
        "m": {
            "nom": "ой",
            "gen": "ого",
            "dat": "ому",
            "acc": "ой",
            "acc_anim": "ого",
            "ins": "ым",
            "prep": "ом",
        },
        "f": {
            "nom": "ая",
            "gen": "ой",
            "dat": "ой",
            "acc": "ую",
            "acc_anim": "ую",
            "ins": "ой",
            "prep": "ой",
        },
        "n": {
            "nom": "ое",
            "gen": "ого",
            "dat": "ому",
            "acc": "ое",
            "acc_anim": "ое",
            "ins": "ым",
            "prep": "ом",
        },
        "pl": {
            "nom": "ые",
            "gen": "ых",
            "dat": "ым",
            "acc": "ые",
            "acc_anim": "ых",
            "ins": "ыми",
            "prep": "ых",
        },
    },
    "velar": {
        "m": {
            "nom": "ий",
            "gen": "ого",
            "dat": "ому",
            "acc": "ий",
            "acc_anim": "ого",
            "ins": "им",
            "prep": "ом",
        },
        "f": {
            "nom": "ая",
            "gen": "ой",
            "dat": "ой",
            "acc": "ую",
            "acc_anim": "ую",
            "ins": "ой",
            "prep": "ой",
        },
        "n": {
            "nom": "ое",
            "gen": "ого",
            "dat": "ому",
            "acc": "ое",
            "acc_anim": "ое",
            "ins": "им",
            "prep": "ом",
        },
        "pl": {
            "nom": "ие",
            "gen": "их",
            "dat": "им",
            "acc": "ие",
            "acc_anim": "их",
            "ins": "ими",
            "prep": "их",
        },
    },
    "hush": {
        "m": {
            "nom": "ий",
            "gen": "его",
            "dat": "ему",
            "acc": "ий",
            "acc_anim": "его",
            "ins": "им",
            "prep": "ем",
        },
        "f": {
            "nom": "ая",
            "gen": "ей",
            "dat": "ей",
            "acc": "ую",
            "acc_anim": "ую",
            "ins": "ей",
            "prep": "ей",
        },
        "n": {
            "nom": "ее",
            "gen": "его",
            "dat": "ему",
            "acc": "ее",
            "acc_anim": "ее",
            "ins": "им",
            "prep": "ем",
        },
        "pl": {
            "nom": "ие",
            "gen": "их",
            "dat": "им",
            "acc": "ие",
            "acc_anim": "их",
            "ins": "ими",
            "prep": "их",
        },
    },
    "stressed_velar": {
        "m": {
            "nom": "ой",
            "gen": "ого",
            "dat": "ому",
            "acc": "ой",
            "acc_anim": "ого",
            "ins": "им",
            "prep": "ом",
        },
        "f": {
            "nom": "ая",
            "gen": "ой",
            "dat": "ой",
            "acc": "ую",
            "acc_anim": "ую",
            "ins": "ой",
            "prep": "ой",
        },
        "n": {
            "nom": "ое",
            "gen": "ого",
            "dat": "ому",
            "acc": "ое",
            "acc_anim": "ое",
            "ins": "им",
            "prep": "ом",
        },
        "pl": {
            "nom": "ие",
            "gen": "их",
            "dat": "им",
            "acc": "ие",
            "acc_anim": "их",
            "ins": "ими",
            "prep": "их",
        },
    },
    "stressed_hush": {
        "m": {
            "nom": "ой",
            "gen": "ого",
            "dat": "ому",
            "acc": "ой",
            "acc_anim": "ого",
            "ins": "им",
            "prep": "ом",
        },
        "f": {
            "nom": "ая",
            "gen": "ой",
            "dat": "ой",
            "acc": "ую",
            "acc_anim": "ую",
            "ins": "ой",
            "prep": "ой",
        },
        "n": {
            "nom": "ое",
            "gen": "ого",
            "dat": "ому",
            "acc": "ое",
            "acc_anim": "ое",
            "ins": "им",
            "prep": "ом",
        },
        "pl": {
            "nom": "ие",
            "gen": "их",
            "dat": "им",
            "acc": "ие",
            "acc_anim": "их",
            "ins": "ими",
            "prep": "их",
        },
    },
}


@dataclass(frozen=True)
class Phrase:

    id: str
    nom: str
    forms: Dict[str, str] = field(default_factory=dict, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "forms", _clean_forms(self.forms))

    @classmethod
    def from_config(cls, word_id, data):
        if not isinstance(data, Mapping):
            raise MorphologyError("%s: статья должна быть объектом" % word_id)
        return cls(
            id=str(word_id),
            nom=_require(data, "nom", word_id),
            forms=data.get("forms") or {},
        )

    def form(self, case="nom"):
        return self.forms.get(normalize_case(case), self.nom)

    @property
    def words(self):
        return len(self.nom.split())


def load_word(word_id, data):
    kind = str((data or {}).get("kind", "")).lower()
    if kind == "noun":
        return Noun.from_config(word_id, data)
    if kind == "adj":
        return Adjective.from_config(word_id, data)
    if kind == "phrase":
        return Phrase.from_config(word_id, data)
    raise MorphologyError("%s: неизвестный kind=%r" % (word_id, kind))


def word_count(text):
    return len(str(text or "").split())


def capitalize(text):
    text = str(text or "")
    if not text:
        return text
    return text[:1].upper() + text[1:]


def join_words(words: Iterable[str]):
    return " ".join(
        part for part in (str(word or "").strip() for word in words) if part
    )


def noun_gender(noun: Noun):
    return noun.gender


def agreed_adjective(adjective: Adjective, noun: Noun, case="nom"):
    return adjective.form(case, noun.gender, noun.animate)


__all__ = [
    "CASES",
    "CASE_RU",
    "GENDERS",
    "MorphologyError",
    "Noun",
    "Adjective",
    "Phrase",
    "load_word",
    "normalize_case",
    "word_count",
    "capitalize",
    "join_words",
    "noun_gender",
    "agreed_adjective",
]
