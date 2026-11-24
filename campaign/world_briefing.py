"""Сводка мира и эпилог как проекция состояния.

Модуль не хранит сюжетных строк. Он читает конфиг мира, профиль героя и
состояние ``WorldEngine`` и собирает экспозицию из уже посчитанных
полей: название мира, державу, режим, нормы, день, репутацию и
организацию. Это тот же принцип, что и у ``campaign.chronicle`` для
кампаний автоматов.
"""

from __future__ import annotations

from typing import Mapping


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _text(value, default=""):
    text = str(value or "").strip()
    return text or str(default)


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _config_of(config=None, world=None):
    if isinstance(config, Mapping):
        return dict(config)
    return dict(getattr(world, "config", {}) or {})


def state_polity(config):
    """Первая держава мира: ярлык из данных, а не авторская строка."""

    for item in _as_mapping(config).get("polities") or ():
        if not isinstance(item, Mapping):
            continue
        if str(item.get("kind") or "") == "state":
            return _text(item.get("label"), item.get("id") or "")
    return ""


def norm_labels(config, count=3):
    labels = []
    for item in _as_mapping(config).get("norms") or ():
        if not isinstance(item, Mapping):
            continue
        label = _text(item.get("label"), item.get("id") or "")
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= count:
            break
    return labels


def briefing_slides(config=None, *, world=None, profile=None):
    """Стартовая сводка свободного мира из конфига и состояния."""

    data = _config_of(config, world)
    if not data:
        return []
    lines = []
    title = _text(data.get("title"), data.get("id") or "мир")
    subtitle = _text(data.get("subtitle"))
    lines.append("Мир: %s." % title)
    if subtitle:
        lines.append(subtitle)
    profile = _as_mapping(profile) or _as_mapping(
        getattr(world, "profile", None)
    )
    name = _text(profile.get("name"))
    if name:
        role = _text(
            profile.get("vocation_label"),
            profile.get("archetype_label") or profile.get("role") or "",
        )
        origin = _text(
            profile.get("origin_label"),
            profile.get("origin") or "",
        )
        tail = ""
        if role:
            tail = "; занятие: %s" % role
        if origin:
            tail += "; происхождение: %s" % origin
        lines.append("Вы: %s%s." % (name, tail))
    polity = state_polity(data)
    if polity:
        lines.append("Держава: %s." % polity)
    lines.append("Режим: свободный мир; история не ограничена.")
    per_day = int(_number(data.get("actions_per_day"), 0))
    if per_day > 0:
        lines.append("Действий в день: %d." % per_day)
    norms = norm_labels(data)
    if norms:
        lines.append("Нормы: %s." % ", ".join(norms))
    if world is not None:
        lines.append(
            "Сейчас: день %d, репутация %.2f."
            % (
                int(_number(getattr(world, "day", 0))),
                _number(
                    _as_mapping(
                        getattr(world, "player_resources", {})
                    ).get("standing")
                ),
            )
        )
    if not lines:
        return []
    return [{"image": "campaign/briefing", "text": "\n".join(lines)}]


def ending_view(world, config=None):
    """Эпилог мира как функция конечного состояния."""

    if world is None:
        return {"slides": [], "outcome": ""}
    data = _config_of(config, world)
    outcome = world.world_outcome()
    title = _text(data.get("title"), data.get("id") or "мир")
    polity = state_polity(data)
    day = int(_number(outcome.get("day")))
    lines = ["Мир «%s»: день %d." % (title, day)]
    lines.append("Режим: свободный мир; история не ограничена.")
    if polity:
        lines.append("Держава: %s." % polity)
    lines.append(
        "Репутация: %.2f · здоровье: %.0f · болезнь: %.2f."
        % (
            _number(outcome.get("standing")),
            _number(outcome.get("health")),
            _number(outcome.get("sickness")),
        )
    )
    ending = _text(outcome.get("ending"))
    if not ending:
        ending = {
            "win": "победа",
            "lose": "поражение",
            "neutral": "нейтрально",
        }.get(_text(outcome.get("outcome")), "")
    if ending:
        lines.append("Исход: %s." % ending)
    if outcome.get("dismissed"):
        lines.append("Должность потеряна; смен: %d." % int(
            _number(outcome.get("dismissal_count"))
        ))
    if outcome.get("collapsed"):
        lines.append("Организация распалась за %d дней." % int(
            _number(outcome.get("collapse_days"))
        ))
    organization = _as_mapping(outcome.get("organization"))
    if organization:
        label = _text(
            organization.get("name"),
            organization.get("id") or "",
        )
        if label:
            lines.append("Организация: %s." % label)
    slides = []
    if lines:
        slides.append(
            {"image": "campaign/ending", "text": "\n".join(lines)}
        )
    return {"slides": slides, "outcome": ending or ""}
