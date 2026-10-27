from __future__ import annotations

import re

CHANCE_BANDS = (
    (0.92, "почти гарантированно"),
    (0.78, "весьма вероятно"),
    (0.62, "вероятно"),
    (0.46, "возможно"),
    (0.30, "маловероятно"),
    (0.15, "почти невероятно"),
    (0.0, "почти невозможно"),
)

CHARACTER_STAT_LABELS = {
    "affinity": "расположение",
    "trust": "доверие",
}

OUTCOME_LABELS = {
    "success": "Успех",
    "failure": "Провал",
    "day": "День завершён",
    "win": "Победа",
    "lose": "Поражение",
}


def chance_label(chance):
    value = max(0.0, min(1.0, float(chance)))
    for threshold, label in CHANCE_BANDS:
        if value >= threshold:
            return label
    return CHANCE_BANDS[-1][1]


def failure_label(chance):
    return chance_label(1.0 - float(chance))


def outcome_label(outcome):
    return OUTCOME_LABELS.get(str(outcome), str(outcome or "Итог"))


def relation_label(value):
    value = max(-1.0, min(1.0, float(value)))
    if value >= 0.60:
        return "близкие"
    if value >= 0.35:
        return "тёплые"
    if value >= 0.12:
        return "дружеские"
    if value > -0.12:
        return "ровные"
    if value > -0.35:
        return "настороженные"
    if value > -0.60:
        return "враждебные"
    return "непримиримые"


def scale_label(value):
    value = max(0.0, min(1.0, float(value)))
    if value >= 0.82:
        return "очень высоко"
    if value >= 0.64:
        return "высоко"
    if value >= 0.46:
        return "средне"
    if value >= 0.28:
        return "низко"
    return "почти нет"


def magnitude_word(value):
    value = abs(float(value))
    if value >= 0.12:
        return "заметно"
    if value >= 0.06:
        return "умеренно"
    if value >= 0.025:
        return "слегка"
    return "едва"


def resource_label(value):
    return scale_label(value)


def skill_rank(value):
    value = max(0.0, min(1.0, float(value)))
    if value >= 0.90:
        return "легенда"
    if value >= 0.75:
        return "выдающийся"
    if value >= 0.60:
        return "мастер"
    if value >= 0.45:
        return "опытный"
    if value >= 0.30:
        return "практик"
    if value >= 0.15:
        return "подмастерье"
    return "ученик"


def skill_next_rank(value):
    value = max(0.0, min(1.0, float(value)))
    for threshold, label in (
        (0.15, "подмастерье"),
        (0.30, "практик"),
        (0.45, "опытный"),
        (0.60, "мастер"),
        (0.75, "выдающийся"),
        (0.90, "легенда"),
    ):
        if value < threshold:
            return label
    return ""


def _direction(value, positive, negative):
    return positive if float(value) >= 0.0 else negative


def _effect_subject(section, character_name=""):
    if section == "player":
        return "вы"
    if section == "node":
        return "ваша структура"
    if section == "target":
        return "цель"
    if section == "character":
        return character_name or "собеседник"
    return ""


def _effect_stat_label(key, stat_labels, character_name=""):
    if key in CHARACTER_STAT_LABELS:
        return CHARACTER_STAT_LABELS[key]
    return (stat_labels or {}).get(key, key)


def format_effect_map(effects, stat_labels=None, character_name=""):
    effects = effects or {}
    lines = []
    sections = [
        (section, effects.get(section) or {})
        for section in ("character", "player", "node", "target")
    ]
    flat_character = {
        key: effects[key] for key in CHARACTER_STAT_LABELS if key in effects
    }
    if flat_character:
        sections.insert(0, ("character", flat_character))
    for section, values in sections:
        for key, value in values.items():
            amount = float(value)
            if abs(amount) < 1e-9:
                continue
            subject = _effect_subject(section, character_name)
            stat = _effect_stat_label(key, stat_labels, character_name)
            word = magnitude_word(amount)
            if key in CHARACTER_STAT_LABELS:
                vibe = _direction(
                    amount,
                    "%s улучшится" % word,
                    "%s ухудшится" % word,
                )
            else:
                vibe = _direction(
                    amount,
                    "%s усилится" % word,
                    "%s ослабнет" % word,
                )
            lines.append("%s: %s %s" % (subject, stat, vibe))
    relation = float(effects.get("relation") or 0.0)
    if abs(relation) >= 1e-9:
        word = magnitude_word(relation)
        direction = _direction(
            relation, "%s улучшатся" % word, "%s ухудшатся" % word
        )
        lines.append("отношения %s" % direction)
    node_relation = float(effects.get("node_relation") or 0.0)
    if abs(node_relation) >= 1e-9:
        word = magnitude_word(node_relation)
        direction = _direction(
            node_relation,
            "%s улучшатся" % word,
            "%s ухудшатся" % word,
        )
        lines.append("отношения со структурой %s" % direction)
    return lines


def summarize_changes(changes):
    groups = {}
    for label, value in changes or ():
        amount = float(value)
        if abs(amount) < 1e-9:
            continue
        direction = "рост" if amount > 0 else "спад"
        word = magnitude_word(amount)
        groups.setdefault((direction, word), []).append(str(label))
    if not groups:
        return ""
    order = {
        ("рост", "заметно"): 0,
        ("рост", "умеренно"): 1,
        ("рост", "слегка"): 2,
        ("рост", "едва"): 3,
        ("спад", "едва"): 4,
        ("спад", "слегка"): 5,
        ("спад", "умеренно"): 6,
        ("спад", "заметно"): 7,
    }
    parts = []
    for key in sorted(groups, key=lambda item: order.get(item, 99)):
        direction, word = key
        verb = "выросло" if direction == "рост" else "просело"
        parts.append(
            "%s %s: %s" % (word.capitalize(), verb, ", ".join(groups[key]))
        )
    return ". ".join(parts)


def cost_summary(action, stat_labels=None):
    cost = (action or {}).get("cost") or {}
    labels = stat_labels or {}
    parts = []
    for key in cost.get("player") or {}:
        parts.append(labels.get(key, key))
    if cost.get("node"):
        parts.append("ресурсы структуры")
    if not parts:
        return "без прямой платы"
    return "плата: %s" % ", ".join(parts)


def reason_text(reason):
    text = str(reason or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s*не ниже\s*\d+(?:[.,]\d+)?%", "", text)
    text = re.sub(r"\s*:\s*нужно\s*\d+(?:[.,]\d+)?%", "", text)
    text = re.sub(r"\s*\(?\d+(?:[.,]\d+)?%\)?", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" .;:")
    return text[:1].upper() + text[1:] if text else ""


def signed_quality(value):
    amount = float(value)
    if amount > 0:
        return "%s лучше" % magnitude_word(amount)
    if amount < 0:
        return "%s хуже" % magnitude_word(amount)
    return "без перемен"
