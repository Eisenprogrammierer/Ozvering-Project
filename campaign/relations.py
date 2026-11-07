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
"""

from __future__ import annotations

RELATION_AXES = ("affinity", "trust", "fear", "respect")

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
# Если форма не задана, используется силовой канал — историческое
# поведение кампанийных действий.
DEFAULT_RELATION_FORM = "force"


def _clamp(value, low=-1.0, high=1.0):
    return max(low, min(high, float(value)))


def relation_effect(axes, form=DEFAULT_RELATION_FORM):
    """Сдвиг шанса от осей цели к действующему автомату.

    `axes` — отношение цели к источнику работы (R_target→source), а не
    наоборот. Возвращает число в `[-RELATION_EFFECT_LIMIT,
    RELATION_EFFECT_LIMIT]`.
    """
    weights = RELATION_EFFECT_WEIGHTS.get(
        str(form or DEFAULT_RELATION_FORM)
    )
    if not weights:
        return 0.0
    axes = axes or {}
    value = 0.0
    for axis, weight in weights.items():
        try:
            value += weight * _clamp(axes.get(axis, 0.0))
        except (TypeError, ValueError):
            continue
    return max(-RELATION_EFFECT_LIMIT, min(RELATION_EFFECT_LIMIT, value))


def relation_effect_view(axes, form=None):
    """Публичное объяснение вклада для UI и логов."""
    forms = (
        [str(form or DEFAULT_RELATION_FORM)]
        if form
        else list(RELATION_EFFECT_WEIGHTS)
    )
    return {
        "axes": {
            axis: _clamp((axes or {}).get(axis, 0.0))
            for axis in RELATION_AXES
        },
        "effects": {
            name: relation_effect(axes, name) for name in forms
        },
        "limit": RELATION_EFFECT_LIMIT,
    }


def asymmetry_rows(outgoing, incoming):
    """Строки «вы → цель» / «цель → вы» для карточки узла.

    `outgoing` — R_player→target, `incoming` — R_target→player. Возвращает
    список `(axis, outgoing, incoming)` в стабильном порядке осей.
    """
    outgoing = outgoing or {}
    incoming = incoming or {}
    return [
        (
            axis,
            _clamp(outgoing.get(axis, 0.0)),
            _clamp(incoming.get(axis, 0.0)),
        )
        for axis in RELATION_AXES
    ]


__all__ = [
    "DEFAULT_RELATION_FORM",
    "RELATION_AXES",
    "RELATION_EFFECT_LIMIT",
    "RELATION_EFFECT_WEIGHTS",
    "asymmetry_rows",
    "relation_effect",
    "relation_effect_view",
]
