CAMP_FRESH_RATIO = 0.40
CAMP_WOUNDED_RATIO = 0.80


def camp_state_for_loss(loss_percent, loss_limit_percent):
    limit = max(1, int(loss_limit_percent))
    ratio = max(0.0, float(loss_percent)) / float(limit)
    if ratio < CAMP_FRESH_RATIO:
        return "fresh"
    if ratio <= CAMP_WOUNDED_RATIO:
        return "wounded"
    return "critical"
