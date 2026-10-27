class RuleEngine:

    @staticmethod
    def try_decision(state, unit_idx, rule, rng=None):
        state.log_event(unit_idx, "Решение штаба: %s" % (rule,))
        return True
