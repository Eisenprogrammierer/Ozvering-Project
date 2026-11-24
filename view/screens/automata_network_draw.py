"""Отрисовка графа, деталей, списков и кнопок."""

from __future__ import annotations

from .automata_network_support import (
    ACCENT,
    BOTTOM_RECT,
    CHARACTER_ROW_H,
    CHARACTER_VISIBLE,
    DETAIL_RECT,
    DIM,
    EDGE,
    GOOD,
    GRAPH_RECT,
    HEIGHT,
    KIND_LABELS,
    MUTED,
    NEED_LABELS,
    PANEL_BORDER,
    PATH_EDGE,
    SIDE_RECT,
    TEXT,
    TRAIT_LABELS,
    WARN,
    WIDTH,
    _draw_bar,
    _integrity_color,
    _integrity_word,
    _money,
    _panel,
    draw_portrait,
    effect_phrase,
    fit_line,
    metric_phrase,
    organ_degrees,
    organ_links,
    pygame,
    wrap_text,
)


class AutomataNetworkDrawMixin:

    def _draw_edge(self, screen, start, end, color, width):
        middle_x = (start[0] + end[0]) // 2
        pygame.draw.lines(
            screen,
            color,
            False,
            [start, (middle_x, start[1]), (middle_x, end[1]), end],
            width,
        )

    def _draw_graph(self, screen):
        _panel(screen, GRAPH_RECT)
        screen.blit(
            self.app.font_small.render(
                "СЕТЬ АВТОМАТОВ · ТОЛЬКО ВАША ФРАКЦИЯ", True, MUTED
            ),
            (GRAPH_RECT.x + 14, GRAPH_RECT.y + 12),
        )
        if self.mode == "automata" and self._selected_automaton_interaction():
            hint = "ВЫБЕРИТЕ АВТОМАТ-ЦЕЛЬ В ГРАФЕ"
            surf = self.app.font_tiny.render(hint, True, WARN)
            screen.blit(
                surf,
                (
                    GRAPH_RECT.right - surf.get_width() - 14,
                    GRAPH_RECT.y + 14,
                ),
            )
        faction = self._faction()
        if faction is None or self._faction_rect is None:
            return
        links = organ_links(faction.organs)
        degrees = organ_degrees(faction.organs)
        path = self._path_ids()
        target_ids = self._automaton_target_ids()

        drawn = set()
        for organ_id, neighbors in links.items():
            for neighbor in neighbors:
                edge = tuple(sorted((str(organ_id), str(neighbor))))
                if edge in drawn:
                    continue
                drawn.add(edge)
                source = self._organ_rects.get(edge[0])
                target = self._organ_rects.get(edge[1])
                if source is None or target is None:
                    continue
                highlighted = edge[0] in path and edge[1] in path
                self._draw_edge(
                    screen,
                    (source.centerx, source.centery),
                    (target.centerx, target.centery),
                    PATH_EDGE if highlighted else EDGE,
                    3 if highlighted else 1,
                )

        pygame.draw.rect(
            screen, (34, 48, 68), self._faction_rect, border_radius=8
        )
        pygame.draw.rect(
            screen, ACCENT, self._faction_rect, 2, border_radius=8
        )
        for line_number, line in enumerate(
            wrap_text(
                self.app.font_small,
                faction.name,
                self._faction_rect.width - 14,
            )[:1]
        ):
            screen.blit(
                self.app.font_small.render(line, True, TEXT),
                (
                    self._faction_rect.x + 7,
                    self._faction_rect.y + 4 + line_number * 18,
                ),
            )
        screen.blit(
            self.app.font_tiny.render(
                "фракция · узлов %d · связей %d"
                % (len(faction.organs), len(drawn)),
                True,
                ACCENT,
            ),
            (
                self._faction_rect.x + 7,
                self._faction_rect.bottom - 17,
            ),
        )

        for organ in faction.organs:
            rect = self._organ_rects.get(organ.id)
            if rect is None:
                continue
            selected = organ.id == self.selected_organ_id
            on_path = organ.id in path
            is_target = organ.id == self.selected_automaton_target_id
            is_candidate = organ.id in target_ids
            fill = (34, 48, 68) if selected else (
                (27, 38, 54) if on_path else (22, 28, 40)
            )
            pygame.draw.rect(screen, fill, rect, border_radius=6)
            if is_target:
                border_color = GOOD
                border_width = 3
            elif is_candidate:
                border_color = WARN
                border_width = 2
            else:
                border_color = ACCENT if selected else (
                    (84, 118, 158) if on_path else PANEL_BORDER
                )
                border_width = 2
            pygame.draw.rect(
                screen,
                border_color,
                rect,
                border_width,
                border_radius=6,
            )
            for line_number, line in enumerate(
                wrap_text(
                    self.app.font_tiny,
                    organ.name,
                    rect.width - 30,
                )[:2]
            ):
                screen.blit(
                    self.app.font_tiny.render(
                        line, True, TEXT if selected else MUTED
                    ),
                    (rect.x + 6, rect.y + 4 + line_number * 11),
                )
            bar = pygame.Rect(
                rect.x + 6, rect.bottom - 10, rect.width - 36, 6
            )
            _draw_bar(
                screen,
                bar,
                organ.integrity,
                _integrity_color(organ.integrity),
            )
            screen.blit(
                self.app.font_tiny.render(
                    _integrity_word(organ.integrity), True, DIM
                ),
                (rect.right - 58, rect.bottom - 25),
            )
            screen.blit(
                self.app.font_tiny.render(
                    "·%d" % degrees.get(organ.id, 0), True, DIM
                ),
                (rect.right - 18, rect.y + 3),
            )

    def _draw_detail(self, screen):
        _panel(screen, DETAIL_RECT)
        if self.mode == "characters":
            self._draw_character_detail(screen)
            return
        organ = self._organ()
        if organ is None:
            screen.blit(
                self.app.font_small.render(
                    "ОРГАН НЕ ВЫБРАН", True, MUTED
                ),
                (DETAIL_RECT.x + 16, DETAIL_RECT.y + 14),
            )
            return
        organs = {item.id: item for item in self._organs()}
        links = organ_links(self._organs())
        neighbors = [
            organs[linked].name
            for linked in links.get(organ.id, ())
            if linked in organs
        ]
        screen.blit(
            self.app.font_small.render(
                "ОРГАН · %s"
                % KIND_LABELS.get(organ.kind, organ.kind).upper(),
                True,
                MUTED,
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 10),
        )
        screen.blit(
            self.app.font_body.render(organ.name, True, TEXT),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 30),
        )
        network_text = "связи (%d): %s" % (
            len(neighbors),
            " · ".join(neighbors) if neighbors else "изолированный узел",
        )
        network_lines = wrap_text(
            self.app.font_tiny,
            network_text,
            DETAIL_RECT.width - 32,
        )
        for line_number, line in enumerate(network_lines[:2]):
            screen.blit(
                self.app.font_tiny.render(line, True, ACCENT),
                (DETAIL_RECT.x + 16, DETAIL_RECT.y + 56 + line_number * 13),
            )
        status = "%s · %s" % (
            organ.status(),
            metric_phrase("целостность", organ.integrity),
        )
        screen.blit(
            self.app.font_tiny.render(
                fit_line(
                    self.app.font_tiny, status, DETAIL_RECT.width - 32
                ),
                True,
                _integrity_color(organ.integrity),
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 88),
        )
        bar = pygame.Rect(
            DETAIL_RECT.x + 250, DETAIL_RECT.y + 90, 200, 9
        )
        _draw_bar(
            screen,
            bar,
            organ.integrity,
            _integrity_color(organ.integrity),
        )
        works_text = "Работы: " + (
            " · ".join(
                str(
                    (
                        self._faction().action(action_id)
                        if self._faction()
                        else {}
                    ).get("label")
                    or action_id
                )
                for action_id in organ.action_ids
            )
            or "нет прямых работ"
        )
        screen.blit(
            self.app.font_tiny.render(
                fit_line(
                    self.app.font_tiny,
                    works_text,
                    DETAIL_RECT.right - (DETAIL_RECT.x + 470) - 16,
                ),
                True,
                MUTED,
            ),
            (DETAIL_RECT.x + 470, DETAIL_RECT.y + 88),
        )

    def _draw_character_detail(self, screen):
        snapshot = self._character_snapshot()
        if snapshot is None:
            screen.blit(
                self.app.font_small.render(
                    "ПЕРСОНАЖ НЕ ВЫБРАН", True, MUTED
                ),
                (DETAIL_RECT.x + 16, DETAIL_RECT.y + 14),
            )
            return
        portrait = pygame.Rect(
            DETAIL_RECT.right - 70, DETAIL_RECT.y + 10, 52, 52
        )
        draw_portrait(
            screen,
            snapshot.get("portrait")
            or "characters/%s" % snapshot.get("id", ""),
            snapshot.get("name", ""),
            portrait,
        )
        screen.blit(
            self.app.font_small.render(
                "ПЕРСОНАЖ · %s"
                % (
                    "лидер фракции"
                    if snapshot.get("is_leader")
                    else snapshot.get("post") or "участник"
                ).upper(),
                True,
                MUTED,
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 10),
        )
        left_width = 260
        screen.blit(
            self.app.font_body.render(
                fit_line(self.app.font_body, snapshot["name"], left_width),
                True,
                TEXT,
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 30),
        )
        organ_id = snapshot.get("organ_id") or ""
        organ = self._faction().organ(organ_id)
        organ_text = (
            "орган: %s" % organ.name
            if organ is not None
            else "орган: не назначен"
        )
        screen.blit(
            self.app.font_tiny.render(
                fit_line(
                    self.app.font_tiny,
                    "%s · %s"
                    % (
                        snapshot.get("post") or "без должности",
                        organ_text,
                    ),
                    left_width,
                ),
                True,
                ACCENT if organ is not None else MUTED,
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 56),
        )
        morale = float(snapshot.get("morale", 0.0))
        screen.blit(
            self.app.font_tiny.render(
                metric_phrase("мораль", morale, high=100.0),
                True,
                _integrity_color(morale / 100.0),
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 76),
        )
        bar = pygame.Rect(DETAIL_RECT.x + 100, DETAIL_RECT.y + 78, 170, 9)
        _draw_bar(
            screen, bar, morale / 100.0, _integrity_color(morale / 100.0)
        )
        needs = sorted(
            snapshot.get("needs", {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
        needs_text = "потребности: " + " · ".join(
            metric_phrase(NEED_LABELS.get(key, key), value)
            for key, value in needs
        )
        traits = sorted(
            snapshot.get("personality", {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:2]
        traits_text = "черты: " + " · ".join(
            metric_phrase(TRAIT_LABELS.get(key, key), value)
            for key, value in traits
        )
        right_x = DETAIL_RECT.x + 300
        right_width = DETAIL_RECT.right - 100 - right_x
        for line_number, line in enumerate(
            wrap_text(self.app.font_tiny, needs_text, right_width)[:2]
        ):
            screen.blit(
                self.app.font_tiny.render(line, True, MUTED),
                (right_x, DETAIL_RECT.y + 12 + line_number * 13),
            )
        for line_number, line in enumerate(
            wrap_text(self.app.font_tiny, traits_text, right_width)[:2]
        ):
            screen.blit(
                self.app.font_tiny.render(line, True, DIM),
                (right_x, DETAIL_RECT.y + 44 + line_number * 13),
            )
        goal = dict(snapshot.get("goal") or {})
        agency = dict(snapshot.get("agency") or {})
        goal_label = goal.get("label") or goal.get("kind") or "нет цели"
        goal_target = goal.get("target_name") or goal.get("target") or ""
        motive = "цель: %s%s · %s · %s" % (
            goal_label,
            (" — " + goal_target) if goal_target else "",
            metric_phrase("доверие", agency.get("trust", 0.5)),
            metric_phrase("обида", agency.get("grievance", 0.0)),
        )
        motive_color = (
            WARN
            if float(agency.get("grievance", 0.0)) >= 0.35
            else MUTED
        )
        for line_number, line in enumerate(
            wrap_text(self.app.font_tiny, motive, left_width)[:2]
        ):
            screen.blit(
                self.app.font_tiny.render(line, True, motive_color),
                (DETAIL_RECT.x + 16, DETAIL_RECT.y + 94 + line_number * 13),
            )

    def _draw_tabs(self, screen):
        for rect, mode, label in (
            (self._automata_tab_rect, "automata", "АВТОМАТЫ"),
            (self._organs_tab_rect, "organs", "ВЛИЯНИЕ"),
            (self._characters_tab_rect, "characters", "ПЕРСОНАЛ"),
        ):
            selected = self.mode == mode
            pygame.draw.rect(
                screen,
                (34, 48, 68) if selected else (24, 30, 43),
                rect,
                border_radius=6,
            )
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                2,
                border_radius=6,
            )
            text = self.app.font_tiny.render(
                label, True, TEXT if selected else MUTED
            )
            screen.blit(text, text.get_rect(center=rect.center))

    def _draw_character_list(self, screen):
        characters = self._characters()
        organ = self._organ()
        header = "ПЕРСОНАЛ · %s" % (
            organ.name if organ is not None else "ВСЯ ФРАКЦИЯ"
        )
        screen.blit(
            self.app.font_tiny.render(header, True, MUTED),
            (SIDE_RECT.x + 14, SIDE_RECT.y + 82),
        )
        if not characters:
            plate = pygame.Rect(
                SIDE_RECT.x + 14,
                SIDE_RECT.y + 104,
                SIDE_RECT.width - 28,
                52,
            )
            pygame.draw.rect(screen, (28, 32, 42), plate, border_radius=6)
            pygame.draw.rect(
                screen, PANEL_BORDER, plate, 1, border_radius=6
            )
            text = self.app.font_small.render(
                "Персонал недоступен", True, WARN
            )
            screen.blit(text, text.get_rect(center=plate.center))
            hint = self.app.font_tiny.render(
                "У этого автомата нет назначенных людей.",
                True,
                DIM,
            )
            screen.blit(
                hint,
                hint.get_rect(
                    center=(plate.centerx, plate.centery + 18)
                ),
            )
            return
        for rect, character in self._character_rows():
            selected = character["id"] == self.selected_character_id
            pygame.draw.rect(
                screen,
                (34, 48, 68) if selected else (22, 28, 40),
                rect,
                border_radius=4,
            )
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                1,
                border_radius=4,
            )
            portrait_rect = pygame.Rect(
                rect.x + 4, rect.y + 3, rect.height - 6, rect.height - 6
            )
            draw_portrait(
                screen,
                character.get("portrait")
                or "characters/%s" % character.get("id", ""),
                character.get("name", ""),
                portrait_rect,
            )
            label = character["name"]
            if character.get("is_leader"):
                label += " · лидер"
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(
                        self.app.font_tiny,
                        label,
                        rect.width - 38,
                    ),
                    True,
                    TEXT if selected else MUTED,
                ),
                (rect.x + 34, rect.y + 2),
            )
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(
                        self.app.font_tiny,
                        "%s · %s"
                        % (
                            character.get("post") or "участник",
                            metric_phrase(
                                "мораль",
                                character.get("morale", 0.0),
                                high=100.0,
                            ),
                        ),
                        rect.width - 38,
                    ),
                    True,
                    DIM,
                ),
                (rect.x + 34, rect.y + 13),
            )
        if len(characters) > CHARACTER_VISIBLE:
            screen.blit(
                self.app.font_tiny.render(
                    "колесо мыши: прокрутка %d/%d"
                    % (
                        self.character_scroll + 1,
                        max(0, len(characters) - CHARACTER_VISIBLE + 1),
                    ),
                    True,
                    DIM,
                ),
                (
                    SIDE_RECT.x + 14,
                    SIDE_RECT.y + 104
                    + CHARACTER_VISIBLE * CHARACTER_ROW_H
                    - 2,
                ),
            )

    def _draw_side(self, screen):
        _panel(screen, SIDE_RECT)
        screen.blit(
            self.app.font_small.render(
                "УПРАВЛЕНИЕ СВОЕЙ СЕТЬЮ", True, MUTED
            ),
            (SIDE_RECT.x + 14, SIDE_RECT.y + 12),
        )
        screen.blit(
            self.app.font_tiny.render(
                fit_line(
                    self.app.font_tiny,
                    "%s · время %s · %s · %s"
                    % (
                        self._faction().name if self._faction() else "—",
                        self.campaign.time_label(),
                        self.campaign.speed_label(),
                        self._slots_label(),
                    ),
                    SIDE_RECT.width - 28,
                ),
                True,
                TEXT,
            ),
            (SIDE_RECT.x + 14, SIDE_RECT.y + 30),
        )
        self._draw_tabs(screen)
        if self.mode == "characters":
            self._draw_character_list(screen)
        else:
            organ = self._organ()
            screen.blit(
                self.app.font_tiny.render(
                    organ.name if organ else "Выберите орган в графе.",
                    True,
                    TEXT,
                ),
                (SIDE_RECT.x + 14, SIDE_RECT.y + 82),
            )
        rows = self._interaction_rows()
        if not rows:
            screen.blit(
                self.app.font_tiny.render(
                    "Нет доступных действий.", True, DIM
                ),
                (
                    SIDE_RECT.x + 14,
                    SIDE_RECT.y + (244 if self.mode == "characters" else 104),
                ),
            )
        for rect, option in rows:
            if self.mode == "characters":
                selected_id = self.selected_character_interaction_id
            elif self.mode == "automata":
                selected_id = self.selected_automaton_interaction_id
            else:
                selected_id = self.selected_interaction_id
            selected = option["id"] == selected_id
            enabled = bool(option.get("enabled"))
            pygame.draw.rect(
                screen,
                (34, 48, 68) if selected else (24, 30, 43),
                rect,
                border_radius=6,
            )
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                2,
                border_radius=6,
            )
            screen.blit(
                self.app.font_small.render(
                    fit_line(
                        self.app.font_small,
                        option["label"],
                        rect.width - 16,
                    ),
                    True,
                    TEXT if enabled else DIM,
                ),
                (rect.x + 8, rect.y + 3),
            )
            detail = _money(option.get("cost", {}))
            if self.mode == "characters" and option.get("morale"):
                detail += " · %s" % effect_phrase(
                    "мораль", option.get("morale", 0.0)
                )
            if self.mode == "automata":
                targets = len(option.get("targets", ()))
                detail += " · цели: %s" % (
                    "несколько" if targets > 1 else "одна"
                )
            if not enabled:
                detail += " · %s" % option.get("reason", "недоступно")
            for line_number, line in enumerate(
                wrap_text(
                    self.app.font_tiny,
                    detail,
                    rect.width - 16,
                )[:2]
            ):
                screen.blit(
                    self.app.font_tiny.render(line, True, DIM),
                    (rect.x + 8, rect.y + 21 + line_number * 12),
                )

        y = (
            rows[-1][0].bottom + 6
            if rows
            else SIDE_RECT.y + (244 if self.mode == "characters" else 104)
        )
        if self.mode == "automata":
            target = self._selected_automaton_target()
            option = self._selected_automaton_interaction()
            if target is not None:
                target_text = "Цель: %s · %s" % (
                    target["name"],
                    _integrity_word(target.get("integrity", 0.0)),
                )
                color = GOOD
            elif option is not None:
                target_text = (
                    "Цель не выбрана: нажмите автомат в графе."
                )
                color = WARN
            else:
                target_text = (
                    "Выберите команду, затем автомат-цель в графе."
                )
                color = DIM
            screen.blit(
                self.app.font_tiny.render(target_text, True, color),
                (SIDE_RECT.x + 14, y),
            )
            y += 15
        if self.message:
            for line in wrap_text(
                self.app.font_tiny, self.message, SIDE_RECT.width - 28
            )[:2]:
                screen.blit(
                    self.app.font_tiny.render(line, True, WARN),
                    (SIDE_RECT.x + 14, y),
                )
                y += 14
        if self.last_result:
            result = self.last_result
            if "source_organ_id" in result:
                text = "%s -> %s: %s" % (
                    result.get("source_organ_name", "автомат"),
                    result.get("target_organ_name", "цель"),
                    _integrity_word(
                        result.get("target_integrity_after", 0.0)
                    ),
                )
            elif "character_name" in result:
                text = "%s -> %s" % (
                    result.get("character_name", "персонаж"),
                    metric_phrase(
                        "мораль",
                        result.get("morale_after", 0.0),
                        high=100.0,
                    ),
                )
            else:
                text = "%s -> %s" % (
                    result.get("organ_name", "орган"),
                    _integrity_word(result.get("integrity_after", 0.0)),
                )
            screen.blit(
                self.app.font_tiny.render(text, True, GOOD),
                (SIDE_RECT.x + 14, y),
            )

        if self.mode == "characters":
            selected = self._selected_character_interaction()
        elif self.mode == "automata":
            selected = self._selected_automaton_interaction()
        else:
            selected = self._selected_interaction()
        if selected is not None:
            y = SIDE_RECT.bottom - 88
            for line in wrap_text(
                self.app.font_tiny,
                selected.get("description") or "",
                SIDE_RECT.width - 28,
            )[:3]:
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (SIDE_RECT.x + 14, y),
                )
                y += 13

    def _draw_bottom(self, screen):
        _panel(screen, BOTTOM_RECT)
        budget = "время %s · %s · цикл %d · %s" % (
            self.campaign.time_label(),
            self.campaign.speed_label(),
            self.campaign.turn,
            self._slots_label(),
        )
        ongoing = self.campaign.ongoing_processes(
            self.campaign.player_side
        )
        if ongoing:
            budget += " · в работе %d" % len(ongoing)
        if self.campaign.outcome:
            budget += " · исход: %s" % self.campaign.outcome
        screen.blit(
            self.app.font_tiny.render(budget, True, MUTED),
            (BOTTOM_RECT.x + 10, BOTTOM_RECT.y + 15),
        )
        pygame.draw.rect(
            screen,
            (46, 86, 138) if self.campaign.can_speed_up() else (40, 44, 56),
            self._speed_up_rect,
            border_radius=7,
        )
        pygame.draw.rect(
            screen, PANEL_BORDER, self._speed_up_rect, 2, border_radius=7
        )
        speed_text = (
            "Ускорить · %s" % self.campaign.speed_label()
            if self.campaign.can_speed_up()
            else "Максимум"
        )
        text = self.app.font_small.render(speed_text, True, TEXT)
        screen.blit(text, text.get_rect(center=self._speed_up_rect.center))
        can_slow = self.campaign.can_slow_down()
        pygame.draw.rect(
            screen,
            (46, 86, 138) if can_slow else (40, 44, 56),
            self._slow_down_rect,
            border_radius=7,
        )
        pygame.draw.rect(
            screen,
            PANEL_BORDER,
            self._slow_down_rect,
            2,
            border_radius=7,
        )
        slow_text = (
            "Медленнее · %s" % self.campaign.speed_label()
            if can_slow
            else "Минимум · %s" % self.campaign.speed_label()
        )
        text = self.app.font_small.render(
            slow_text, True, TEXT if can_slow else DIM
        )
        screen.blit(
            text, text.get_rect(center=self._slow_down_rect.center)
        )
        pygame.draw.rect(
            screen, (46, 86, 138), self._back_rect, border_radius=7
        )
        pygame.draw.rect(
            screen, PANEL_BORDER, self._back_rect, 2, border_radius=7
        )
        text = self.app.font_small.render("Назад", True, TEXT)
        screen.blit(text, text.get_rect(center=self._back_rect.center))

    def _draw_apply(self, screen):
        pygame.draw.rect(
            screen, (46, 86, 138), self._apply_rect, border_radius=7
        )
        pygame.draw.rect(
            screen, PANEL_BORDER, self._apply_rect, 2, border_radius=7
        )
        if self.mode == "characters":
            enabled = self.selected_character_interaction_id is not None
        elif self.mode == "automata":
            enabled = (
                self.selected_automaton_interaction_id is not None
                and self.selected_automaton_target_id is not None
            )
        else:
            enabled = self.selected_interaction_id is not None
        if not self.campaign.finished and enabled:
            label = "Начать · 1 слот"
            color = TEXT
        elif (
            self.mode == "automata"
            and self.selected_automaton_interaction_id
        ):
            label = "Выберите цель в графе"
            color = DIM
        else:
            label = "Выберите действие"
            color = DIM
        text = self.app.font_small.render(label, True, color)
        screen.blit(text, text.get_rect(center=self._apply_rect.center))

    def draw(self, screen):
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 190))
        screen.blit(dim, (0, 0))
        screen.blit(
            self.app.font_title.render("Сеть автоматов", True, TEXT),
            (24, 24),
        )
        status = "время %s · скорость %s · цикл %d · %s" % (
            self.campaign.time_label(),
            self.campaign.speed_label(),
            self.campaign.turn,
            self._slots_label(),
        )
        if self.campaign.outcome:
            status += " · исход: %s" % self.campaign.outcome
        screen.blit(
            self.app.font_small.render(status, True, MUTED), (24, 62)
        )
        self._layout()
        self._draw_graph(screen)
        self._draw_detail(screen)
        self._draw_side(screen)
        self._draw_apply(screen)
        self._draw_bottom(screen)
