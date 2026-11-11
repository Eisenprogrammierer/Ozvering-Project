"""BDI-слой персонажей: желания, убеждения и намерения.

Модуль отделяет **данные** BDI от кода. Все 16 желаний, предикаты
убеждений, сути намерений, коэффициенты затухания и связей читаются из
``configs/characters/bdi.json``. Код знает только формулы:

* желание растёт со временем и заражает соседние желания через
  ``spillover``;
* запущенное желание давит на силу и энергию через ``force_drain`` и
  ``energy_drain``;
* удовлетворение желания возвращает силу/энергию через
  ``satisfaction``;
* убеждение — триплет ``(субъект, предикат, объект)``;
* намерение — дуплет ``(объект намерения, суть намерения)``;
* смерть персонажа наступает при ``force <= 0``, а не по отдельной
  шкале здоровья.

Здоровье, раны и болезнь — не метрики автомата, а состояния BDI. Они
живут в :class:`BDIState.conditions` и влияют на силу/энергию.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

DEFAULT_PATH = (
    Path(__file__).resolve().parent
    / "configs"
    / "characters"
    / "bdi.json"
)

NEEDS = (
    "hunger",
    "thirst",
    "fatigue",
    "health",
    "fear",
    "anxiety",
    "loneliness",
    "reproduction",
    "knowledge",
    "creativity",
    "boredom",
    "status",
    "spirituality",
    "skill",
    "love",
    "friendship",
)


class BDIError(ValueError):
    """Некорректный файл BDI или нарушение контракта триплета/дуплета."""


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(result) or math.isinf(result):
        return float(default)
    return result


def _text(value, default=""):
    text = str(value or "").strip()
    return text or default


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _number(value, low)))


def boundary_split(value):
    """Разделить строку ``kind:id`` на вид и идентификатор."""
    text = _text(value)
    if ":" not in text:
        return "", text
    kind, _, identifier = text.partition(":")
    return kind, identifier


@dataclass(frozen=True)
class Belief:
    """Убеждение-триплет: субъект, предикат, объект.

    ``subject`` и ``object`` — идентификаторы автоматов. Предикат — имя
    свойства или отношения из ``belief_predicates``. Объект может быть
    внешним идентификатором, если контент ещё не создал автомат: BDI не
    обязан знать весь мир.
    """

    subject: str
    predicate: str
    object: str

    def __post_init__(self):
        object.__setattr__(self, "subject", _text(self.subject))
        object.__setattr__(self, "predicate", _text(self.predicate))
        object.__setattr__(self, "object", _text(self.object))
        if not self.subject or not self.predicate or not self.object:
            raise BDIError("убеждение требует subject, predicate и object")

    def as_tuple(self) -> Tuple[str, str, str]:
        return (self.subject, self.predicate, self.object)

    def as_dict(self) -> dict:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
        }

    @classmethod
    def from_data(cls, data):
        if isinstance(data, Belief):
            return data
        if isinstance(data, Mapping):
            return cls(
                data.get("subject"),
                data.get("predicate"),
                data.get("object"),
            )
        if isinstance(data, (list, tuple)) and len(data) == 3:
            return cls(data[0], data[1], data[2])
        raise BDIError("убеждение должно быть триплетом или объектом")


@dataclass(frozen=True)
class Intention:
    """Намерение-дуплет: объект намерения и суть намерения.

    Объект — другой автомат, персонаж или потребность. Вид объекта
    выводится по имени: если ``target`` входит в 16 желаний, это
    потребность; если начинается с ``character:``/``automaton:`` —
    явный вид; иначе считается идентификатором автомата.
    """

    target: str
    essence: str

    def __post_init__(self):
        object.__setattr__(self, "target", _text(self.target))
        object.__setattr__(self, "essence", _text(self.essence))
        if not self.target or not self.essence:
            raise BDIError("намерение требует target и essence")

    @property
    def target_kind(self) -> str:
        explicit, identifier = boundary_split(self.target)
        if explicit in ("character", "automaton", "need"):
            return explicit
        if self.target in NEEDS:
            return "need"
        return "automaton"

    @property
    def target_id(self) -> str:
        _kind, identifier = boundary_split(self.target)
        return identifier

    # --- производные проекции для старого UI и логов ----------------
    @property
    def kind(self) -> str:
        """Легаси-вид действия; каноническая суть — ``essence``."""
        return self.essence

    @property
    def need(self) -> str:
        """Потребность-объект, если намерение направлено на желание."""
        return self.target if self.target in NEEDS else ""

    def as_tuple(self) -> Tuple[str, str]:
        return (self.target, self.essence)

    def as_dict(self) -> dict:
        return {"target": self.target, "essence": self.essence}

    @classmethod
    def from_data(cls, data):
        if isinstance(data, Intention):
            return data
        if isinstance(data, Mapping):
            return cls(data.get("target"), data.get("essence"))
        if isinstance(data, (list, tuple)) and len(data) == 2:
            return cls(data[0], data[1])
        raise BDIError("намерение должно быть дуплетом или объектом")


@dataclass(frozen=True)
class NeedDefinition:
    key: str
    label: str
    good: str
    initial: float
    growth: float
    threshold: float
    force_drain: float
    energy_drain: float
    spillover: Mapping[str, float] = field(default_factory=dict)
    satisfaction: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ConditionDefinition:
    key: str
    label: str
    maximum: float
    progress: float
    rest_recovery: float
    treat_rate: float
    work_penalty: float
    work_floor: float
    force_drain: float
    energy_drain: float
    health_need_growth: float
    extra: Mapping[str, float] = field(default_factory=dict)


class BDIConfig:
    """Разобранная модель BDI и её коэффициентов."""

    def __init__(self, data, path=None):
        if not isinstance(data, Mapping):
            raise BDIError("корень bdi.json должен быть объектом")
        self.path = Path(path) if path is not None else None
        self.schema = int(_number(data.get("schema"), 1))
        if self.schema != 1:
            raise BDIError("неподдерживаемая схема BDI: %s" % self.schema)
        self.label = _text(data.get("label"), "BDI персонажей")
        self.history = max(1, int(_number(data.get("history"), 8)))
        self.strict_predicates = bool(data.get("strict_predicates", False))
        self.death = dict(data.get("death") or {})
        if self.death.get("metric", "force") != "force":
            raise BDIError("смерть BDI пока считается только по force")

        raw_needs = data.get("needs")
        if not isinstance(raw_needs, Mapping) or not raw_needs:
            raise BDIError("needs должен быть непустым объектом")
        self.needs: Dict[str, NeedDefinition] = {}
        for key, value in raw_needs.items():
            key = str(key)
            if not isinstance(value, Mapping):
                raise BDIError("needs.%s должен быть объектом" % key)
            self.needs[key] = NeedDefinition(
                key=key,
                label=_text(value.get("label"), key),
                good=_text(value.get("good"), key),
                initial=_clamp(value.get("initial"), 0.0, 1.0),
                growth=max(0.0, _number(value.get("growth"), 0.0)),
                threshold=_clamp(value.get("threshold"), 0.0, 1.0),
                force_drain=max(0.0, _number(value.get("force_drain"), 0.0)),
                energy_drain=max(
                    0.0, _number(value.get("energy_drain"), 0.0)
                ),
                spillover={
                    str(name): _number(amount, 0.0)
                    for name, amount in _as_mapping(
                        value.get("spillover")
                    ).items()
                },
                satisfaction={
                    str(name): _number(amount, 0.0)
                    for name, amount in _as_mapping(
                        value.get("satisfaction")
                    ).items()
                },
            )
        if set(self.needs) != set(NEEDS):
            missing = sorted(set(NEEDS) - set(self.needs))
            extra = sorted(set(self.needs) - set(NEEDS))
            raise BDIError(
                "BDI должен содержать ровно 16 канонических желаний; "
                "нет: %s; лишние: %s" % (missing, extra)
            )

        self.conditions: Dict[str, ConditionDefinition] = {}
        for key, value in _as_mapping(data.get("conditions")).items():
            key = str(key)
            value = _as_mapping(value)
            extra = {
                str(name): _number(amount, 0.0)
                for name, amount in value.items()
                if name
                not in {
                    "label",
                    "max",
                    "progress",
                    "rest_recovery",
                    "treat_rate",
                    "work_penalty",
                    "work_floor",
                    "force_drain",
                    "energy_drain",
                    "health_need_growth",
                }
            }
            self.conditions[key] = ConditionDefinition(
                key=key,
                label=_text(value.get("label"), key),
                maximum=max(0.0, _number(value.get("max"), 1.0)),
                progress=max(0.0, _number(value.get("progress"), 0.0)),
                rest_recovery=max(
                    0.0, _number(value.get("rest_recovery"), 0.0)
                ),
                treat_rate=max(0.0, _number(value.get("treat_rate"), 0.0)),
                work_penalty=_clamp(
                    value.get("work_penalty"), 0.0, 1.0
                ),
                work_floor=_clamp(value.get("work_floor"), 0.0, 1.0),
                force_drain=max(
                    0.0, _number(value.get("force_drain"), 0.0)
                ),
                energy_drain=max(
                    0.0, _number(value.get("energy_drain"), 0.0)
                ),
                health_need_growth=max(
                    0.0, _number(value.get("health_need_growth"), 0.0)
                ),
                extra=extra,
            )

        self.predicates = {
            str(key): dict(_as_mapping(value))
            for key, value in _as_mapping(
                data.get("belief_predicates")
            ).items()
        }
        self.essences = {
            str(key): dict(_as_mapping(value))
            for key, value in _as_mapping(
                data.get("intention_essences")
            ).items()
        }
        self.decision = dict(_as_mapping(data.get("decision")))
        self.decision.setdefault("need_weight", 1.0)
        self.decision.setdefault("belief_weight", 0.18)
        self.decision.setdefault("intention_weight", 0.22)
        self.decision.setdefault("novelty", 0.04)
        self.decision.setdefault("trait_center", 0.5)
        self.decision.setdefault("predicate_weights", {})
        self._validate()

    def _validate(self):
        for predicate in self.predicates:
            if not predicate:
                raise BDIError("пустой предикат убеждения")
        for key, essence in self.essences.items():
            need = essence.get("need")
            if need is not None and str(need) not in self.needs:
                raise BDIError(
                    "intention_essences.%s: неизвестная потребность %s"
                    % (key, need)
                )
        for need in self.needs.values():
            for target in need.spillover:
                if target not in self.needs:
                    raise BDIError(
                        "needs.%s.spillover: неизвестное желание %s"
                        % (need.key, target)
                    )
        return self

    def need(self, key):
        return self.needs.get(str(key))

    def predicate(self, key):
        return self.predicates.get(str(key))

    def essence(self, key):
        return self.essences.get(str(key))

    def need_for_essence(self, essence):
        item = self.essences.get(str(essence)) or {}
        return str(item.get("need") or "")

    def validate_belief(self, belief):
        belief = Belief.from_data(belief)
        if self.strict_predicates and belief.predicate not in self.predicates:
            raise BDIError("неизвестный предикат %r" % belief.predicate)
        return belief

    def validate_intention(self, intention):
        intention = Intention.from_data(intention)
        if self.strict_predicates and intention.essence not in self.essences:
            raise BDIError("неизвестная суть намерения %r" % intention.essence)
        return intention

    @property
    def need_names(self):
        return tuple(self.needs)


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _parse_file(path):
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise BDIError("файл BDI не найден: %s" % path) from exc
    except json.JSONDecodeError as exc:
        raise BDIError("битый JSON BDI %s: %s" % (path, exc)) from exc
    return BDIConfig(data, path=path)


@lru_cache(maxsize=8)
def _load_cached(path_text, mtime_ns):
    return _parse_file(path_text)


def load_bdi(path=None, use_cache=True):
    path = Path(path) if path is not None else DEFAULT_PATH
    if not use_cache:
        return _parse_file(path)
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise BDIError("файл BDI не найден: %s" % path) from exc
    return _load_cached(str(path.resolve()), stat.st_mtime_ns)


def default_bdi_path():
    return DEFAULT_PATH


@dataclass
class BDIState:
    """Живое состояние BDI одного персонажа.

    ``needs`` — 16 желаний (0 — удовлетворено, 1 — предельная нужда).
    ``beliefs`` — список триплетов, ``intentions`` — история дуплетов.
    ``conditions`` — болезнь/раны, которые не являются метриками автомата.
    """

    character_id: str = "character"
    config: BDIConfig = field(default_factory=load_bdi)
    needs: Dict[str, float] = field(default_factory=dict)
    beliefs: List[Belief] = field(default_factory=list)
    intentions: List[Intention] = field(default_factory=list)
    conditions: Dict[str, float] = field(default_factory=dict)
    traits: Dict[str, float] = field(default_factory=dict)
    last_deltas: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.character_id = _text(self.character_id, "character")
        values = dict(self.needs or {})
        self.needs = {
            key: _clamp(
                values.get(key, definition.initial), 0.0, 1.0
            )
            for key, definition in self.config.needs.items()
        }
        self.conditions = {
            key: _clamp(
                (self.conditions or {}).get(key, 0.0),
                0.0,
                definition.maximum,
            )
            for key, definition in self.config.conditions.items()
        }
        self.beliefs = [
            self.config.validate_belief(item) for item in (self.beliefs or ())
        ]
        self.intentions = [
            self.config.validate_intention(item)
            for item in (self.intentions or ())
        ][-self.config.history :]
        self.traits = {
            str(key): _clamp(value, 0.0, 1.0)
            for key, value in _as_mapping(self.traits).items()
        }

    # --- убеждения -------------------------------------------------
    def believe(self, subject, predicate, object):
        belief = self.config.validate_belief(
            Belief(subject, predicate, object)
        )
        self.beliefs = [
            item
            for item in self.beliefs
            if not (
                item.subject == belief.subject
                and item.predicate == belief.predicate
            )
        ]
        self.beliefs.append(belief)
        inverse = (
            self.config.predicate(belief.predicate) or {}
        ).get("inverse")
        if inverse and self.config.strict_predicates:
            self.beliefs.append(
                Belief(belief.object, str(inverse), belief.subject)
            )
        return belief

    def forget(self, subject, predicate=None, object=None):
        removed = []
        kept = []
        for item in self.beliefs:
            match = item.subject == str(subject)
            if predicate is not None:
                match = match and item.predicate == str(predicate)
            if object is not None:
                match = match and item.object == str(object)
            (removed if match else kept).append(item)
        self.beliefs = kept
        return removed

    def beliefs_about(self, target):
        target = str(target)
        return [
            item
            for item in self.beliefs
            if item.object == target or item.subject == target
        ]

    def belief_value(self, predicate, target=None):
        values = []
        for item in self.beliefs:
            if item.predicate != str(predicate):
                continue
            if target is not None and item.object != str(target):
                continue
            weight = _number(
                (self.config.decision.get("predicate_weights") or {}).get(
                    item.predicate
                ),
                0.1,
            )
            values.append(weight)
        return sum(values) / max(1.0, len(values)) if values else 0.0

    # --- намерения -------------------------------------------------
    def intend(self, target, essence):
        intention = self.config.validate_intention(
            Intention(target, essence)
        )
        self.intentions = (
            self.intentions + [intention]
        )[-self.config.history :]
        return intention

    def should(self, essence):
        """Поддерживается ли суть текущим намерением."""
        return bool(self.intentions and self.intentions[-1].essence == essence)

    def latest_intention(self):
        return self.intentions[-1] if self.intentions else None

    # --- желания и логика -----------------------------------------
    def weighted_desires(self, trait_model=None):
        """Веса желаний: нужда × поправка черт × поправка убеждений."""
        values = dict(self.traits)
        factors = {}
        if trait_model is not None:
            factors = trait_model.coefficient_factors(values)
        result = {}
        base = _number(self.config.decision.get("need_weight"), 1.0)
        for key, definition in self.config.needs.items():
            factor = _number(factors.get("need:%s" % key), 1.0)
            factor *= _number(factors.get("need_weight"), 1.0)
            result[key] = _clamp(self.needs[key] * base * factor, 0.0, 4.0)
        return result

    def neglect_pressure(self, trait_model=None):
        """Давление запущенных желаний на силу и энергию."""
        factors = (
            trait_model.coefficient_factors(self.traits)
            if trait_model is not None
            else {}
        )
        force = 0.0
        energy = 0.0
        for key, definition in self.config.needs.items():
            value = self.needs[key]
            if value < definition.threshold:
                continue
            severity = (value - definition.threshold) / max(
                1e-9, 1.0 - definition.threshold
            )
            force += definition.force_drain * severity * _number(
                factors.get("force_drain"), 1.0
            )
            energy += definition.energy_drain * severity * _number(
                factors.get("energy_drain"), 1.0
            )
        for key, definition in self.config.conditions.items():
            severity = self.conditions.get(key, 0.0) / max(
                1e-9, definition.maximum
            )
            force += definition.force_drain * severity
            energy += definition.energy_drain * severity
        return {"force": force, "energy": energy}

    def condition_work_factor(self):
        """Множитель работы от болезней и ран."""
        factor = 1.0
        for key, definition in self.config.conditions.items():
            severity = self.conditions.get(key, 0.0) / max(
                1e-9, definition.maximum
            )
            if severity <= 0.0:
                continue
            factor *= max(
                definition.work_floor,
                1.0 - definition.work_penalty * severity,
            )
        return max(0.0, min(1.0, factor))

    def choose_intention(self, trait_model=None, context=None):
        """Выбрать дуплет ``(объект, суть)`` по желаниям и убеждениям.

        Контекст может задать ``targets`` — доступные объекты для
        социальных намерений. Без контекста объектом становится сама
        потребность, что соответствует дуплету «потребность + суть».
        """
        context = dict(context or {})
        desires = self.weighted_desires(trait_model)
        base = _number(self.config.decision.get("need_weight"), 1.0)
        belief_weight = _number(
            self.config.decision.get("belief_weight"), 0.18
        )
        intention_weight = _number(
            self.config.decision.get("intention_weight"), 0.22
        )
        predicate_weights = (
            self.config.decision.get("predicate_weights") or {}
        )
        best_need = max(
            self.config.needs,
            key=lambda key: (desires[key], key),
        )
        best_essence = ""
        best_score = -1.0
        preferred = str(context.get("preferred") or "")
        forbidden = {str(item) for item in context.get("forbidden") or ()}
        for essence, data in self.config.essences.items():
            need = str(data.get("need") or "")
            if not need:
                continue
            score = desires.get(need, 0.0) * base
            score += _number(data.get("belief_bonus"), 0.0) * belief_weight
            for predicate, weight in predicate_weights.items():
                score += (
                    self.belief_value(predicate)
                    * _number(weight, 0.0)
                    * belief_weight
                )
            if self.should(essence):
                score += intention_weight * 0.5
            if preferred and essence == preferred:
                score += 0.75 + intention_weight
            if essence in forbidden:
                score = -1.0
            if score > best_score:
                best_score, best_essence = score, essence
        if best_score < 0.0 and preferred and preferred not in forbidden:
            best_essence = preferred
        if not best_essence:
            data = self.config.essences.get("rest") or {}
            best_essence = "rest" if data else next(self.config.essences)
        target = str(context.get("target") or "")
        if not target:
            target = best_need if best_need in NEEDS else self.character_id
        return self.intend(target, best_essence)

    def tick(
        self,
        seconds=1.0,
        in_combat=False,
        under_fire=0.0,
        support=0.0,
        resting=False,
        order_needs=None,
        rate_multipliers=None,
        trait_model=None,
        seconds_per_unit=1800.0,
    ):
        """Продвинуть желания и состояния, вернуть дельты.

        Возвращает словарь с изменениями ``needs``, ``force``,
        ``energy``, ``sickness`` и ``wound``. Сила/энергия не хранятся в
        BDI: вызывающий код применяет их к автомату.
        """
        scale = max(0.0, _number(seconds, 1.0)) / max(
            1e-9, _number(seconds_per_unit, 1800.0)
        )
        under_fire = _clamp(under_fire, 0.0, 1.0)
        before_needs = dict(self.needs)
        before_conditions = dict(self.conditions)
        multipliers = {
            str(key): max(0.0, _number(value, 1.0))
            for key, value in _as_mapping(rate_multipliers).items()
        }
        factors = (
            trait_model.coefficient_factors(self.traits)
            if trait_model is not None
            else {}
        )
        growth_factor = _number(factors.get("need_growth"), 1.0)
        support_value = max(0.0, min(1.0, _number(support)))
        for key, definition in self.config.needs.items():
            delta = definition.growth * growth_factor
            delta *= multipliers.get(key, 1.0)
            if in_combat and key in ("fatigue", "fear", "anxiety", "health"):
                delta += 0.003 + 0.010 * under_fire
            if key in ("fear", "anxiety"):
                delta += 0.006 * under_fire
            if key == "boredom" and not in_combat:
                delta += 0.003
            self.needs[key] = _clamp(
                self.needs[key] + delta * scale, 0.0, 1.0
            )
        if support_value > 0.0:
            for key in (
                "loneliness",
                "friendship",
                "love",
                "fear",
                "anxiety",
            ):
                self.needs[key] = _clamp(
                    self.needs[key] - 0.014 * support_value * scale,
                    0.0,
                    1.0,
                )
        if resting:
            for key in ("fatigue", "hunger", "thirst", "boredom"):
                self.needs[key] = _clamp(
                    self.needs[key] - 0.035 * scale, 0.0, 1.0
                )
        if in_combat:
            self.needs["skill"] = _clamp(
                self.needs["skill"] - 0.012 * scale, 0.0, 1.0
            )
            self.needs["status"] = _clamp(
                self.needs["status"] - 0.006 * scale, 0.0, 1.0
            )
        for key, amount in _as_mapping(order_needs).items():
            if key in self.needs:
                self.needs[key] = _clamp(
                    self.needs[key] - _number(amount, 0.0) * scale, 0.0, 1.0
                )
        # Запущенные желания заражают соседние: пренебрежение одним
        # желанием больно бьёт по другим.
        spillover = {}
        for key, definition in self.config.needs.items():
            if self.needs[key] < definition.threshold:
                continue
            severity = (self.needs[key] - definition.threshold) / max(
                1e-9, 1.0 - definition.threshold
            )
            for target, amount in definition.spillover.items():
                spillover[target] = spillover.get(target, 0.0) + (
                    _number(amount) * severity * scale
                )
        for key, amount in spillover.items():
            if key in self.needs:
                self.needs[key] = _clamp(
                    self.needs[key] + amount, 0.0, 1.0
                )
        # Болезни и раны добавляют нужду в здоровье и давят на F/E.
        for key, definition in self.config.conditions.items():
            value = self.conditions.get(key, 0.0)
            if value <= 0.0:
                continue
            severity = value / max(1e-9, definition.maximum)
            self.needs["health"] = _clamp(
                self.needs["health"]
                + definition.health_need_growth * severity * scale,
                0.0,
                1.0,
            )
            if resting:
                self.conditions[key] = _clamp(
                    value - definition.rest_recovery * scale,
                    0.0,
                    definition.maximum,
                )
            else:
                self.conditions[key] = _clamp(
                    value + definition.progress * scale,
                    0.0,
                    definition.maximum,
                )
        pressure = self.neglect_pressure(trait_model)
        deltas = {
            "force": -pressure["force"] * scale,
            "energy": -pressure["energy"] * scale,
            "needs": {
                key: self.needs[key] - before_needs[key]
                for key in self.needs
            },
            "conditions": {
                key: self.conditions[key] - before_conditions.get(key, 0.0)
                for key in self.conditions
            },
        }
        self.last_deltas = deltas
        return deltas

    def satisfy(self, effects):
        """Удовлетворить желания; вернуть прирост силы и энергии."""
        restored = {}
        force_gain = 0.0
        energy_gain = 0.0
        for need, amount in _as_mapping(effects).items():
            need = str(need)
            definition = self.config.needs.get(need)
            if definition is None:
                continue
            amount = max(0.0, _number(amount))
            before = self.needs[need]
            self.needs[need] = _clamp(before - amount, 0.0, 1.0)
            restored[need] = before - self.needs[need]
            factor = restored[need] * 10.0
            force_gain += _number(
                definition.satisfaction.get("force")
            ) * factor
            energy_gain += _number(
                definition.satisfaction.get("energy")
            ) * factor
        return {
            "restored": restored,
            "force": force_gain,
            "energy": energy_gain,
        }

    def infect(self, severity):
        definition = self.config.conditions.get("sickness")
        if definition is None:
            return 0.0
        before = self.conditions.get("sickness", 0.0)
        self.conditions["sickness"] = max(
            before,
            _clamp(severity, 0.0, definition.maximum),
        )
        return self.conditions["sickness"] - before

    def injure(self, severity):
        definition = self.config.conditions.get("wound")
        if definition is None:
            return 0.0
        before = self.conditions.get("wound", 0.0)
        self.conditions["wound"] = max(
            before,
            _clamp(severity, 0.0, definition.maximum),
        )
        return self.conditions["wound"] - before

    def treat(self, amount):
        definition = self.config.conditions.get("sickness")
        if definition is None:
            return 0.0
        before = self.conditions.get("sickness", 0.0)
        self.conditions["sickness"] = _clamp(
            before - max(0.0, _number(amount)) * definition.treat_rate,
            0.0,
            definition.maximum,
        )
        return before - self.conditions["sickness"]

    def treat_wound(self, amount):
        definition = self.config.conditions.get("wound")
        if definition is None:
            return 0.0
        before = self.conditions.get("wound", 0.0)
        self.conditions["wound"] = _clamp(
            before - max(0.0, _number(amount)) * definition.treat_rate,
            0.0,
            definition.maximum,
        )
        return before - self.conditions["wound"]

    def condition(self, key):
        return self.conditions.get(str(key), 0.0)

    def is_wounded(self):
        return self.condition("wound") > 0.0

    def is_sick(self):
        return self.condition("sickness") > 0.0

    # --- сериализация ---------------------------------------------
    def state_dict(self):
        return {
            "character_id": self.character_id,
            "needs": {
                key: round(_clamp(value), 6)
                for key, value in self.needs.items()
            },
            "beliefs": [item.as_dict() for item in self.beliefs],
            "intentions": [item.as_dict() for item in self.intentions],
            "conditions": {
                key: round(_clamp(value), 6)
                for key, value in self.conditions.items()
            },
            "traits": {
                key: round(_clamp(value), 6)
                for key, value in self.traits.items()
            },
        }

    def load_state_dict(self, state):
        state = _as_mapping(state)
        self.character_id = _text(
            state.get("character_id"), self.character_id
        )
        for key, value in _as_mapping(state.get("needs")).items():
            if key in self.needs:
                self.needs[key] = _clamp(value)
        self.beliefs = [
            self.config.validate_belief(item)
            for item in (state.get("beliefs") or ())
        ]
        self.intentions = [
            self.config.validate_intention(item)
            for item in (state.get("intentions") or ())
        ][-self.config.history :]
        for key, definition in self.config.conditions.items():
            if key in _as_mapping(state.get("conditions")):
                self.conditions[key] = _clamp(
                    state["conditions"][key], 0.0, definition.maximum
                )
        self.traits = {
            str(key): _clamp(value, 0.0, 1.0)
            for key, value in _as_mapping(state.get("traits")).items()
        }
        return self

    def snapshot(self):
        return {
            "character_id": self.character_id,
            "needs": {
                key: round(_clamp(value), 3)
                for key, value in self.needs.items()
            },
            "desires": {
                key: round(_clamp(value), 3)
                for key, value in self.weighted_desires().items()
            },
            "beliefs": [item.as_dict() for item in self.beliefs],
            "intentions": [item.as_dict() for item in self.intentions],
            "conditions": {
                key: round(_clamp(value), 3)
                for key, value in self.conditions.items()
            },
            "pressure": {
                key: round(value, 4)
                for key, value in self.neglect_pressure().items()
            },
        }


__all__ = [
    "BDIError",
    "BDIConfig",
    "BDIState",
    "Belief",
    "ConditionDefinition",
    "Intention",
    "NEEDS",
    "NeedDefinition",
    "default_bdi_path",
    "load_bdi",
]
