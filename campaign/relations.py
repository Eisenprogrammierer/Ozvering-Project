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


class RelationStore:
    """Направленные отношения кампании: ``source → target → axis``.

    Ось — не актив фракции и не скалярная репутация: у каждого
    направления свой набор значений. Значения лежат в ``-1..1``, поэтому
    вражда и союз — это разные знаки одной оси, а не два разных поля.

    ``source`` и ``target`` — любые идентификаторы контента: фракции,
    персонажи, органы. Хранилище не проверяет существование субъекта:
    это делает вызывающий код или линтер, а снимок должен переживать
    удалённых персонажей.
    """

    def __init__(
        self,
        axes=None,
        weights=None,
        limit=None,
        form_map=None,
        neutral=0.0,
    ):
        self.axes = tuple(axes or RELATION_AXES)
        self.weights = dict(weights or RELATION_EFFECT_WEIGHTS)
        try:
            self.limit = abs(float(limit))
        except (TypeError, ValueError):
            self.limit = RELATION_EFFECT_LIMIT
        if self.limit <= 0.0:
            self.limit = RELATION_EFFECT_LIMIT
        self.form_map = {
            str(key): str(value)
            for key, value in (form_map or {}).items()
            if str(key or "").strip() and str(value or "").strip()
        }
        self.neutral = _clamp(neutral, -1.0, 1.0)
        self._values: dict = {}

    @classmethod
    def from_config(cls, config=None):
        """Собрать хранилище из блока ``relation_model``."""
        config = config if isinstance(config, Mapping) else {}
        raw_axes = config.get("axes")
        if raw_axes is None:
            raw_axes = config.get("relation_axes")
        axes = relation_axes_from_config({"relation_axes": raw_axes})
        weights = relation_effect_weights_from_config(
            {
                "relation_effect_weights": config.get("effect_weights")
                or config.get("relation_effect_weights")
            }
        )
        limit = relation_effect_limit_from_config(
            {
                "relation_effect_limit": config.get("effect_limit")
                or config.get("relation_effect_limit")
            }
        )
        form_map = config.get("forms") or config.get("form_map") or {}
        return cls(
            axes=axes,
            weights=weights,
            limit=limit,
            form_map=form_map,
            neutral=config.get("neutral", 0.0),
        )

    def _subject(self, value):
        return str(value or "").strip()

    def form_for(self, form):
        """Свести форму работы к форме отношения из данных."""
        name = str(form or DEFAULT_RELATION_FORM)
        return self.form_map.get(name, name)

    def value(self, source, target, axis):
        """Одно значение оси; отсутствующая связь читается как нейтраль."""
        source = self._subject(source)
        target = self._subject(target)
        axis = self._subject(axis)
        if not source or not target or not axis:
            return self.neutral
        try:
            return _clamp(
                self._values.get(source, {})
                .get(target, {})
                .get(axis, self.neutral)
            )
        except (TypeError, ValueError):
            return self.neutral

    def axes_for(self, source, target):
        """Все настроенные оси направления; отсутствующие — нейтральны."""
        return {
            axis: self.value(source, target, axis) for axis in self.axes
        }

    def set(self, source, target, values):
        """Заменить оси направления, не трогая остальные направления."""
        source = self._subject(source)
        target = self._subject(target)
        if not source or not target:
            return {}
        clean = {}
        for axis, value in (values or {}).items():
            axis = self._subject(axis)
            if not axis:
                continue
            try:
                clean[axis] = _clamp(value)
            except (TypeError, ValueError):
                continue
        if not clean:
            self._values.get(source, {}).pop(target, None)
        else:
            self._values.setdefault(source, {})[target] = clean
        return dict(clean)

    def add(self, source, target, values, scale=1.0):
        """Прибавить дельты и вернуть фактически применённые изменения."""
        source = self._subject(source)
        target = self._subject(target)
        if not source or not target:
            return {}
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            scale = 1.0
        if scale == 0.0:
            return {}
        current = self.axes_for(source, target)
        before = dict(current)
        for axis, value in (values or {}).items():
            axis = self._subject(axis)
            if not axis:
                continue
            try:
                delta = float(value) * scale
            except (TypeError, ValueError):
                continue
            if not delta:
                continue
            current[axis] = _clamp(
                current.get(axis, self.neutral) + delta
            )
        applied = {
            axis: current[axis] - before.get(axis, self.neutral)
            for axis in current
            if axis not in before
            or abs(current[axis] - before[axis]) > 1e-12
        }
        if applied:
            self.set(source, target, current)
        return applied

    def effect(self, source, target, form=DEFAULT_RELATION_FORM):
        """Вклад отношений ``source → target`` в приём формы работы."""
        return relation_effect(
            self.axes_for(source, target),
            self.form_for(form),
            weights=self.weights,
            limit=self.limit,
        )

    def view(self, source=None):
        """Срез для UI: ``{target: {axis: value}}`` или всё хранилище."""
        source = self._subject(source)
        if source:
            return {
                target: dict(values)
                for target, values in self._values.get(
                    source, {}
                ).items()
            }
        return self.snapshot()

    def snapshot(self):
        """Копия хранилища для снимка кампании."""
        return {
            source: {
                target: dict(values)
                for target, values in targets.items()
            }
            for source, targets in self._values.items()
        }

    def load(self, data):
        """Заменить хранилище снимком; старые сейвы дают пустую матрицу."""
        self._values = {}
        for source, targets in (data or {}).items():
            if not isinstance(targets, Mapping):
                continue
            for target, values in targets.items():
                if not isinstance(values, Mapping):
                    continue
                self.set(source, target, values)
        return self

    def __bool__(self):
        return any(self._values.values())

    def __len__(self):
        return sum(len(targets) for targets in self._values.values())


__all__ = [
    "RelationStore",
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
