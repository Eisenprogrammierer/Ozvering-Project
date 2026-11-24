"""Выбор фракции, органа, взаимодействия и персонажа."""

from __future__ import annotations

from .automata_network_support import (
    logger,
)


class AutomataNetworkSelectionMixin:

    def select_faction(self, side):
        """Выбрать можно только свою фракцию."""
        if str(side) != self.campaign.player_side:
            self.message = (
                "В режиме сети можно влиять только на свою фракцию."
            )
            logger.info("Сеть: отклонена чужая фракция %s", side)
            return False
        faction = self._faction()
        if faction is None:
            return False
        self.selected_faction_side = faction.side
        self.selected_organ_id = self._default_organ_id(faction)
        self.selected_interaction_id = None
        self.selected_automaton_interaction_id = None
        self.selected_automaton_target_id = None
        self.message = ""
        self.last_result = None
        return True

    def select_organ(self, organ_id, mode=None):
        faction = self._faction()
        if faction is None or faction.organ(organ_id) is None:
            self.message = "Этот орган не принадлежит вашей фракции."
            return False
        if mode in ("automata", "organs", "characters"):
            self.mode = mode
        elif self.mode != "characters":
            self.mode = "organs"
        self.selected_organ_id = str(organ_id)
        self.selected_interaction_id = None
        self.selected_automaton_interaction_id = None
        self.selected_automaton_target_id = None
        self._sync_character_selection()
        self.message = ""
        return True

    def select_interaction(self, interaction_id):
        option = next(
            (
                item
                for item in self._interaction_options()
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return False
        self.selected_interaction_id = option["id"]
        self.message = ""
        return True

    def select_automaton_interaction(self, interaction_id):
        option = next(
            (
                item
                for item in self._automaton_interaction_options()
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return False
        if self.selected_automaton_interaction_id == option["id"]:
            self.selected_automaton_interaction_id = None
            self.selected_automaton_target_id = None
            self.message = ""
            return True
        self.selected_automaton_interaction_id = option["id"]
        self.selected_automaton_target_id = None
        if option.get("targets"):
            self.message = (
                "Выберите автомат-цель в графе: %s."
                % ", ".join(
                    target["name"] for target in option["targets"][:3]
                )
            )
        else:
            self.message = option.get("reason") or "Нет доступных целей."
        return True

    def select_automaton_target(self, target_id):
        option = self._selected_automaton_interaction()
        if option is None:
            self.message = "Сначала выберите команду автомата."
            return False
        target = next(
            (
                item
                for item in option.get("targets", ())
                if item["id"] == str(target_id)
            ),
            None,
        )
        if target is None:
            self.message = "Эта цель не подходит для выбранной команды."
            return False
        self.selected_automaton_target_id = target["id"]
        self.message = "Цель: %s. Нажмите «Применить»." % target["name"]
        return True

    def select_character(self, character_id):
        character = self.campaign.character(
            self.campaign.player_side, character_id
        )
        if character is None:
            self.message = "Этот персонаж не принадлежит вашей фракции."
            return False
        organ_id = str(
            getattr(character, "campaign_organ_id", "") or ""
        )
        if (
            self.selected_organ_id
            and organ_id
            and organ_id != str(self.selected_organ_id)
        ):
            self.message = (
                "Этот персонаж не входит в персонал выбранного автомата."
            )
            return False
        self.mode = "characters"
        self.selected_character_id = str(character_id)
        self.selected_character_interaction_id = None
        self.message = ""
        return True

    def select_character_interaction(self, interaction_id):
        option = next(
            (
                item
                for item in self._character_interaction_options()
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return False
        self.selected_character_interaction_id = option["id"]
        self.message = ""
        return True

    def _slots_label(self):
        slots = self.campaign.slot_state(self.campaign.player_side)
        return "слоты %d/%d" % (slots["used"], slots["slots"])
