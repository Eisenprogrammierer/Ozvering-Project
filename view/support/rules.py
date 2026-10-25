"""Минимальные правила решений для UI-каркаса.

Легаси-``RuleEngine`` менял битовые маски и метаморфозы мира. Здесь решения
интерфейса применяются через ``EffectInterpreter``; правило оставлено как
совместимый no-op, чтобы экран последствий работал без легаси-ядра.
"""


class RuleEngine:
    """Совместимый фасад: правила UI не меняют математическое ядро."""

    @staticmethod
    def try_decision(state, unit_idx, rule, rng=None):
        state.log_event(unit_idx, "Решение штаба: %s" % (rule,))
        return True
