"""Личность: характеристики, навыки, предметы."""

from __future__ import annotations

from .world_screen_support import (
    ACCENT,
    BAD,
    CONTENT_RECT,
    DIM,
    MUTED,
    PANEL_BG_SOFT,
    PANEL_BORDER,
    RIGHT_RECT,
    TEXT,
    WARN,
    pygame,
    world_text,
    wrap_text,
)


class WorldScreenPersonalityMixin:

    def _draw_personality_content(self, screen):
        self.entity_rows = []
        self.action_rows = []
        self.skill_rows = []
        self.item_rows = []
        sub = self._active_group_id("personality")
        if sub == "skills":
            self._draw_skill_tree(screen)
        elif sub == "items":
            self._draw_items(screen)
        else:
            self._draw_characteristics(screen)

    def _draw_characteristics(self, screen):
        self._draw_panel(screen, CONTENT_RECT, "ХАРАКТЕРИСТИКИ")
        profile = self.engine.profile
        portrait = self.art.portrait("player", (96, 116))
        screen.blit(portrait, (CONTENT_RECT.x + 16, CONTENT_RECT.y + 46))
        pygame.draw.rect(
            screen,
            PANEL_BORDER,
            (CONTENT_RECT.x + 16, CONTENT_RECT.y + 46, 96, 116),
            1,
        )
        x = CONTENT_RECT.x + 128
        y = CONTENT_RECT.y + 46
        name = str(profile.get("name") or "Новый герой")
        screen.blit(self.app.font_body.render(name, True, TEXT), (x, y))
        y += 24
        summary = " · ".join(
            str(item)
            for item in (
                profile.get("origin"),
                profile.get("vocation"),
                profile.get("reputation"),
            )
            if item
        )
        y = self._draw_wrapped(
            screen,
            summary,
            x,
            y,
            CONTENT_RECT.width - 150,
            MUTED,
            max_lines=1,
        )
        y = self._draw_wrapped(
            screen,
            "семья: %s · образование: %s"
            % (profile.get("family", "—"), profile.get("education", "—")),
            x,
            y + 3,
            CONTENT_RECT.width - 150,
            MUTED,
            max_lines=1,
        )
        y = self._draw_wrapped(
            screen,
            "покровитель: %s · недостаток: %s"
            % (profile.get("patron", "—"), profile.get("flaw", "—")),
            x,
            y + 3,
            CONTENT_RECT.width - 150,
            MUTED,
            max_lines=1,
        )
        values = ", ".join(profile.get("values") or ())
        traits = ", ".join(profile.get("traits") or ())
        y = self._draw_wrapped(
            screen,
            "ценности: %s" % values,
            x,
            y + 6,
            CONTENT_RECT.width - 150,
            WARN,
            max_lines=1,
        )
        self._draw_wrapped(
            screen,
            "черты: %s" % traits,
            x,
            y + 2,
            CONTENT_RECT.width - 150,
            (184, 196, 214),
            max_lines=2,
        )
        office = self.engine.player_office()
        card = pygame.Rect(
            CONTENT_RECT.x + 16,
            CONTENT_RECT.y + 188,
            CONTENT_RECT.width - 32,
            70,
        )
        pygame.draw.rect(screen, PANEL_BG_SOFT, card, border_radius=6)
        pygame.draw.rect(screen, PANEL_BORDER, card, 1, border_radius=6)
        screen.blit(
            self.app.font_small.render("ДОЛЖНОСТЬ", True, WARN),
            (card.x + 12, card.y + 8),
        )
        screen.blit(
            self.app.font_body.render(office.get("title", "—"), True, TEXT),
            (card.x + 12, card.y + 27),
        )
        screen.blit(
            self.app.font_tiny.render(
                "%s · %s · полномочия: %s"
                % (
                    office.get("node_name", "—"),
                    office.get("level_label", "—"),
                    world_text.scale_label(office.get("authority", 0.0)),
                ),
                True,
                MUTED,
            ),
            (card.x + 12, card.y + 50),
        )
        screen.blit(
            self.app.font_tiny.render("пригодность к сферам", True, WARN),
            (CONTENT_RECT.x + 16, CONTENT_RECT.y + 276),
        )
        aptitudes = profile.get("aptitudes") or {}
        index = 0
        for domain in self.engine.config.get("domains") or ():
            value = float(aptitudes.get(domain["id"], 0.0))
            column = index % 3
            row = index // 3
            px = CONTENT_RECT.x + 16 + column * 255
            py = CONTENT_RECT.y + 296 + row * 34
            screen.blit(
                self.app.font_tiny.render(
                    self.engine.domain_label(domain["id"]), True, DIM
                ),
                (px, py),
            )
            self._draw_bar(
                screen,
                pygame.Rect(px, py + 15, 150, 4),
                value,
                (112, 164, 208),
            )
            screen.blit(
                self.app.font_tiny.render(
                    world_text.scale_label(value), True, MUTED
                ),
                (px + 156, py),
            )
            index += 1
        return

    def _draw_skill_tree(self, screen):
        self._draw_panel(screen, CONTENT_RECT, "ДРЕВО НАВЫКОВ")
        branches = self.engine.skill_tree()
        if not branches:
            screen.blit(
                self.app.font_tiny.render(
                    "древо навыков ещё не описано", True, DIM
                ),
                (CONTENT_RECT.x + 16, CONTENT_RECT.y + 52),
            )
            return
        root_x = CONTENT_RECT.centerx
        root_y = CONTENT_RECT.y + 62
        pygame.draw.circle(screen, (46, 68, 92), (root_x, root_y), 28, 2)
        root = self.app.font_tiny.render("ПРАКТИКА", True, TEXT)
        screen.blit(root, root.get_rect(center=(root_x, root_y)))
        column_w = 240
        gap = 20
        total = column_w * len(branches) + gap * (len(branches) - 1)
        left = CONTENT_RECT.centerx - total // 2
        for branch_index, branch in enumerate(branches):
            bx = left + branch_index * (column_w + gap)
            branch_center = bx + column_w // 2
            pygame.draw.line(
                screen,
                (62, 82, 106),
                (root_x, root_y + 28),
                (branch_center, CONTENT_RECT.y + 112),
                2,
            )
            screen.blit(
                self.app.font_small.render(
                    branch.get("label", ""), True, WARN
                ),
                (bx, CONTENT_RECT.y + 104),
            )
            screen.blit(
                self.app.font_tiny.render(
                    self._clip_text(
                        self.app.font_tiny,
                        branch.get("description", ""),
                        column_w,
                    ),
                    True,
                    DIM,
                ),
                (bx, CONTENT_RECT.y + 122),
            )
            skill_y = CONTENT_RECT.y + 142
            for skill_index, skill in enumerate(branch.get("skills") or ()):
                rect = pygame.Rect(bx, skill_y, column_w, 66)
                selected = skill["id"] == self.selected_skill_id
                fill = (38, 62, 88) if selected else (20, 26, 37)
                pygame.draw.rect(screen, fill, rect, border_radius=5)
                pygame.draw.rect(
                    screen,
                    ACCENT if selected else PANEL_BORDER,
                    rect,
                    1,
                    border_radius=5,
                )
                icon = self.art.skill_icon(skill["id"], (30, 30))
                screen.blit(icon, (rect.x + 6, rect.y + 8))
                screen.blit(
                    self.app.font_small.render(
                        skill.get("label", skill["id"]), True, TEXT
                    ),
                    (rect.x + 44, rect.y + 6),
                )
                rank = world_text.skill_rank(skill.get("value", 0.0))
                screen.blit(
                    self.app.font_tiny.render(rank, True, ACCENT),
                    (rect.x + 44, rect.y + 24),
                )
                self._draw_bar(
                    screen,
                    pygame.Rect(rect.x + 44, rect.y + 40, 120, 4),
                    skill.get("value", 0.0),
                    (112, 164, 208),
                )
                next_rank = world_text.skill_next_rank(skill.get("value", 0.0))
                if next_rank:
                    screen.blit(
                        self.app.font_tiny.render(
                            "след.: %s" % next_rank, True, DIM
                        ),
                        (rect.x + 44, rect.y + 50),
                    )
                self.skill_rows.append((rect, skill["id"]))
                if skill_index < len(branch.get("skills") or ()) - 1:
                    pygame.draw.line(
                        screen,
                        (62, 82, 106),
                        (branch_center, rect.bottom),
                        (branch_center, rect.bottom + 10),
                        2,
                    )
                skill_y += 76

    def _draw_items(self, screen):
        self._draw_panel(screen, CONTENT_RECT, "НАЛИЧНЫЕ ПРЕДМЕТЫ")
        items = self.engine.player_items()
        if not items:
            screen.blit(
                self.app.font_tiny.render(
                    "при вас нет личных предметов", True, DIM
                ),
                (CONTENT_RECT.x + 16, CONTENT_RECT.y + 52),
            )
            return
        card_w = (CONTENT_RECT.width - 48) // 2
        card_h = 112
        for index, item in enumerate(items):
            column = index % 2
            row = index // 2
            rect = pygame.Rect(
                CONTENT_RECT.x + 16 + column * (card_w + 16),
                CONTENT_RECT.y + 48 + row * (card_h + 12),
                card_w,
                card_h,
            )
            selected = item["id"] == self.selected_item_id
            fill = (38, 62, 88) if selected else (20, 26, 37)
            pygame.draw.rect(screen, fill, rect, border_radius=6)
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                1,
                border_radius=6,
            )
            icon = self.art.item_icon(item, (60, 60))
            screen.blit(icon, (rect.x + 10, rect.y + 12))
            pygame.draw.rect(
                screen,
                PANEL_BORDER,
                (rect.x + 10, rect.y + 12, 60, 60),
                1,
            )
            screen.blit(
                self.app.font_small.render(
                    self._clip_text(
                        self.app.font_small,
                        item.get("label", item["id"]),
                        rect.width - 90,
                    ),
                    True,
                    TEXT,
                ),
                (rect.x + 82, rect.y + 12),
            )
            desc = wrap_text(
                self.app.font_tiny,
                item.get("description", ""),
                rect.width - 94,
            )
            for line_index, line in enumerate(desc[:3]):
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (rect.x + 82, rect.y + 34 + line_index * 13),
                )
            self.item_rows.append((rect, item["id"]))

    def _draw_personality_right(self, screen):
        self._draw_panel(screen, RIGHT_RECT, "ЛИЧНОСТЬ")
        y = RIGHT_RECT.y + 44
        if self.selected_skill_id:
            skill = None
            for branch in self.engine.skill_tree():
                for item in branch.get("skills") or ():
                    if item["id"] == self.selected_skill_id:
                        skill = item
                        break
                if skill:
                    break
            if skill:
                icon = self.art.skill_icon(skill["id"], (48, 48))
                screen.blit(icon, (RIGHT_RECT.x + 14, y))
                pygame.draw.rect(
                    screen,
                    PANEL_BORDER,
                    (RIGHT_RECT.x + 14, y, 48, 48),
                    1,
                )
                screen.blit(
                    self.app.font_body.render(
                        skill.get("label", skill["id"]), True, TEXT
                    ),
                    (RIGHT_RECT.x + 76, y),
                )
                screen.blit(
                    self.app.font_tiny.render(
                        "ранг: %s"
                        % world_text.skill_rank(skill.get("value", 0.0)),
                        True,
                        ACCENT,
                    ),
                    (RIGHT_RECT.x + 76, y + 22),
                )
                y += 60
                y = self._draw_wrapped(
                    screen,
                    skill.get("description", ""),
                    RIGHT_RECT.x + 14,
                    y,
                    RIGHT_RECT.width - 28,
                    (190, 205, 220),
                    max_lines=4,
                )
                next_rank = world_text.skill_next_rank(skill.get("value", 0.0))
                if next_rank:
                    y = self._draw_wrapped(
                        screen,
                        "следующий порог: %s" % next_rank,
                        RIGHT_RECT.x + 14,
                        y + 6,
                        RIGHT_RECT.width - 28,
                        WARN,
                        max_lines=1,
                    )
                self._draw_bar(
                    screen,
                    pygame.Rect(
                        RIGHT_RECT.x + 14, y + 8, RIGHT_RECT.width - 28, 6
                    ),
                    skill.get("value", 0.0),
                    (112, 164, 208),
                )
                y += 26
        elif self.selected_item_id:
            item = None
            for candidate in self.engine.player_items():
                if candidate["id"] == self.selected_item_id:
                    item = candidate
                    break
            if item:
                icon = self.art.item_icon(item, (72, 72))
                screen.blit(icon, (RIGHT_RECT.x + 14, y))
                pygame.draw.rect(
                    screen,
                    PANEL_BORDER,
                    (RIGHT_RECT.x + 14, y, 72, 72),
                    1,
                )
                screen.blit(
                    self.app.font_body.render(
                        item.get("label", item["id"]), True, TEXT
                    ),
                    (RIGHT_RECT.x + 98, y),
                )
                screen.blit(
                    self.app.font_tiny.render("личный предмет", True, ACCENT),
                    (RIGHT_RECT.x + 98, y + 24),
                )
                y += 88
                y = self._draw_wrapped(
                    screen,
                    item.get("description", ""),
                    RIGHT_RECT.x + 14,
                    y,
                    RIGHT_RECT.width - 28,
                    (190, 205, 220),
                    max_lines=5,
                )
                screen.blit(
                    self.app.font_tiny.render(
                        "ДЕЙСТВИЯ С ПРЕДМЕТОМ", True, WARN
                    ),
                    (RIGHT_RECT.x + 14, y + 8),
                )
                options = self._action_options()
                self._draw_action_list(
                    screen,
                    options,
                    y + 26,
                    RIGHT_RECT.y + 322,
                    rect=RIGHT_RECT,
                )
                if self.selected_action_id:
                    self._draw_button(
                        screen,
                        self._execute_rect(),
                        "Совершить",
                        True,
                        accent=True,
                    )
        else:
            office = self.engine.player_office()
            screen.blit(
                self.app.font_body.render(
                    self.engine.profile.get("name", "Новый герой"),
                    True,
                    TEXT,
                ),
                (RIGHT_RECT.x + 14, y),
            )
            y += 24
            y = self._draw_wrapped(
                screen,
                "%s · %s"
                % (office.get("title", "—"), office.get("node_name", "—")),
                RIGHT_RECT.x + 14,
                y,
                RIGHT_RECT.width - 28,
                MUTED,
                max_lines=2,
            )
            screen.blit(
                self.app.font_tiny.render("ЛИЧНЫЕ РЕСУРСЫ", True, WARN),
                (RIGHT_RECT.x + 14, y + 10),
            )
            y += 28
            for key in ("standing", "influence", "favor", "evidence"):
                value = float(self.engine.player_resources.get(key, 0.0))
                screen.blit(
                    self.app.font_tiny.render(
                        self.engine.stat_label(key), True, DIM
                    ),
                    (RIGHT_RECT.x + 14, y),
                )
                self._draw_bar(
                    screen,
                    pygame.Rect(RIGHT_RECT.x + 120, y + 4, 110, 4),
                    value,
                    (118, 202, 156),
                )
                screen.blit(
                    self.app.font_tiny.render(
                        world_text.resource_label(value), True, MUTED
                    ),
                    (RIGHT_RECT.x + 238, y),
                )
                y += 19
            y += 6
            y = self._draw_wrapped(
                screen,
                "Характеристики показывают, на что вы опираетесь. "
                "Навыки растут через действия и службу.",
                RIGHT_RECT.x + 14,
                y,
                RIGHT_RECT.width - 28,
                MUTED,
                max_lines=3,
            )
            if self.message:
                y = self._draw_wrapped(
                    screen,
                    self.message,
                    RIGHT_RECT.x + 14,
                    y + 4,
                    RIGHT_RECT.width - 28,
                    BAD,
                    max_lines=2,
                )
        if self.message and self.selected_skill_id:
            self._draw_wrapped(
                screen,
                self.message,
                RIGHT_RECT.x + 14,
                RIGHT_RECT.y + 300,
                RIGHT_RECT.width - 28,
                BAD,
                max_lines=2,
            )
        self._draw_log(screen, RIGHT_RECT.y + 382)
