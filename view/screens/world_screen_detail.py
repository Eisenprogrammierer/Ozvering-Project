"""Карточки организаций, норм и персонажей, прогноз действия."""

from __future__ import annotations

from .world_screen_support import (
    ACCENT,
    BAD,
    CHARACTER_CIRCLES,
    DIM,
    GOOD,
    MID_RECT,
    MUTED,
    ORGANIZATION_CATEGORIES,
    PANEL_BORDER,
    RIGHT_RECT,
    TEXT,
    WARN,
    asymmetry_rows,
    pygame,
    world_text,
    wrap_text,
)


class WorldScreenDetailMixin:

    def _draw_organization_content(self, screen):
        group_id = self._active_group_id("organizations")
        rows = self._active_organizations()
        title = "%s организации" % ORGANIZATION_CATEGORIES.get(
            group_id, group_id
        )
        self._draw_entity_list(screen, title.upper(), rows, "organization")
        self._draw_organization_detail(screen)

    def _draw_organization_detail(self, screen):
        self._draw_panel(screen, MID_RECT, "СТРУКТУРА И ДЕЙСТВИЯ")
        self.action_rows = []
        node = self.engine.node(self.selected_target_id)
        if node is None:
            if self._active_organizations():
                text = "Выберите организацию слева."
            else:
                text = (
                    "В этой категории пока никого нет. Выберите другую "
                    "подвкладку или измените отношения со структурами."
                )
            self._draw_wrapped(
                screen,
                text,
                MID_RECT.x + 12,
                MID_RECT.y + 48,
                MID_RECT.width - 24,
                DIM,
                max_lines=3,
            )
            return
        icon = self.art.organization_icon(node, (58, 58))
        screen.blit(icon, (MID_RECT.x + 12, MID_RECT.y + 44))
        pygame.draw.rect(
            screen,
            PANEL_BORDER,
            (MID_RECT.x + 12, MID_RECT.y + 44, 58, 58),
            1,
        )
        x = MID_RECT.x + 82
        screen.blit(
            self.app.font_body.render(
                self._clip_text(self.app.font_body, node["name"], 330),
                True,
                TEXT,
            ),
            (x, MID_RECT.y + 44),
        )
        detail = "%s · %s · %s" % (
            self.engine.domain_label(node["domain"]),
            self.engine.node_level_label(node),
            self.engine.polities.get(node.get("polity"), {}).get(
                "label", node.get("polity") or "—"
            ),
        )
        screen.blit(
            self.app.font_tiny.render(
                self._clip_text(self.app.font_tiny, detail, 340),
                True,
                ACCENT,
            ),
            (x, MID_RECT.y + 67),
        )
        outgoing = self.engine.relation_axes(
            self.engine.player_node_id, node["id"]
        )
        incoming = self.engine.relation_axes(
            node["id"], self.engine.player_node_id
        )
        screen.blit(
            self.app.font_tiny.render(
                "вы → цель: %s · цель → вы: %s"
                % (
                    world_text.relation_label(outgoing["affinity"]),
                    world_text.relation_label(incoming["affinity"]),
                ),
                True,
                self._relation_color(incoming["affinity"]),
            ),
            (x, MID_RECT.y + 82),
        )
        axes_parts = []
        for axis, forward, backward in asymmetry_rows(
            outgoing, incoming, self.engine.relation_axis_ids
        ):
            if abs(forward) < 0.02 and abs(backward) < 0.02:
                continue
            axes_parts.append(
                "%s %+.2f/%+.2f"
                % (
                    world_text.relation_axis_label(
                        axis, self.engine.relation_axis_short_labels
                    ),
                    forward,
                    backward,
                )
            )
        if axes_parts:
            screen.blit(
                self.app.font_tiny.render(
                    self._clip_text(
                        self.app.font_tiny,
                        "оси вы/цель: " + " · ".join(axes_parts),
                        346,
                    ),
                    True,
                    DIM,
                ),
                (x, MID_RECT.y + 96),
            )
        desc = wrap_text(self.app.font_tiny, node.get("description", ""), 330)
        for index, line in enumerate(desc[:2]):
            screen.blit(
                self.app.font_tiny.render(line, True, MUTED),
                (x, MID_RECT.y + 110 + index * 13),
            )
        stats = node.get("stats") or {}
        stat_keys = (
            "power",
            "wealth",
            "legitimacy",
            "cohesion",
            "reach",
            "capacity",
        )
        sx = MID_RECT.x + 12
        sy = MID_RECT.y + 132
        for index, key in enumerate(stat_keys):
            column = index % 2
            row = index // 2
            px = sx + column * 206
            py = sy + row * 18
            value = float(stats.get(key, 0.0))
            screen.blit(
                self.app.font_tiny.render(
                    self.engine.stat_label(key), True, DIM
                ),
                (px, py),
            )
            bar = pygame.Rect(px + 100, py + 4, 82, 4)
            self._draw_bar(screen, bar, value, (112, 164, 208))
        action_top = MID_RECT.y + 196
        screen.blit(
            self.app.font_tiny.render(
                "ДЕЙСТВИЯ · доступные и закрытые", True, WARN
            ),
            (MID_RECT.x + 12, action_top - 18),
        )
        options = self._action_options()
        self._draw_action_list(
            screen, options, action_top, MID_RECT.bottom - 8
        )

    def _draw_norm_content(self, screen):
        rows = self._active_norms()
        title = "НОРМЫ И ОБЫЧАИ"
        self._draw_entity_list(screen, title, rows, "norm")
        self._draw_norm_detail(screen)

    def _draw_norm_detail(self, screen):
        self._draw_panel(screen, MID_RECT, "НОРМА И ДЕЙСТВИЯ")
        self.action_rows = []
        norm = self.engine.norms.get(self.selected_norm_id)
        if norm is None:
            self._draw_wrapped(
                screen,
                "В мире пока нет объявленных норм.",
                MID_RECT.x + 12,
                MID_RECT.y + 48,
                MID_RECT.width - 24,
                DIM,
                max_lines=3,
            )
            return
        screen.blit(
            self.app.font_body.render(
                self._clip_text(
                    self.app.font_body, norm.get("label", norm["id"]), 400
                ),
                True,
                TEXT,
            ),
            (MID_RECT.x + 12, MID_RECT.y + 44),
        )
        detail = " · ".join(
            str(item)
            for item in (
                self.engine.domain_label(norm.get("domain", "")),
                norm.get("status", ""),
                norm.get("scope", ""),
            )
            if item
        )
        screen.blit(
            self.app.font_tiny.render(detail, True, ACCENT),
            (MID_RECT.x + 12, MID_RECT.y + 70),
        )
        y = self._draw_wrapped(
            screen,
            norm.get("description", ""),
            MID_RECT.x + 12,
            MID_RECT.y + 92,
            MID_RECT.width - 24,
            MUTED,
            max_lines=4,
        )
        action_top = max(y + 16, MID_RECT.y + 156)
        screen.blit(
            self.app.font_tiny.render(
                "ДЕЙСТВИЯ · доступные и закрытые", True, WARN
            ),
            (MID_RECT.x + 12, action_top - 18),
        )
        options = self._action_options()
        self._draw_action_list(
            screen, options, action_top, MID_RECT.bottom - 8
        )

    def _draw_character_content(self, screen):
        group_id = self._active_group_id("characters")
        rows = self._active_characters()
        title = CHARACTER_CIRCLES.get(group_id, group_id)
        self._draw_entity_list(screen, title.upper(), rows, "character")
        self._draw_character_detail(screen)

    def _draw_character_detail(self, screen):
        self._draw_panel(screen, MID_RECT, "ЧЕЛОВЕК И РАЗГОВОР")
        self.action_rows = []
        character = self.engine.character(self.selected_character_id)
        if character is None:
            if self._active_characters():
                text = "Выберите человека слева."
            else:
                text = "В этом круге пока никого нет."
            self._draw_wrapped(
                screen,
                text,
                MID_RECT.x + 12,
                MID_RECT.y + 48,
                MID_RECT.width - 24,
                DIM,
                max_lines=3,
            )
            return
        portrait = self.art.portrait(character["id"], (86, 104))
        screen.blit(portrait, (MID_RECT.x + 12, MID_RECT.y + 44))
        pygame.draw.rect(
            screen,
            PANEL_BORDER,
            (MID_RECT.x + 12, MID_RECT.y + 44, 86, 104),
            1,
        )
        x = MID_RECT.x + 112
        screen.blit(
            self.app.font_body.render(
                self._clip_text(self.app.font_body, character["name"], 310),
                True,
                TEXT,
            ),
            (x, MID_RECT.y + 44),
        )
        screen.blit(
            self.app.font_tiny.render(
                self._clip_text(
                    self.app.font_tiny, character.get("role", ""), 310
                ),
                True,
                ACCENT,
            ),
            (x, MID_RECT.y + 67),
        )
        tags = " · ".join(character.get("tags") or ())
        if tags:
            screen.blit(
                self.app.font_tiny.render(tags, True, WARN),
                (x, MID_RECT.y + 84),
            )
        desc = wrap_text(
            self.app.font_tiny,
            character.get("description", ""),
            310,
        )
        for index, line in enumerate(desc[:3]):
            screen.blit(
                self.app.font_tiny.render(line, True, MUTED),
                (x, MID_RECT.y + 100 + index * 13),
            )
        affinity = float(character.get("affinity", 0.0))
        trust = float(character.get("trust", 0.0))
        stat_rows = [("расположение", affinity), ("доверие", trust)]
        fear = float(character.get("fear", 0.0))
        respect = float(character.get("respect", 0.0))
        if abs(fear) > 1e-9:
            stat_rows.append(("страх", fear))
        if abs(respect) > 1e-9:
            stat_rows.append(("уважение", respect))
        for index, (label, value) in enumerate(stat_rows):
            y = MID_RECT.y + 136 + index * 18
            screen.blit(
                self.app.font_tiny.render(label, True, DIM),
                (x, y),
            )
            self._draw_bar(
                screen,
                pygame.Rect(x + 92, y + 4, 120, 4),
                (value + 1.0) / 2.0,
                self._relation_color(value),
            )
            screen.blit(
                self.app.font_tiny.render(
                    world_text.relation_label(value), True, MUTED
                ),
                (x + 220, y),
            )
        action_top = MID_RECT.y + 136 + len(stat_rows) * 18 + 10
        screen.blit(
            self.app.font_tiny.render(
                "РАЗГОВОР И ДЕЙСТВИЯ · доступные и закрытые", True, WARN
            ),
            (MID_RECT.x + 12, action_top - 18),
        )
        options = self._action_options()
        self._draw_action_list(
            screen, options, action_top, MID_RECT.bottom - 8
        )

    def _draw_forecast_action(self, screen, y, preview):
        action = preview.get("action") or {}
        target = preview.get("target_label") or "—"
        screen.blit(
            self.app.font_body.render(
                self._clip_text(
                    self.app.font_body,
                    action.get("label", "Действие"),
                    RIGHT_RECT.width - 28,
                ),
                True,
                TEXT,
            ),
            (RIGHT_RECT.x + 14, y),
        )
        y += 24
        y = self._draw_wrapped(
            screen,
            "цель: %s" % target,
            RIGHT_RECT.x + 14,
            y,
            RIGHT_RECT.width - 28,
            MUTED,
            max_lines=1,
        )
        y = self._draw_wrapped(
            screen,
            world_text.cost_summary(action, self.engine.stat_labels),
            RIGHT_RECT.x + 14,
            y + 2,
            RIGHT_RECT.width - 28,
            WARN,
            max_lines=1,
        )
        if not preview.get("enabled"):
            y = self._draw_wrapped(
                screen,
                "недоступно: %s"
                % world_text.reason_text(preview.get("reason")),
                RIGHT_RECT.x + 14,
                y + 8,
                RIGHT_RECT.width - 28,
                BAD,
                max_lines=2,
            )
            return y
        chance = float(preview.get("success_chance", 0.0))
        color = self._chance_color(chance)
        screen.blit(
            self.app.font_small.render(
                "успех: %s" % world_text.chance_label(chance),
                True,
                color,
            ),
            (RIGHT_RECT.x + 14, y + 8),
        )
        y += 28
        y = self._draw_wrapped(
            screen,
            preview.get("success_text", ""),
            RIGHT_RECT.x + 14,
            y,
            RIGHT_RECT.width - 28,
            (190, 205, 220),
            max_lines=2,
        )
        effects = world_text.format_effect_map(
            preview.get("success_effects_map"),
            self.engine.stat_labels,
            preview.get("target_label", ""),
            self.engine.relation_axis_labels,
        )
        if effects:
            y = self._draw_wrapped(
                screen,
                " · ".join(effects[:4]),
                RIGHT_RECT.x + 14,
                y + 2,
                RIGHT_RECT.width - 28,
                GOOD,
                max_lines=3,
            )
        failure_chance = float(preview.get("failure_chance", 0.0))
        screen.blit(
            self.app.font_tiny.render(
                "если не выйдет: %s" % world_text.chance_label(failure_chance),
                True,
                BAD if failure_chance >= 0.46 else MUTED,
            ),
            (RIGHT_RECT.x + 14, y + 8),
        )
        y += 24
        y = self._draw_wrapped(
            screen,
            preview.get("failure_text", ""),
            RIGHT_RECT.x + 14,
            y,
            RIGHT_RECT.width - 28,
            (190, 180, 180),
            max_lines=2,
        )
        failure_effects = world_text.format_effect_map(
            preview.get("failure_effects_map"),
            self.engine.stat_labels,
            preview.get("target_label", ""),
            self.engine.relation_axis_labels,
        )
        if failure_effects:
            y = self._draw_wrapped(
                screen,
                " · ".join(failure_effects[:4]),
                RIGHT_RECT.x + 14,
                y + 2,
                RIGHT_RECT.width - 28,
                BAD,
                max_lines=2,
            )
        return y

    def _draw_forecast_result(self, screen, y, result):
        outcome = result.get("outcome", "")
        color = {"success": GOOD, "failure": BAD, "win": GOOD}.get(
            outcome, WARN
        )
        screen.blit(
            self.app.font_body.render(
                world_text.outcome_label(outcome), True, color
            ),
            (RIGHT_RECT.x + 14, y),
        )
        y += 24
        y = self._draw_wrapped(
            screen,
            "действие: %s" % result.get("action_label", ""),
            RIGHT_RECT.x + 14,
            y,
            RIGHT_RECT.width - 28,
            MUTED,
            max_lines=1,
        )
        y = self._draw_wrapped(
            screen,
            result.get("text", ""),
            RIGHT_RECT.x + 14,
            y + 2,
            RIGHT_RECT.width - 28,
            (190, 205, 220),
            max_lines=4,
        )
        summary = world_text.summarize_changes(result.get("changes"))
        if summary:
            y = self._draw_wrapped(
                screen,
                summary,
                RIGHT_RECT.x + 14,
                y + 4,
                RIGHT_RECT.width - 28,
                WARN,
                max_lines=4,
            )
        return y

    def _draw_forecast(self, screen):
        self._draw_panel(screen, RIGHT_RECT, "ПРОГНОЗ")
        y = RIGHT_RECT.y + 44
        context = self.selected_action_context or self.action_context
        if self.selected_action_id and context in (
            "organization",
            "character",
            "norm",
            "world",
        ):
            option = self.selected_action_option or {}
            if context == "character":
                preview = self.engine.character_preview(
                    self.selected_action_id, self.selected_character_id
                )
            elif context == "world":
                preview = self.engine.preview(
                    self.selected_action_id,
                    target_ref=option.get("target_ref") or {},
                )
            else:
                preview = self.engine.preview(
                    self.selected_action_id, self.selected_target_id
                )
            if preview is not None:
                self._draw_forecast_action(screen, y, preview)
        elif self.last_result:
            self._draw_forecast_result(screen, y, self.last_result)
        else:
            if (
                self.action_context == "character"
                and self.selected_character_id
            ):
                character = (
                    self.engine.character(self.selected_character_id) or {}
                )
                text = (
                    "Выбран человек: %s. Выберите разговор слева. "
                    "Шанс и последствия показаны качественно, без "
                    "точных процентов."
                ) % character.get("name", "—")
            elif (
                self.action_context == "organization"
                and self.selected_target_id
            ):
                node = self.engine.node(self.selected_target_id) or {}
                text = (
                    "Выбрана структура: %s. Выберите действие слева. "
                    "Шанс и последствия показаны качественно, без "
                    "точных процентов."
                ) % node.get("name", "—")
            elif self.action_context == "norm" and self.selected_norm_id:
                norm = self.engine.norms.get(self.selected_norm_id) or {}
                text = (
                    "Выбрана норма: %s. Выберите, как на неё сослаться "
                    "или что с ней сделать."
                ) % norm.get("label", "—")
            elif self.main_tab == "norms" and not self._active_norms():
                text = "В мире пока нет объявленных норм."
            elif self.main_tab == "organizations" and not (
                self._active_organizations()
            ):
                text = (
                    "В этой категории пока нет организаций. Выберите "
                    "другую подвкладку или измените отношения со "
                    "структурами."
                )
            elif self.main_tab == "characters" and not (
                self._active_characters()
            ):
                text = "В этом круге пока никого нет."
            else:
                text = (
                    "Выберите человека, структуру или норму, затем "
                    "действие. Шанс и последствия показаны качественно, "
                    "без точных процентов."
                )
            y = self._draw_wrapped(
                screen,
                text,
                RIGHT_RECT.x + 14,
                y,
                RIGHT_RECT.width - 28,
                MUTED,
                max_lines=6,
            )
            self._draw_wrapped(
                screen,
                "Серые действия остаются видны вместе с причиной отказа.",
                RIGHT_RECT.x + 14,
                y + 6,
                RIGHT_RECT.width - 28,
                DIM,
                max_lines=3,
            )
        if self.message:
            self._draw_wrapped(
                screen,
                self.message,
                RIGHT_RECT.x + 14,
                RIGHT_RECT.y + 300,
                RIGHT_RECT.width - 28,
                BAD,
                max_lines=2,
            )
        self._draw_button(
            screen,
            self._execute_rect(),
            "Совершить",
            bool(self.selected_action_id),
            accent=True,
        )
        self._draw_log(screen, RIGHT_RECT.y + 382)
