"""Долгосрочные стратегии автономных узлов (Data-Driven, срез A10).

До этого слоя узел выбирал одно действие в сутки по сиюминутной оценке
`_ai_score()`. Стратегия добавляет горизонт: у узла появляется цель на
несколько дней, прогресс которой виден и сохраняется в снимке мира.

Контент задаётся JSON. В конфиге мира можно указать либо массив
`"strategies"`, либо путь `"strategies_path"` к отдельному файлу:

    {
      "id": "order_consolidation",
      "label": "Укрепить порядок",
      "nodes": {"domains": ["order"]},
      "target": {"kinds": ["institution"]},
      "horizon_days": 6,
      "goal": {"stat": "legitimacy", "target": 0.72},
      "actions": {"negotiate": 0.8, "inspect": 0.4},
      "bonus": 0.25,
      "completion": {"stats": {"cohesion": 0.02},
                     "text": "Порядок укрепился."},
      "expiry": {"stats": {"legitimacy": -0.01},
                 "text": "Окно упущено."}
    }

Селекторы `nodes`/`target` поддерживают `id`/`ids`, `domains`, `levels`,
`kinds`, `polities` и `tags`. `goal.stat` — шкала узла; направление
задаётся `direction: "increase"|"decrease"` (по умолчанию increase).
`actions` — веса бонуса для конкретных действий. Бонус убывает по мере
прогресса, поэтому узел не застревает в одной стратегии навсегда.

Модуль не зависит от `WorldEngine`: он только читает JSON и считает
прогресс, а применение эффектов и запись в журнал остаются в мире.
"""

import json
from pathlib import Path

from .errors import CampaignError


def _clamp(value, low=0.0, high=1.0):
    return max(float(low), min(float(high), float(value)))


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _text(value, default=""):
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        raise CampaignError("не удалось прочитать %s: %s" % (path, exc))
    except ValueError as exc:
        raise CampaignError("некорректный JSON %s: %s" % (path, exc))


def _resolve_path(path, base_dir=None):
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    roots = []
    if base_dir:
        roots.append(Path(base_dir))
    roots.append(Path.cwd())
    roots.append(Path(__file__).resolve().parents[1])
    for root in roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return (roots[-1] / candidate).resolve()


def _selector(raw):
    """Нормализовать селектор в ``(ids, filters)``.

    Список — это явные id. Словарь — фильтры. Пустой/None означает «все».
    """
    if raw is None:
        return set(), {}
    if isinstance(raw, (list, tuple, set)):
        return {str(item) for item in raw}, {}
    if isinstance(raw, str):
        return {raw}, {}
    if not isinstance(raw, dict):
        raise CampaignError("селектор должен быть списком или объектом")
    ids = {
        str(item)
        for item in (
            raw.get("ids")
            or raw.get("id")
            or []
        )
        if str(item)
    }
    filters = {}
    for key in ("domains", "levels", "kinds", "polities", "tags"):
        values = raw.get(key)
        if values is None:
            continue
        if isinstance(values, str):
            values = [values]
        filters[key] = {str(item) for item in values}
    return ids, filters


def _matches(record, ids, filters):
    if ids and _text(record.get("id")) not in ids:
        return False
    aliases = {
        "domains": "domain",
        "levels": "level",
        "kinds": "kind",
        "polities": "polity",
    }
    for key, allowed in filters.items():
        if key == "tags":
            tags = {str(item) for item in (record.get("tags") or ())}
            if not tags & allowed:
                return False
            continue
        value = record.get(aliases.get(key, key))
        if isinstance(value, (list, tuple, set)):
            values = {str(item) for item in value}
            if not values & allowed:
                return False
        elif _text(value) not in allowed:
            return False
    return True


class NodeStrategy:
    """Одна долгосрочная цель узла, прочитанная из JSON."""

    def __init__(self, raw):
        if not isinstance(raw, dict):
            raise CampaignError("стратегия должна быть объектом")
        self.id = _text(raw.get("id"))
        if not self.id:
            raise CampaignError("у стратегии пустой id")
        self.label = _text(raw.get("label"), self.id)
        self.description = _text(raw.get("description"))
        self.horizon_days = max(1, _as_int(raw.get("horizon_days"), 5))
        self.bonus = max(0.0, _as_float(raw.get("bonus"), 0.15))
        self.priority = _as_int(raw.get("priority"), 0)
        self.repeat = bool(raw.get("repeat", False))
        self.cooldown_days = max(0, _as_int(raw.get("cooldown_days"), 0))
        self.goal = dict(raw.get("goal") or {})
        self.actions = {
            str(key): max(0.0, _as_float(value))
            for key, value in (raw.get("actions") or {}).items()
        }
        self.node_ids, self.node_filters = _selector(
            raw.get("nodes") or raw.get("node")
        )
        self.target_ids, self.target_filters = _selector(
            raw.get("targets") or raw.get("target")
        )
        self.completion = dict(raw.get("completion") or {})
        self.expiry = dict(raw.get("expiry") or {})

    def matches_node(self, node):
        return _matches(node, self.node_ids, self.node_filters)

    def matches_target(self, target):
        if target is None:
            return not self.target_ids and not self.target_filters
        return _matches(target, self.target_ids, self.target_filters)

    def action_weight(self, action_id):
        return self.actions.get(str(action_id), 0.0)

    def stat(self):
        return _text(self.goal.get("stat"))

    def target_value(self):
        return _as_float(self.goal.get("target"), 1.0)

    def direction(self):
        return _text(self.goal.get("direction"), "increase")

    def progress(self, node, state):
        """Нормированный прогресс 0..1 от стартового значения шкалы."""
        stat = self.stat()
        if not stat:
            return 0.0
        value = _as_float((node.get("stats") or {}).get(stat), 0.0)
        start = _as_float(state.get("start_value"), value)
        target = self.target_value()
        if self.direction() == "decrease":
            span = start - target
            if span <= 1e-9:
                return 1.0 if value <= target else 0.0
            return _clamp((start - value) / span)
        span = target - start
        if span <= 1e-9:
            return 1.0 if value >= target else 0.0
        return _clamp((value - start) / span)

    def new_state(self, node, day):
        stat = self.stat()
        return {
            "start_day": int(day),
            "start_value": _as_float(
                (node.get("stats") or {}).get(stat), 0.0
            ),
            "completed": False,
            "expired": False,
            "resolved_day": 0,
            "actions": {},
        }

    def score_bonus(self, action_id, node, state, day):
        """Аддитивный бонус к `_ai_score()` с учётом срочности."""
        if state.get("completed") or state.get("expired"):
            return 0.0
        weight = self.action_weight(action_id)
        if weight <= 0.0:
            return 0.0
        progress = self.progress(node, state)
        elapsed = max(0, int(day) - _as_int(state.get("start_day"), day))
        urgency = 1.0 + 0.5 * elapsed / float(self.horizon_days)
        return self.bonus * weight * max(0.05, 1.0 - progress) * urgency

    def advance(self, node, state, day):
        """Обновить прогресс; вернуть событие завершения/провала или None.

        Стратегия не завершается в день своего создания: узлу нужен хотя
        бы один полный день, чтобы действие успело изменить шкалу. Это
        также не даёт уже достигнутой цели мгновенно добавить событие в
        первый же `end_day()`.
        """
        if state.get("completed") or state.get("expired"):
            return None
        start = _as_int(state.get("start_day"), day)
        if int(day) <= start:
            return None
        progress = self.progress(node, state)
        if progress >= 1.0:
            state["completed"] = True
            state["resolved_day"] = int(day)
            return {
                "strategy": self.id,
                "label": self.label,
                "event": "completed",
                "progress": 1.0,
                "text": _text(
                    self.completion.get("text"),
                    "Цель стратегии «%s» достигнута." % self.label,
                ),
                "stats": dict(self.completion.get("stats") or {}),
            }
        elapsed = max(
            0, int(day) - _as_int(state.get("start_day"), day)
        )
        if elapsed >= self.horizon_days:
            state["expired"] = True
            state["resolved_day"] = int(day)
            return {
                "strategy": self.id,
                "label": self.label,
                "event": "expired",
                "progress": progress,
                "text": _text(
                    self.expiry.get("text"),
                    "Срок стратегии «%s» истёк." % self.label,
                ),
                "stats": dict(self.expiry.get("stats") or {}),
            }
        return None

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "horizon_days": self.horizon_days,
            "bonus": self.bonus,
            "priority": self.priority,
            "goal": dict(self.goal),
            "actions": dict(self.actions),
            "repeat": self.repeat,
            "cooldown_days": self.cooldown_days,
        }


class StrategyBook:
    """Коллекция стратегий мира с валидацией ссылок на действия."""

    def __init__(self, strategies=None):
        self.strategies = []
        seen = set()
        for raw in strategies or ():
            strategy = raw if isinstance(raw, NodeStrategy) else (
                NodeStrategy(raw)
            )
            if strategy.id in seen:
                raise CampaignError(
                    "повторяется id стратегии %r" % strategy.id
                )
            seen.add(strategy.id)
            self.strategies.append(strategy)
        self.strategies.sort(
            key=lambda item: (-item.priority, item.id)
        )

    @classmethod
    def from_config(cls, config, base_dir=None):
        """Прочитать стратегии из мира: массив и/или внешний JSON."""
        raw = []
        path = _text((config or {}).get("strategies_path"))
        if path:
            resolved = _resolve_path(path, base_dir)
            payload = _load_json(resolved)
            if isinstance(payload, dict):
                payload = payload.get("strategies") or []
            if not isinstance(payload, list):
                raise CampaignError(
                    "%s: strategies должен быть списком" % resolved
                )
            raw.extend(payload)
        inline = (config or {}).get("strategies")
        if inline is not None:
            if isinstance(inline, dict):
                inline = inline.get("strategies") or []
            if not isinstance(inline, list):
                raise CampaignError("strategies должен быть списком")
            raw.extend(inline)
        return cls(raw)

    def __len__(self):
        return len(self.strategies)

    def for_node(self, node):
        if node is None:
            return []
        return [
            strategy
            for strategy in self.strategies
            if strategy.matches_node(node)
        ]

    def get(self, strategy_id):
        for strategy in self.strategies:
            if strategy.id == strategy_id:
                return strategy
        return None

    def validate(self, action_ids=None, node_ids=None):
        """Проверить ссылки контента; вернуть список предупреждений.

        Неизвестное действие или узел — ошибка контента, а не падение
        мира: `validate_world()` превращает её в `WorldError`, а ручной
        загрузчик может показать предупреждение.
        """
        action_ids = set(action_ids or ())
        node_ids = set(node_ids or ())
        warnings = []
        for strategy in self.strategies:
            for action_id in strategy.actions:
                if action_ids and action_id not in action_ids:
                    raise CampaignError(
                        "%s: неизвестное действие %r"
                        % (strategy.id, action_id)
                    )
            for node_id in strategy.node_ids:
                if node_ids and node_id not in node_ids:
                    raise CampaignError(
                        "%s: неизвестный узел %r"
                        % (strategy.id, node_id)
                    )
            if strategy.target_ids:
                for node_id in strategy.target_ids:
                    if node_ids and node_id not in node_ids:
                        warnings.append(
                            "%s: цель %r пока отсутствует"
                            % (strategy.id, node_id)
                        )
        return warnings

    def as_list(self):
        return [strategy.as_dict() for strategy in self.strategies]


__all__ = [
    "NodeStrategy",
    "StrategyBook",
]
