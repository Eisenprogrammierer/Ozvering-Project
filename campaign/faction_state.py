"""Производное состояние фракции из BDI персонажей и контекста сети.

У фракции-автомата больше нет собственного «кошелька» ролевых активов.
``legitimacy``, ``cohesion``, ``supply``, ``fear``, ``morale``, ``influence``
и ``energy`` — не независимые шкалы, которые кто-то двигает напрямую, а
проекции трёх вещей:

* BDI персонажей: удовлетворённость желаний, черты, мораль, сила и
  энергия;
* целостность органов сети: типы органов дают разные вклады;
* контекст взаимодействий: краткоживущие импульсы от работ, приказов,
  влияний и событий.

Формулы и веса лежат в ``configs/campaigns/base/automata_defaults.json``
(раздел ``faction_state``). Python знает только контракт: как прочитать
метрику, как сложить взвешенную сумму и как разложить изменение актива
обратно в BDI/органы/контекст. Добавить новый актив или изменить вклад
можно в JSON, не трогая этот модуль.
"""

from __future__ import annotations

from collections.abc import MutableMapping
import math
from typing import Dict, Iterable, Mapping

from .defaults import default_dict

try:
    STATE_DEFAULTS = default_dict("faction_state")
except Exception:  # pragma: no cover - защита от старого конфига
    STATE_DEFAULTS = {}

ASSET_FORMULAS: Dict[str, list] = dict(
    STATE_DEFAULTS.get("assets") or {}
)
ASSET_DRIVERS: Dict[str, list] = dict(
    STATE_DEFAULTS.get("drivers") or {}
)
CONTEXT_NEUTRAL = float(STATE_DEFAULTS.get("context_neutral", 0.5))
CONTEXT_DECAY = float(STATE_DEFAULTS.get("context_decay", 0.08))
CONTEXT_MIN = float(STATE_DEFAULTS.get("context_min", -10.0))
CONTEXT_MAX = float(STATE_DEFAULTS.get("context_max", 10.0))
DRIVER_GAIN = float(STATE_DEFAULTS.get("driver_gain", 0.8))
MORALE_SCALE = float(STATE_DEFAULTS.get("morale_scale", 100.0))


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(result) or math.isinf(result):
        return float(default)
    return result


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _number(value, low)))


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _alive(character):
    if character is None:
        return False
    if getattr(character, "is_dead", None):
        return False
    return not bool(getattr(character, "dead", False))


def _max_force(character, default=1.0):
    return max(
        1e-9,
        _number(getattr(character, "state", {}).get("max_force"), default),
    )


def _max_energy(character, default=1.0):
    return max(
        1e-9,
        _number(getattr(character, "state", {}).get("max_energy"), default),
    )


def character_metric(character, metric):
    """Прочитать одну BDI-метрику персонажа.

    Поддерживаются ``need.<key>``, ``satisfaction.<key>``,
    ``condition.<key>``, ``trait.<key>``, ``morale``, ``force``,
    ``energy``, ``alive`` и ``division.<dimension>=<value>``.
    """
    if character is None:
        return 0.0
    metric = str(metric or "")
    if metric == "morale":
        return _clamp(_number(getattr(character, "morale", 0.0)) / 100.0)
    if metric == "force":
        return _clamp(
            _number(getattr(character, "force", 0.0))
            / _max_force(character)
        )
    if metric == "energy":
        return _clamp(
            _number(getattr(character, "energy_pool", 0.0))
            / _max_energy(character)
        )
    if metric == "alive":
        return 1.0 if _alive(character) else 0.0
    needs = getattr(character, "needs", {}) or {}
    if metric.startswith("need."):
        return _clamp(needs.get(metric[5:], 0.0))
    if metric.startswith("satisfaction."):
        return _clamp(1.0 - _number(needs.get(metric[13:], 0.0)))
    conditions = getattr(character, "conditions", {}) or {}
    if metric.startswith("condition."):
        return _clamp(conditions.get(metric[10:], 0.0))
    values = getattr(getattr(character, "personality", None), "values", {})
    if metric.startswith("trait."):
        return _clamp((values or {}).get(metric[6:], 0.0))
    if metric.startswith("division."):
        spec = metric[len("division.") :]
        key, separator, expected = spec.partition("=")
        divisions = getattr(character, "divisions", None)
        actual = divisions.get(key) if divisions is not None else None
        if not separator:
            return 1.0 if actual else 0.0
        return 1.0 if str(actual or "") == expected else 0.0
    return 0.5


def _mean(values, default=0.5):
    values = list(values)
    if not values:
        return default
    return sum(values) / float(len(values))


def _faction_characters(faction):
    characters = list(getattr(faction, "characters", ()) or ())
    alive = [item for item in characters if _alive(item)]
    return alive or characters


def _organ_mean(organs, default=0.5):
    organs = list(organs or ())
    if not organs:
        return default
    weights = [
        max(1e-9, _number(getattr(item, "weight", 1.0), 1.0))
        for item in organs
    ]
    total = sum(weights)
    return sum(
        _clamp(getattr(item, "integrity", 0.0)) * weight
        for item, weight in zip(organs, weights)
    ) / total


def _network_links(organs):
    # Локальная копия, чтобы не тянуть campaign.fractal в этот модуль.
    organs = list(organs or ())
    by_id = {str(getattr(item, "id", "")): item for item in organs}
    result = {organ_id: set() for organ_id in by_id}
    for organ in organs:
        organ_id = str(getattr(organ, "id", ""))
        for linked in getattr(organ, "links", ()) or ():
            linked = str(linked)
            if linked in by_id and linked != organ_id:
                result[organ_id].add(linked)
                result[linked].add(organ_id)
        parent_id = str(getattr(organ, "parent_id", "") or "")
        if parent_id in by_id and parent_id != organ_id:
            result[organ_id].add(parent_id)
            result[parent_id].add(organ_id)
    return {key: sorted(value) for key, value in result.items()}


def faction_metric(faction, metric):
    """Прочитать агрегированную метрику фракции по имени из JSON."""
    metric = str(metric or "")
    characters = _faction_characters(faction)
    organs = list(getattr(faction, "organs", ()) or ())
    if metric.startswith("characters.mean:"):
        key = metric[len("characters.mean:") :]
        return _mean(
            [character_metric(item, key) for item in characters], 0.5
        )
    if metric.startswith("characters.max:"):
        key = metric[len("characters.max:") :]
        values = [character_metric(item, key) for item in characters]
        return max(values) if values else 0.5
    if metric.startswith("characters.min:"):
        key = metric[len("characters.min:") :]
        values = [character_metric(item, key) for item in characters]
        return min(values) if values else 0.5
    if metric == "organs.mean":
        return _organ_mean(organs)
    if metric.startswith("organs.kind:"):
        kind = metric[len("organs.kind:") :]
        return _organ_mean(
            [item for item in organs if str(getattr(item, "kind", "")) == kind]
        )
    if metric == "network.density":
        links = _network_links(organs)
        count = len(links)
        if count <= 1:
            return 0.0
        edges = sum(len(value) for value in links.values()) / 2.0
        return _clamp(edges / float(count * (count - 1) / 2.0))
    if metric == "network.degree":
        links = _network_links(organs)
        if not links:
            return 0.0
        top = max(1, len(links) - 1)
        return _mean(
            [len(value) / float(top) for value in links.values()], 0.0
        )
    if metric.startswith("organization."):
        key = metric[len("organization.") :]
        snapshot = _as_mapping(
            getattr(faction, "organization_snapshot", {}) or {}
        )
        return _clamp(snapshot.get(key, 0.5))
    if metric.startswith("subfactions.mean:"):
        key = metric[len("subfactions.mean:") :]
        return _mean(
            [
                _number(_as_mapping(getattr(item, "assets", {})).get(key))
                for item in (getattr(faction, "subfactions", ()) or ())
            ],
            0.5,
        )
    if metric.startswith("subfactions.max:"):
        key = metric[len("subfactions.max:") :]
        values = [
            _number(_as_mapping(getattr(item, "assets", {})).get(key))
            for item in (getattr(faction, "subfactions", ()) or ())
        ]
        return max(values) if values else 0.5
    if metric.startswith("subfactions.min:"):
        key = metric[len("subfactions.min:") :]
        values = [
            _number(_as_mapping(getattr(item, "assets", {})).get(key))
            for item in (getattr(faction, "subfactions", ()) or ())
        ]
        return min(values) if values else 0.5
    if metric.startswith("subfactions."):
        rest = metric[len("subfactions.") :]
        sub_id, _separator, key = rest.partition(".")
        for item in getattr(faction, "subfactions", ()) or ():
            if str(getattr(item, "id", "")) != sub_id:
                continue
            return _clamp(
                _as_mapping(getattr(item, "assets", {})).get(key)
            )
        return 0.5
    if metric.startswith("context."):
        key = metric[len("context.") :]
        context = _as_mapping(getattr(faction, "context", {}) or {})
        # Контекст — не шкала 0..1, а краткоживущий импульс. Отрицательное
        # значение означает «дефицит», положительное — «подпитку».
        return _clamp(
            context.get(key, CONTEXT_NEUTRAL),
            CONTEXT_MIN,
            CONTEXT_MAX,
        )
    try:
        return _number(metric, 0.5)
    except (TypeError, ValueError):
        return 0.5


def asset_keys(faction=None):
    """Порядок активов: сначала формулы, затем данные пресета."""
    keys = list(ASSET_FORMULAS)
    if faction is not None:
        record = _as_mapping(getattr(faction, "record", {}) or {})
        for source in (
            record.get("assets"),
            record.get("score_assets"),
            getattr(faction, "score_assets", None),
            getattr(faction, "context", None),
        ):
            for key in _as_mapping(source):
                if key not in keys:
                    keys.append(str(key))
    return keys


def asset_terms(faction, key):
    terms = ASSET_FORMULAS.get(str(key))
    if terms:
        return [dict(item) for item in terms if isinstance(item, Mapping)]
    return [
        {"metric": "context.%s" % key, "weight": 0.5},
        {"metric": "organs.mean", "weight": 0.5},
    ]


def derived_asset(faction, key, default=0.0):
    """Посчитать один актив как взвешенную проекцию состояния."""
    terms = asset_terms(faction, key)
    total = 0.0
    weight_sum = 0.0
    for term in terms:
        weight = _number(term.get("weight"), 0.0)
        if not weight:
            continue
        total += weight * faction_metric(
            faction, term.get("metric")
        )
        weight_sum += abs(weight)
    if weight_sum <= 0.0:
        return _clamp(default)
    return _clamp(total / weight_sum)


def derived_assets(faction):
    """Все производные активы фракции в стабильном порядке."""
    return {
        key: derived_asset(faction, key)
        for key in asset_keys(faction)
    }


def _apply_character_driver(faction, driver, effect):
    characters = list(getattr(faction, "characters", ()) or ())
    if driver.get("leader"):
        characters = characters[:1]
    if not characters:
        return
    need = driver.get("need")
    trait = driver.get("trait")
    condition = driver.get("condition")
    for character in characters:
        if need:
            needs = getattr(character, "needs", None)
            if isinstance(needs, dict) and need in needs:
                needs[need] = _clamp(
                    _number(needs.get(need, 0.0)) + effect
                )
        if trait:
            values = getattr(
                getattr(character, "personality", None), "values", None
            )
            if isinstance(values, dict) and trait in values:
                values[trait] = _clamp(
                    _number(values.get(trait, 0.0)) + effect
                )
        if condition:
            conditions = getattr(character, "conditions", None)
            if isinstance(conditions, dict) and condition in conditions:
                conditions[condition] = _clamp(
                    _number(conditions.get(condition, 0.0)) + effect
                )
        if driver.get("morale"):
            character.morale = max(
                0.0,
                min(
                    100.0,
                    _number(getattr(character, "morale", 0.0))
                    + effect * MORALE_SCALE,
                ),
            )
        if driver.get("force"):
            maximum = _max_force(character)
            character.force = max(
                0.0,
                min(
                    maximum,
                    _number(getattr(character, "force", 0.0))
                    + effect * maximum,
                ),
            )
        if driver.get("energy"):
            maximum = _max_energy(character)
            character.energy_pool = max(
                0.0,
                min(
                    maximum,
                    _number(getattr(character, "energy_pool", 0.0))
                    + effect * maximum,
                ),
            )


def _apply_organ_driver(faction, driver, effect):
    organs = list(getattr(faction, "organs", ()) or ())
    kind = driver.get("kind")
    if kind:
        organs = [
            item for item in organs if str(getattr(item, "kind", "")) == kind
        ]
    for organ in organs:
        organ.integrity = _clamp(
            _number(getattr(organ, "integrity", 0.0)) + effect
        )


def apply_asset_delta(faction, key, delta):
    """Разложить изменение актива в BDI, органы и контекст сети.

    Возвращает фактически записанный контекстный импульс. Именно поэтому
    ``add_asset`` больше не является независимой записью в кошелёк
    фракции: отрицательная цена снабжения повышает голод персонажей,
    положительный эффект законности снижает нужду в статусе и т.д.
    """
    key = str(key)
    delta = _number(delta, 0.0)
    if not delta:
        return 0.0
    context = getattr(faction, "context", None)
    if not isinstance(context, dict):
        context = {}
        faction.context = context
    before = _number(context.get(key, CONTEXT_NEUTRAL))
    context[key] = _clamp(before + delta, CONTEXT_MIN, CONTEXT_MAX)
    applied = context[key] - before
    for driver in ASSET_DRIVERS.get(key, ()) or ():
        if not isinstance(driver, Mapping):
            continue
        weight = _number(driver.get("weight"), 0.0)
        effect = delta * weight * DRIVER_GAIN
        if not effect:
            continue
        target = str(driver.get("target") or "characters")
        if target == "organs":
            _apply_organ_driver(faction, driver, effect)
        else:
            _apply_character_driver(faction, driver, effect)
    return applied


def set_asset_value(faction, key, value):
    """Совместимый помощник: подобрать контекст под желаемое значение.

    Это не отдельное хранилище актива. Мы решаем обратную задачу формулы
    и записываем только контекстный импульс, поэтому следующий тик снова
    считает актив из BDI и органов.
    """
    key = str(key)
    target = _clamp(value)
    terms = asset_terms(faction, key)
    total = 0.0
    known = 0.0
    context_weight = 0.0
    context_key = "context.%s" % key
    for term in terms:
        weight = _number(term.get("weight"), 0.0)
        if not weight:
            continue
        total += abs(weight)
        metric = str(term.get("metric") or "")
        if metric == context_key:
            context_weight += weight
        else:
            known += weight * faction_metric(faction, metric)
    context = getattr(faction, "context", None)
    if not isinstance(context, dict):
        context = {}
        faction.context = context
    if context_weight:
        context[key] = _clamp(
            (target * total - known) / context_weight,
            CONTEXT_MIN,
            CONTEXT_MAX,
        )
    else:
        context[key] = _clamp(target, CONTEXT_MIN, CONTEXT_MAX)
    return derived_asset(faction, key)


def bump_context(faction, key, delta):
    """Добавить импульс взаимодействия, не меняя BDI напрямую."""
    key = str(key)
    context = getattr(faction, "context", None)
    if not isinstance(context, dict):
        context = {}
        faction.context = context
    before = _number(context.get(key, CONTEXT_NEUTRAL))
    context[key] = _clamp(
        before + _number(delta, 0.0), CONTEXT_MIN, CONTEXT_MAX
    )
    return context[key] - before


def relax_context(faction, rate=None, baseline=None):
    """Подтянуть контекст к стартовому фону (старый ``asset_relax``).

    Без явной скорости используется ``faction_state.context_decay`` из
    JSON, чтобы затухание импульсов оставалось контентом.
    """
    rate = CONTEXT_DECAY if rate is None else rate
    rate = _clamp(rate, 0.0, 1.0)
    if rate <= 0.0:
        return
    context = getattr(faction, "context", None)
    if not isinstance(context, dict):
        context = {}
        faction.context = context
    baseline = _as_mapping(
        baseline
        if baseline is not None
        else getattr(faction, "baseline_context", {})
    )
    for key, value in list(context.items()):
        target = _clamp(baseline.get(key, CONTEXT_NEUTRAL))
        context[key] = _clamp(
            _number(value) + rate * (target - _number(value)),
            CONTEXT_MIN,
            CONTEXT_MAX,
        )
    for key, value in baseline.items():
        context.setdefault(str(key), _clamp(value))


class DerivedAssets(MutableMapping):
    """Read/write view над производными активами фракции.

    Чтение всегда считает формулу заново, запись раскладывается в BDI,
    органы и контекст. Это сохраняет совместимость со старым кодом
    (``faction.assets[key]``), но не создаёт независимый словарь активов.
    """

    def __init__(self, faction):
        self._faction = faction

    def __getitem__(self, key):
        return derived_asset(self._faction, key)

    def __setitem__(self, key, value):
        set_asset_value(self._faction, key, value)

    def __delitem__(self, key):
        context = getattr(self._faction, "context", None)
        if isinstance(context, dict):
            context.pop(str(key), None)

    def __iter__(self):
        return iter(asset_keys(self._faction))

    def __len__(self):
        return len(asset_keys(self._faction))

    def __repr__(self):
        return repr(dict(self.items()))


__all__ = [
    "ASSET_DRIVERS",
    "ASSET_FORMULAS",
    "CONTEXT_NEUTRAL",
    "DerivedAssets",
    "apply_asset_delta",
    "asset_keys",
    "asset_terms",
    "bump_context",
    "character_metric",
    "derived_asset",
    "derived_assets",
    "faction_metric",
    "relax_context",
    "set_asset_value",
]
