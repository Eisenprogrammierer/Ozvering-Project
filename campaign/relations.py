"""Влияние осей отношений на работу кампании (WORLD_CORE_MODEL §7.6).

`affinity/trust/fear/respect` хранятся для каждого направления. До этого
среза на исход действия влияла только `affinity` (через `_ai_score`).
Модуль задаёт явные, небольшие вклады осей в приём работы:

* `info` лучше проходит к тому, кто доверяет и расположен; страх мешает
  доверию, уважение немного помогает авторитету;
* `force` лучше проходит к тому, кто боится или уважает; доверие само по
  себе не заставляет подчиняться силе.

Вклад ограничен `RELATION_EFFECT_LIMIT`, чтобы отношения смещали шанс, а
не заменяли `F/E`, навык и сопротивление. Это ответ на №37: ось влияет на
вход (принятие работы), а не только на выбор действия.

F-20: набор осей, подписи и веса читаются из конфига мира. Легаси-оси
`affinity/trust/fear/respect` остаются в наборе всегда, поэтому старые
сейвы и миры без блока `relation_axes` работают как раньше. Новые
эмоциональные оси (`romance`, `family`, `ritual`, `vassalage`) — это
данные, а не ветки Python.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable, Mapping

RELATION_AXES = ("affinity", "trust", "fear", "respect")

RELATION_AXIS_LABELS = {
    "affinity": "расположение",
    "trust": "доверие",
    "fear": "страх",
    "respect": "уважение",
}

RELATION_AXIS_SHORT_LABELS = {
    "affinity": "расп.",
    "trust": "дов.",
    "fear": "страх",
    "respect": "уваж.",
}

RELATION_EFFECT_WEIGHTS = {
    "force": {
        "affinity": 0.02,
        "trust": -0.02,
        "fear": 0.10,
        "respect": 0.08,
    },
    "info": {
        "affinity": 0.06,
        "trust": 0.14,
        "fear": -0.04,
        "respect": 0.04,
    },
}
RELATION_EFFECT_LIMIT = 0.20
DEFAULT_RELATION_FORM = "force"


def _clamp(value, low=-1.0, high=1.0):
    return max(low, min(high, float(value)))


def _axis_name(value: Any) -> str:
    return str(value or "").strip()


def _axis_meta(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _configured_axes(raw: Any) -> list:
    """Имена осей из ``relation_axes`` в порядке объявления.

    Поддерживаются список строк и объект ``{axis: {label, short}}``.
    Пустые и повторяющиеся имена пропускаются.
    """
    if isinstance(raw, Mapping):
        values = list(raw.keys())
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        return []
    result = []
    for value in values:
        name = _axis_name(value)
        if name and name not in result:
            result.append(name)
    return result


def relation_axes_from_config(
    config: Mapping[str, Any] | None = None,
) -> tuple:
    """Полный набор осей мира: данные конфига + легаси-оси.

    Порядок стабилен: сначала объявленные миром оси, затем недостающие
    легаси-оси. `affinity` гарантированно присутствует, потому что
    скалярная проекция `relations` и старые сейвы опираются на неё.
    """
    config = config or {}
    configured = _configured_axes(config.get("relation_axes"))
    axes = list(configured)
    for axis in RELATION_AXES:
        if axis not in axes:
            axes.append(axis)
    return tuple(axes)


def _axis_label(config: Mapping[str, Any], axis: str, short: bool) -> str:
    raw = config.get("relation_axes")
    meta = {}
    if isinstance(raw, Mapping):
        meta = _axis_meta(raw.get(axis))
    defaults = (
        RELATION_AXIS_SHORT_LABELS if short else RELATION_AXIS_LABELS
    )
    key = "short" if short else "label"
    return str(meta.get(key) or defaults.get(axis) or axis)


def relation_axis_labels_from_config(
    config: Mapping[str, Any] | None = None,
    axes: Iterable[str] | None = None,
) -> dict:
    """Полные подписи осей: ``axis -> label``."""
    config = config or {}
    order = tuple(axes or relation_axes_from_config(config))
    return {axis: _axis_label(config, axis, False) for axis in order}


def relation_axis_short_labels_from_config(
    config: Mapping[str, Any] | None = None,
    axes: Iterable[str] | None = None,
) -> dict:
    """Короткие подписи осей для узких мест UI."""
    config = config or {}
    order = tuple(axes or relation_axes_from_config(config))
    return {axis: _axis_label(config, axis, True) for axis in order}


def relation_effect_weights_from_config(
    config: Mapping[str, Any] | None = None,
) -> dict:
    """Веса форм из конфига с легаси-значениями по умолчанию.

    Формы, которых нет ни в конфиге, ни в легаси-таблице, дают нулевой
    вклад, а не падение.
    """
    config = config or {}
    raw = config.get("relation_effect_weights")
    result = {
        form: dict(weights)
        for form, weights in RELATION_EFFECT_WEIGHTS.items()
    }
    if not isinstance(raw, Mapping):
        return result
    for form, weights in raw.items():
        form_name = _axis_name(form)
        if not form_name or not isinstance(weights, Mapping):
            continue
        result[form_name] = {
            _axis_name(axis): float(value)
            for axis, value in weights.items()
            if _axis_name(axis)
        }
    return result


def relation_effect_limit_from_config(
    config: Mapping[str, Any] | None = None,
) -> float:
    """Предел суммарного вклада отношений в шанс."""
    config = config or {}
    try:
        value = float(config.get("relation_effect_limit"))
    except (TypeError, ValueError):
        return RELATION_EFFECT_LIMIT
    if value <= 0.0:
        return RELATION_EFFECT_LIMIT
    return value


def normalize_relation_axes_config(raw: Any) -> Mapping[str, Any]:
    """Проверить и нормализовать блок ``relation_axes`` мира.

    Возвращает объект ``{axis: {label, short}}``. Список строк также
    допустим и превращается в объект с пустыми подписями. Ошибки
    вызывает ``CampaignError``-совместимым ``ValueError``, чтобы
    ``validate_world`` мог обернуть их в ``WorldError``.
    """
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        entries = list(raw.items())
    elif isinstance(raw, (list, tuple)):
        entries = [(axis, {}) for axis in raw]
    else:
        raise ValueError("relation_axes: ожидался объект или список")
    result = OrderedDict()
    for axis, meta in entries:
        name = _axis_name(axis)
        if not name:
            raise ValueError("relation_axes: пустое имя оси")
        if name in result:
            raise ValueError("relation_axes: повторяется ось %r" % name)
        if meta is None:
            meta = {}
        if not isinstance(meta, Mapping):
            raise ValueError(
                "relation_axes.%s: ожидался объект" % name
            )
        label = str(meta.get("label") or "").strip()
        short = str(meta.get("short") or "").strip()
        result[name] = {
            key: value
            for key, value in (("label", label), ("short", short))
            if value
        }
    return dict(result)


def relation_effect(
    axes,
    form=DEFAULT_RELATION_FORM,
    *,
    weights=None,
    limit=None,
):
    """Сдвиг шанса от осей цели к действующему автомату.

    `axes` — отношение цели к источнику работы (R_target→source), а не
    наоборот. Возвращает число в `[-limit, limit]`.
    """
    table = weights if weights is not None else RELATION_EFFECT_WEIGHTS
    form_weights = table.get(str(form or DEFAULT_RELATION_FORM))
    if not form_weights:
        return 0.0
    try:
        bound = float(limit) if limit is not None else RELATION_EFFECT_LIMIT
    except (TypeError, ValueError):
        bound = RELATION_EFFECT_LIMIT
    if bound <= 0.0:
        bound = RELATION_EFFECT_LIMIT
    axes = axes or {}
    value = 0.0
    for axis, weight in form_weights.items():
        try:
            value += float(weight) * _clamp(axes.get(axis, 0.0))
        except (TypeError, ValueError):
            continue
    return max(-bound, min(bound, value))


def relation_effect_view(
    axes,
    form=None,
    *,
    axes_order=None,
    weights=None,
    limit=None,
):
    """Публичное объяснение вклада для UI и логов."""
    table = weights if weights is not None else RELATION_EFFECT_WEIGHTS
    order = tuple(axes_order or RELATION_AXES)
    forms = [str(form or DEFAULT_RELATION_FORM)] if form else list(table)
    try:
        bound = float(limit) if limit is not None else RELATION_EFFECT_LIMIT
    except (TypeError, ValueError):
        bound = RELATION_EFFECT_LIMIT
    return {
        "axes": {
            axis: _clamp((axes or {}).get(axis, 0.0)) for axis in order
        },
        "effects": {
            name: relation_effect(
                axes, name, weights=table, limit=bound
            )
            for name in forms
        },
        "limit": bound,
    }


def asymmetry_rows(outgoing, incoming, axes=None):
    """Строки «вы → цель» / «цель → вы» для карточки узла.

    `outgoing` — R_player→target, `incoming` — R_target→player. Возвращает
    список `(axis, outgoing, incoming)` в стабильном порядке осей.
    """
    outgoing = outgoing or {}
    incoming = incoming or {}
    order = tuple(axes or RELATION_AXES)
    return [
        (
            axis,
            _clamp(outgoing.get(axis, 0.0)),
            _clamp(incoming.get(axis, 0.0)),
        )
        for axis in order
    ]


__all__ = [
    "DEFAULT_RELATION_FORM",
    "RELATION_AXES",
    "RELATION_AXIS_LABELS",
    "RELATION_AXIS_SHORT_LABELS",
    "RELATION_EFFECT_LIMIT",
    "RELATION_EFFECT_WEIGHTS",
    "asymmetry_rows",
    "normalize_relation_axes_config",
    "relation_axes_from_config",
    "relation_axis_labels_from_config",
    "relation_axis_short_labels_from_config",
    "relation_effect",
    "relation_effect_limit_from_config",
    "relation_effect_view",
    "relation_effect_weights_from_config",
]
