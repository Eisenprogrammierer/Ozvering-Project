"""Игровой чат: выбор фракции-автомата, персонажа и стиля ответа.

Экран не содержит диалоговой логики: он только собирает выбор игрока и
передаёт свободный текст в ``app.dialogue_session(...)``. Ответ агента
приходит уже разобранным, доказанным, синтезированным и стилизованным.
Память беседы хранится в ``DialogueMemoryStore`` приложения и попадает в
сохранение вместе с кампанией.
"""

from __future__ import annotations

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import line_height, wrap_text
from view.support.log_journal import get_logger

logger = get_logger("view.dialogue_chat")

WIDTH, HEIGHT = 1280, 720
LEFT_RECT = pygame.Rect(24, 96, 320, 552)
RIGHT_RECT = pygame.Rect(356, 96, 900, 552)
INPUT_RECT = pygame.Rect(356, 662, 900, 46)
BACK_RECT = pygame.Rect(1136, 14, 120, 40)
PANEL_BG = (18, 23, 33, 242)
PANEL_BORDER = (58, 70, 92)
TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
BAD = (226, 112, 112)
WARN = (230, 184, 96)
PLAYER_BG = (32, 52, 82)
AGENT_BG = (25, 31, 43)
FACTION_ROW_H = 32
CHARACTER_ROW_H = 24
MAX_INPUT = 500
MAX_HISTORY = 80


def _panel(surface, rect, fill=PANEL_BG):
    shape = pygame.Surface(rect.size, pygame.SRCALPHA)
    shape.fill(fill)
    surface.blit(shape, rect.topleft)
    pygame.draw.rect(surface, PANEL_BORDER, rect, 2, border_radius=8)


def _button(surface, rect, label, font, active=False, enabled=True):
    if not enabled:
        color = (42, 46, 58)
    elif active:
        color = (58, 112, 170)
    else:
        color = (42, 58, 82)
    pygame.draw.rect(surface, color, rect, border_radius=6)
    pygame.draw.rect(surface, PANEL_BORDER, rect, 2, border_radius=6)
    surface.blit(
        font.render(label, True, TEXT if enabled else DIM),
        font.render(label, True, TEXT if enabled else DIM).get_rect(
            center=rect.center
        ),
    )


class DialogueChatScreen(BaseScreen):
    """Простой чат от лица игрового персонажа."""

    escape_action = "custom"

    def __init__(self, app, side=None, character_id=None):
        super().__init__(app)
        self.campaign = getattr(app, "automata_campaign", None)
        self.catalog = None
        self.style_engine = None
        try:
            from campaign.dialogue.style import StyleEngine

            self.catalog = app._dialogue_catalog()
            self.style_engine = StyleEngine(self.catalog)
        except Exception as exc:
            logger.warning("Стили диалога не загружены: %s", exc)
        self.style_id = (
            self.style_engine.resolve(None, None)
            if self.style_engine is not None
            else ""
        )
        self.side = ""
        self.character_id = ""
        self.session = None
        self.input_text = ""
        self.focused = True
        self.message = ""
        self.character_scroll = 0
        self._sessions = {}
        self._histories = {}
        self._choose_default(side, character_id)
        self._start_text_input()
        logger.info(
            "Чат открыт: фракция=%s, персонаж=%s, стиль=%s",
            self.side,
            self.character_id,
            self.style_id,
        )

    # --- выбор собеседника -------------------------------------------

    def _factions(self):
        campaign = self.campaign
        if campaign is None:
            return []
        result = []
        for faction in getattr(campaign, "factions", {}).values():
            if getattr(faction, "dissolved", False):
                continue
            if not self._characters_for(faction.side):
                continue
            result.append(faction)
        return result

    def _faction(self, side):
        if self.campaign is None:
            return None
        return self.campaign.faction(side)

    def _characters_for(self, side):
        faction = self._faction(side)
        if faction is None:
            return []
        result = []
        for item in faction.character_options() or ():
            if item.get("is_player"):
                continue
            result.append(item)
        return result

    def _alive(self, item):
        return bool(item) and not bool(item.get("dead"))

    def _choose_default(self, side=None, character_id=None):
        factions = self._factions()
        if not factions:
            return
        by_side = {faction.side: faction for faction in factions}
        campaign = self.campaign
        player_side = str(getattr(campaign, "player_side", ""))
        rival = str(getattr(campaign, "rival_side", "") or "")
        candidate = str(side or "")
        if candidate not in by_side:
            if rival in by_side and rival != player_side:
                candidate = rival
            else:
                candidate = next(
                    (
                        faction.side
                        for faction in factions
                        if faction.side != player_side
                    ),
                    factions[0].side,
                )
        self.side = candidate
        self._select_character(character_id)

    def _default_character(self, side, preferred=None):
        options = [item for item in self._characters_for(side) if self._alive(item)]
        if not options:
            return ""
        preferred = str(preferred or "")
        for item in options:
            if str(item.get("id")) == preferred:
                return preferred
        for item in options:
            if item.get("is_leader"):
                return str(item.get("id") or "")
        return str(options[0].get("id") or "")

    def _select_character(self, character_id=None):
        self.character_id = self._default_character(self.side, character_id)
        self.character_scroll = 0
        self.session = self._session()
        if self.session is not None:
            self.session.set_style(self.style_id)

    def _select_faction(self, side):
        if side == self.side:
            return
        self.side = str(side)
        self._select_character(None)
        self.message = ""
        logger.info("Чат: выбрана фракция %s", self.side)

    def _select_character_id(self, character_id):
        if character_id == self.character_id:
            return
        item = next(
            (
                item
                for item in self._characters_for(self.side)
                if str(item.get("id")) == str(character_id)
            ),
            None,
        )
        if item is None:
            return
        if not self._alive(item):
            self.message = "Этот персонаж больше не может отвечать."
            return
        self.character_id = str(character_id)
        self.session = self._session()
        if self.session is not None:
            self.session.set_style(self.style_id)
        self.message = ""
        logger.info(
            "Чат: выбран персонаж %s (%s)", character_id, self.side
        )

    def _key(self):
        return (self.side, self.character_id)

    def _session(self):
        if self.campaign is None or not self.side or not self.character_id:
            return None
        key = self._key()
        if key in self._sessions:
            return self._sessions[key]
        try:
            session = self.app.dialogue_session(
                self.side, self.character_id
            )
        except Exception as exc:
            logger.warning("Сессия чата не создана: %s", exc)
            self.message = "Не удалось установить связь: %s" % exc
            return None
        if session is not None:
            session.set_style(self.style_id)
            self._sessions[key] = session
        return session

    def _history(self):
        return self._histories.setdefault(self._key(), [])

    def _player_name(self):
        session = self.session
        if session is not None:
            name = str(
                getattr(session.knowledge, "player_name", "") or ""
            ).strip()
            if name:
                return name
        return "Вы"

    def _agent_name(self):
        session = self.session
        if session is not None:
            name = str(
                getattr(session.knowledge, "speaker_name", "") or ""
            ).strip()
            if name:
                return name
        item = next(
            (
                item
                for item in self._characters_for(self.side)
                if str(item.get("id")) == self.character_id
            ),
            None,
        )
        return str((item or {}).get("name") or "Собеседник")

    def _agent_subtitle(self):
        session = self.session
        if session is None:
            return ""
        knowledge = session.knowledge
        parts = [
            str(getattr(knowledge, "speaker_post", "") or "").strip(),
            str(getattr(knowledge, "faction_name", "") or "").strip(),
        ]
        return " · ".join(part for part in parts if part)

    # --- стиль -------------------------------------------------------

    def _select_style(self, style_id):
        if self.style_engine is None:
            return
        if not self.style_engine.has(style_id):
            return
        self.style_id = str(style_id)
        if self.session is not None:
            self.session.set_style(self.style_id)
        self.message = ""
        logger.info("Чат: выбран стиль %s", self.style_id)

    def _style_spec(self):
        if self.style_engine is None:
            return None
        return self.style_engine.styles.get(self.style_id)

    # --- отправка ----------------------------------------------------

    def _send(self):
        text = str(self.input_text or "").strip()
        if not text:
            self.message = "Введите сообщение."
            return
        session = self.session or self._session()
        if session is None:
            self.message = "Собеседник недоступен."
            return
        history = self._history()
        history.append({"role": "player", "text": text})
        self.input_text = ""
        self.message = ""
        try:
            turn = session.respond(text)
            answer = turn.answer
            history.append(
                {
                    "role": "agent",
                    "text": answer.text,
                    "kind": answer.kind,
                    "plan": answer.plan_id,
                }
            )
            logger.info(
                "Чат: %s → %s; план=%s; вид=%s",
                self.character_id,
                text[:80],
                answer.plan_id,
                answer.kind,
            )
        except Exception as exc:
            logger.exception("Ошибка ответа в чате: %s", exc)
            history.append(
                {
                    "role": "system",
                    "text": "Связь прервалась: %s" % exc,
                }
            )
            self.message = "Ошибка диалога: %s" % exc
        if len(history) > MAX_HISTORY:
            del history[: len(history) - MAX_HISTORY]

    # --- ввод --------------------------------------------------------

    def _start_text_input(self):
        try:
            pygame.key.start_text_input()
        except Exception:
            pass

    def _stop_text_input(self):
        try:
            pygame.key.stop_text_input()
        except Exception:
            pass

    def on_escape(self):
        self._stop_text_input()
        self.app.manager.pop()

    def handle_event(self, event):
        if event.type == getattr(pygame, "TEXTINPUT", -1):
            text = str(getattr(event, "text", "") or "")
            if text:
                self.input_text = (self.input_text + text)[:MAX_INPUT]
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.input_text = self.input_text[:-1]
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._send()
                return
            if event.key == pygame.K_ESCAPE:
                self.on_escape()
                return
            if event.key == pygame.K_v and (
                getattr(event, "mod", 0) & pygame.KMOD_CTRL
            ):
                try:
                    self.input_text = (
                        self.input_text + pygame.scrap.get_text()
                    )[:MAX_INPUT]
                except Exception:
                    pass
                return
            return
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if LEFT_RECT.collidepoint(pos):
                total = len(self._characters_for(self.side))
                visible = self._visible_characters()
                if total > visible:
                    self.character_scroll = max(
                        0,
                        min(
                            total - visible,
                            self.character_scroll - event.y,
                        ),
                    )
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        pos = event.pos
        if BACK_RECT.collidepoint(pos):
            self.on_escape()
            return
        if INPUT_RECT.collidepoint(pos):
            self.focused = True
            return
        if self._send_rect().collidepoint(pos):
            self._send()
            return
        for rect, faction in self._faction_rows():
            if rect.collidepoint(pos):
                self._select_faction(faction.side)
                return
        for rect, item in self._character_rows():
            if rect.collidepoint(pos):
                self._select_character_id(item.get("id"))
                return
        for rect, spec in self._style_rows():
            if rect.collidepoint(pos):
                self._select_style(spec.id)
                return

    # --- геометрия ---------------------------------------------------

    def _faction_rows(self):
        rows = []
        y = LEFT_RECT.y + 46
        for faction in self._factions():
            rect = pygame.Rect(
                LEFT_RECT.x + 8,
                y,
                LEFT_RECT.width - 16,
                FACTION_ROW_H - 4,
            )
            rows.append((rect, faction))
            y += FACTION_ROW_H
        return rows

    def _characters_header_y(self):
        rows = self._faction_rows()
        if not rows:
            return LEFT_RECT.y + 46
        return rows[-1][0].bottom + 16

    def _visible_characters(self):
        start = self._characters_header_y() + 24
        return max(1, (LEFT_RECT.bottom - 10 - start) // CHARACTER_ROW_H)

    def _character_rows(self):
        rows = []
        y = self._characters_header_y() + 24
        options = self._characters_for(self.side)
        visible = self._visible_characters()
        start = max(
            0, min(self.character_scroll, len(options) - visible)
        )
        for item in options[start : start + visible]:
            rect = pygame.Rect(
                LEFT_RECT.x + 8,
                y,
                LEFT_RECT.width - 16,
                CHARACTER_ROW_H - 2,
            )
            rows.append((rect, item))
            y += CHARACTER_ROW_H
        return rows

    def _style_rows(self):
        if self.style_engine is None:
            return []
        specs = list(self.style_engine.specs())
        if not specs:
            return []
        per_row = min(4, len(specs))
        width = (
            RIGHT_RECT.width - 24 - 4 * (per_row - 1)
        ) // per_row
        rows = []
        for index, spec in enumerate(specs):
            row = index // per_row
            column = index % per_row
            rect = pygame.Rect(
                RIGHT_RECT.x + 12 + column * (width + 4),
                RIGHT_RECT.y + 70 + row * 28,
                width,
                24,
            )
            rows.append((rect, spec))
        return rows

    def _style_description_y(self):
        rows = self._style_rows()
        if not rows:
            return RIGHT_RECT.y + 76
        return rows[-1][0].bottom + 8

    def _chat_rect(self):
        top = self._style_description_y() + 20
        return pygame.Rect(
            RIGHT_RECT.x + 12,
            top,
            RIGHT_RECT.width - 24,
            RIGHT_RECT.bottom - top - 12,
        )

    def _send_rect(self):
        return pygame.Rect(
            INPUT_RECT.right - 108,
            INPUT_RECT.y + 5,
            100,
            36,
        )

    # --- отрисовка ---------------------------------------------------

    def draw(self, screen):
        screen.fill((13, 16, 24))
        screen.blit(
            self.app.font_title.render("СВЯЗЬ", True, TEXT), (24, 12)
        )
        screen.blit(
            self.app.font_small.render(
                "Выберите автомат, собеседника и стиль ответа.",
                True,
                MUTED,
            ),
            (24, 52),
        )
        _button(
            screen,
            BACK_RECT,
            "Назад",
            self.app.font_small,
            enabled=True,
        )

        _panel(screen, LEFT_RECT)
        screen.blit(
            self.app.font_small.render(
                "ФРАКЦИИ-АВТОМАТЫ", True, MUTED
            ),
            (LEFT_RECT.x + 12, LEFT_RECT.y + 12),
        )
        for rect, faction in self._faction_rows():
            active = faction.side == self.side
            pygame.draw.rect(
                screen,
                (34, 52, 78) if active else (25, 31, 43),
                rect,
                border_radius=5,
            )
            pygame.draw.rect(
                screen,
                ACCENT if active else PANEL_BORDER,
                rect,
                2 if active else 1,
                border_radius=5,
            )
            label = faction.name
            if faction.side == getattr(
                self.campaign, "player_side", ""
            ):
                label += " · вы"
            screen.blit(
                self.app.font_small.render(label, True, TEXT),
                (rect.x + 8, rect.y + 6),
            )

        header_y = self._characters_header_y()
        screen.blit(
            self.app.font_small.render("СОБЕСЕДНИКИ", True, MUTED),
            (LEFT_RECT.x + 12, header_y),
        )
        options = self._characters_for(self.side)
        visible = self._visible_characters()
        if len(options) > visible:
            hint = "%d–%d из %d" % (
                self.character_scroll + 1,
                min(
                    len(options),
                    self.character_scroll + visible,
                ),
                len(options),
            )
            screen.blit(
                self.app.font_tiny.render(hint, True, DIM),
                (LEFT_RECT.right - 80, header_y + 2),
            )
        for rect, item in self._character_rows():
            active = str(item.get("id")) == self.character_id
            alive = self._alive(item)
            pygame.draw.rect(
                screen,
                (30, 46, 68) if active else (22, 27, 37),
                rect,
                border_radius=4,
            )
            if active:
                pygame.draw.rect(
                    screen, ACCENT, rect, 1, border_radius=4
                )
            label = str(item.get("name") or "")
            if item.get("is_leader"):
                label = "* " + label
            screen.blit(
                self.app.font_tiny.render(
                    label, True, TEXT if alive else DIM
                ),
                (rect.x + 8, rect.y + 4),
            )

        _panel(screen, RIGHT_RECT)
        screen.blit(
            self.app.font_small.render(self._agent_name(), True, TEXT),
            (RIGHT_RECT.x + 12, RIGHT_RECT.y + 10),
        )
        screen.blit(
            self.app.font_tiny.render(
                self._agent_subtitle(), True, MUTED
            ),
            (RIGHT_RECT.x + 12, RIGHT_RECT.y + 32),
        )
        screen.blit(
            self.app.font_tiny.render(
                "СТИЛЬ ОТВЕТА", True, MUTED
            ),
            (RIGHT_RECT.x + 12, RIGHT_RECT.y + 52),
        )
        for rect, spec in self._style_rows():
            _button(
                screen,
                rect,
                spec.label,
                self.app.font_tiny,
                active=spec.id == self.style_id,
            )
        spec = self._style_spec()
        if spec is not None:
            screen.blit(
                self.app.font_tiny.render(
                    spec.description, True, DIM
                ),
                (RIGHT_RECT.x + 12, self._style_description_y()),
            )
        self._draw_chat(screen)
        self._draw_input(screen)
        if self.message:
            screen.blit(
                self.app.font_tiny.render(self.message, True, BAD),
                (24, 672),
            )

    def _message_blocks(self, rect):
        history = self._history()
        if not history:
            return []
        player = self._player_name()
        agent = self._agent_name()
        blocks = []
        for item in history:
            role = item.get("role")
            if role == "player":
                label = player + ":"
                color = ACCENT
                fill = PLAYER_BG
            elif role == "system":
                label = "Система:"
                color = WARN
                fill = AGENT_BG
            else:
                label = agent + ":"
                color = GOOD
                fill = AGENT_BG
            lines = wrap_text(
                self.app.font_tiny,
                str(item.get("text") or ""),
                rect.width - 16,
            )
            height = (
                line_height(self.app.font_tiny)
                + len(lines) * line_height(self.app.font_tiny)
                + 8
            )
            blocks.append((label, color, fill, lines, height))
        return blocks

    def _draw_chat(self, screen):
        rect = self._chat_rect()
        pygame.draw.rect(screen, (14, 18, 26), rect, border_radius=6)
        pygame.draw.rect(
            screen, PANEL_BORDER, rect, 1, border_radius=6
        )
        blocks = self._message_blocks(rect)
        if not blocks:
            hint = [
                "Свободный чат: спросите о мире, войне, фракции или персонаже.",
                "Стиль меняет только форму ответа, но не факты и не вывод.",
                "Enter — отправить, ESC — вернуться.",
            ]
            y = rect.y + 12
            for line in hint:
                screen.blit(
                    self.app.font_tiny.render(line, True, DIM),
                    (rect.x + 8, y),
                )
                y += 20
            return

        lh = line_height(self.app.font_tiny)
        total = sum(block[4] for block in blocks)
        start = 0
        while total > rect.height - 12 and start < len(blocks) - 1:
            total -= blocks[start][4]
            start += 1
        y = rect.bottom - 6 - total
        old_clip = screen.get_clip()
        screen.set_clip(rect)
        for label, color, fill, lines, height in blocks[start:]:
            pygame.draw.rect(
                screen,
                fill,
                pygame.Rect(
                    rect.x + 4,
                    y,
                    rect.width - 8,
                    height - 2,
                ),
                border_radius=4,
            )
            screen.blit(
                self.app.font_tiny.render(label, True, color),
                (rect.x + 10, y + 2),
            )
            line_y = y + 2 + lh
            for line in lines:
                screen.blit(
                    self.app.font_tiny.render(line, True, TEXT),
                    (rect.x + 10, line_y),
                )
                line_y += lh
            y += height
        screen.set_clip(old_clip)

    def _draw_input(self, screen):
        pygame.draw.rect(
            screen, (20, 26, 36), INPUT_RECT, border_radius=6
        )
        pygame.draw.rect(
            screen,
            ACCENT if self.focused else PANEL_BORDER,
            INPUT_RECT,
            2,
            border_radius=6,
        )
        text = self.input_text
        if not text:
            text = "Напишите сообщение..."
            color = DIM
        else:
            color = TEXT
        max_width = self._send_rect().x - INPUT_RECT.x - 20
        while text and self.app.font_small.size(text)[0] > max_width:
            text = text[1:]
        screen.blit(
            self.app.font_small.render(text, True, color),
            (INPUT_RECT.x + 10, INPUT_RECT.y + 12),
        )
        _button(
            screen,
            self._send_rect(),
            "Отправить",
            self.app.font_small,
            enabled=bool(self.input_text.strip()),
        )
