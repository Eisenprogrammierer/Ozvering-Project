"""Линтер языковых шаблонов, payload и форм работы."""

from __future__ import annotations

import string
from collections.abc import Mapping

from core41.payload import (
    PAYLOAD_KINDS,
    PayloadError,
    normalize_payload_kinds,
)
from .actions import ActionError, FormCatalog


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


CHRONICLE_PHRASES_KEYS = {
    "schema",
    "description",
    "buckets",
    "openings",
    "decision_patterns",
    "cause_patterns",
    "facts_unit",
    "changes_prefix",
    "strongest_pattern",
    "empty_actor",
    "empty_target",
}


def _template_fields(text):
    """Имена плейсхолдеров шаблона; кривой шаблон даёт ``None``."""

    try:
        return {
            field
            for _literal, field, _spec, _conversion in (
                string.Formatter().parse(text)
            )
            if field
        }
    except ValueError:
        return None


def _template_list_problems(items, name, required):
    """Проверить список шаблонов: непустой, с нужными плейсхолдерами."""

    if not isinstance(items, list) or not items:
        return ["%s должен быть непустым списком" % name]
    allowed = set(required)
    problems = []
    for index, item in enumerate(items):
        if not isinstance(item, str) or not item.strip():
            problems.append(
                "%s[%d]: нужна непустая строка" % (name, index)
            )
            continue
        fields = _template_fields(item)
        if fields is None:
            problems.append(
                "%s[%d]: кривой шаблон %r" % (name, index, item)
            )
            continue
        missing = allowed - fields
        if missing:
            problems.append(
                "%s[%d]: нет обязательных плейсхолдеров %s"
                % (name, index, ", ".join(sorted(missing)))
            )
        extra = fields - allowed
        if extra:
            problems.append(
                "%s[%d]: неизвестные плейсхолдеры %s"
                % (name, index, ", ".join(sorted(extra)))
            )
    return problems


def lint_chronicle_phrases_data(data):
    """Проверить языковые шаблоны хроники.

    Шаблоны описывают только форму уже посчитанного эпизода: категории
    значимости, открытия и связки с решением/причиной. Линтер следит,
    чтобы данные не превращались в сюжет и чтобы каждый плейсхолдер был
    заполним из полей эпизода.
    """

    if not isinstance(data, Mapping):
        return ["шаблоны хроники должны быть объектом"]
    problems = []
    unknown = set(data) - CHRONICLE_PHRASES_KEYS
    if unknown:
        problems.append(
            "неизвестные поля: %s" % ", ".join(sorted(unknown))
        )
    if data.get("schema") != 1:
        problems.append("schema должен быть равен 1")
    buckets = data.get("buckets")
    bucket_ids = []
    if not isinstance(buckets, list) or not buckets:
        problems.append("buckets должен быть непустым списком")
    else:
        for index, item in enumerate(buckets):
            if not isinstance(item, Mapping):
                problems.append(
                    "buckets[%d] должен быть объектом" % index
                )
                continue
            extra = set(item) - {"id", "min"}
            if extra:
                problems.append(
                    "buckets[%d]: неизвестные поля %s"
                    % (index, ", ".join(sorted(extra)))
                )
            bucket_id = str(item.get("id") or "").strip()
            if not bucket_id:
                problems.append("buckets[%d]: пустой id" % index)
            elif bucket_id in bucket_ids:
                problems.append(
                    "buckets[%d]: повтор id %s" % (index, bucket_id)
                )
            else:
                bucket_ids.append(bucket_id)
            minimum = item.get("min")
            if isinstance(minimum, bool) or not isinstance(
                minimum, (int, float)
            ):
                problems.append(
                    "buckets[%d]: min должен быть числом" % index
                )
    openings = data.get("openings")
    if not isinstance(openings, Mapping) or not openings:
        problems.append("openings должен быть непустым объектом")
    else:
        for key, items in openings.items():
            if key not in bucket_ids:
                problems.append(
                    "openings: категория %s отсутствует в buckets" % key
                )
            if not isinstance(items, list) or not items:
                problems.append(
                    "openings.%s должен быть непустым списком" % key
                )
                continue
            for index, item in enumerate(items):
                if not isinstance(item, str) or not item.strip():
                    problems.append(
                        "openings.%s[%d]: нужна непустая строка"
                        % (key, index)
                    )
                    continue
                fields = _template_fields(item)
                if fields is None:
                    problems.append(
                        "openings.%s[%d]: кривой шаблон %r"
                        % (key, index, item)
                    )
                elif fields:
                    problems.append(
                        "openings.%s[%d]: открытие не должно иметь "
                        "плейсхолдеров" % (key, index)
                    )
        missing = [
            name for name in bucket_ids if name not in openings
        ]
        if missing:
            problems.append(
                "openings: нет категорий %s" % ", ".join(missing)
            )
    problems.extend(
        _template_list_problems(
            data.get("decision_patterns"),
            "decision_patterns",
            ("decision", "body"),
        )
    )
    problems.extend(
        _template_list_problems(
            data.get("cause_patterns"),
            "cause_patterns",
            ("cause",),
        )
    )
    strongest = data.get("strongest_pattern")
    if not isinstance(strongest, str) or not strongest.strip():
        problems.append(
            "strongest_pattern должен быть непустой строкой"
        )
    else:
        fields = _template_fields(strongest)
        if fields is None:
            problems.append("strongest_pattern: кривой шаблон")
        elif fields != {"label"}:
            problems.append(
                "strongest_pattern: нужен ровно плейсхолдер {label}"
            )
    for key in (
        "facts_unit",
        "changes_prefix",
        "empty_actor",
        "empty_target",
    ):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append("%s должен быть непустой строкой" % key)
    return problems


def lint_payload_kinds_data(data):
    """Проверить реестр видов payload и его схему."""
    try:
        normalize_payload_kinds(data)
    except PayloadError as exc:
        return [str(exc)]
    return []


def lint_forms_data(data):
    """Проверить манифест форм и наличие обработчиков."""
    if not isinstance(data, Mapping):
        return ["манифест форм должен быть объектом"]
    entries = data.get("forms")
    if not isinstance(entries, list) or not entries:
        return ["forms должен быть непустым списком"]
    try:
        catalog = FormCatalog(entries, source="forms")
        catalog.check_handlers()
    except ActionError as exc:
        return [str(exc)]
    problems = []
    for form in catalog:
        if not form.payload_kinds:
            problems.append("%s: не задан payload_kinds" % form.id)
        if not form.target_kinds:
            problems.append("%s: не задан target_kinds" % form.id)
        unknown = [
            kind for kind in form.payload_kinds if kind not in PAYLOAD_KINDS
        ]
        if unknown:
            problems.append(
                "%s: неизвестные payload_kinds %s"
                % (form.id, ", ".join(sorted(unknown)))
            )
    return problems
