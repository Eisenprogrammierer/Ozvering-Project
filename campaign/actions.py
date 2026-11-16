"""Открытый каталог действий и манифест форм (P3).

Действие больше не обязано быть записью «фракция → орган → соперник».
Модуль даёт три независимых примитива:

* ``FormCatalog`` — манифест ``configs/campaigns/forms.json``: какие
  формы существуют, какой у них обработчик и каких адресатов они
  допускают;
* ``ActionSpec`` (нормализованный словарь) — одна схема для кампании,
  мира и сцены: ``id``, ``form``, ``actor``/``target`` как ``entity_ref``,
  ``template``/``effects``;
* ``merge_action_catalogs`` — сборка нескольких JSON-файлов по ``id`` с
  явным переопределением и диагностикой конфликтов.

Модуль ничего не применяет и не знает о ``WorldEngine``. Он только
проверяет данные и собирает ``WorkPlan`` через существующий
``campaign.work.build_work``. Поэтому новая форма или действие
добавляются JSON-ом, а не ветвлением по id в Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .errors import CampaignError
from .work import WorkPlan, build_work

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORMS_PATH = ROOT / "configs" / "campaigns" / "forms.json"
DEFAULT_HANDLERS_DIR = ROOT / "configs" / "campaigns" / "base" / "handlers"

ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# Типы ``entity_ref``. ``organization`` — общий тип для фракции/органа,
# ``institution``/``asset`` — типы узлов мира, ``place`` — любой узел,
# если действие адресует место, а не структуру.
ENTITY_KINDS = (
    "character",
    "organization",
    "organ",
    "institution",
    "asset",
    "item",
    "place",
    "norm",
)


class ActionError(CampaignError):
    """Ошибка данных действия или манифеста форм."""


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _text(value, default=""):
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _read_json(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise ActionError("%s: %s" % (path, exc))


def _tuple_text(values):
    if values is None:
        return ()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        raise ActionError("ожидался список строк, получено %r" % (values,))
    result = []
    for value in values:
        text = _text(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


@dataclass(frozen=True)
class FormSpec:
    """Одна форма работы из манифеста."""

    id: str
    label: str = ""
    description: str = ""
    payload_kinds: Tuple[str, ...] = ()
    target_kinds: Tuple[str, ...] = ()
    default_handler: bool = True
    tags: Tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data):
        data = _as_mapping(data)
        form_id = _text(data.get("id"))
        if not form_id or not ACTION_ID_RE.match(form_id):
            raise ActionError("форма: некорректный id %r" % (form_id,))
        target_kinds = _tuple_text(data.get("target_kinds"))
        unknown = [kind for kind in target_kinds if kind not in ENTITY_KINDS]
        if unknown:
            raise ActionError(
                "%s: неизвестные target_kinds %s"
                % (form_id, ", ".join(unknown))
            )
        return cls(
            id=form_id,
            label=_text(data.get("label"), form_id),
            description=_text(data.get("description")),
            payload_kinds=_tuple_text(data.get("payload_kinds")),
            target_kinds=target_kinds,
            default_handler=bool(data.get("default_handler", True)),
            tags=_tuple_text(data.get("tags")),
        )

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "payload_kinds": list(self.payload_kinds),
            "target_kinds": list(self.target_kinds),
            "default_handler": bool(self.default_handler),
            "tags": list(self.tags),
        }


class FormCatalog:
    """Манифест форм с проверкой обработчиков."""

    def __init__(self, forms=None, source=""):
        self.source = str(source or "")
        self._forms: Dict[str, FormSpec] = {}
        for form in forms or ():
            spec = form if isinstance(form, FormSpec) else FormSpec.from_dict(form)
            if spec.id in self._forms:
                raise ActionError("форма %s объявлена дважды" % spec.id)
            self._forms[spec.id] = spec

    @classmethod
    def load(cls, path=None, handlers_dir=None):
        path = Path(path) if path is not None else DEFAULT_FORMS_PATH
        data = _read_json(path)
        if isinstance(data, list):
            entries = data
        else:
            entries = _as_mapping(data).get("forms") or ()
        catalog = cls(entries, source=str(path))
        catalog.check_handlers(handlers_dir)
        return catalog

    def check_handlers(self, handlers_dir=None):
        directory = (
            Path(handlers_dir)
            if handlers_dir is not None
            else DEFAULT_HANDLERS_DIR
        )
        if not directory.is_dir():
            return []
        problems = []
        for form in self._forms.values():
            if not form.default_handler:
                continue
            if not (directory / ("%s.json" % form.id)).is_file():
                problems.append(
                    "%s: нет обработчика %s.json"
                    % (self.source or form.id, form.id)
                )
        if problems:
            raise ActionError("; ".join(problems))
        return []

    def get(self, form_id):
        return self._forms.get(_text(form_id))

    def require(self, form_id):
        form = self.get(form_id)
        if form is None:
            raise ActionError("неизвестная форма %r" % (_text(form_id),))
        return form

    def ids(self):
        return tuple(sorted(self._forms))

    def __contains__(self, form_id):
        return _text(form_id) in self._forms

    def __iter__(self):
        return iter(self._forms.values())

    def __len__(self):
        return len(self._forms)

    def as_dict(self):
        return {
            "schema": 1,
            "forms": [form.as_dict() for form in self],
        }


def _normalize_target(value):
    """Привести ``actor``/``target`` к словарю с ``kinds``."""
    if value is None:
        return {}
    if isinstance(value, str):
        value = {"kinds": [value]}
    if isinstance(value, (list, tuple)):
        value = {"kinds": list(value)}
    if not isinstance(value, Mapping):
        raise ActionError("actor/target должен быть объектом или списком")
    data = dict(value)
    kinds = data.get("kinds")
    if kinds is None and data.get("kind") is not None:
        kinds = [data.get("kind")]
    if isinstance(kinds, str):
        kinds = [kinds]
    if kinds is not None:
        if not isinstance(kinds, (list, tuple)):
            raise ActionError("target.kinds должен быть списком")
        data["kinds"] = _tuple_text(kinds)
    return data


def normalize_action(action, forms=None):
    """Проверить и нормализовать одну запись действия.

    Возвращает новый словарь, не меняя исходный. Старые действия мира
    без ``form`` остаются допустимыми: они применяют эффекты напрямую и
    не проходят через ``WorkPlan``. Если ``form`` указан, он обязан быть
    в манифесте.
    """
    if not isinstance(action, Mapping):
        raise ActionError("действие должно быть объектом")
    data = dict(action)
    action_id = _text(data.get("id"))
    if not action_id or not ACTION_ID_RE.match(action_id):
        raise ActionError("действие: некорректный id %r" % (action_id,))
    data["id"] = action_id
    data["label"] = _text(data.get("label"), action_id)
    template = dict(_as_mapping(data.get("template")))
    form = _text(data.get("form") or template.get("form"))
    if form:
        if forms is not None:
            forms.require(form)
        data["form"] = form
        template.setdefault("form", form)
    if template:
        data["template"] = template
    data["actor"] = _normalize_target(data.get("actor"))
    data["target"] = _normalize_target(data.get("target"))
    kinds = (data.get("target") or {}).get("kinds") or ()
    unknown = [kind for kind in kinds if kind not in ENTITY_KINDS]
    if unknown:
        raise ActionError(
            "%s: неизвестные target.kinds %s"
            % (action_id, ", ".join(unknown))
        )
    payload = data.get("payload")
    if payload and "payload" not in template:
        template["payload"] = payload
        data["template"] = template
    return data


def _has_effects(action):
    if action.get("effects") or action.get("handler"):
        return True
    for branch in ("success", "failure", "immediate"):
        if _as_mapping(action.get(branch)).get("effects"):
            return True
    return False


def lint_action(action, forms=None, require_form=False):
    """Вернуть список проблем действия; пустой список — всё в порядке."""
    problems = []
    try:
        data = normalize_action(action, forms=forms)
    except ActionError as exc:
        return [str(exc)]
    form = _text(data.get("form"))
    if not form:
        if require_form:
            problems.append("%s: нет form" % data["id"])
    elif forms is not None and form not in forms:
        problems.append("%s: неизвестная форма %s" % (data["id"], form))
    target = _as_mapping(data.get("target"))
    if not target.get("kinds") and not target.get("self"):
        problems.append("%s: target.kinds не задан" % data["id"])
    if not _has_effects(data):
        problems.append("%s: нет effects или handler" % data["id"])
    return problems


def merge_action_catalogs(sources, forms=None):
    """Собрать действия из нескольких JSON-источников по ``id``.

    ``sources`` — пары ``(label, data)``, где ``data`` — объект с
    ``actions`` или список действий. Действия из более позднего источника
    переопределяют более ранние по ``id``. Дубликат внутри одного
    источника — ошибка. Возвращает ``(actions, problems, overrides)``.
    """
    merged: Dict[str, dict] = {}
    order: List[str] = []
    problems: List[str] = []
    overrides: List[dict] = []
    for label, data in sources:
        if isinstance(data, Mapping):
            entries = data.get("actions") or ()
        elif isinstance(data, (list, tuple)):
            entries = data
        else:
            problems.append("%s: ожидался объект или список действий" % label)
            continue
        seen = set()
        for entry in entries:
            try:
                action = normalize_action(entry, forms=forms)
            except ActionError as exc:
                problems.append("%s: %s" % (label, exc))
                continue
            action_id = action["id"]
            if action_id in seen:
                problems.append(
                    "%s: действие %s объявлено дважды" % (label, action_id)
                )
                continue
            seen.add(action_id)
            if action_id in merged:
                overrides.append(
                    {
                        "id": action_id,
                        "from": merged[action_id].get("_source", ""),
                        "to": label,
                    }
                )
            action = dict(action)
            action["_source"] = label
            if action_id not in merged:
                order.append(action_id)
            merged[action_id] = action
    actions = [merged[action_id] for action_id in order]
    return actions, problems, overrides


def parse_entity_ref(value):
    """Разобрать универсальную ссылку на сущность.

    Поддерживаются ``{"kind": "character", "id": "..."}`` и короткая
    строка ``"character:..."``. ``kind`` обязан быть в ``ENTITY_KINDS``.
    """
    if isinstance(value, Mapping):
        kind = _text(value.get("kind") or value.get("type"))
        entity_id = _text(value.get("id"))
    elif isinstance(value, str) and ":" in value:
        kind, entity_id = value.split(":", 1)
        kind, entity_id = _text(kind), _text(entity_id)
    else:
        raise ActionError("entity_ref должен быть объектом kind/id")
    if kind not in ENTITY_KINDS:
        raise ActionError("неизвестный kind entity_ref %r" % (kind,))
    if not entity_id:
        raise ActionError("entity_ref: пустой id")
    return {"kind": kind, "id": entity_id}


def validate_entity_ref(value, known=None):
    """Проверить ссылку и, если передан ``known``, её существование.

    ``known`` — отображение ``kind -> iterable id``. Для ``place``
    допускаются узлы мира, поэтому вызывающий может передать один и тот
    же набор для ``place``/``institution``/``asset``.
    """
    ref = parse_entity_ref(value)
    if known is not None:
        ids = known.get(ref["kind"])
        if ids is not None and ref["id"] not in set(ids):
            raise ActionError(
                "сущность %s:%s не найдена" % (ref["kind"], ref["id"])
            )
    return ref


def entity_matches(ref, kinds):
    """Проходит ли ``entity_ref`` по списку допустимых видов."""
    kinds = set(kinds or ())
    if not kinds:
        return True
    kind = parse_entity_ref(ref)["kind"]
    return bool(kinds & {kind, "organization"} if kind == "organ" else kinds & {kind})


def build_spec_work(action, actor=None, target=None, campaign=None):
    """``ActionSpec`` → ``WorkPlan`` через существующий ``build_work``."""
    data = normalize_action(action)
    plan = build_work(data, actor, target, campaign)
    if plan is not None and data.get("form"):
        plan.meta.setdefault("form", data["form"])
    return plan


def improvised_work(
    intent,
    forms=None,
    actor=None,
    target=None,
    campaign=None,
    enabled=False,
):
    """Собрать работу из свободного намерения, если политика разрешает.

    По умолчанию импровизация выключена: ``enabled=False`` возвращает
    ``None``. Включённая импровизация всё равно требует существующую
    форму, валидный ``entity_ref`` и совместимость адресата с
    ``form.target_kinds``. План помечается ``meta["source"] =
    "improvised"``, чтобы отличить его от объявленного действия.
    """
    if not enabled:
        return None
    intent = _as_mapping(intent)
    form_id = _text(intent.get("form"))
    if not form_id:
        raise ActionError("импровизация: не указана form")
    if forms is not None:
        form = forms.require(form_id)
    else:
        form = None
    target_ref = intent.get("target")
    if target_ref is not None:
        ref = parse_entity_ref(target_ref)
        if form is not None and not entity_matches(ref, form.target_kinds):
            raise ActionError(
                "импровизация: форма %s не адресует %s"
                % (form_id, ref["kind"])
            )
    payload = dict(_as_mapping(intent.get("payload")))
    payload.setdefault("kind", form_id)
    amount = intent.get("amount", 0.01)
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.01
    spec = {
        "id": _text(intent.get("id"), "improvised"),
        "label": _text(intent.get("label"), "Свободное действие"),
        "form": form_id,
        "target": target_ref or {},
        "template": {
            "amount": max(0.0, amount),
            "duration": intent.get("duration", 1.0),
            "payload": payload,
        },
    }
    plan = build_spec_work(spec, actor=actor, target=target, campaign=campaign)
    if plan is not None:
        plan.meta["source"] = "improvised"
    return plan


__all__ = [
    "ACTION_ID_RE",
    "ActionError",
    "DEFAULT_FORMS_PATH",
    "DEFAULT_HANDLERS_DIR",
    "ENTITY_KINDS",
    "FormCatalog",
    "FormSpec",
    "build_spec_work",
    "entity_matches",
    "improvised_work",
    "lint_action",
    "merge_action_catalogs",
    "normalize_action",
    "parse_entity_ref",
    "validate_entity_ref",
]
