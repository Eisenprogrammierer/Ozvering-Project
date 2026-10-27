import random
import zlib

import pygame

from .screen_manager import BaseScreen
from .widgets import Button, Panel
from .asset_loader import AssetLoader
from .text_layout import draw_fitted, wrap_text
from view.support.traits import get_report_noise_modifier
from view.support.needs import SUPPLY_LABELS
from view.support.log_journal import get_logger

logger = get_logger("view.overlays")

RADIO_OPEN_SIZE = (230, 292)
RADIO_OPEN_POS = (735, 215)
RADIO_LOG_RECT = pygame.Rect(310, 520, 650, 92)
RADIO_PAGE_SIZE = 7

NOTEBOOK_RECT = pygame.Rect(-60, -20, 1400, 760)
LEFT_PAGE_RECT = pygame.Rect(160, 90, 410, 530)
RIGHT_PAGE_RECT = pygame.Rect(630, 90, 410, 530)
LEFT_PAGE_ANGLE = -1.5
RIGHT_PAGE_ANGLE = -1.5
INK_COLOR = (35, 30, 25)
ARROW_COLOR = (95, 85, 75)
TEXT_BOTTOM_MARGIN = 48

EQUIPMENT_LABELS = {
    "U_tanks": "танки",
    "U_sp_guns": "САУ",
    "U_at_guns": "ПТ-САУ",
    "U_artillery": "орудия",
    "U_mlrs": "РСЗО",
    "U_otrk": "ОТРК",
    "U_sam": "ЗРК",
}


def _wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip()
        if font.size(test_line)[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines


class OverlayScreen(BaseScreen):

    def __init__(self, app, rect):
        super().__init__(app)
        self.panel = Panel(rect)
        self.close_btn = Button(
            (rect[0] + rect[2] - 46, rect[1] + 8, 38, 34),
            "X",
            app.font_body,
            app.manager.pop,
        )

    def draw_base(self, screen, title):
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        t = self.app.font_body.render(title, True, (220, 220, 230))
        screen.blit(t, (self.panel.rect.x + 20, self.panel.rect.y + 14))
        self.close_btn.draw(screen)


class NotebookOverlay(OverlayScreen):

    def __init__(self, app):
        super().__init__(app, tuple(NOTEBOOK_RECT))
        tabs_data = [dict(t) for t in app.content.notebook.get("tabs", [])]
        tabs_data.append(self._build_live_tab(app))
        self.content_lines = []
        for i, tab in enumerate(tabs_data):
            if i > 0:
                self.content_lines.append(("separator", ""))
            label = tab.get("label", "")
            if label:
                self.content_lines.append(("heading", label))
            for line in tab.get("lines", []):
                self.content_lines.append(("line", line))

        self.notebook_img = AssetLoader.load(
            "items/notebook_open", NOTEBOOK_RECT.size
        )
        self.spreads = self._build_spreads()
        self.page = 0
        self.prev_rect = pygame.Rect(
            LEFT_PAGE_RECT.x + 18,
            LEFT_PAGE_RECT.bottom - 42,
            24,
            20,
        )
        self.next_rect = pygame.Rect(
            RIGHT_PAGE_RECT.right - 42,
            RIGHT_PAGE_RECT.bottom - 42,
            24,
            20,
        )
        logger.info(
            "Блокнот открыт: вкладок=%d, строк=%d, разворотов=%d",
            len(tabs_data),
            len(self.content_lines),
            len(self.spreads),
        )

    def _order_label(self, st, idx):
        cfg = st.class_configs[st.class_ids[idx]]
        if "order" not in cfg.segment_layout.segments:
            return "—"
        val = st.read_segment(idx, "order")
        ot = getattr(self.app.engine, "order_table", None)
        if ot is not None and 0 <= val < len(ot.orders):
            return ot.orders[val]["label"]
        return st.get_segment_label(idx, "order")

    def _unit_report_line(self, st, idx):
        head = st.label_of(idx)
        if st.factions[idx] != st.factions[st.player_idx]:
            head += " (противник)"
        parts = []
        cfg = st.class_configs[st.class_ids[idx]]
        if "U_manpower" in cfg.voltage_layout.channel_index:
            parts.append(f"л.с. {st.read_voltage(idx, 'U_manpower'):.0f}")
        if "U_casualties" in cfg.voltage_layout.channel_index:
            parts.append(f"потери {st.read_voltage(idx, 'U_casualties'):.0%}")
        for ch, name in EQUIPMENT_LABELS.items():
            if ch in cfg.voltage_layout.channel_index:
                v = st.read_voltage(idx, ch)
                if v > 0:
                    parts.append(f"{name}: {v:.0f}")
        if "order" in cfg.segment_layout.segments:
            parts.append(f"приказ: {self._order_label(st, idx)}")
        if parts:
            return f"{head} — {', '.join(parts)}"
        return head

    def _build_live_tab(self, app):
        st = app.engine.state
        lines = ["Сводка на момент открытия:"]
        for i in range(st.count):
            cfg = st.class_configs[st.class_ids[i]]
            if cfg.class_name != "military_unit":
                continue
            lines.append(self._unit_report_line(st, i))
        return {"id": "live", "label": "Донесения", "lines": lines}

    def _line_height(self, kind):
        if kind == "heading":
            return self.app.font_body.get_height() + 10
        if kind == "separator":
            return 16
        return self.app.font_small.get_height() + 6

    def _build_spreads(self):
        page_w = min(LEFT_PAGE_RECT.width, RIGHT_PAGE_RECT.width)
        left_h = LEFT_PAGE_RECT.height - TEXT_BOTTOM_MARGIN
        right_h = RIGHT_PAGE_RECT.height - TEXT_BOTTOM_MARGIN
        spreads = []
        left = []
        right = []
        side = "left"
        y = 0
        for kind, text in self.content_lines:
            if kind == "separator":
                entries = [("separator", "")]
            elif kind == "heading":
                entries = [
                    ("heading", w)
                    for w in _wrap_text(text, self.app.font_body, page_w)
                ]
            else:
                entries = [
                    ("line", w)
                    for w in _wrap_text(text, self.app.font_small, page_w)
                ]
            for entry_kind, entry_text in entries:
                h = self._line_height(entry_kind)
                limit = left_h if side == "left" else right_h
                if y + h > limit:
                    if side == "left":
                        side = "right"
                        y = 0
                    else:
                        spreads.append((left, right))
                        left = []
                        right = []
                        side = "left"
                        y = 0
                if side == "left":
                    left.append((entry_kind, entry_text))
                else:
                    right.append((entry_kind, entry_text))
                y += h
        if left or right:
            spreads.append((left, right))
        if not spreads:
            spreads.append(([], []))
        return spreads

    def _blit_page(self, screen, lines, page_rect, angle):
        if not lines:
            return
        line_heights = [self._line_height(k) for k, _ in lines]
        height = sum(line_heights)
        temp = pygame.Surface(
            (page_rect.width, max(height, 1)), pygame.SRCALPHA
        )
        y = 0
        for (kind, text), lh in zip(lines, line_heights):
            if kind == "heading":
                surf = self.app.font_body.render(text, True, INK_COLOR)
                temp.blit(surf, (0, y))
            elif kind == "separator":
                pygame.draw.line(
                    temp,
                    (120, 100, 70),
                    (0, y + lh // 2),
                    (page_rect.width, y + lh // 2),
                    1,
                )
            else:
                surf = self.app.font_small.render(text, True, INK_COLOR)
                temp.blit(surf, (0, y))
            y += lh
        rotated = pygame.transform.rotate(temp, angle)
        dest = rotated.get_rect()
        dest.center = (
            page_rect.centerx,
            page_rect.y + dest.height // 2 + 6,
        )
        screen.blit(rotated, dest)

    def _draw_arrow(self, screen, rect, direction):
        if direction == "next":
            points = [
                (rect.left + 4, rect.top + 2),
                (rect.left + 4, rect.bottom - 2),
                (rect.right - 2, rect.centery),
            ]
        else:
            points = [
                (rect.right - 4, rect.top + 2),
                (rect.right - 4, rect.bottom - 2),
                (rect.left + 2, rect.centery),
            ]
        pygame.draw.polygon(screen, ARROW_COLOR, points)

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            logger.info("Блокнот: переход на разворот %d", self.page + 1)

    def next_page(self):
        if self.page < len(self.spreads) - 1:
            self.page += 1
            logger.info("Блокнот: переход на разворот %d", self.page + 1)

    def handle_event(self, event):
        if self.close_btn.handle_event(event):
            return
        if event.type == pygame.MOUSEWHEEL:
            if event.y < 0:
                self.next_page()
            elif event.y > 0:
                self.prev_page()
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.next_rect.collidepoint(event.pos):
                self.next_page()
            elif self.prev_rect.collidepoint(event.pos):
                self.prev_page()

    def draw(self, screen):
        overlay = pygame.Surface((1280, 720), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        screen.blit(overlay, (0, 0))
        screen.blit(self.notebook_img, NOTEBOOK_RECT.topleft)
        left_lines, right_lines = self.spreads[self.page]
        self._blit_page(screen, left_lines, LEFT_PAGE_RECT, LEFT_PAGE_ANGLE)
        self._blit_page(screen, right_lines, RIGHT_PAGE_RECT, RIGHT_PAGE_ANGLE)
        info = f"{self.page + 1} / {len(self.spreads)}"
        info_surf = self.app.font_small.render(info, True, INK_COLOR)
        screen.blit(
            info_surf,
            (
                RIGHT_PAGE_RECT.centerx - info_surf.get_width() // 2,
                RIGHT_PAGE_RECT.bottom - 36,
            ),
        )
        self._draw_arrow(screen, self.prev_rect, "prev")
        self._draw_arrow(screen, self.next_rect, "next")
        self.close_btn.draw(screen)


class BinocularsOverlay(BaseScreen):

    SECTORS = ("front", "left", "right")
    PANEL_RECT = pygame.Rect(260, 410, 760, 230)
    TEXT_RECT = pygame.Rect(282, 430, 716, 148)
    LINE_HEIGHT = 24
    STAGE_WAIT_SECONDS = 300
    TYPE_LABELS = {
        "tanks": "танки",
        "infantry": "пехота",
        "fortifications": "фортификации",
    }
    ORDER_SCALE = (
        "aggressive_attack",
        "attack",
        "cautious_attack",
        "holding_defense",
        "defense",
        "desperate_defense",
    )
    TENDENCY_LABELS = {
        "attack": "маневрируют",
        "move": "в движении",
        "defense": "держат оборону",
        "rest": "в районах отдыха",
    }

    def __init__(self, app):
        super().__init__(app)
        self.current = 0
        self.stage = 0
        self.names = ["Фронт", "Левый фланг", "Правый фланг"]
        self.sector_buttons = [
            Button(
                (280, 650, 200, 40),
                self.names[0],
                app.font_small,
                lambda: self.set_view(0),
            ),
            Button(
                (540, 650, 200, 40),
                self.names[1],
                app.font_small,
                lambda: self.set_view(1),
            ),
            Button(
                (800, 650, 200, 40),
                self.names[2],
                app.font_small,
                lambda: self.set_view(2),
            ),
        ]
        self.close_btn = Button(
            (1235, 12, 40, 34), "X", app.font_body, self.cancel_and_close
        )
        self.panel = Panel(self.PANEL_RECT)
        self.btn_stop = Button(
            (
                self.PANEL_RECT.x + 22,
                self.PANEL_RECT.bottom - 52,
                240,
                42,
            ),
            "Прекратить",
            app.font_body,
            self.cancel_and_close,
        )
        self.btn_continue = Button(
            (
                self.PANEL_RECT.right - 262,
                self.PANEL_RECT.bottom - 52,
                240,
                42,
            ),
            "Продолжить",
            app.font_body,
            self.advance_observation,
        )
        logger.info("Бинокль открыт")

    def set_view(self, i):
        self.current = i
        self.stage = 0
        self.btn_continue.text = "Продолжить"

    def cancel_and_close(self):
        ts = getattr(self.app, "time_system", None)
        if (
            ts is not None
            and ts.active_action
            and ts.active_action.definition_id == "binoculars_recon"
        ):
            ts.cancel_active_action()
        self.app.manager.pop()

    def advance_observation(self):
        if self.stage >= 3:
            self.app.manager.pop()
            return
        ts = getattr(self.app, "time_system", None)
        if ts is not None:
            ts.wait(self.STAGE_WAIT_SECONDS)
        self.stage += 1
        if self.stage >= 3:
            self.btn_continue.text = "Завершить"

    def _fatigue(self):
        ts = getattr(self.app, "time_system", None)
        if ts is None:
            return 0.0
        return float(ts.get_fatigue())

    def _noise_mult(self):
        trait_mult = get_report_noise_modifier(self.app)
        mult = trait_mult * (1.0 + 1.5 * self._fatigue())
        return max(0.25, min(3.0, mult))

    def _noise_rng(self, sector):
        ts = getattr(self.app, "time_system", None)
        day = ts.day if ts is not None else 1
        seed = zlib.crc32(f"{sector}:{day}".encode("utf-8"))
        return random.Random(seed)

    def _is_dead(self, idx):
        st = self.app.engine.state
        cfg = st.class_configs[st.class_ids[idx]]
        if "condition" in cfg.segment_layout.segments:
            if st.read_segment(idx, "condition") == 0:
                return True
        ch = cfg.voltage_layout.channel_index.get("U_manpower")
        if ch is not None and st.read_voltage(idx, "U_manpower") <= 0:
            return True
        return False

    def _voltage(self, idx, channel):
        st = self.app.engine.state
        cfg = st.class_configs[st.class_ids[idx]]
        if channel not in cfg.voltage_layout.channel_index:
            return 0.0
        return float(st.read_voltage(idx, channel))

    def _order_id(self, idx):
        st = self.app.engine.state
        cfg = st.class_configs[st.class_ids[idx]]
        if "order" not in cfg.segment_layout.segments:
            return "rest"
        val = st.read_segment(idx, "order")
        ot = getattr(self.app.engine, "order_table", None)
        if ot is not None and 0 <= val < len(ot.orders):
            return ot.orders[val]["id"]
        return "rest"

    def _order_label(self, order_id):
        ot = getattr(self.app.engine, "order_table", None)
        if ot is not None:
            idx = ot.id_to_index.get(order_id)
            if idx is not None:
                return ot.orders[idx]["label"]
        return order_id

    def _sector_enemies(self, sector):
        from view.support.geometry import direction_between

        st = self.app.engine.state
        p = st.player_idx
        result = []
        for i in range(st.count):
            if i == p:
                continue
            cfg = st.class_configs[st.class_ids[i]]
            if cfg.class_name != "military_unit":
                continue
            if st.factions[i] == st.factions[p]:
                continue
            if self._is_dead(i):
                continue
            d = direction_between(
                st.coords[p, 0],
                st.coords[p, 1],
                st.coords[i, 0],
                st.coords[i, 1],
            )
            if d is None:
                continue
            rel = (d - st.headings[p]) % 4
            s = {0: "front", 1: "right", 3: "left"}.get(rel)
            if s == sector:
                result.append(i)
        return result

    def _sector_stats(self, sector):
        st = self.app.engine.state
        stats = {
            "companies": 0,
            "manpower": 0.0,
            "tanks": 0.0,
            "guns": 0.0,
            "orders": {},
        }
        for i in self._sector_enemies(sector):
            cfg = st.class_configs[st.class_ids[i]]
            if "size" in cfg.segment_layout.segments:
                if st.read_segment(i, "size") != 1:
                    continue
            stats["companies"] += 1
            stats["manpower"] += self._voltage(i, "U_manpower")
            stats["tanks"] += self._voltage(i, "U_tanks")
            stats["guns"] += sum(
                self._voltage(i, ch)
                for ch in (
                    "U_sp_guns",
                    "U_at_guns",
                    "U_artillery",
                    "U_mlrs",
                )
            )
            oid = self._order_id(i)
            stats["orders"][oid] = stats["orders"].get(oid, 0.0) + 1
        return stats

    def _dominant_order(self, stats):
        orders = stats["orders"]
        if not orders:
            return "rest"
        return max(orders, key=orders.get)

    def _tendency_of(self, order_id):
        if order_id in (
            "aggressive_attack",
            "attack",
            "cautious_attack",
        ):
            return "attack"
        if order_id in ("move", "forced_march"):
            return "move"
        if order_id in (
            "holding_defense",
            "defense",
            "desperate_defense",
        ):
            return "defense"
        return "rest"

    def _noised_order(self, rng, mult, order_id):
        if order_id not in self.ORDER_SCALE:
            return order_id
        if rng.random() >= min(0.5, 0.25 * mult):
            return order_id
        idx = self.ORDER_SCALE.index(order_id)
        idx += rng.choice((-1, 1))
        idx = max(0, min(len(self.ORDER_SCALE) - 1, idx))
        return self.ORDER_SCALE[idx]

    def _true_type(self, stats):
        if stats["tanks"] >= 10:
            return "tanks"
        if (
            stats["guns"] >= 8
            and self._tendency_of(self._dominant_order(stats)) == "defense"
        ):
            return "fortifications"
        return "infantry"

    def _report_lines(self, sector):
        stats = self._sector_stats(sector)
        if self.stage == 0:
            return ["Наблюдение начато. Продолжайте смотреть."]
        if stats["companies"] == 0:
            return ["Противник в секторе не обнаружен."]
        rng = self._noise_rng(sector)
        mult = self._noise_mult()
        fatigue = self._fatigue()
        lines = []
        if self.stage == 1:
            size_word = "много" if stats["manpower"] >= 1200 else "немного"
            true_type = self._true_type(stats)
            p_error = min(0.45, 0.15 * mult)
            if rng.random() < p_error:
                guessed = rng.choice(
                    [t for t in self.TYPE_LABELS if t != true_type]
                )
            else:
                guessed = true_type
            lines.append(f"Противник замечен. Похоже, его {size_word}.")
            lines.append(f"Видимо, это {self.TYPE_LABELS[guessed]}.")
        elif self.stage == 2:
            companies = max(1.0, stats["manpower"] / 450.0)
            spread = 0.25 * mult
            lo = max(1, int(companies * max(0.5, 1.0 - spread)))
            hi = max(lo, int(round(companies * (1.0 + spread))))
            noised = self._noised_order(rng, mult, self._dominant_order(stats))
            tendency = self.TENDENCY_LABELS[self._tendency_of(noised)]
            lines.append(
                f"{lo}-{hi} рот "
                f"({self.TYPE_LABELS[self._true_type(stats)]}), "
                f"{tendency}."
            )
            if stats["tanks"] > 0:
                rough = max(
                    0,
                    int(
                        stats["tanks"]
                        * rng.uniform(
                            max(0.5, 1 - 0.4 * mult),
                            1 + 0.4 * mult,
                        )
                    ),
                )
                lines.append(f"Бронетехника: примерно {rough} машин.")
        else:
            mp_err = min(0.5, 0.10 * mult)
            tech_err = min(0.5, 0.15 * mult)
            mp = max(
                0,
                int(
                    round(
                        stats["manpower"]
                        * rng.uniform(1 - mp_err, 1 + mp_err)
                        / 10
                    )
                    * 10
                ),
            )
            lines.append(f"Насчитано: л.с. ~ {mp}.")
            if stats["tanks"] > 0:
                tanks = max(
                    0,
                    int(
                        round(
                            stats["tanks"]
                            * rng.uniform(1 - tech_err, 1 + tech_err)
                        )
                    ),
                )
                lines.append(f"Танки ~ {tanks}.")
            if stats["guns"] > 0:
                guns = max(
                    0,
                    int(
                        round(
                            stats["guns"]
                            * rng.uniform(1 - tech_err, 1 + tech_err)
                        )
                    ),
                )
                lines.append(f"Орудия/САУ ~ {guns}.")
            lines.append(
                f"Приказ противника: "
                f"{self._order_label(self._dominant_order(stats))}."
            )
        lines.append(
            f"Поправка наблюдателя: x{mult:.2f} " f"(усталость {fatigue:.0%})."
        )
        return lines

    def _view_asset(self):
        sector = self.SECTORS[self.current]
        stats = self._sector_stats(sector)
        if stats["companies"] == 0:
            return None
        rng = self._noise_rng(sector)
        true_type = self._true_type(stats)
        if self.stage <= 1:
            p_error = min(0.45, 0.15 * self._noise_mult())
            if rng.random() < p_error:
                shown = rng.choice(
                    [t for t in self.TYPE_LABELS if t != true_type]
                )
            else:
                shown = true_type
        else:
            shown = true_type
        qty = "many" if stats["manpower"] >= 1200 else "few"
        return f"views/{shown}_{qty}"

    def handle_event(self, event):
        if self.close_btn.handle_event(event):
            return
        if self.btn_stop.handle_event(event):
            return
        if self.btn_continue.handle_event(event):
            return
        for b in self.sector_buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        screen.fill((0, 0, 0))
        asset = self._view_asset()
        if asset:
            img = AssetLoader.load(asset, (1080, 720))
            screen.blit(img, ((1280 - 1080) // 2, 0))
        else:
            caption = self.app.font_body.render(
                "В секторе никого не видно.", True, (160, 160, 170)
            )
            screen.blit(caption, caption.get_rect(center=(640, 340)))
        self.panel.draw(screen)
        lines = self._report_lines(self.SECTORS[self.current])
        screen.set_clip(self.TEXT_RECT)
        y = self.TEXT_RECT.top
        for raw in lines:
            if y > self.TEXT_RECT.bottom - self.LINE_HEIGHT:
                break
            for wrapped in _wrap_text(
                raw, self.app.font_small, self.TEXT_RECT.width
            ):
                if y > self.TEXT_RECT.bottom - self.LINE_HEIGHT:
                    break
                screen.blit(
                    self.app.font_small.render(wrapped, True, (230, 230, 235)),
                    (self.TEXT_RECT.left, y),
                )
                y += self.LINE_HEIGHT
        screen.set_clip(None)
        self.btn_stop.draw(screen)
        self.btn_continue.draw(screen)
        for b in self.sector_buttons:
            b.draw(screen)
        self.close_btn.draw(screen)


class LogisticsOverlay(OverlayScreen):

    OPERATION_LABELS = {
        "fortify": "Укрепить позицию",
        "fierce_attack": "Усилить натиск",
        "active_defense": "Активная оборона",
        "medevac": "Медицинская эвакуация",
        "morale_boost": "Поднять дух",
    }

    def __init__(self, app):
        super().__init__(app, (200, 40, 880, 640))
        self.feedback = ""
        self._op_buttons = []
        self._convoy_buttons = []
        self._target_buttons = []
        self.rts = self._find_rts()
        self._targets = set()
        panel = self.panel.rect
        rx = panel.x + 500
        y = panel.y + 126
        for op_id in (
            "fortify",
            "fierce_attack",
            "active_defense",
            "medevac",
            "morale_boost",
        ):
            btn = Button(
                (rx, y, 350, 30),
                self.OPERATION_LABELS.get(op_id, op_id),
                app.font_tiny,
                lambda oid=op_id: self.apply_operation(oid),
            )
            self._op_buttons.append((op_id, btn))
            y += 46
        y = panel.y + 390
        for kind, label in (
            ("general", "Общий конвой"),
            ("water", "Питьевая вода"),
            ("ammo", "Боеприпасы"),
            ("medical", "Медикаменты"),
            ("fuel", "Горючее"),
        ):
            btn = Button(
                (rx, y, 350, 28),
                label,
                app.font_tiny,
                lambda k=kind: self.request_convoy(k),
            )
            self._convoy_buttons.append((kind, btn))
            y += 31
        self._init_targets()
        self._build_target_buttons()

    def _find_rts(self):
        for screen in reversed(getattr(self.app.manager, "stack", [])):
            if hasattr(screen, "_selected_dets"):
                return screen
        return None

    def _player_units(self):
        state = self.app.engine.state
        return [
            det
            for det in state.units
            if det.side == state.player_side
            and not getattr(det, "broken", False)
            and det.force > 1
        ]

    def _init_targets(self):
        selected = []
        if self.rts is not None and hasattr(self.rts, "_selected_dets"):
            selected = [
                det.name
                for det in self.rts._selected_dets()
                if det.side == self.app.engine.state.player_side
            ]
        if selected:
            self._targets = set(selected)
        else:
            self._targets = {det.name for det in self._player_units()}

    def _build_target_buttons(self):
        panel = self.panel.rect
        x = panel.x + 16
        top = panel.y + 316
        button_y = panel.bottom - 30
        units = self._player_units()
        available = max(1, button_y - 8 - top)
        row_h = min(19, max(14, available // max(1, len(units))))
        self._target_row_h = row_h
        y = top
        for det in units:
            btn = Button(
                (x, y, 360, row_h - 2),
                "[ ] %s" % det.name,
                self.app.font_tiny,
                lambda name=det.name: self.toggle_target(name),
                alpha=120,
            )
            self._target_buttons.append((det.name, btn))
            y += row_h
        self.btn_all = Button(
            (x, button_y, 174, 22),
            "Все",
            self.app.font_tiny,
            self.select_all_targets,
        )
        self.btn_none = Button(
            (x + 186, button_y, 174, 22),
            "Никого",
            self.app.font_tiny,
            self.clear_targets,
        )

    def _selected_idx(self):
        state = self.app.engine.state
        for index, det in enumerate(state.units):
            if det.name in self._targets:
                return index
        if self.rts is not None and self.rts.selected:
            return self.rts.selected[0]
        return state.player_idx

    def toggle_target(self, name):
        if name in self._targets:
            self._targets.discard(name)
        else:
            self._targets.add(name)
        self.feedback = "Целей: %d" % len(self._targets)

    def select_all_targets(self):
        self._targets = {name for name, _btn in self._target_buttons}
        self.feedback = "Выбраны все роты"

    def clear_targets(self):
        self._targets.clear()
        self.feedback = "Цели не выбраны"

    def apply_operation(self, op_id):
        ls = self.app.engine.state.logistics
        targets = [
            name
            for name, _btn in self._target_buttons
            if name in self._targets
        ]
        if not targets:
            self.feedback = "Выберите хотя бы одну роту"
            return
        result = ls.apply_operation(op_id, targets)
        if result.get("ok"):
            self.feedback = "Выполнено для %d %s" % (
                result.get("count", len(targets)),
                "роты" if result.get("count", len(targets)) == 1 else "рот",
            )
        else:
            self.feedback = result.get("reason", "Нет")

    def request_convoy(self, kind):
        ls = self.app.engine.state.logistics
        result = ls.request_convoy(kind)
        if result.get("ok"):
            self.feedback = "Конвой в пути: ETA %d мин · риск %d%%" % (
                result.get("eta_minutes", 0),
                round(float(result.get("risk", 0.0)) * 100),
            )
        else:
            self.feedback = result.get("reason", "Нет влияния")

    def handle_event(self, event):
        for _oid, btn in self._op_buttons:
            if btn.handle_event(event):
                return
        for _kind, btn in self._convoy_buttons:
            if btn.handle_event(event):
                return
        for _name, btn in self._target_buttons:
            if btn.handle_event(event):
                return
        if self.btn_all.handle_event(event):
            return
        if self.btn_none.handle_event(event):
            return
        if self.close_btn.handle_event(event):
            return

    def _alive_target_names(self):
        alive = {det.name for det in self._player_units()}
        self._targets &= alive
        return alive

    def draw(self, screen):
        self.draw_base(screen, "Логистика дивизии")
        st = self.app.engine.state
        ls = getattr(st, "logistics", None)
        panel = self.panel.rect
        if ls is None:
            screen.blit(
                self.app.font_body.render(
                    "Логистическая система не активна.", True, (200, 100, 100)
                ),
                (panel.x + 20, panel.y + 80),
            )
            self.close_btn.draw(screen)
            return
        self._alive_target_names()
        count = len(self._targets)
        idx = self._selected_idx()
        det = st.det_at(idx)
        draw_fitted(
            screen,
            [self.app.font_tiny],
            "Склад, расход и готовность. Отметьте цели слева; стоимость "
            "операции растёт с числом рот.",
            pygame.Rect(panel.x + 20, panel.y + 44, panel.width - 40, 16),
            (150, 165, 180),
        )
        if det is not None:
            draw_fitted(
                screen,
                [self.app.font_tiny],
                "Открыто: %s · снабжение %d%%"
                % (det.name, round(ls.supply_of(idx) * 100)),
                pygame.Rect(panel.x + 20, panel.y + 61, 380, 12),
                (175, 190, 202),
            )
        if self.feedback:
            draw_fitted(
                screen,
                [self.app.font_tiny],
                self.feedback,
                pygame.Rect(
                    panel.x + 420, panel.y + 61, panel.width - 440, 12
                ),
                (224, 185, 95),
                align="right",
            )

        y = panel.y + 78
        screen.blit(
            self.app.font_small.render("СКЛАД", True, (205, 218, 230)),
            (panel.x + 20, y),
        )
        y += 24
        headers = (
            ("Класс", panel.x + 20, 104),
            ("Запас", panel.x + 132, 76),
            ("В сутки", panel.x + 224, 84),
            ("Хватит", panel.x + 330, 120),
        )
        for text, hx, width in headers:
            draw_fitted(
                screen,
                [self.app.font_tiny],
                text,
                pygame.Rect(hx, y, width, 12),
                (130, 145, 158),
            )
        y += 18
        for row in ls.status_rows():
            draw_fitted(
                screen,
                [self.app.font_tiny],
                row["label"],
                pygame.Rect(panel.x + 20, y, 108, 12),
                (210, 220, 230),
            )
            draw_fitted(
                screen,
                [self.app.font_tiny],
                "%d" % round(row["stock"]),
                pygame.Rect(panel.x + 132, y, 76, 12),
                (220, 230, 238),
            )
            draw_fitted(
                screen,
                [self.app.font_tiny],
                "%.1f" % row["daily"],
                pygame.Rect(panel.x + 224, y, 84, 12),
                (165, 180, 192),
            )
            days = row["days"]
            days_text = "—" if days is None else ("%.1f дн" % days)
            color = (
                (190, 110, 100)
                if days is not None and days < 2
                else (150, 195, 160)
            )
            draw_fitted(
                screen,
                [self.app.font_tiny],
                days_text,
                pygame.Rect(panel.x + 330, y, 120, 12),
                color,
            )
            y += 18

        screen.blit(
            self.app.font_small.render(
                "ГОТОВНОСТЬ · ЦЕЛИ ОПЕРАЦИЙ", True, (205, 218, 230)
            ),
            (panel.x + 20, panel.y + 292),
        )
        by_name = {unit.name: (i, unit) for i, unit in enumerate(st.units)}
        for name, btn in self._target_buttons:
            entry = by_name.get(name)
            if entry is None:
                continue
            i, unit = entry
            value = ls.supply_of(i)
            color = (
                (96, 190, 120)
                if value >= 0.7
                else (224, 164, 74) if value >= 0.4 else (224, 88, 88)
            )
            selected = name in self._targets
            btn.text = ("[x] " if selected else "[ ] ") + unit.name
            btn.draw(screen)
            bar = pygame.Rect(panel.x + 384, btn.rect.centery - 3, 72, 6)
            pygame.draw.rect(screen, (38, 46, 55), bar)
            pygame.draw.rect(
                screen,
                color,
                (bar.x, bar.y, int(bar.width * min(1.0, value)), bar.height),
            )
            draw_fitted(
                screen,
                [self.app.font_tiny],
                "%d%%" % round(value * 100),
                pygame.Rect(panel.x + 458, btn.rect.y, 32, btn.rect.height),
                color,
                align="right",
                valign="center",
            )
        self.btn_all.draw(screen)
        self.btn_none.draw(screen)

        rx = panel.x + 500
        screen.blit(
            self.app.font_small.render("ОПЕРАЦИИ", True, (205, 218, 230)),
            (rx, panel.y + 78),
        )
        draw_fitted(
            screen,
            [self.app.font_tiny],
            "Целей: %d · цена за каждую роту" % count,
            pygame.Rect(rx, panel.y + 100, 350, 14),
            (175, 190, 202) if count else (190, 118, 118),
        )
        for op_id, btn in self._op_buttons:
            btn.draw(screen)
            effective = max(1, count)
            cost = ls.operation_cost(op_id, effective)
            cost_text = ", ".join(
                "%s %d" % (SUPPLY_LABELS.get(k, k), round(v))
                for k, v in cost.items()
            )
            ok, reason = ls.can_operation(op_id, effective)
            info = cost_text + ("" if ok else " · " + reason)
            draw_fitted(
                screen,
                [self.app.font_tiny],
                info,
                pygame.Rect(
                    btn.rect.x + 6, btn.rect.y + 31, btn.rect.width - 12, 12
                ),
                (150, 165, 178) if ok else (190, 118, 118),
            )
        screen.blit(
            self.app.font_small.render(
                "КОНВОИ (за влияние)", True, (205, 218, 230)
            ),
            (rx, panel.y + 366),
        )
        for _kind, btn in self._convoy_buttons:
            btn.draw(screen)
        influence_text = "Влияние: %d (+%.1f/ч) · автоколонна через %d мин" % (
            int(ls.stock("influence")),
            ls.influence_per_hour,
            int(round(ls.next_free_convoy_minutes)),
        )
        draw_fitted(
            screen,
            [self.app.font_tiny],
            influence_text,
            pygame.Rect(rx, panel.y + 548, 350, 14),
            (224, 185, 95),
        )

        pending = ls.convoy_status_rows()
        draw_fitted(
            screen,
            [self.app.font_tiny],
            ("В ПУТИ: %d" % len(pending)) if pending else "В ПУТИ: нет",
            pygame.Rect(rx, panel.y + 566, 350, 12),
            (175, 190, 202),
        )
        for row_index, row in enumerate(pending[:3]):
            text = "%s · %d мин · риск %d%% · %s" % (
                row["label"],
                row["eta"],
                round(row["risk"] * 100),
                row["cargo"],
            )
            draw_fitted(
                screen,
                [self.app.font_tiny],
                text,
                pygame.Rect(rx, panel.y + 580 + row_index * 14, 350, 12),
                (190, 205, 218),
            )
        self.close_btn.draw(screen)


class RadioOverlay(OverlayScreen):

    def __init__(self, app):
        super().__init__(app, (290, 90, 700, 540))
        st = app.engine.state
        self.units = [
            (i, st.entity_ids[i])
            for i in range(st.count)
            if st.class_configs[st.class_ids[i]].class_name == "military_unit"
            and st.factions[i] == "player"
        ]
        self.selected = 0
        self.page = 0
        self.log = "Выберите подразделение."
        self.log_scroll = 0
        self.log_lines = []
        self.radio_img = AssetLoader.load("items/radio_open", RADIO_OPEN_SIZE)
        self.btn_connect = Button(
            (660, 160, 280, 38),
            "Связаться",
            app.font_small,
            self.connect,
        )
        self.btn_prev = Button(
            (320, 478, 135, 24),
            "< стр.",
            app.font_small,
            self.prev_page,
        )
        self.btn_next = Button(
            (465, 478, 135, 24),
            "стр. >",
            app.font_small,
            self.next_page,
        )
        self.buttons = []
        self._build_unit_buttons()

    def _page_count(self):
        return max(
            1, (len(self.units) + RADIO_PAGE_SIZE - 1) // RADIO_PAGE_SIZE
        )

    def _display_name(self, st, idx):
        label = st.label_of(idx)
        root = idx
        guard = 0
        while st.parent_ids[root] != -1 and guard < 16:
            root = st.parent_ids[root]
            guard += 1
        root_label = st.label_of(root)
        tail = ""
        if root != idx and label.startswith(root_label):
            tail = label[len(root_label) :].strip()
        tids = getattr(st, "tactical_ids", None)
        tid = tids[idx] if tids is not None and idx < len(tids) else ""
        if tail:
            name = f"{tid} · {tail}" if tid else tail
        else:
            name = label
        if len(name) > 30:
            name = name[:27] + "..."
        return name

    def _build_unit_buttons(self):
        st = self.app.engine.state
        self.buttons = []
        start = self.page * RADIO_PAGE_SIZE
        for n, (idx, eid) in enumerate(
            self.units[start : start + RADIO_PAGE_SIZE]
        ):
            self.buttons.append(
                Button(
                    (320, 160 + n * 46, 280, 38),
                    self._display_name(st, idx),
                    self.app.font_small,
                    lambda n=start + n: self.select(n),
                )
            )

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self._build_unit_buttons()

    def next_page(self):
        if self.page < self._page_count() - 1:
            self.page += 1
            self._build_unit_buttons()

    def select(self, i):
        self.selected = i

    def connect(self):
        if not self.units:
            self.log = "Нет доступных подразделений."
            return
        idx, eid = self.units[self.selected]
        st = self.app.engine.state
        cfg = st.class_configs[st.class_ids[idx]]
        name = self._display_name(st, idx)
        manpower = None
        if "U_manpower" in cfg.voltage_layout.channel_index:
            manpower = st.read_voltage(idx, "U_manpower")
        casualties = None
        if "U_casualties" in cfg.voltage_layout.channel_index:
            casualties = st.read_voltage(idx, "U_casualties")
        equipment = []
        for ch, label in EQUIPMENT_LABELS.items():
            if ch in cfg.voltage_layout.channel_index:
                value = st.read_voltage(idx, ch)
                if value > 0:
                    equipment.append("%s %.0f" % (label, value))
        lines = [name]
        status = []
        if manpower is not None:
            status.append("л.с. %.0f" % manpower)
        if casualties is not None:
            status.append("потери %.0f%%" % (casualties * 100))
        if status:
            lines.append(" · ".join(status))
        lines.append("Техника: %s" % (", ".join(equipment) or "—"))
        lines.append("Приказ: %s" % self._order_label(st, idx))
        events = [e["message"] for e in st.event_log if e["entity_id"] == eid][
            -2:
        ]
        if events:
            lines.append("Связь: " + " / ".join(events))
        self.log = "\n".join(lines)
        self.log_scroll = 0

    def _order_label(self, st, idx):
        cfg = st.class_configs[st.class_ids[idx]]
        if "order" not in cfg.segment_layout.segments:
            return "—"
        val = st.read_segment(idx, "order")
        ot = getattr(self.app.engine, "order_table", None)
        if ot is not None and 0 <= val < len(ot.orders):
            return ot.orders[val]["label"]
        return st.get_segment_label(idx, "order")

    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL and RADIO_LOG_RECT.collidepoint(
            pygame.mouse.get_pos()
        ):
            self.log_scroll = max(0, self.log_scroll - event.y)
            return
        if self.close_btn.handle_event(event):
            return
        if self.btn_connect.handle_event(event):
            return
        if self.btn_prev.handle_event(event):
            return
        if self.btn_next.handle_event(event):
            return
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        self.draw_base(screen, "Рация")
        for b in self.buttons:
            b.draw(screen)
        self.btn_prev.draw(screen)
        self.btn_next.draw(screen)
        info = f"{self.page + 1}/{self._page_count()}"
        info_surf = self.app.font_small.render(info, True, (150, 150, 160))
        screen.blit(info_surf, (610, 482))
        self.btn_connect.draw(screen)
        if self.radio_img:
            screen.blit(self.radio_img, RADIO_OPEN_POS)

        font = self.app.font_tiny
        lines = []
        for paragraph in str(self.log).split("\n"):
            lines.extend(wrap_text(font, paragraph, RADIO_LOG_RECT.width - 10))
        self.log_lines = lines
        max_lines = max(1, (RADIO_LOG_RECT.height - 24) // 13)
        max_scroll = max(0, len(lines) - max_lines)
        self.log_scroll = max(0, min(self.log_scroll, max_scroll))
        pygame.draw.rect(screen, (9, 18, 12), RADIO_LOG_RECT, border_radius=4)
        pygame.draw.rect(
            screen, (50, 92, 58), RADIO_LOG_RECT, 1, border_radius=4
        )
        y = RADIO_LOG_RECT.top + 4
        for line in lines[self.log_scroll : self.log_scroll + max_lines]:
            screen.blit(
                font.render(line, True, (140, 220, 140)),
                (RADIO_LOG_RECT.left + 5, y),
            )
            y += 13
        if max_scroll:
            hint = self.app.font_tiny.render(
                "колесо — прокрутка (%d/%d)"
                % (self.log_scroll + 1, max_scroll + 1),
                True,
                (110, 150, 115),
            )
            screen.blit(
                hint,
                (
                    RADIO_LOG_RECT.right - hint.get_width() - 6,
                    RADIO_LOG_RECT.bottom - 13,
                ),
            )
        self.close_btn.draw(screen)


class TurnLogOverlay(OverlayScreen):

    def __init__(self, app):
        super().__init__(app, (240, 60, 800, 600))

    def handle_event(self, event):
        if self.close_btn.handle_event(event):
            return

    def draw(self, screen):
        self.draw_base(screen, "Лог последнего тика")
        y = 130
        if not self.app.engine.state.tick_events:
            screen.blit(
                self.app.font_small.render(
                    "Нет событий.", True, (180, 180, 190)
                ),
                (270, y),
            )
            return
        for event in self.app.engine.state.tick_events[-30:]:
            tick = event.get("tick", "?")
            message = event.get("message", "")
            line = f"[{tick}] {message}"
            if len(line) > 96:
                line = line[:93] + "..."
            screen.blit(
                self.app.font_small.render(line, True, (210, 210, 220)),
                (270, y),
            )
            y += 22
            if y > 620:
                break
