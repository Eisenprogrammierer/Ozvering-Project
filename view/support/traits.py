"""Модификаторы отчётов. В UI-каркасе личностная черта — необязательный
бонус сюжета; при отсутствии данных возвращается нейтральное значение.
"""


def get_report_noise_modifier(app):
    """Множитель шума разведки (1.0 — нейтрально)."""
    interp = getattr(app, "storyline_interpreter", None)
    if interp is None:
        return 1.0
    variables = getattr(interp, "variables", {}) or {}
    trait = variables.get("trait")
    return {
        "observant": 0.75,
        "cautious": 0.9,
        "impulsive": 1.2,
        "reckless": 1.35,
    }.get(trait, 1.0)
