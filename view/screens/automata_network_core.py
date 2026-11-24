"""Состояние экрана, фракции, органы, персонажи и раскладка."""

from __future__ import annotations

from .automata_network_support import (
    CHARACTER_ROW_H,
    CHARACTER_VISIBLE,
    GRAPH_RECT,
    INTERACTION_ROW_H,
    NODE_GAP_Y,
    NODE_H,
    NODE_W,
    SIDE_RECT,
    math,
    organ_degrees,
    organ_links,
    pygame,
)


class AutomataNetworkCoreMixin:

    def _faction(self):
        return self.campaign.faction(self.campaign.player_side)

    def _organs(self):
        faction = self._faction()
        return list(faction.organs) if faction is not None else []

    def _organ(self):
        faction = self._faction()
        if faction is None or self.selected_organ_id is None:
            return None
        return faction.organ(self.selected_organ_id)

    def _default_organ_id(self, faction):
        if faction is None or not faction.organs:
            return None
        degrees = organ_degrees(faction.organs)
        ordered = sorted(
            faction.organs,
            key=lambda item: (
                -degrees.get(item.id, 0),
                item.name,
                item.id,
            ),
        )
        return ordered[0].id

    def _all_characters(self):
        return self.campaign.character_options(self.campaign.player_side)

    def _characters(self):
        """Персонал выбранного автомата, а не вся фракция.

        Игрок выбирает киберотдел — видит сотрудников киберотдела.
        Если у органа никого нет, список пуст, и экран честно пишет
        «Персонал недоступен», а не подсовывает людей из других узлов.
        """
        characters = self._all_characters()
        organ_id = str(self.selected_organ_id or "")
        if not organ_id:
            return characters
        return [
            item
            for item in characters
            if str(item.get("organ_id") or "") == organ_id
        ]

    def _sync_character_selection(self):
        characters = self._characters()
        ids = {str(item.get("id")) for item in characters}
        if str(self.selected_character_id or "") not in ids:
            self.selected_character_id = (
                characters[0]["id"] if characters else None
            )
            self.selected_character_interaction_id = None
        self.character_scroll = 0
        return self.selected_character_id

    def _character(self):
        if self.selected_character_id is None:
            return None
        return self.campaign.character(
            self.campaign.player_side, self.selected_character_id
        )

    def _character_snapshot(self):
        character = self._character()
        if character is None:
            return None
        return self._faction().character_snapshot(character)

    def _interaction_options(self):
        organ = self._organ()
        if organ is None:
            return []
        return self.campaign.organ_interaction_options(
            self.campaign.player_side, organ.id
        )

    def _character_interaction_options(self):
        if self.selected_character_id is None:
            return []
        return self.campaign.character_interaction_options(
            self.campaign.player_side, self.selected_character_id
        )

    def _selected_interaction(self):
        if self.selected_interaction_id is None:
            return None
        return next(
            (
                item
                for item in self._interaction_options()
                if item["id"] == self.selected_interaction_id
            ),
            None,
        )

    def _automaton_interaction_options(self):
        organ = self._organ()
        if organ is None:
            return []
        return self.campaign.automaton_interaction_options(
            self.campaign.player_side, organ.id
        )

    def _selected_automaton_interaction(self):
        if self.selected_automaton_interaction_id is None:
            return None
        return next(
            (
                item
                for item in self._automaton_interaction_options()
                if item["id"] == self.selected_automaton_interaction_id
            ),
            None,
        )

    def _selected_automaton_target(self):
        if self.selected_automaton_target_id is None:
            return None
        option = self._selected_automaton_interaction()
        if option is None:
            return None
        return next(
            (
                target
                for target in option.get("targets", ())
                if target["id"] == self.selected_automaton_target_id
            ),
            None,
        )

    def _automaton_target_ids(self):
        option = self._selected_automaton_interaction()
        if option is None or self.mode != "automata":
            return set()
        return {target["id"] for target in option.get("targets", ())}

    def _selected_character_interaction(self):
        if self.selected_character_interaction_id is None:
            return None
        return next(
            (
                item
                for item in self._character_interaction_options()
                if item["id"] == self.selected_character_interaction_id
            ),
            None,
        )

    def _path_ids(self):
        """Выбранный узел и его соседи по сети — для подсветки связей."""
        organ = self._organ()
        if organ is None:
            return set()
        links = organ_links(self._organs())
        return {organ.id, *links.get(organ.id, ())}

    def _sync_storyline(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return
        snapshot = self.campaign.snapshot()
        interp.state["automata"] = snapshot
        interp.set_variable("automata_elapsed", snapshot["elapsed"])
        interp.set_variable("automata_speed", snapshot["speed"])

    def update(self, dt):
        """Реальное время не останавливается при открытой сети."""
        if self.campaign.finished:
            return
        before = self.campaign.turn
        self.campaign.advance_realtime(dt, snapshot=False)
        self._report_finished_process()
        if self.campaign.turn != before or self.campaign.finished:
            self._sync_storyline()
        if self.campaign.finished:
            self._check_storyline_outcome()

    def _report_finished_process(self):
        """Показать итог влияния, когда слот освободился."""
        record = self.campaign.last_process_result
        if not record:
            return
        process_id = str(record.get("id") or "")
        if not process_id or process_id == self._seen_process_result:
            return
        self._seen_process_result = process_id
        if str(record.get("side")) != self.campaign.player_side:
            return
        result = record.get("result") or {}
        if not result:
            return
        label = result.get("label") or record.get("label") or "действие"
        self.message = "%s: завершено · %s" % (
            label,
            self._slots_label(),
        )
        self.last_result = result

    def _increase_speed(self):
        if self.campaign.finished:
            return
        before = self.campaign.speed
        self.campaign.speed_up()
        if self.campaign.speed != before:
            self.message = (
                "Скорость времени: %s."
                % self.campaign.speed_label()
            )
        else:
            self.message = (
                "Достигнута максимальная скорость: %s."
                % self.campaign.speed_label()
            )

    def _decrease_speed(self):
        """Отменить одно ускорение, но не опускаться ниже ``1×``."""
        if self.campaign.finished:
            return
        before = self.campaign.speed
        self.campaign.slow_down()
        if self.campaign.speed != before:
            self.message = (
                "Ускорение отменено: скорость %s."
                % self.campaign.speed_label()
            )
        else:
            self.message = (
                "Минимальная скорость: %s." % self.campaign.speed_label()
            )

    def _layout(self):
        """Разложить органы сеткой, а не колонками иерархии."""
        self._organ_rects = {}
        self._faction_rect = None
        faction = self._faction()
        if faction is None:
            return
        self._faction_rect = pygame.Rect(
            GRAPH_RECT.x + 14,
            GRAPH_RECT.y + 30,
            190,
            40,
        )
        organs = sorted(
            faction.organs,
            key=lambda item: (item.kind, item.name, item.id),
        )
        if not organs:
            return
        count = len(organs)
        available_w = GRAPH_RECT.width - 32
        available_h = GRAPH_RECT.bottom - 12 - (GRAPH_RECT.y + 82)
        target_ratio = available_w / float(max(1, available_h))
        best_columns = 1
        best_score = None
        for columns in range(1, count + 1):
            if columns * NODE_W > available_w and columns > 1:
                continue
            rows = int(math.ceil(count / float(columns)))
            block_w = columns * NODE_W
            block_h = rows * NODE_H
            score = abs(
                (block_w / float(max(1, block_h))) - target_ratio
            )
            if best_score is None or score < best_score:
                best_score = score
                best_columns = columns
        columns = max(1, best_columns)
        rows = int(math.ceil(count / float(columns)))
        gap_x = min(
            42,
            max(
                12,
                (available_w - columns * NODE_W)
                // max(1, columns - 1),
            ),
        )
        gap_y = min(
            NODE_GAP_Y + 30,
            max(
                NODE_GAP_Y,
                (available_h - rows * NODE_H) // max(1, rows - 1),
            ),
        )
        total_w = columns * NODE_W + (columns - 1) * gap_x
        total_h = rows * NODE_H + (rows - 1) * gap_y
        start_x = GRAPH_RECT.x + (GRAPH_RECT.width - total_w) // 2
        top = GRAPH_RECT.y + 82
        start_y = top + max(0, (available_h - total_h) // 2)
        for index, organ in enumerate(organs):
            row, column = divmod(index, columns)
            self._organ_rects[organ.id] = pygame.Rect(
                start_x + column * (NODE_W + gap_x),
                start_y + row * (NODE_H + gap_y),
                NODE_W,
                NODE_H,
            )

    def organ_rect(self, organ_id):
        if not self._organ_rects:
            self._layout()
        return self._organ_rects.get(str(organ_id))

    def _interaction_rows(self):
        if self.mode == "characters":
            interaction_top = SIDE_RECT.y + 244
            options = self._character_interaction_options()[:4]
        elif self.mode == "automata":
            interaction_top = SIDE_RECT.y + 104
            options = self._automaton_interaction_options()[:4]
        else:
            interaction_top = SIDE_RECT.y + 104
            options = self._interaction_options()[:4]
        rows = []
        for index, option in enumerate(options):
            rect = pygame.Rect(
                SIDE_RECT.x + 14,
                interaction_top + index * INTERACTION_ROW_H,
                SIDE_RECT.width - 28,
                INTERACTION_ROW_H - 6,
            )
            rows.append((rect, option))
        return rows

    def _character_rows(self):
        characters = self._characters()
        visible = characters[
            self.character_scroll : self.character_scroll + CHARACTER_VISIBLE
        ]
        rows = []
        top = SIDE_RECT.y + 104
        for index, character in enumerate(visible):
            rect = pygame.Rect(
                SIDE_RECT.x + 14,
                top + index * CHARACTER_ROW_H,
                SIDE_RECT.width - 28,
                CHARACTER_ROW_H - 2,
            )
            rows.append((rect, character))
        return rows
