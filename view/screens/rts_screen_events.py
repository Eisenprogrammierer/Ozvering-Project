"""Обработка событий и кликов по UI."""

from __future__ import annotations

from .rts_screen_support import (
    MAP_RECT,
    pygame,
)


class RTSScreenEventsMixin:

    def handle_event(self, event):
        for b in (
            self.btn_pause,
            self.btn_speed1,
            self.btn_speed2,
            self.btn_speed4,
            self.btn_speed8,
            self.btn_plan_hold,
            self.btn_plan_advance,
            self.btn_plan_off,
            self.btn_hold,
            self.btn_attack,
            self.btn_cautious,
            self.btn_withdraw,
            self.btn_march,
            self.btn_rest,
            self.btn_stop,
            self.btn_orders,
            self.btn_needs,
            self.btn_journal,
            self.btn_logistics,
            self.btn_radio,
        ):
            if b.handle_event(event):
                return
        if event.type == pygame.KEYDOWN:
            group_number = {
                pygame.K_1: 1,
                pygame.K_2: 2,
                pygame.K_3: 3,
                pygame.K_4: 4,
                pygame.K_5: 5,
                pygame.K_6: 6,
            }.get(event.key)
            if group_number is not None:
                mods = getattr(event, "mod", 0)
                if mods & pygame.KMOD_CTRL:
                    self.assign_group(group_number)
                    return
                if mods & (pygame.KMOD_SHIFT | pygame.KMOD_ALT):
                    self.select_group(group_number)
                    return
            if event.key in (pygame.K_SPACE, pygame.K_p):
                self.toggle_pause()
            elif event.key == pygame.K_1:
                self.set_speed(1)
            elif event.key == pygame.K_2:
                self.set_speed(2)
            elif event.key == pygame.K_3:
                self.set_speed(4)
            elif event.key == pygame.K_4:
                self.set_speed(8)
            elif event.key == pygame.K_h:
                self.command_hold()
            elif event.key == pygame.K_g:
                self.command_plan_hold()
            elif event.key == pygame.K_t:
                self.command_plan_advance()
            elif event.key == pygame.K_y:
                self.command_plan_off()
            elif event.key == pygame.K_r:
                self.command_rest()
            elif event.key == pygame.K_a:
                if getattr(event, "mod", 0) & pygame.KMOD_CTRL:
                    self.select_all_units()
                else:
                    self.command_attack_nearest()
            elif event.key == pygame.K_c:
                self.command_cautious_attack()
            elif event.key == pygame.K_w:
                self.command_withdraw()
            elif event.key == pygame.K_m:
                self.command_force_march()
            elif event.key == pygame.K_s:
                self.command_stop()
            elif event.key == pygame.K_o:
                self.open_orders()
            elif event.key == pygame.K_n:
                self.open_needs()
            elif event.key in (
                pygame.K_PLUS,
                pygame.K_EQUALS,
                pygame.K_KP_PLUS,
            ):
                self.zoom_in()
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.zoom_out()
            elif event.key == pygame.K_0:
                self.zoom_reset()
            elif event.key == pygame.K_f:
                self.command_focus_hover()
            return
        if event.type == pygame.MOUSEWHEEL:
            if MAP_RECT.collidepoint(pygame.mouse.get_pos()):
                if event.y > 0:
                    self.zoom_in()
                elif event.y < 0:
                    self.zoom_out()
                return
        if event.type == pygame.MOUSEMOTION:
            self._hover_idx = self._unit_at(event.pos)
            if self._drag_start is not None:
                x, y = self._drag_start
                self._drag_rect = pygame.Rect(
                    min(x, event.pos[0]),
                    min(y, event.pos[1]),
                    abs(event.pos[0] - x),
                    abs(event.pos[1] - y),
                )
            return
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                if self._handle_ui_click(event.pos, getattr(event, "mod", 0)):
                    return
                hit = self._unit_at(event.pos)
                if hit is not None:
                    if hit in self._player_indices():
                        self.active_group = None
                        if getattr(event, "mod", 0) & pygame.KMOD_SHIFT:
                            if hit in self.selected:
                                self.selected.remove(hit)
                            else:
                                self.selected.append(hit)
                        else:
                            self.selected = [hit]
                    else:

                        enemy = self._set_target_enemy(hit)
                        if enemy is not None:
                            self._feedback(
                                "Цель: %s — ПКМ или «Атака»" % enemy.name,
                                1.5,
                            )
                    return
                if MAP_RECT.collidepoint(event.pos):
                    self._drag_start = event.pos
                    self._drag_rect = pygame.Rect(event.pos, (0, 0))
            elif event.button == 3:
                for number, rect in self._group_rects:
                    if rect.collidepoint(event.pos):
                        self.assign_group(number)
                        return
                if MAP_RECT.collidepoint(event.pos):
                    mods = getattr(event, "mod", 0) or pygame.key.get_mods()
                    if mods & pygame.KMOD_SHIFT:
                        self._issue_plan_target(
                            self._cell_from_mouse(event.pos)
                        )
                        return
                    hit = self._unit_at(event.pos)
                    if hit is not None and hit not in self._player_indices():
                        self._issue_attack(hit)
                    else:
                        self._issue_ground(self._cell_from_mouse(event.pos))
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._drag_rect is not None:
                rect = self._drag_rect.copy()
                self._drag_start = None
                self._drag_rect = None
                if rect.width < 6 and rect.height < 6:
                    return
                chosen = []
                for i in self._player_indices():
                    p = self._display_pos.get(self.state.units[i].name)
                    if p and rect.collidepoint(p):
                        chosen.append(i)
                if chosen:
                    self.selected = chosen
                else:
                    self.selected = []
                self.active_group = None
            return

    def _handle_ui_click(self, pos, mods=0):

        if not mods:
            mods = pygame.key.get_mods()
        for number, rect in self._group_rects:
            if rect.collidepoint(pos):
                if mods & pygame.KMOD_CTRL:
                    self.assign_group(number)
                else:
                    self.select_group(number)
                return True

        if pygame.Rect(12, 64, 208, 22).collidepoint(pos):
            self.select_all_units()
            return True

        row = min(7, max(0, (pos[1] - 94) // 24))
        col = None
        if pygame.Rect(12, 94, 100, 192).collidepoint(pos):
            col = 0
        elif pygame.Rect(120, 94, 100, 192).collidepoint(pos):
            col = 1
        if col is not None:
            players = self._player_indices()
            list_pos = row * 2 + col
            if list_pos < len(players):
                self.selected = [players[list_pos]]
                return True

        if pygame.Rect(930, 9, 28, 36).collidepoint(pos):
            self.zoom_out()
            return True
        if pygame.Rect(962, 9, 28, 36).collidepoint(pos):
            self.zoom_in()
            return True
        if pygame.Rect(994, 9, 40, 36).collidepoint(pos):
            self.zoom_reset()
            return True

        if self._commander_rect.collidepoint(pos):
            self.open_needs()
            return True
        return False
