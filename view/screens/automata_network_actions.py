"""Применение взаимодействий, конец хода и исход сюжета."""

from __future__ import annotations

from .automata_network_support import (
    delta_phrase,
    logger,
)


class AutomataNetworkActionsMixin:

    def _apply_result(self, result):
        self._sync_storyline()
        if not result or not result.get("ok"):
            self.message = (
                result.get("reason") if result else "Действие не выполнено."
            )
            return result
        self.message = ""
        self.last_result = result
        if result.get("started"):
            slots = result.get("slots") or self.campaign.slot_state(
                self.campaign.player_side
            )
            self.message = (
                "%s: начато · %s · слоты %d/%d"
                % (
                    result.get("label", "действие"),
                    self.campaign.duration_label(
                        float(result.get("duration", 0.0))
                    ),
                    slots.get("used", 0),
                    slots.get("slots", self.campaign.action_slots),
                )
            )
            return result
        if result.get("kind") == "automaton" or "source_organ_id" in result:
            self.message = "%s -> %s: %s; %s" % (
                result.get("source_organ_name", "автомат"),
                result.get("target_organ_name", "цель"),
                result.get("label", "команда"),
                delta_phrase(
                    "целостность",
                    result.get("target_integrity_before", 0.0),
                    result.get("target_integrity_after", 0.0),
                ),
            )
        elif result.get("kind") == "character" or "character_name" in result:
            self.message = "%s: %s; %s" % (
                result.get("character_name", "персонаж"),
                result.get("label", "действие"),
                delta_phrase(
                    "мораль",
                    result.get("morale_before", 0.0),
                    result.get("morale_after", 0.0),
                    scale=100.0,
                ),
            )
        else:
            self.message = "%s: %s" % (
                result.get("label", "взаимодействие"),
                delta_phrase(
                    "целостность",
                    result.get("integrity_before", 0.0),
                    result.get("integrity_after", 0.0),
                ),
            )
        slots = self.campaign.slot_state(self.campaign.player_side)
        logger.debug(
            "Сеть: %s; мораль %s→%s; целостность %s→%s; "
            "слоты %d/%d",
            result.get("label", "?"),
            result.get("morale_before"),
            result.get("morale_after"),
            result.get("integrity_before"),
            result.get("integrity_after"),
            slots["used"],
            slots["slots"],
        )
        if self.campaign.finished:
            self._check_storyline_outcome()
        return result

    def apply_interaction(self):
        organ = self._organ()
        if organ is None:
            self.message = "Сначала выберите орган."
            return None
        if self.selected_interaction_id is None:
            self.message = "Сначала выберите взаимодействие."
            return None
        option = self._selected_interaction()
        if option is None or not option.get("enabled"):
            self.message = (
                option.get("reason")
                if option
                else "Взаимодействие недоступно."
            )
            return None
        if self.campaign.finished:
            self.message = "Кампания уже завершена."
            return None
        self.campaign.ensure_clock()
        result = self.campaign.perform_organ_interaction(
            self.campaign.player_side,
            organ.id,
            self.selected_interaction_id,
        )
        result = dict(result)
        result["kind"] = "organ"
        self.selected_interaction_id = None
        slots = self.campaign.slot_state(self.campaign.player_side)
        logger.info(
            "Сеть: %s → %s; цикл %d; слоты %d/%d",
            result.get("organ_name", organ.name),
            result.get("interaction_id", "?"),
            self.campaign.turn,
            slots["used"],
            slots["slots"],
        )
        return self._apply_result(result)

    def apply_automaton_interaction(self):
        organ = self._organ()
        if organ is None:
            self.message = "Сначала выберите автомат-источник."
            return None
        if self.selected_automaton_interaction_id is None:
            self.message = "Сначала выберите команду автомата."
            return None
        if self.selected_automaton_target_id is None:
            self.message = "Выберите автомат-цель в графе."
            return None
        option = self._selected_automaton_interaction()
        if option is None or not option.get("enabled"):
            self.message = (
                option.get("reason")
                if option
                else "Команда недоступна."
            )
            return None
        if self.campaign.finished:
            self.message = "Кампания уже завершена."
            return None
        self.campaign.ensure_clock()
        result = self.campaign.perform_automaton_interaction(
            self.campaign.player_side,
            organ.id,
            self.selected_automaton_target_id,
            self.selected_automaton_interaction_id,
        )
        result = dict(result)
        result["kind"] = "automaton"
        self.selected_automaton_interaction_id = None
        self.selected_automaton_target_id = None
        slots = self.campaign.slot_state(self.campaign.player_side)
        logger.info(
            "Сеть: автомат %s → %s (%s); цикл %d; слоты %d/%d",
            result.get("source_organ_name", organ.name),
            result.get("target_organ_name", "цель"),
            result.get("interaction_id", "?"),
            self.campaign.turn,
            slots["used"],
            slots["slots"],
        )
        return self._apply_result(result)

    def apply_character_interaction(self):
        character = self._character()
        if character is None:
            self.message = "Сначала выберите персонажа."
            return None
        if self.selected_character_interaction_id is None:
            self.message = "Сначала выберите действие."
            return None
        option = self._selected_character_interaction()
        if option is None or not option.get("enabled"):
            self.message = (
                option.get("reason")
                if option
                else "Действие недоступно."
            )
            return None
        if self.campaign.finished:
            self.message = "Кампания уже завершена."
            return None
        self.campaign.ensure_clock()
        result = self.campaign.perform_character_interaction(
            self.campaign.player_side,
            self.selected_character_id,
            self.selected_character_interaction_id,
        )
        result = dict(result)
        result["kind"] = "character"
        self.selected_character_interaction_id = None
        slots = self.campaign.slot_state(self.campaign.player_side)
        logger.info(
            "Сеть: персонаж %s → %s; цикл %d; слоты %d/%d",
            result.get("character_name", self.selected_character_id),
            result.get("interaction_id", "?"),
            self.campaign.turn,
            slots["used"],
            slots["slots"],
        )
        return self._apply_result(result)

    def apply_current(self):
        if self.mode == "characters":
            return self.apply_character_interaction()
        if self.mode == "automata":
            return self.apply_automaton_interaction()
        return self.apply_interaction()

    def end_turn(self):
        """Legacy: завершить цикл и вернуть часы без остановки времени."""
        if self.campaign.finished:
            return None
        self.campaign.end_turn()
        if self.campaign.finished:
            self.message = "Кампания завершена."
            self._check_storyline_outcome()
            self._sync_storyline()
            return None
        self.campaign.begin_turn()
        self.last_result = None
        self.selected_interaction_id = None
        self.selected_automaton_interaction_id = None
        self.selected_automaton_target_id = None
        self.selected_character_interaction_id = None
        slots = self.campaign.slot_state(self.campaign.player_side)
        self.message = (
            "Цикл завершён. Цикл %d; слоты %d/%d."
            % (self.campaign.turn, slots["used"], slots["slots"])
        )
        self._sync_storyline()
        logger.info(
            "Сеть: цикл завершён, цикл %d, слоты %d/%d",
            self.campaign.turn,
            slots["used"],
            slots["slots"],
        )
        return None

    def _check_storyline_outcome(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None or self.campaign.outcome is None:
            return
        if interp.check_lose_conditions():
            self.app.finish_storyline_outcome("lose")
        elif interp.check_win_conditions():
            self.app.finish_storyline_outcome("win")
