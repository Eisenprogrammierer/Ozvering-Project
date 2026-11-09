"""Обязательства кампании: долг, услуга, служба и свидетельство.

`WORLD_CORE_MODEL` §7.3 №19 и §7.6 №36 просят математическую форму
обязательства. Это не энергия и не второй бюджет действий, а отдельная
запись отношения между двумя сторонами:

```text
obligation = {
    creditor, debtor, kind, amount,
    created_day, due_day, fulfilled_day, status, note,
}
```

`creditor` — тот, кому должны; `debtor` — тот, кто должен. `amount`
положителен и задаёт силу обязательства, но не списывается из `E`:
исполнение — социальный акт, который меняет доверие и расположение.
`status` принимает `open/fulfilled/cancelled`; просрочка не стирает долг,
а вычисляется как `overdue(day)`.

Стороны — идентификаторы персонажей, узлов или зарезервированное
`"player"` (герой). Легаси-поле `evidence` остаётся ресурсом-свидетельством,
а не автоматически обязательством: контент может создать обязательство
явно.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import CampaignError

OBLIGATION_KINDS = ("debt", "favor", "duty", "evidence")
DEFAULT_OBLIGATION_KIND = "favor"
OBLIGATION_STATUSES = ("open", "fulfilled", "cancelled")

OBLIGATION_FULFILL_TRUST = 0.06
OBLIGATION_FULFILL_AFFINITY = 0.03


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


def _clamp(value, low=-1.0, high=1.0):
    return max(low, min(high, float(value)))


@dataclass
class Obligation:
    """Одна запись обязательства."""

    id: str
    creditor: str
    debtor: str
    kind: str = DEFAULT_OBLIGATION_KIND
    amount: float = 1.0
    created_day: int = 1
    due_day: int = None
    fulfilled_day: int = None
    status: str = "open"
    note: str = ""

    def active(self):
        return self.status == "open"

    def overdue(self, day):
        return (
            self.active()
            and self.due_day is not None
            and _as_int(day, 0) > int(self.due_day)
        )

    def due(self, day):
        return (
            self.active()
            and self.due_day is not None
            and _as_int(day, 0) >= int(self.due_day)
        )

    def to_dict(self):
        return {
            "id": self.id,
            "creditor": self.creditor,
            "debtor": self.debtor,
            "kind": self.kind,
            "amount": float(self.amount),
            "created_day": int(self.created_day),
            "due_day": None if self.due_day is None else int(self.due_day),
            "fulfilled_day": (
                None
                if self.fulfilled_day is None
                else int(self.fulfilled_day)
            ),
            "status": self.status,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            return None
        creditor = str(raw.get("creditor") or "").strip()
        debtor = str(raw.get("debtor") or "").strip()
        if not creditor or not debtor or creditor == debtor:
            return None
        kind = str(raw.get("kind") or DEFAULT_OBLIGATION_KIND).strip()
        if kind not in OBLIGATION_KINDS:
            return None
        amount = _as_float(raw.get("amount"), 1.0)
        if amount <= 0.0:
            return None
        status = str(raw.get("status") or "open").strip()
        if status not in OBLIGATION_STATUSES:
            return None
        due = raw.get("due_day")
        fulfilled = raw.get("fulfilled_day")
        return cls(
            id=str(raw.get("id") or ""),
            creditor=creditor,
            debtor=debtor,
            kind=kind,
            amount=amount,
            created_day=max(0, _as_int(raw.get("created_day"), 1)),
            due_day=None if due is None else max(0, _as_int(due, 0)),
            fulfilled_day=(
                None
                if fulfilled is None
                else max(0, _as_int(fulfilled, 0))
            ),
            status=status,
            note=str(raw.get("note") or ""),
        )


class ObligationLedger:
    """Детерминированный журнал обязательств кампании."""

    def __init__(self, items=None):
        self.items = []
        for raw in items or ():
            obligation = (
                raw
                if isinstance(raw, Obligation)
                else Obligation.from_dict(raw)
            )
            if obligation is not None:
                self.items.append(obligation)

    def __len__(self):
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def _next_id(self):
        taken = {obligation.id for obligation in self.items}
        index = len(self.items) + 1
        while "obl%d" % index in taken:
            index += 1
        return "obl%d" % index

    def add(
        self,
        creditor,
        debtor,
        kind=DEFAULT_OBLIGATION_KIND,
        amount=1.0,
        *,
        created_day=1,
        due_day=None,
        note="",
    ):
        creditor = str(creditor or "").strip()
        debtor = str(debtor or "").strip()
        if not creditor or not debtor:
            raise CampaignError("обязательство требует кредитора и должника")
        if creditor == debtor:
            raise CampaignError("сторона не может быть должна сама себе")
        kind = str(kind or DEFAULT_OBLIGATION_KIND).strip()
        if kind not in OBLIGATION_KINDS:
            raise CampaignError("неизвестный вид обязательства: %s" % kind)
        amount = _as_float(amount, 1.0)
        if amount <= 0.0:
            raise CampaignError("сумма обязательства должна быть > 0")
        created_day = max(0, _as_int(created_day, 1))
        due_day = None if due_day is None else max(0, _as_int(due_day, 0))
        if due_day is not None and due_day < created_day:
            raise CampaignError("срок обязательства раньше его создания")
        obligation = Obligation(
            id=self._next_id(),
            creditor=creditor,
            debtor=debtor,
            kind=kind,
            amount=amount,
            created_day=created_day,
            due_day=due_day,
            note=str(note or ""),
        )
        self.items.append(obligation)
        return obligation

    def get(self, obligation_id):
        obligation_id = str(obligation_id or "")
        for obligation in self.items:
            if obligation.id == obligation_id:
                return obligation
        return None

    def open(self, day=None):
        """Все открытые обязательства, включая просроченные."""
        return [item for item in self.items if item.active()]

    def due(self, day):
        return [item for item in self.items if item.due(day)]

    def overdue(self, day):
        return [item for item in self.items if item.overdue(day)]

    def for_party(self, party):
        party = str(party or "")
        return [
            item
            for item in self.items
            if item.creditor == party or item.debtor == party
        ]

    def fulfill(self, obligation_id, day=1):
        obligation = self.get(obligation_id)
        if obligation is None or not obligation.active():
            return None
        obligation.status = "fulfilled"
        obligation.fulfilled_day = max(0, _as_int(day, 1))
        return obligation

    def cancel(self, obligation_id, day=1):
        obligation = self.get(obligation_id)
        if obligation is None or not obligation.active():
            return None
        obligation.status = "cancelled"
        obligation.fulfilled_day = max(0, _as_int(day, 1))
        return obligation

    def summary(self, day=None):
        day = 0 if day is None else _as_int(day, 0)
        open_items = self.open()
        return {
            "total": len(self.items),
            "open": len(open_items),
            "fulfilled": sum(
                1 for item in self.items if item.status == "fulfilled"
            ),
            "cancelled": sum(
                1 for item in self.items if item.status == "cancelled"
            ),
            "due": len(self.due(day)),
            "overdue": len(self.overdue(day)),
        }

    def to_list(self):
        return [item.to_dict() for item in self.items]

    def load(self, items):
        self.items = []
        for raw in items or ():
            obligation = Obligation.from_dict(raw)
            if obligation is not None:
                self.items.append(obligation)
        return self

    def copy(self):
        return ObligationLedger(items=list(self.to_list()))


__all__ = [
    "DEFAULT_OBLIGATION_KIND",
    "OBLIGATION_FULFILL_AFFINITY",
    "OBLIGATION_FULFILL_TRUST",
    "OBLIGATION_KINDS",
    "OBLIGATION_STATUSES",
    "Obligation",
    "ObligationLedger",
]
