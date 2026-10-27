from __future__ import annotations

NEUTRAL = {
    "label": "Без черты",
    "summary": "Обычный командир без выраженной особенности.",
    "report_noise": 1.0,
    "fear_rate": 1.0,
    "anxiety_rate": 1.0,
    "fatigue_rate": 1.0,
    "health_rate": 1.0,
    "hunger_rate": 1.0,
    "thirst_rate": 1.0,
    "morale_baseline": 0.0,
    "troop_morale_per_day": 0.0,
    "supply_consumption": 1.0,
    "influence_rate": 1.0,
    "operation_cost": 1.0,
    "convoy_time": 1.0,
    "convoy_risk": 1.0,
    "action_effect": 1.0,
    "action_cost": 1.0,
    "action_cooldown": 1.0,
    "action_bonus": {},
}


TRAITS = {
    "knight": {
        "label": "Рыцарь",
        "summary": "Держит слово и берёт удар на себя: выше мораль, "
        "страх растёт медленнее, люди спокойнее.",
        "fear_rate": 0.78,
        "anxiety_rate": 0.88,
        "morale_baseline": 8.0,
        "troop_morale_per_day": 3.0,
        "influence_rate": 1.05,
        "convoy_risk": 0.95,
        "action_bonus": {"encourage": 1.20, "pray": 1.10},
    },
    "general_scholar": {
        "label": "Генерал-учёный",
        "summary": "Планирует снабжение и обучение: дешевле операции, "
        "быстрее конвои, сильнее учёба.",
        "anxiety_rate": 0.84,
        "report_noise": 0.75,
        "operation_cost": 0.80,
        "convoy_time": 0.78,
        "convoy_risk": 0.85,
        "action_bonus": {"train": 1.30, "medical": 1.10},
    },
    "freeloader": {
        "label": "Халявщик",
        "summary": "Ищет тёплое место: больше расход запасов, слабее "
        "личные действия и ниже мораль войск.",
        "morale_baseline": -5.0,
        "troop_morale_per_day": -3.0,
        "supply_consumption": 1.20,
        "influence_rate": 0.75,
        "operation_cost": 1.15,
        "convoy_time": 1.15,
        "convoy_risk": 1.15,
        "action_effect": 0.85,
        "action_cost": 1.15,
        "action_cooldown": 1.15,
    },
    "mercenary": {
        "label": "Наёмник",
        "summary": "Война — работа: больше влияния и дешевле операции, "
        "но люди держатся за плату, а не за идею.",
        "morale_baseline": -2.0,
        "troop_morale_per_day": -1.0,
        "influence_rate": 1.30,
        "operation_cost": 0.90,
        "convoy_time": 1.05,
        "supply_consumption": 1.05,
        "action_bonus": {"letters": 0.90},
    },
    "pretty_eyes": {
        "label": "Красивые глазки",
        "summary": "Связи и обаяние: больше влияния, легче достать "
        "конвой, чуть выше мораль.",
        "morale_baseline": 2.0,
        "influence_rate": 1.15,
        "convoy_time": 0.95,
        "convoy_risk": 0.95,
        "action_bonus": {"socialize": 1.15, "encourage": 1.10},
    },
    "truth_teller": {
        "label": "Правдоруб",
        "summary": "Честность сплачивает людей, но штаб не любит "
        "неудобных докладов: выше мораль, меньше влияния.",
        "morale_baseline": 4.0,
        "fear_rate": 0.90,
        "troop_morale_per_day": 1.0,
        "influence_rate": 0.90,
        "action_bonus": {"encourage": 1.10},
    },
    "careerist": {
        "label": "Кадровик",
        "summary": "Работает по регламенту: дешевле операции, быстрее "
        "бумаги, но люди чувствуют расчёт.",
        "operation_cost": 0.90,
        "convoy_time": 0.95,
        "influence_rate": 1.05,
        "action_bonus": {"train": 1.10, "letters": 0.95},
    },
    "reservist": {
        "label": "Резервист",
        "summary": "Не отвык от службы, но бережёт силы: меньше усталости, "
        "слабее эффект личных действий.",
        "fatigue_rate": 0.90,
        "morale_baseline": -2.0,
        "supply_consumption": 1.10,
        "action_effect": 0.90,
    },
}


def normalize_trait(trait):
    key = str(trait or "").strip()
    return key if key in TRAITS else None


def trait_label(trait):
    key = normalize_trait(trait)
    if key is None:
        return NEUTRAL["label"]
    return TRAITS[key]["label"]


def trait_summary(trait):
    key = normalize_trait(trait)
    if key is None:
        return NEUTRAL["summary"]
    return TRAITS[key].get("summary", NEUTRAL["summary"])


def trait_modifiers(trait):
    key = normalize_trait(trait)
    result = dict(NEUTRAL)
    result["action_bonus"] = dict(NEUTRAL["action_bonus"])
    if key is None:
        return result
    data = TRAITS[key]
    for field, value in data.items():
        if field == "action_bonus":
            merged = dict(result["action_bonus"])
            merged.update(value or {})
            result["action_bonus"] = merged
        elif field in result:
            result[field] = value
    result["key"] = key
    return result


def get_report_noise_modifier(app):
    interp = getattr(app, "storyline_interpreter", None)
    if interp is None:
        return 1.0
    variables = getattr(interp, "variables", {}) or {}
    trait = variables.get("trait")
    return float(trait_modifiers(trait).get("report_noise", 1.0))
