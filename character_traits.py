"""Данные и расчёт черт характера.

Модуль отделяет **определения** черт от кода: базы, разброс, модификаторы
архетипов, влияние на потребности, мораль, панику, фанатизм и выбор
намерения лежат в ``configs/characters/traits.json``. Код знает только
формулу ``base + scale * (value - center)`` и порядок применения эффектов.

``warfare.Personality`` и ``warfare.Character`` используют этот загрузчик,
поэтому изменение силы черты не требует правки Python-кода.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
from typing import Dict, Mapping

DEFAULT_PATH = (
    Path(__file__).resolve().parent
    / "configs"
    / "characters"
    / "traits.json"
)


class TraitDataError(ValueError):
    """Файл черт отсутствует или содержит некорректное определение."""


def default_traits_path():
    return DEFAULT_PATH


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _text(value, default=""):
    text = str(value or "").strip()
    return text or default


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _number(value, low)))


@dataclass(frozen=True)
class LinearEffect:
    """Линейный эффект черты: ``base + scale * (value - center)``."""

    base: float = 0.0
    scale: float = 0.0
    center: float = 0.0

    def apply(self, value):
        return self.base + self.scale * (float(value) - self.center)

    @classmethod
    def from_data(cls, data, where):
        if not isinstance(data, Mapping):
            raise TraitDataError("%s: эффект должен быть объектом" % where)
        return cls(
            base=_number(data.get("base"), 0.0),
            scale=_number(data.get("scale"), 0.0),
            center=_number(data.get("center"), 0.0),
        )


@dataclass(frozen=True)
class TraitDefinition:
    key: str
    label: str
    summary: str
    base: float
    need_urgency: Mapping[str, LinearEffect] = field(default_factory=dict)
    need_growth: Mapping[str, LinearEffect] = field(default_factory=dict)
    morale_baseline: LinearEffect = LinearEffect()
    panic_score: LinearEffect = LinearEffect()
    fanatic_score: LinearEffect = LinearEffect()
    intent_bias: Mapping[str, LinearEffect] = field(default_factory=dict)


def _effects(data, where):
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise TraitDataError("%s: должен быть объектом" % where)
    return {
        str(key): LinearEffect.from_data(value, "%s.%s" % (where, key))
        for key, value in data.items()
    }


class TraitModel:
    """Разобранная модель черт и связанных коэффициентов."""

    def __init__(self, data, path=None):
        if not isinstance(data, Mapping):
            raise TraitDataError("корень файла черт должен быть объектом")
        self.path = Path(path) if path is not None else None
        self.schema = int(_number(data.get("schema"), 1))
        if self.schema != 1:
            raise TraitDataError("неподдерживаемая версия схемы: %s" % self.schema)
        self.label = _text(data.get("label"), "Черты характера")
        self.variance = max(0.0, _number(data.get("variance"), 0.0))

        raw_traits = data.get("traits")
        if not isinstance(raw_traits, Mapping) or not raw_traits:
            raise TraitDataError("traits должен быть непустым объектом")
        self.traits: Dict[str, TraitDefinition] = {}
        for key, value in raw_traits.items():
            key = str(key)
            if not isinstance(value, Mapping):
                raise TraitDataError("traits.%s должен быть объектом" % key)
            label = _text(value.get("label"))
            summary = _text(value.get("summary"))
            if not label or not summary:
                raise TraitDataError(
                    "traits.%s: нужны label и summary" % key
                )
            self.traits[key] = TraitDefinition(
                key=key,
                label=label,
                summary=summary,
                base=_clamp(value.get("base"), 0.0, 1.0),
                need_urgency=_effects(
                    value.get("need_urgency"), "traits.%s.need_urgency" % key
                ),
                need_growth=_effects(
                    value.get("need_growth"), "traits.%s.need_growth" % key
                ),
                morale_baseline=LinearEffect.from_data(
                    value.get("morale_baseline") or {},
                    "traits.%s.morale_baseline" % key,
                ),
                panic_score=LinearEffect.from_data(
                    value.get("panic_score") or {},
                    "traits.%s.panic_score" % key,
                ),
                fanatic_score=LinearEffect.from_data(
                    value.get("fanatic_score") or {},
                    "traits.%s.fanatic_score" % key,
                ),
                intent_bias=_effects(
                    value.get("intent_bias"), "traits.%s.intent_bias" % key
                ),
            )

        self.archetypes = self._parse_archetypes(data.get("archetypes"))
        model = data.get("model") or {}
        if not isinstance(model, Mapping):
            raise TraitDataError("model должен быть объектом")
        self.model = dict(model)
        self.morale = self._section("morale")
        self.mind = self._section("mind")
        self.intent = self._section("intent")
        self.detachment = self._section("detachment")
        self._validate_model()

    def _section(self, name):
        value = self.model.get(name) or {}
        if not isinstance(value, Mapping):
            raise TraitDataError("model.%s должен быть объектом" % name)
        return dict(value)

    def _parse_archetypes(self, data):
        if data is None:
            return {}
        if not isinstance(data, Mapping):
            raise TraitDataError("archetypes должен быть объектом")
        result = {}
        for key, value in data.items():
            key = str(key)
            if not isinstance(value, Mapping):
                raise TraitDataError("archetypes.%s должен быть объектом" % key)
            modifiers = value.get("modifiers") or {}
            if not isinstance(modifiers, Mapping):
                raise TraitDataError(
                    "archetypes.%s.modifiers должен быть объектом" % key
                )
            clean = {}
            for trait, amount in modifiers.items():
                trait = str(trait)
                if trait not in self.traits:
                    raise TraitDataError(
                        "archetypes.%s: неизвестная черта %s" % (key, trait)
                    )
                clean[trait] = _number(amount, 0.0)
            result[key] = {
                "label": _text(value.get("label"), key),
                "modifiers": clean,
            }
        return result

    def _validate_model(self):
        intents = self.intent.get("intents")
        if not isinstance(intents, (list, tuple)) or not intents:
            raise TraitDataError("model.intent.intents должен быть списком")
        self.intents = tuple(str(item) for item in intents)
        need_intents = self.intent.get("need_intents")
        if not isinstance(need_intents, Mapping):
            raise TraitDataError("model.intent.need_intents должен быть объектом")
        for need, mapping in need_intents.items():
            if not isinstance(mapping, Mapping):
                raise TraitDataError(
                    "model.intent.need_intents.%s должен быть объектом" % need
                )
            for intent, weight in mapping.items():
                if str(intent) not in self.intents:
                    raise TraitDataError(
                        "model.intent.need_intents.%s: неизвестное намерение %s"
                        % (need, intent)
                    )
                if _number(weight, 0.0) < 0.0:
                    raise TraitDataError(
                        "model.intent.need_intents.%s.%s: вес не может быть < 0"
                        % (need, intent)
                    )
        force = self.intent.get("force", [])
        if not isinstance(force, (list, tuple)):
            raise TraitDataError("model.intent.force должен быть списком")
        for rule in force:
            if not isinstance(rule, Mapping):
                raise TraitDataError("model.intent.force: правило не объект")
            if str(rule.get("intent")) not in self.intents:
                raise TraitDataError(
                    "model.intent.force: неизвестное намерение %s"
                    % rule.get("intent")
                )

    # ------------------------------------------------------------------
    # Личность
    # ------------------------------------------------------------------
    @property
    def trait_names(self):
        return tuple(self.traits)

    @property
    def labels(self):
        return {key: item.label for key, item in self.traits.items()}

    def definition(self, key):
        return self.traits.get(str(key))

    def archetype_modifiers(self, archetype):
        item = self.archetypes.get(str(archetype or ""))
        return dict(item["modifiers"]) if item else {}

    def roll(self, seed=0, archetype="rifleman"):
        """Собрать значения черт: база + разброс + модификатор архетипа."""
        import random

        rng = random.Random(int(seed))
        modifiers = self.archetype_modifiers(archetype)
        values = {}
        for key in self.trait_names:
            definition = self.traits[key]
            value = definition.base
            value += rng.uniform(-self.variance, self.variance)
            value += modifiers.get(key, 0.0)
            values[key] = _clamp(value, 0.0, 1.0)
        return values

    # ------------------------------------------------------------------
    # Динамика потребностей
    # ------------------------------------------------------------------
    def urgency_factor(self, need, values):
        need = str(need)
        result = 1.0
        for key, definition in self.traits.items():
            effect = definition.need_urgency.get(need)
            if effect is not None:
                result *= effect.apply(values.get(key, definition.base))
        return result

    def growth_factor(self, need, values):
        need = str(need)
        result = 1.0
        for key, definition in self.traits.items():
            effect = definition.need_growth.get(need)
            if effect is not None:
                result *= effect.apply(values.get(key, definition.base))
        return result

    def morale_baseline(self, values):
        total = 0.0
        for key, definition in self.traits.items():
            total += definition.morale_baseline.apply(
                values.get(key, definition.base)
            )
        return total

    def panic_contribution(self, values):
        total = 0.0
        for key, definition in self.traits.items():
            total += definition.panic_score.apply(
                values.get(key, definition.base)
            )
        return total

    def fanatic_contribution(self, values):
        total = 0.0
        for key, definition in self.traits.items():
            total += definition.fanatic_score.apply(
                values.get(key, definition.base)
            )
        return total

    # ------------------------------------------------------------------
    # Логика действий
    # ------------------------------------------------------------------
    def intent_bias(self, values):
        result = {}
        for key, definition in self.traits.items():
            value = values.get(key, definition.base)
            for intent, effect in definition.intent_bias.items():
                result[intent] = result.get(intent, 0.0) + effect.apply(value)
        return result

    def _rule_matches(self, rule, values, modulation):
        if "trait" in rule:
            key = str(rule.get("trait"))
            definition = self.traits.get(key)
            if definition is None:
                return False
            value = values.get(key, definition.base)
            if "at_least" in rule and value < _number(rule["at_least"]):
                return False
            if "at_most" in rule and value > _number(rule["at_most"]):
                return False
            return True
        if "mod" in rule:
            key = str(rule.get("mod"))
            value = _number(getattr(modulation, key, 0.0), 0.0)
            if "at_least" in rule and value < _number(rule["at_least"]):
                return False
            if "at_most" in rule and value > _number(rule["at_most"]):
                return False
            return True
        return False

    def intention_scores(self, desires, values, modulation=None):
        """Оценки намерений: потребности + черты + приказы.

        Потребность даёт вклад во все намерения, указанные в
        ``need_intents``. Черты добавляют стабильную поправку, поэтому
        одинаковые потребности у смелого и осторожного персонажа ведут к
        разным действиям.
        """
        scores = {intent: 0.0 for intent in self.intents}
        mapping = self.intent.get("need_intents") or {}
        for need, urgency in (desires or {}).items():
            for intent, weight in (mapping.get(str(need)) or {}).items():
                if intent in scores:
                    scores[intent] += _number(urgency, 0.0) * _number(
                        weight, 0.0
                    )
        for intent, value in self.intent_bias(values).items():
            if intent in scores:
                scores[intent] += value
        for rule in self.intent.get("force", []):
            if not self._rule_matches(rule, values, modulation):
                continue
            intent = str(rule.get("intent"))
            if intent in scores:
                scores[intent] += _number(rule.get("bonus"), 1.0)
        return scores

    def choose_intent(self, desires, values, modulation=None):
        scores = self.intention_scores(desires, values, modulation)
        if not scores:
            return "fire", {}
        intent = max(scores, key=lambda key: (scores[key], key))
        return intent, scores

    def reason(self, intent):
        return str(
            (self.intent.get("reasons") or {}).get(str(intent), "устав")
        )

    def fanaticism_override(self):
        return _number(self.intent.get("fanaticism_override"), 0.35)

    # ------------------------------------------------------------------
    # Отделение: агрегаты черт
    # ------------------------------------------------------------------
    def aggregate(self, profile, values):
        weights = self.detachment.get(profile) or {}
        if not isinstance(weights, Mapping) or not weights:
            return 0.5
        total = 0.0
        weighted = 0.0
        for key, weight in weights.items():
            definition = self.traits.get(str(key))
            if definition is None:
                continue
            weight = _number(weight, 0.0)
            total += abs(weight)
            weighted += weight * values.get(str(key), definition.base)
        if total <= 0.0:
            return 0.5
        return _clamp(weighted / total, 0.0, 1.0)

    def detachment_value(self, key, default=0.0):
        return _number(self.detachment.get(key), default)

    def detachment_effect(self, key, value, default=0.0):
        data = self.detachment.get(key)
        if not isinstance(data, Mapping):
            return default
        return LinearEffect.from_data(data, "model.detachment.%s" % key).apply(
            value
        )

    def mind_value(self, key, default=0.0):
        return _number(self.mind.get(key), default)

    def morale_value(self, key, default=0.0):
        return _number(self.morale.get(key), default)

    def morale_stress(self, needs):
        weights = self.morale.get("stress") or {}
        return sum(
            _number(needs.get(str(need)), 0.0) * _number(weight, 0.0)
            for need, weight in weights.items()
        )

    def panic_threshold(self):
        return self.mind_value("panic_threshold", 0.42)

    def shaken_threshold(self):
        return self.mind_value("shaken_threshold", 0.30)

    def fanatic_threshold(self):
        return self.mind_value("fanatic_threshold", 0.48)

    def fanatic_morale_floor(self):
        return self.mind_value("fanatic_morale_floor", 32.0)

    def panic_timer(self):
        return int(self.mind_value("panic_timer", 3))

    def panic_cooldown(self):
        return int(self.mind_value("panic_cooldown", 20))

    def fanatic_timer(self):
        return int(self.mind_value("fanatic_timer", 3))

    def fanatic_cooldown(self):
        return int(self.mind_value("fanatic_cooldown", 16))


def _parse_file(path):
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise TraitDataError("файл черт не найден: %s" % path) from exc
    except json.JSONDecodeError as exc:
        raise TraitDataError("битый JSON черт %s: %s" % (path, exc)) from exc
    return TraitModel(data, path=path)


@lru_cache(maxsize=8)
def _load_cached(path_text, mtime_ns):
    return _parse_file(path_text)


def load_traits(path=None, use_cache=True):
    path = Path(path) if path is not None else DEFAULT_PATH
    if not use_cache:
        return _parse_file(path)
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise TraitDataError("файл черт не найден: %s" % path) from exc
    return _load_cached(str(path.resolve()), stat.st_mtime_ns)
