"""Коалиции кампании: формирование, сотрудничество и распад (§7.3 №19).

Коалиция — не новый тип автомата и не второй бюджет. Это **устойчивая
связка узлов**, которая:

* формируется из взаимных осей отношений (`affinity`, `trust`) и
  обязательств между сторонами;
* усиливает сотрудничество: узел чуть охотнее работает с союзником;
* распадается, когда взаимная опора падает ниже порога несколько дней
  подряд или из связки выбывает участник.

Математическая форма пары:

```text
pair(a, b) = (avg_axes(R_a→b) + avg_axes(R_b→a)) / 2
             + obligation_bonus · min(obligations(a,b), 3)
```

`pair` ограничен `[0, 1]`. Коалиция формируется, когда `pair` не ниже
`form_threshold` в течение `form_days` дней; распадается, когда средняя
сила связки ниже `decay_threshold` в течение `decay_days` дней. Это
детерминированно: пары перебираются по id, смещение по времени не нужно.

Блок `coalitions` в конфиге мира выключен по умолчанию. Старые миры и
сейвы не получают ни коалиций, ни бонусов к выбору действий.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_COALITIONS = {
    "enabled": False,
    "min_members": 2,
    "max_members": 4,
    "max_coalitions": 4,
    "form_threshold": 0.35,
    "decay_threshold": 0.15,
    "form_days": 2,
    "decay_days": 3,
    "axes": ("affinity", "trust"),
    "obligation_bonus": 0.06,
    "cooperation_bonus": 0.05,
    "include_player": False,
}

COALITION_STATUSES = ("active", "dissolved")


def _as_text(value, default=""):
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _as_float(value, low)))


def _axes(raw):
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (list, tuple)) and raw:
        return tuple(str(item) for item in raw if str(item).strip())
    return DEFAULT_COALITIONS["axes"]


def coalition_config(raw=None):
    """Нормализовать блок `coalitions`; пустой блок выключен."""
    raw = raw if isinstance(raw, dict) else {}
    config = dict(DEFAULT_COALITIONS)
    config["enabled"] = bool(raw.get("enabled", False))
    config["min_members"] = max(2, _as_int(raw.get("min_members"), 2))
    config["max_members"] = max(
        config["min_members"], _as_int(raw.get("max_members"), 4)
    )
    config["max_coalitions"] = max(
        1, _as_int(raw.get("max_coalitions"), 4)
    )
    config["form_threshold"] = _clamp(
        raw.get("form_threshold", 0.35), 0.0, 1.0
    )
    config["decay_threshold"] = _clamp(
        raw.get("decay_threshold", 0.15), 0.0, 1.0
    )
    config["form_days"] = max(1, _as_int(raw.get("form_days"), 2))
    config["decay_days"] = max(1, _as_int(raw.get("decay_days"), 3))
    config["axes"] = _axes(raw.get("axes"))
    config["obligation_bonus"] = max(
        0.0, _as_float(raw.get("obligation_bonus"), 0.06)
    )
    config["cooperation_bonus"] = max(
        0.0, _as_float(raw.get("cooperation_bonus"), 0.05)
    )
    config["include_player"] = bool(raw.get("include_player", False))
    return config


def pair_score(
    axes_ab,
    axes_ba,
    obligations=0,
    axes=None,
    obligation_bonus=None,
):
    """Сила связи двух узлов в `[0, 1]`.

    `axes_ab` — R_a→b, `axes_ba` — R_b→a. Учитываются только выбранные оси;
    обязательства добавляют ограниченный бонус, но не заменяют отношения.
    """
    axes = tuple(axes or DEFAULT_COALITIONS["axes"])
    bonus = (
        DEFAULT_COALITIONS["obligation_bonus"]
        if obligation_bonus is None
        else max(0.0, _as_float(obligation_bonus))
    )
    ab = [_clamp((axes_ab or {}).get(axis, 0.0)) for axis in axes]
    ba = [_clamp((axes_ba or {}).get(axis, 0.0)) for axis in axes]
    left = sum(ab) / len(ab) if ab else 0.0
    right = sum(ba) / len(ba) if ba else 0.0
    value = 0.5 * (left + right)
    value += bonus * min(3, max(0, _as_int(obligations, 0)))
    return _clamp(value)


def _pair_key(left, right):
    left, right = str(left), str(right)
    return (left, right) if left <= right else (right, left)


@dataclass
class Coalition:
    """Постоянная связка узлов с общей силой и сроком жизни."""

    id: str
    members: tuple
    created_day: int = 1
    strength: float = 0.0
    status: str = "active"
    last_active_day: int = 1
    dissolved_day: int = None
    reason: str = ""
    name: str = ""

    def active(self):
        return self.status == "active"

    def to_dict(self):
        return {
            "id": self.id,
            "members": list(self.members),
            "created_day": int(self.created_day),
            "strength": float(self.strength),
            "status": self.status,
            "last_active_day": int(self.last_active_day),
            "dissolved_day": (
                None
                if self.dissolved_day is None
                else int(self.dissolved_day)
            ),
            "reason": self.reason,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            return None
        members = []
        for item in raw.get("members") or ():
            item = _as_text(item)
            if item and item not in members:
                members.append(item)
        if len(members) < 2:
            return None
        status = _as_text(raw.get("status"), "active")
        if status not in COALITION_STATUSES:
            status = "active"
        dissolved = raw.get("dissolved_day")
        return cls(
            id=_as_text(raw.get("id")),
            members=tuple(members),
            created_day=max(0, _as_int(raw.get("created_day"), 1)),
            strength=_clamp(raw.get("strength", 0.0)),
            status=status,
            last_active_day=max(
                0, _as_int(raw.get("last_active_day"), 1)
            ),
            dissolved_day=(
                None
                if dissolved is None
                else max(0, _as_int(dissolved, 0))
            ),
            reason=_as_text(raw.get("reason")),
            name=_as_text(raw.get("name"))
            or "Союз: %s" % ", ".join(members),
        )


@dataclass
class CoalitionBook:
    """Детерминированный журнал коалиций и давления на их границах."""

    items: list = field(default_factory=list)
    pressure: dict = field(default_factory=dict)
    decay_pressure: dict = field(default_factory=dict)
    next_index: int = 1

    def __len__(self):
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def active(self):
        return [item for item in self.items if item.active()]

    def get(self, coalition_id):
        coalition_id = str(coalition_id or "")
        for item in self.items:
            if item.id == coalition_id:
                return item
        return None

    def for_node(self, node_id):
        node_id = str(node_id or "")
        return [
            item for item in self.active() if node_id in item.members
        ]

    def partners(self, node_id):
        node_id = str(node_id or "")
        result = []
        for item in self.for_node(node_id):
            for member in item.members:
                if member != node_id and member not in result:
                    result.append(member)
        return result

    def strength(self, left, right):
        """Сила связи двух узлов внутри активной коалиции (0, если нет)."""
        key = _pair_key(left, right)
        for item in self.active():
            if key[0] in item.members and key[1] in item.members:
                return float(item.strength)
        return 0.0

    def _next_id(self):
        taken = {item.id for item in self.items}
        while "coa%d" % self.next_index in taken:
            self.next_index += 1
        result = "coa%d" % self.next_index
        self.next_index += 1
        return result

    def _member_names(self, members, names=None):
        names = names or {}
        return [names.get(member, member) for member in members]

    def _form(self, members, day, strength, names):
        members = tuple(members)
        coalition = Coalition(
            id=self._next_id(),
            members=members,
            created_day=int(day),
            strength=_clamp(strength),
            last_active_day=int(day),
            name="Союз: %s" % ", ".join(
                self._member_names(members, names)
            ),
        )
        self.items.append(coalition)
        for key in list(self.pressure):
            if key[0] in members or key[1] in members:
                self.pressure.pop(key, None)
        return coalition

    def _dissolve(self, coalition, day, reason):
        coalition.status = "dissolved"
        coalition.dissolved_day = int(day)
        coalition.reason = str(reason)
        self.decay_pressure.pop(coalition.id, None)

    def update(
        self,
        day,
        pair_scores,
        eligible=None,
        config=None,
        names=None,
    ):
        """Один суточный шаг: распад, затем формирование.

        `pair_scores` — `{(a, b): score}` для всех рассматриваемых пар;
        `eligible` — `{node_id: bool}` (жив/на месте). Возвращает события
        формирования и распада; при выключенном блоке — пустой список.
        """
        config = config or coalition_config()
        if not config["enabled"]:
            return []
        eligible = eligible or {}
        names = names or {}
        pair_scores = {
            _pair_key(left, right): _clamp(score)
            for (left, right), score in (pair_scores or {}).items()
        }
        events = []

        for coalition in list(self.active()):
            present = [
                member
                for member in coalition.members
                if eligible.get(member, True)
            ]
            if len(present) < config["min_members"]:
                self._dissolve(
                    coalition, day, "участники выбыли"
                )
                events.append(self._event(coalition, "dissolved", day))
                continue
            scores = []
            for index, left in enumerate(present):
                for right in present[index + 1 :]:
                    scores.append(pair_scores.get(_pair_key(left, right), 0.0))
            strength = sum(scores) / len(scores) if scores else 0.0
            coalition.strength = _clamp(strength)
            if strength + 1e-9 >= config["decay_threshold"]:
                coalition.last_active_day = int(day)
                self.decay_pressure[coalition.id] = 0
                continue
            streak = self.decay_pressure.get(coalition.id, 0) + 1
            self.decay_pressure[coalition.id] = streak
            if streak >= config["decay_days"]:
                self._dissolve(
                    coalition, day, "взаимная опора ослабла"
                )
                events.append(self._event(coalition, "dissolved", day))

        busy = {
            member
            for coalition in self.active()
            for member in coalition.members
        }
        candidates = []
        for key, score in pair_scores.items():
            left, right = key
            if left == right:
                continue
            if not eligible.get(left, True) or not eligible.get(right, True):
                continue
            if left in busy or right in busy:
                continue
            if score + 1e-9 < config["form_threshold"]:
                self.pressure[key] = 0
                continue
            streak = self.pressure.get(key, 0) + 1
            self.pressure[key] = streak
            if streak >= config["form_days"]:
                candidates.append((score, left, right))

        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        for score, left, right in candidates:
            if len(self.active()) >= config["max_coalitions"]:
                break
            busy = {
                member
                for coalition in self.active()
                for member in coalition.members
            }
            if left in busy or right in busy:
                continue
            members = [left, right]
            while len(members) < config["max_members"]:
                best = None
                for candidate in sorted(
                    node
                    for node in eligible
                    if eligible.get(node, True)
                    and node not in members
                    and node not in busy
                ):
                    links = [
                        pair_scores.get(_pair_key(candidate, member), 0.0)
                        for member in members
                    ]
                    weakest = min(links) if links else 0.0
                    if weakest + 1e-9 < config["form_threshold"]:
                        continue
                    key = (-weakest, candidate)
                    if best is None or key < best[0]:
                        best = (key, candidate)
                if best is None:
                    break
                members.append(best[1])
            coalition = self._form(
                members,
                day,
                sum(
                    pair_scores.get(_pair_key(left_member, right_member), 0.0)
                    for index, left_member in enumerate(members)
                    for right_member in members[index + 1 :]
                )
                / max(
                    1,
                    len(members) * (len(members) - 1) // 2,
                ),
                names,
            )
            events.append(self._event(coalition, "formed", day))
            busy.update(members)

        for key in list(self.pressure):
            if key not in pair_scores:
                self.pressure.pop(key, None)
        return events

    @staticmethod
    def _event(coalition, action, day):
        if action == "formed":
            text = "%s сформирован (сила %.2f)." % (
                coalition.name,
                coalition.strength,
            )
        else:
            text = "%s распался: %s." % (
                coalition.name,
                coalition.reason or "нет опоры",
            )
        return {
            "day": int(day),
            "kind": "coalition",
            "action": action,
            "coalition_id": coalition.id,
            "members": list(coalition.members),
            "strength": float(coalition.strength),
            "text": text,
        }

    def view(self, day=None):
        active = self.active()
        return {
            "enabled": bool(active) or bool(self.items),
            "day": day,
            "active": [item.to_dict() for item in active],
            "dissolved": [
                item.to_dict()
                for item in self.items
                if not item.active()
            ],
            "count": len(active),
        }

    def to_dict(self):
        return {
            "items": [item.to_dict() for item in self.items],
            "pressure": {
                "%s|%s" % key: int(value)
                for key, value in self.pressure.items()
            },
            "decay_pressure": {
                str(key): int(value)
                for key, value in self.decay_pressure.items()
            },
            "next_index": int(self.next_index),
        }

    def load(self, raw):
        raw = raw if isinstance(raw, dict) else {}
        self.items = []
        for item in raw.get("items") or ():
            coalition = Coalition.from_dict(item)
            if coalition is not None:
                self.items.append(coalition)
        self.pressure = {}
        for key, value in (raw.get("pressure") or {}).items():
            left, _, right = str(key).partition("|")
            if left and right:
                self.pressure[_pair_key(left, right)] = max(
                    0, _as_int(value)
                )
        self.decay_pressure = {
            str(key): max(0, _as_int(value))
            for key, value in (raw.get("decay_pressure") or {}).items()
        }
        self.next_index = max(1, _as_int(raw.get("next_index"), 1))
        return self

    def copy(self):
        return CoalitionBook().load(self.to_dict())


__all__ = [
    "COALITION_STATUSES",
    "Coalition",
    "CoalitionBook",
    "DEFAULT_COALITIONS",
    "coalition_config",
    "pair_score",
]
