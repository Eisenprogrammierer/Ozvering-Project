"""Декларативные эффекты приказов и решений.

Поддерживаются поля ``targets`` (``player`` или entity id), ``add_voltages``,
``set_segments`` и ``log``. Эффекты применяются к адаптеру ``CampaignState``,
который переводит их в приказы/состояние отделений нового войскового слоя.
"""

from .log_journal import get_logger

logger = get_logger("view.effects")


class EffectInterpreter:
    """Применить декларативный эффект к кампании."""

    @staticmethod
    def _resolve_targets(state, targets):
        if not targets:
            return [state.player_idx]
        out = []
        for target in targets:
            if target == "player":
                out.extend(
                    i for i in range(state.count)
                    if state.factions[i] == "player"
                )
                continue
            try:
                idx = state.entity_ids.index(target)
            except ValueError:
                continue
            out.append(idx)
        return sorted(set(out))

    @classmethod
    def apply(cls, state, effect):
        if not effect or state is None:
            return False
        applied = True
        for idx in cls._resolve_targets(state, effect.get("targets")):
            for segment, value in (effect.get("set_segments") or {}).items():
                state.set_segment(idx, segment, value)
            for channel, delta in (effect.get("add_voltages") or {}).items():
                state.add_voltage(idx, channel, float(delta))
        text = effect.get("log")
        if text:
            state.log_event(state.player_idx, text)
            logger.info("Эффект: %s", text)
        return applied
