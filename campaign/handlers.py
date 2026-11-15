"""Реестр обработчиков получателя: JSON-правила + сборка ``WorkReport``.

Фаза 3–4a [`WORK_MECHANIC_PLAN.md`](../docs/WORK_MECHANIC_PLAN.md): работа
кампании больше не несёт ``effects``/``failure`` в записи. Эффект
вычисляет обработчик получателя по ``form`` и контексту; правила лежат
в ``configs/campaigns/base/handlers/*.json``.

Обработчик — детерминированная функция ``(work, context, report) ->
WorkReport``. Стохастика (шанс, бросок) живёт в резолвере
(``campaign.automata``), а не в обработчике: это сохраняет
воспроизводимость и позволяет тестировать правила отдельно.

JSON-схема правила (файл ``handlers/<form>.json``)::

    {
      "form": "information",
      "rules": [
        {
          "when": {"id": "imperial_edict"},
          "receiver": {
            "accepts": ["legitimacy"],
            "effect": {
              "if": {"legitimacy": {"below": 0.5}},
              "then": {"legitimacy": -0.035, "fear": 0.01},
              "else": {"legitimacy": -0.01}
            }
          },
          "sender": {"legitimacy": 0.01},
          "trace": {"essence": "legitimize"}
        }
      ],
      "default": {
        "receiver": {"effect": {}},
        "sender": {}
      }
    }

Ключи правила:

* ``when`` — условия выбора правила. Основной ключ — ``id`` (id
  capability/взаимодействия); также поддерживаются ``payload_kind``,
  ``form``, ``target`` (``self``/``rival``/…), ``organ`` (id
  органа-получателя), ``requires`` (типизированные клаузы для
  ``check_conditions``). Все условия должны совпасть; первое подходящее
  правило выигрывает.
* ``receiver`` — что делает получатель:
  * ``accepts`` — список активов/потребностей, которые он принимает;
  * ``effect`` — либо готовый словарь эффекта, либо условная форма
    ``{"if": {...}, "then": {...}, "else": {...}}``.
* ``sender`` — что получает отправитель (обычно небольшой сдвиг).
* ``failure`` — необязательная ветка ``receiver``/``sender`` для
  ``success=False``. Провал — исход правила, а не второй словарь
  эффектов в capability.
* ``trace.essence`` — подсказка для ``trace.essence``; если пусто,
  берётся ``plan.essence_hint``.

Если правило не найдено и ``default`` пуст, обработчик возвращает
нейтральный отчёт (``accepted=True``, ``effect={}``) с корректным
балансом работы: отсутствие правила не должно ломать конвейер.

**Подстановка контекста взаимодействий.** В ``receiver.effect`` и
``sender`` можно использовать ключи ``"$organ_id"``,
``"$character_id"``, ``"$target_organ_id"``, ``"$source_organ_id"``.
Они раскрываются из ``plan.meta`` — это позволяет одному правилу
адресовать конкретный орган/персонаж, не дублируя правило под каждый
id.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Mapping, Optional

from core41.model import conversion_efficiency, conversion_report
from core41.types import Work, WorkReport

from .conditions import check_conditions

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
HANDLERS_DIR = ROOT / "configs" / "campaigns" / "base" / "handlers"

_META_KEYS = (
    "organ_id",
    "character_id",
    "target_organ_id",
    "source_organ_id",
    "interaction_id",
    "kind",
)


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


def _compare(current, op, expected):
    try:
        if op == "below":
            return current < expected
        if op == "above":
            return current > expected
        if op == "at_most":
            return current <= expected
        if op == "at_least":
            return current >= expected
        if op == "==":
            return current == expected
        if op == "!=":
            return current != expected
        return current == expected
    except TypeError:
        return False


def _eval_condition(spec, context):
    spec = _as_mapping(spec)
    if not spec:
        return True
    for key, value in spec.items():
        if isinstance(value, Mapping) and (
            "below" in value
            or "above" in value
            or "at_most" in value
            or "at_least" in value
            or "==" in value
            or "!=" in value
        ):
            for op, expected in value.items():
                if not _compare(
                    _number(context.get(key), 0.0),
                    op,
                    _number(expected, 0.0),
                ):
                    return False
        else:
            if _number(context.get(key), 0.0) != _number(value, 0.0):
                return False
    return True


def _resolve_effect(effect, receiver_context):
    effect = _as_mapping(effect)
    if "if" not in effect:
        return dict(effect)
    condition = _as_mapping(effect.get("if"))
    if _eval_condition(condition, receiver_context):
        return dict(_as_mapping(effect.get("then")))
    return dict(_as_mapping(effect.get("else")))


def _expand_meta(value, meta):
    """Рекурсивно заменить ``$organ_id``/``$character_id``/… из ``meta``.

    Работает и для ключей, и для значений. Если мета-ключ неизвестен
    (нет в ``plan.meta``), замена не происходит — правило всё равно
    соберётся, а лишний ключ уйдёт в ``ignored`` у ``apply_effects``.
    """
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            text_key = str(key)
            if text_key in _META_KEYS:
                expanded = meta.get(text_key)
                if expanded:
                    result[str(expanded)] = _expand_meta(item, meta)
                    continue
            result[text_key] = _expand_meta(item, meta)
        return result
    if isinstance(value, list):
        return [_expand_meta(item, meta) for item in value]
    if isinstance(value, str):
        for name in _META_KEYS:
            token = "$%s" % name
            if value == token:
                return meta.get(name, value)
        return value
    return value


def _receiver_state(faction, plan, work):
    assets = getattr(faction, "assets", {}) or {}
    state = {
        str(key): _number(value, 0.0)
        for key, value in assets.items()
    }
    state["payload_kind"] = _payload_kind(plan.payload)
    state["form"] = str(work.form or "")
    state["amount"] = _number(work.amount, 0.0)
    return state


def _payload_kind(payload):
    if not payload:
        return ""
    for item in payload:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        if str(item[0]) == "kind":
            return str(item[1] or "")
    return ""


def _condition_context(faction, target, plan, work, campaign):
    base = {
        "faction": faction,
        "target": target,
        "character": (
            faction.characters[0]
            if getattr(faction, "characters", ())
            else None
        ),
        "target_character": (
            target.characters[0]
            if target is not None
            and getattr(target, "characters", ())
            else None
        ),
        "turn": 0,
        "used_actions": set(),
        "labels": {},
        "payload_kind": _payload_kind(plan.payload),
        "form": str(work.form or ""),
        "capability_id": str(getattr(plan, "capability_id", "") or ""),
    }
    if campaign is not None:
        try:
            real = campaign._condition_context(faction, target)
        except Exception:
            real = None
        if real:
            base.update(real)
    return base


def _match_when(when, plan, work, faction, target, campaign):
    when = _as_mapping(when)
    if not when:
        return True
    if "id" in when:
        expected = str(when.get("id") or "")
        if expected and expected != str(plan.capability_id or ""):
            return False
    if "payload_kind" in when:
        expected = str(when.get("payload_kind") or "")
        if _payload_kind(plan.payload) != expected:
            return False
    if "form" in when:
        if str(work.form or "") != str(when.get("form") or ""):
            return False
    if "target" in when:
        expected = str(when.get("target") or "")
        if expected and expected != str(plan.target_side or ""):
            return False
    if "organ" in when:
        expected = str(when.get("organ") or "")
        organ = getattr(target, "organ", None)
        if expected and callable(organ):
            try:
                if target.organ(expected) is None:
                    return False
            except Exception:
                return False
    if "requires" in when:
        reason = check_conditions(
            when.get("requires"),
            _condition_context(faction, target, plan, work, campaign),
        )
        if reason:
            return False
    return True


def _empty_report(work, plan, success=True):
    amount = max(0.0, _number(work.amount, 0.0))
    efficiency = conversion_efficiency(work.form)
    stored = min(amount, amount * efficiency)
    report = conversion_report(amount, work.form, stored, efficiency)
    return WorkReport(
        accepted=True,
        success=bool(success),
        amount=amount,
        efficiency=report.get("efficiency", efficiency),
        stored=report.get("stored", 0.0),
        loss=report.get("loss", 0.0),
        entropy=report.get("entropy", 0.0),
        effect={},
        projections={},
        payload=dict(plan.payload or ()),
        trace={"essence": str(plan.essence_hint or "")},
    )


def apply_rule(rule, work, plan, faction, target, campaign, success=True):
    """Применить одно JSON-правило к получателю.

    Возвращает ``WorkReport`` с ``effect``/``projections``. Поля
    ``stored/loss/entropy`` считаются через ``conversion_report`` от
    объёма работы: это баланс, а не «эффект».

    ``$organ_id``/``$character_id``/… в ``receiver.effect`` и ``sender``
    раскрываются из ``plan.meta`` до сборки ``projections``.
    """
    rule = _as_mapping(rule)
    amount = max(0.0, _number(work.amount, 0.0))
    efficiency = conversion_efficiency(work.form)
    receiver_state = _receiver_state(faction, plan, work)
    if success:
        receiver_spec = _as_mapping(rule.get("receiver"))
        sender_spec = _as_mapping(rule.get("sender"))
    else:
        failure = _as_mapping(rule.get("failure"))
        receiver_spec = _as_mapping(failure.get("receiver"))
        sender_spec = _as_mapping(failure.get("sender"))
    effect = _resolve_effect(receiver_spec.get("effect"), receiver_state)
    projections = {}
    if effect:
        projections["target"] = dict(effect)
    if sender_spec:
        projections["self"] = dict(sender_spec)
    meta = dict(getattr(plan, "meta", {}) or {})
    if meta:
        projections = _expand_meta(projections, meta)
    stored = min(amount, amount * efficiency)
    report = conversion_report(amount, work.form, stored, efficiency)
    trace_essence = str(
        _as_mapping(rule.get("trace")).get("essence")
        or plan.essence_hint
        or ""
    )
    return WorkReport(
        accepted=True,
        success=bool(success),
        amount=amount,
        efficiency=report.get("efficiency", efficiency),
        stored=report.get("stored", 0.0),
        loss=report.get("loss", 0.0),
        entropy=report.get("entropy", 0.0),
        effect=dict(effect),
        projections=projections,
        payload=dict(plan.payload or ()),
        trace={"essence": trace_essence},
    )


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("Правило обработчика не загружено %s: %s", path, exc)
        return None


class HandlerRegistry:
    """Реестр обработчиков по форме, собранный из JSON-файлов.

    Ленивая загрузка: первый ``receive`` по форме читает файл
    ``handlers/<form>.json`` один раз и кеширует. Если файла нет —
    используется нейтральный обработчик (``accepted=True``,
    ``effect={}``).
    """

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else HANDLERS_DIR
        self._cache: Dict[str, dict] = {}
        self._loaded = set()

    def _load_form(self, form):
        if form in self._loaded:
            return self._cache.get(form)
        self._loaded.add(form)
        path = self.directory / ("%s.json" % form)
        if not path.is_file():
            self._cache[form] = None
            return None
        data = _load_json(path)
        if not isinstance(data, dict):
            self._cache[form] = None
            return None
        self._cache[form] = data
        return data

    def rules_for(self, form):
        data = self._load_form(form)
        if not data:
            return []
        return list(data.get("rules") or ())

    def default_for(self, form):
        data = self._load_form(form)
        if not data:
            return {}
        return dict(data.get("default") or {})

    def receive(self, work, plan, faction, target, campaign, success=True):
        for rule in self.rules_for(work.form):
            when = _as_mapping(rule).get("when")
            if _match_when(when, plan, work, faction, target, campaign):
                return apply_rule(
                    rule, work, plan, faction, target, campaign, success
                )
        default = self.default_for(work.form)
        if default:
            return apply_rule(
                default, work, plan, faction, target, campaign, success
            )
        return _empty_report(work, plan, success=success)


_DEFAULT_REGISTRY: Optional[HandlerRegistry] = None


def registry(directory=None):
    global _DEFAULT_REGISTRY
    if directory is not None:
        return HandlerRegistry(directory)
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = HandlerRegistry()
    return _DEFAULT_REGISTRY


def receive(work, plan, faction, target, campaign, success=True):
    """Публичная точка: ``receive`` из JSON-правил.

    Вызывается из ``campaign.automata.perform`` (фаза 3) и
    ``perform_*_interaction`` (фаза 4a). Форма ``work.form`` выбирает
    файл правил; внутри правила читают ``plan.payload`` и состояние
    фракции.
    """
    return registry().receive(
        work, plan, faction, target, campaign, success=success
    )


__all__ = [
    "HandlerRegistry",
    "apply_rule",
    "receive",
    "registry",
]
