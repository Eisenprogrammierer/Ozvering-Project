"""Граница управления BDI-автоматами кампании (WORLD_CORE_MODEL §7.3).

Игрок — не внешний наблюдатель, который двигает фишки. Но и персонаж —
не марионетка: у него есть собственные убеждения, желания и намерения.
Модуль фиксирует явную границу между человеческим решением и автономией.

Что игрок может переопределить:

* `autonomy` — включить/выключить самостоятельные контакты персонажа;
* `intentions` — задать следующую ветку автономного контакта
  (`reconcile`/`rapprochement`/`probe`) или снять её;
* `beliefs`/`desires` — передать явные значения для UI/отладки; они не
  переписывают обученные веса политики;
* `work_queue` — не хранится здесь: очередь работы — это `IntentQueue`,
  игрок планирует и отменяет действия через неё.

У директивы есть срок (`expires_day`) и источник. По истечении срока
персонаж возвращается к своей политике — автономия не «залипает».
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import CampaignError

CONTROL_SCOPES = (
    "autonomy",
    "beliefs",
    "desires",
    "intentions",
    "work_queue",
)
AUTONOMY_BRANCHES = ("reconcile", "rapprochement", "probe")
DEFAULT_SOURCE = "player"


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _scope(value):
    scope = str(value or "").strip()
    if scope not in CONTROL_SCOPES:
        raise CampaignError("неизвестная область управления: %s" % scope)
    return scope


def _payload(scope, value):
    """Нормализовать payload директивы под её область."""
    if scope == "autonomy":
        if isinstance(value, dict):
            return {"enabled": bool(value.get("enabled", True))}
        return {"enabled": bool(value)}
    if scope == "intentions":
        if value is None or value == "":
            return {"branch": ""}
        if isinstance(value, dict):
            branch = str(value.get("branch") or "").strip()
        else:
            branch = str(value).strip()
        if branch and branch not in AUTONOMY_BRANCHES:
            raise CampaignError(
                "неизвестная ветка автономии: %s" % branch
            )
        return {"branch": branch}
    if scope in ("beliefs", "desires"):
        if not isinstance(value, dict):
            raise CampaignError(
                "%s ожидает объект значений" % scope
            )
        return {
            str(key): float(number)
            for key, number in value.items()
        }
    if scope == "work_queue":
        if isinstance(value, dict):
            return dict(value)
        return {"mode": str(value or "manual")}
    return value


@dataclass(frozen=True)
class Directive:
    """Одно переопределение игрока для конкретного персонажа."""

    target: str
    scope: str
    payload: object
    day: int = 1
    expires_day: int = None
    source: str = DEFAULT_SOURCE

    def active(self, day):
        if self.expires_day is None:
            return True
        return _as_int(day, 0) <= int(self.expires_day)

    def to_dict(self):
        return {
            "target": self.target,
            "scope": self.scope,
            "payload": self.payload,
            "day": int(self.day),
            "expires_day": (
                None if self.expires_day is None else int(self.expires_day)
            ),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            return None
        target = str(raw.get("target") or "").strip()
        if not target:
            return None
        try:
            scope = _scope(raw.get("scope"))
            payload = _payload(scope, raw.get("payload"))
        except CampaignError:
            return None
        expires = raw.get("expires_day")
        return cls(
            target=target,
            scope=scope,
            payload=payload,
            day=max(0, _as_int(raw.get("day"), 0)),
            expires_day=None if expires is None else _as_int(expires, 0),
            source=str(raw.get("source") or DEFAULT_SOURCE),
        )


@dataclass
class DirectiveBook:
    """Активные директивы игрока, переживающие сохранение мира."""

    items: list = field(default_factory=list)

    def set(
        self,
        target,
        scope,
        payload,
        *,
        day=1,
        expires_day=None,
        source=DEFAULT_SOURCE,
    ):
        """Записать директиву; старая того же target/scope заменяется."""
        target = str(target or "").strip()
        if not target:
            raise CampaignError("директива требует target")
        scope = _scope(scope)
        directive = Directive(
            target=target,
            scope=scope,
            payload=_payload(scope, payload),
            day=max(0, _as_int(day, 0)),
            expires_day=(
                None
                if expires_day is None
                else max(0, _as_int(expires_day, 0))
            ),
            source=str(source or DEFAULT_SOURCE),
        )
        self.clear(target, scope)
        self.items.append(directive)
        return directive

    def get(self, target, scope, day=None):
        """Последняя активная директива target/scope или `None`."""
        target = str(target or "")
        scope = str(scope or "")
        for directive in reversed(self.items):
            if (
                directive.target == target
                and directive.scope == scope
                and (day is None or directive.active(day))
            ):
                return directive
        return None

    def active(self, day):
        return [
            directive
            for directive in self.items
            if directive.active(day)
        ]

    def clear(self, target=None, scope=None):
        target = None if target is None else str(target)
        scope = None if scope is None else str(scope)
        before = len(self.items)
        self.items = [
            directive
            for directive in self.items
            if not (
                (target is None or directive.target == target)
                and (scope is None or directive.scope == scope)
            )
        ]
        return before - len(self.items)

    def prune(self, day):
        """Убрать истёкшие директивы; вернуть их число."""
        before = len(self.items)
        self.items = [
            directive
            for directive in self.items
            if directive.active(day)
        ]
        return before - len(self.items)

    def autonomy_enabled(self, target, day):
        directive = self.get(target, "autonomy", day)
        if directive is None:
            return True
        return bool(directive.payload.get("enabled", True))

    def intended_branch(self, target, day):
        directive = self.get(target, "intentions", day)
        if directive is None:
            return ""
        return str(directive.payload.get("branch") or "")

    def view(self, day=None, target=None):
        """Снимок для UI: target → scope → payload."""
        result = {}
        for directive in self.items:
            if target is not None and directive.target != str(target):
                continue
            if day is not None and not directive.active(day):
                continue
            result.setdefault(directive.target, {})[
                directive.scope
            ] = dict(directive.payload) if isinstance(
                directive.payload, dict
            ) else directive.payload
        return result

    def to_list(self):
        return [directive.to_dict() for directive in self.items]

    def load(self, items):
        self.items = []
        for raw in items or ():
            directive = Directive.from_dict(raw)
            if directive is not None:
                self.items.append(directive)
        return self

    def copy(self):
        return DirectiveBook(
            items=[Directive.from_dict(item.to_dict()) for item in self.items]
        )


__all__ = [
    "AUTONOMY_BRANCHES",
    "CONTROL_SCOPES",
    "DEFAULT_SOURCE",
    "Directive",
    "DirectiveBook",
]
