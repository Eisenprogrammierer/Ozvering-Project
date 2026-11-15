"""Capability → Work: сборка работы из записи действия кампании.

Фаза 2–4a [`WORK_MECHANIC_PLAN.md`](../docs/WORK_MECHANIC_PLAN.md):
работа кампании перестаёт быть «словарём эффектов» и становится
``core41.types.Work``. Модуль **ничего не применяет** — он только
собирает план работы из capability (записи ``actions``) или из записи
взаимодействия (organ/automaton/character interaction) и фактического
контекста (актор, цель, кампания).

Контракт:

* ``amount`` — из ``template.amount``, иначе — конверсия ``cost`` через
  ``conversion_quote`` (явная потеря); если ``campaign`` не передан,
  сумма модулей ``cost`` (1:1) — совместимый fallback для тестов и
  офлайн-сборки;
* ``form`` — из ``template.form``, иначе ``action.form``, иначе
  ``force``; для взаимодействий ``form`` — это ``kind``
  (``organ_interaction``/``automaton_interaction``/
  ``character_interaction``), потому что handlers для них выбираются по
  форме, а ветка — по ``meta.interaction_id``;
* ``payload`` — из ``template.payload`` (нормализуется через
  ``make_payload``); ошибка схемы не роняет сборку, payload становится
  пустым, а причина пишется в ``payload_error``;
* ``duration`` — из ``template.duration``, иначе 1.0;
* ``target_side`` — фактическая сторона цели;
* ``essence_hint`` — ``hints.essence`` (или ``action.essence``);
* ``meta`` — контекст взаимодействия (``interaction_id``, ``organ_id``,
  ``character_id``, ``target_organ_id``); ``build_work`` его не
  заполняет, ``build_interaction_work`` заполняет.

Модуль не импортирует ``campaign.automata``: ``WorkPlan`` не зависит от
кампании. Это позволяет тестировать сборку отдельно от рантайма.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping

from core41.payload import PayloadError, make_payload
from core41.types import Work


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def cost_to_amount(cost):
    """Сумма модулей ``cost`` в активах.

    Временная мера: цена в активах не списывается бесплатно, но и не
    переводится в энергию 1:1 (это сделает ``conversion_quote`` ниже).
    Здесь нужен только объём работы до конверсии.
    """
    total = 0.0
    for _key, value in _as_mapping(cost).items():
        total += abs(_number(value, 0.0))
    return max(0.0, total)


def convert_cost(cost, form, campaign=None):
    """Перевести ``cost`` в ``amount`` работы через явную конверсию.

    Если ``campaign`` передан, используется
    ``campaign.economy.conversion_quote`` — это единственный способ
    получить ``loss``/``entropy`` при переводе актива в энергию. Без
    ``campaign`` сумма модулей возвращается как ``amount``, а
    ``efficiency`` = 1.0: это офлайн-оценка без экономики кампании.

    Возвращает ``(amount, efficiency, loss, entropy, report)``; ``report``
    — исходный ответ ``conversion_quote`` (или ``None``).
    """
    base = cost_to_amount(cost)
    if base <= 0.0:
        return 0.0, 0.0, 0.0, 0.0, None
    if campaign is None:
        return base, 1.0, 0.0, 0.0, None
    try:
        from .economy import conversion_quote

        report = conversion_quote(base, str(form or "force"))
    except Exception:
        return base, 1.0, 0.0, 0.0, None
    amount = _number(report.get("amount"), base)
    efficiency = _number(report.get("efficiency"), 1.0)
    loss = _number(report.get("loss"), 0.0)
    entropy = _number(report.get("entropy"), 0.0)
    return amount, efficiency, loss, entropy, report


def build_payload(action):
    """Собрать ``payload`` из capability, если он там объявлен.

    Фаза 2–4a не требует payload в контенте: если в записи есть
    ``template.payload``, он нормализуется через ``make_payload``;
    иначе payload пуст. Ошибка схемы (``PayloadError``) не роняет
    сборку — payload становится пустым, а причина возвращается
    вызывающему.

    Возвращает ``(payload, error)``: ``payload`` — кортеж пар,
    ``error`` — строка причины или пустая.
    """
    template = _as_mapping(action.get("template"))
    raw = template.get("payload")
    if not raw:
        return (), ""
    try:
        if isinstance(raw, Mapping):
            kind = str(raw.get("kind") or "")
            if not kind:
                return tuple(sorted(raw.items())), ""
            data = {k: v for k, v in raw.items() if k != "kind"}
            return make_payload(kind, **data), ""
        if isinstance(raw, (list, tuple)):
            if len(raw) == 2 and not isinstance(raw[0], (list, tuple)):
                return tuple(sorted(raw)), ""
            return tuple(raw), ""
    except PayloadError as exc:
        return (), str(exc)
    return (), ""


@dataclass
class WorkPlan:
    """План работы: capability/интеракция → ``Work`` + метаданные.

    Поля:

    * ``capability_id`` — id записи действия или взаимодействия;
    * ``amount`` — объём работы в ``E`` (после конверсии);
    * ``form`` — канал (``force``/``info``/``organ_interaction``/…);
    * ``payload`` — нормализованный кортеж пар;
    * ``duration`` — длительность;
    * ``target_side`` — фактическая сторона цели;
    * ``cost_assets`` — исходная цена в активах (для отчёта и сверки);
    * ``payload_error`` — причина, если payload не собрался;
    * ``essence_hint`` — ``hints.essence`` (не влияет на эффект;
      используется для ``trace.essence``);
    * ``efficiency``/``loss``/``entropy`` — предварительная конверсия
      ``cost`` → ``amount``;
    * ``meta`` — контекст взаимодействия (``interaction_id``,
      ``organ_id``, ``character_id``, ``target_organ_id``). Для
      capability пуст; для взаимодействий заполняется
      ``build_interaction_work``. ``handlers.receive`` читает
      ``meta.interaction_id`` для выбора ветки правила.
    """

    capability_id: str
    amount: float
    form: str
    payload: tuple = ()
    duration: float = 1.0
    target_side: str = ""
    cost_assets: Dict[str, float] = field(default_factory=dict)
    payload_error: str = ""
    essence_hint: str = ""
    efficiency: float = 0.0
    loss: float = 0.0
    entropy: float = 0.0
    meta: Dict[str, str] = field(default_factory=dict)

    def to_work(self):
        return Work(
            amount=max(0.0, float(self.amount)),
            form=str(self.form or "force"),
            payload=tuple(self.payload or ()),
            duration=float(self.duration or 1.0),
        )

    def as_dict(self):
        return {
            "capability_id": str(self.capability_id),
            "amount": round(max(0.0, float(self.amount)), 6),
            "form": str(self.form),
            "payload": list(self.payload or ()),
            "duration": round(float(self.duration or 1.0), 6),
            "target_side": str(self.target_side),
            "cost_assets": {
                str(key): round(float(value), 6)
                for key, value in self.cost_assets.items()
            },
            "payload_error": str(self.payload_error),
            "essence_hint": str(self.essence_hint),
            "efficiency": round(float(self.efficiency), 6),
            "loss": round(float(self.loss), 6),
            "entropy": round(float(self.entropy), 6),
            "meta": dict(self.meta or {}),
        }


def _hints(action):
    hints = _as_mapping(action.get("hints"))
    essence = str(hints.get("essence") or "").strip()
    if not essence:
        essence = str(action.get("essence") or "").strip()
    return essence


def build_work(action, actor, target, campaign=None):
    """Собрать ``WorkPlan`` из capability (``action``).

    ``amount`` берётся из явного ``template.amount``; иначе — конверсия
    ``cost`` через ``conversion_quote`` (если ``campaign`` передан) или
    сумма модулей (офлайн-оценка). ``form`` — из ``template.form``, иначе
    ``action.form``. ``payload`` — из ``template.payload``. ``duration``
    — из ``template.duration``, иначе 1.0. ``target_side`` — фактическая
    сторона, которую выбрал ``_target_side``.

    Не бросает: любая ошибка — это ``None``; вызывающий возвращает
    игроку причину, не применяя частичную работу.
    """
    try:
        template = _as_mapping(action.get("template"))
        form = str(
            template.get("form")
            or action.get("form")
            or "force"
        )
        cost = _as_mapping(action.get("cost"))
        explicit_amount = template.get("amount")
        if explicit_amount is None:
            amount, efficiency, loss, entropy, _report = convert_cost(
                cost, form, campaign
            )
        else:
            amount = _number(explicit_amount, 0.0)
            efficiency = 0.0
            loss = 0.0
            entropy = 0.0
        if amount <= 0.0:
            return None
        payload, payload_error = build_payload(action)
        duration = _number(template.get("duration"), 1.0)
        if duration <= 0.0:
            duration = 1.0
        target_side = str(getattr(target, "side", "") or "")
        return WorkPlan(
            capability_id=str(action.get("id") or ""),
            amount=amount,
            form=form,
            payload=payload,
            duration=duration,
            target_side=target_side,
            cost_assets={
                str(key): _number(value, 0.0)
                for key, value in cost.items()
            },
            payload_error=payload_error,
            essence_hint=_hints(action),
            efficiency=efficiency,
            loss=loss,
            entropy=entropy,
            meta={},
        )
    except Exception:
        return None


def build_interaction_work(record, kind, source, target, campaign=None):
    """Собрать ``WorkPlan`` из записи взаимодействия.

    ``record`` — organ/automaton/character interaction (dict). ``kind`` —
    ``"organ_interaction"``/``"automaton_interaction"``/
    ``"character_interaction"``; он же становится ``form`` в ``Work``,
    потому что handlers выбираются по форме. ``amount`` — из
    ``template.amount`` (если в записи есть) или через конверсию
    ``cost``. ``meta`` заполняется контекстом:

    * ``interaction_id`` — id записи;
    * ``organ_id`` — для organ interaction (id органа-цели);
    * ``target_organ_id`` — для automaton interaction (id органа-цели);
    * ``source_organ_id`` — для automaton interaction (id органа-источника);
    * ``character_id`` — для character interaction (id персонажа-цели).

    ``target_side`` — ``"organ"``/``"character"``/``"automaton"``;
    handlers для этих форм знают, что цель — не фракция, и пишут в
    ``organs``/``needs``/``personality`` через ``apply_effects``.

    Не бросает: любая ошибка — ``None``.
    """
    try:
        record = _as_mapping(record)
        kind = str(kind or "").strip()
        if kind not in (
            "organ_interaction",
            "automaton_interaction",
            "character_interaction",
        ):
            return None
        template = _as_mapping(record.get("template"))
        cost = _as_mapping(record.get("cost"))
        explicit_amount = template.get("amount")
        if explicit_amount is None:
            amount, efficiency, loss, entropy, _report = convert_cost(
                cost, kind, campaign
            )
        else:
            amount = _number(explicit_amount, 0.0)
            efficiency = 0.0
            loss = 0.0
            entropy = 0.0
        if amount <= 0.0:
            return None
        payload, payload_error = build_payload(record)
        duration = _number(template.get("duration"), 1.0)
        if duration <= 0.0:
            duration = 1.0
        meta = {
            "interaction_id": str(record.get("id") or ""),
            "kind": kind,
        }
        if kind == "organ_interaction":
            meta["organ_id"] = str(record.get("organ_id") or "")
            target_side = "organ"
        elif kind == "automaton_interaction":
            meta["source_organ_id"] = str(
                record.get("source_organ_id") or ""
            )
            meta["target_organ_id"] = str(
                record.get("target_organ_id") or ""
            )
            target_side = "automaton"
        else:
            meta["character_id"] = str(record.get("character_id") or "")
            target_side = "character"
        return WorkPlan(
            capability_id=str(record.get("id") or ""),
            amount=amount,
            form=kind,
            payload=payload,
            duration=duration,
            target_side=target_side,
            cost_assets={
                str(key): _number(value, 0.0)
                for key, value in cost.items()
            },
            payload_error=payload_error,
            essence_hint=_hints(record),
            efficiency=efficiency,
            loss=loss,
            entropy=entropy,
            meta=meta,
        )
    except Exception:
        return None


__all__ = [
    "WorkPlan",
    "build_interaction_work",
    "build_payload",
    "build_work",
    "convert_cost",
    "cost_to_amount",
]
