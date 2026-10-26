"""Генератор естественных русских названий автоматов и взаимодействий.

Название собирается из ограниченной грамматики:

    [прилагательные] существительное [родительные группы] [фраза]

Количество слов задаётся усечённым логистическим распределением (мода 2,
потолок 10). Падежи и согласование выводятся морфологией, а не подстановкой
готовых строк.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Dict, List, Optional, Sequence

from .catalog import NamingCatalog, default_catalog
from .distribution import MAX_WORDS, sample_word_count
from .morphology import (
    Adjective, Noun, Phrase, capitalize, join_words, word_count,
)


@dataclass(frozen=True)
class Recipe:
    """Сколько слотов каждого вида использовать."""

    adjectives: int
    dep1_words: int
    dep2_words: int
    extension_words: int

    @property
    def total(self):
        conjunction = 1 if self.dep2_words else 0
        return (1 + self.adjectives + self.dep1_words + self.dep2_words
                + conjunction + self.extension_words)


@dataclass(frozen=True)
class NameResult:
    """Готовое название и его падежные формы."""

    text: str
    kind: str
    seed: int
    forms: Dict[str, str] = field(default_factory=dict)
    parts: Dict = field(default_factory=dict)
    mode: Optional[str] = None
    need: Optional[str] = None
    level: Optional[int] = None
    theme: Optional[str] = None

    @property
    def words(self):
        return word_count(self.text)

    @property
    def nom(self):
        return self.forms.get("nom", self.text)

    @property
    def gen(self):
        return self.forms.get("gen", self.text)

    def render(self, case="nom"):
        return self.forms.get(str(case or "nom"), self.text)

    def as_dict(self):
        return {
            "text": self.text,
            "kind": self.kind,
            "seed": self.seed,
            "words": self.words,
            "mode": self.mode,
            "need": self.need,
            "level": self.level,
            "theme": self.theme,
            "forms": dict(self.forms),
            "parts": dict(self.parts),
        }

    def __str__(self):
        return self.text


def _ordered_sample(rng, values: Sequence, count):
    if count <= 0 or not values:
        return []
    count = min(int(count), len(values))
    indices = sorted(rng.sample(range(len(values)), count))
    return [values[index] for index in indices]


def _phrase_lengths(phrases: Sequence[Phrase]):
    return sorted({phrase.words for phrase in phrases})


def _root_key(word):
    """Грубый корень для запрета тавтологий вроде «резервный резерв»."""
    text = str(getattr(word, "nom", "") or "").lower().replace("ё", "е")
    return text[:5]


def _with_primary(pool):
    """Для классов заменить широкие пулы на ядро «тема + уровень»."""
    selected = dict(pool)
    for key in ("heads", "adjectives", "dependents",
                "dependent_adjectives"):
        primary = pool.get("primary_" + key)
        if primary:
            selected[key] = primary
    return selected


def _filter_pool(pool, head):
    key = _root_key(head)
    filtered = dict(pool)
    filtered["adjectives"] = [item for item in pool["adjectives"]
                              if _root_key(item) != key]
    filtered["dependents"] = [item for item in pool["dependents"]
                              if _root_key(item) != key]
    filtered["dependent_adjectives"] = [
        item for item in pool["dependent_adjectives"]
        if _root_key(item) != key
    ]
    return filtered


def _plans(pool, target: int):
    """Все рецепты, дающие ровно ``target`` слов."""
    adjective_count = len(pool["adjectives"])
    dependent_count = len(pool["dependents"])
    dep_adjective_count = len(pool["dependent_adjectives"])
    extension_lengths = _phrase_lengths(pool["extensions"])
    recipes = []
    for adjectives in range(0, min(2, adjective_count) + 1):
        for dep1 in (0, 1, 2):
            if dep1 and not dependent_count:
                continue
            for dep2 in (0, 1, 2):
                if dep2 and (not dep1 or dependent_count < 2):
                    continue
                needed_dep_adjectives = (
                    (1 if dep1 == 2 else 0) + (1 if dep2 == 2 else 0))
                if needed_dep_adjectives > dep_adjective_count:
                    continue
                for extension in [0] + extension_lengths:
                    recipe = Recipe(adjectives, dep1, dep2, extension)
                    if recipe.total == target and recipe.total <= MAX_WORDS:
                        recipes.append(recipe)
    return recipes


def _fallback_plan(pool, target: int):
    for candidate in range(min(MAX_WORDS, target), 0, -1):
        plans = _plans(pool, candidate)
        if plans:
            return plans
    return [Recipe(0, 0, 0, 0)]


class NameGenerator:
    """Детерминированный по seed генератор названий."""

    def __init__(self, catalog: Optional[NamingCatalog] = None, seed=0):
        self.catalog = catalog or default_catalog()
        self.seed = int(seed)
        self.rng = random.Random(self.seed)

    def _random(self, seed=None):
        if seed is None:
            return self.rng
        return random.Random(int(seed))

    def automaton_name(self, mode, need=None, level=1, theme=None, seed=None):
        """Название автомата класса ``mode``."""
        if not mode:
            raise ValueError("нужен класс автомата (mode)")
        rng = self._random(seed)
        pool, selected_theme = self.catalog.pool_for(
            mode, need=need, level=level, theme=theme)
        return self._build(
            pool, rng, kind="automaton", mode=mode, need=need,
            level=int(level or 1), theme=selected_theme,
            seed=seed if seed is not None else self.seed)

    def interaction_name(self, type_id, seed=None):
        """Название семантического типа взаимодействия."""
        rng = self._random(seed)
        pool = self.catalog.interaction_pool(type_id)
        return self._build(pool, rng, kind="interaction", mode=type_id,
                           seed=seed if seed is not None else self.seed)

    def generate_many(self, mode, need=None, level=1, theme=None, count=10,
                      seed=None):
        """Несколько разных названий для одного класса."""
        rng = self._random(seed)
        results = []
        seen = set()
        attempts = 0
        limit = max(1, int(count))
        while len(results) < limit and attempts < limit * 40:
            attempts += 1
            pool, selected_theme = self.catalog.pool_for(
                mode, need=need, level=level, theme=theme)
            item = self._build(
                pool, rng, kind="automaton", mode=mode, need=need,
                level=int(level or 1), theme=selected_theme,
                seed=seed if seed is not None else self.seed)
            if item.text in seen:
                continue
            seen.add(item.text)
            results.append(item)
        return results

    def _build(self, pool, rng, kind, mode=None, need=None, level=None,
               theme=None, seed=None):
        if not pool.get("heads"):
            raise ValueError("в пуле нет существительных-голов")
        head_pool = pool.get("primary_heads") or pool["heads"]
        head: Noun = rng.choice(head_pool)
        pool = _filter_pool(_with_primary(pool), head)
        target = sample_word_count(rng)
        plans = _plans(pool, target) or _fallback_plan(pool, target)
        recipe = rng.choice(plans)
        last_error = None
        for _ in range(8):
            try:
                return self._render(
                    pool, rng, recipe, head, kind=kind, mode=mode, need=need,
                    level=level, theme=theme, seed=seed)
            except (IndexError, ValueError) as exc:
                last_error = exc
        raise ValueError("не удалось собрать название: %s" % last_error)

    def _render(self, pool, rng, recipe: Recipe, head, kind, mode, need, level,
                theme, seed=None):
        adjectives: List[Adjective] = _ordered_sample(
            rng, pool["adjectives"], recipe.adjectives)
        lengths = [length for length in
                   (recipe.dep1_words, recipe.dep2_words) if length]
        dependent_nouns: List[Noun] = rng.sample(
            pool["dependents"], len(lengths))
        available_dep_adjectives = list(pool["dependent_adjectives"])
        dependents = []
        for length, noun in zip(lengths, dependent_nouns):
            tokens = []
            if length == 2:
                candidates = [
                    item for item in available_dep_adjectives
                    if _root_key(item) != _root_key(noun)
                ]
                if not candidates:
                    raise ValueError(
                        "нет подходящего прилагательного для зависимого")
                adjective = rng.choice(candidates)
                available_dep_adjectives.remove(adjective)
                tokens.append(
                    adjective.form("gen", noun.gender, noun.animate))
            tokens.append(noun.form("gen"))
            dependents.append((tokens, noun))
        phrase = None
        if recipe.extension_words:
            options = [item for item in pool["extensions"]
                       if item.words == recipe.extension_words]
            if not options:
                raise ValueError("нет фразы нужной длины")
            phrase = rng.choice(options)

        gender = head.gender
        animate = head.animate
        head_nom = head.form("nom")
        adjective_nom = [item.form("nom", gender, animate)
                         for item in adjectives]
        dependent_tokens = []
        for index, (tokens, _) in enumerate(dependents):
            if index:
                dependent_tokens.append("и")
            dependent_tokens.extend(tokens)
        tokens = adjective_nom + [head_nom] + dependent_tokens
        if phrase is not None:
            tokens.append(phrase.form("nom"))
        text = capitalize(join_words(tokens))
        if word_count(text) != recipe.total:
            raise ValueError("длина названия не совпала с рецептом")

        forms = {}
        for case in ("nom", "gen", "dat", "acc", "ins", "prep"):
            case_tokens = [
                item.form(case, gender, animate) for item in adjectives
            ] + [head.form(case)] + dependent_tokens
            if phrase is not None:
                case_tokens.append(phrase.form(case))
            forms[case] = capitalize(join_words(case_tokens))
        forms["nom"] = text

        return NameResult(
            text=text,
            kind=kind,
            seed=int(seed if seed is not None else self.seed),
            forms=forms,
            parts={
                "head": {"id": head.id, "text": head_nom},
                "adjectives": [{"id": item.id,
                                "text": item.form("nom", gender, animate)}
                               for item in adjectives],
                "dependents": [
                    {"id": noun.id, "text": noun.form("gen"),
                     "tokens": list(tokens)}
                    for tokens, noun in dependents
                ],
                "extension": ({"id": phrase.id, "text": phrase.nom}
                              if phrase is not None else None),
                "recipe": {
                    "adjectives": recipe.adjectives,
                    "dep1_words": recipe.dep1_words,
                    "dep2_words": recipe.dep2_words,
                    "extension_words": recipe.extension_words,
                },
            },
            mode=mode,
            need=need,
            level=level,
            theme=theme,
        )


__all__ = ["Recipe", "NameResult", "NameGenerator"]
