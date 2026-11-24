"""Инициализация, новый старт, окно, ввод и главный цикл."""

from __future__ import annotations

from .app_support import (
    BG_COLOR,
    FPS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    logger,
    pygame,
)


class AppCoreMixin:

    def apply_to_player(self, channel, delta):
        if self.engine:
            self.engine.state.add_voltage(self.player_idx, channel, delta)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.screen = pygame.display.set_mode(
                (SCREEN_WIDTH, SCREEN_HEIGHT),
                pygame.FULLSCREEN | pygame.SCALED,
            )
        else:
            self.screen = pygame.display.set_mode(
                (SCREEN_WIDTH, SCREEN_HEIGHT)
            )
        logger.info("Полноэкранный режим: %s", self.fullscreen)

    def new_game(self):
        from .screens.role_select import RoleSelectScreen

        self.selected_role = None
        self.selected_archetype_id = ""
        self.selected_player_character_id = ""
        self.selected_player_character_label = ""
        self.selected_archetype_label = ""
        self.selected_faction_id = None
        self.campaign_preset = None
        self.automata_campaign = None
        self.dialogue_memory = None
        self.strategy = None
        self.strategy_config = None
        self.world = None
        self.world_config = None
        self.world_clock = None
        self.player_profile = None
        self.player_identity = None
        self.manager.push(RoleSelectScreen(self))
        logger.info("Запрошена новая игра: выбор роли")

    def _campaign_seed(self, storyline):
        try:
            return int(
                storyline.get("campaign_seed", storyline.get("seed", 7))
            )
        except (TypeError, ValueError):
            return 7

    def quit(self):
        logger.info("Приложение останавливается")
        self.running = False

    def handle_global_key(self, event):
        """Глобальные горячие клавиши окна, а не текстового поля.

        Одиночные буквы здесь не перехватываются: в чате связи «д» —
        обычный текст. Журнал и завершение цикла висят на ``Ctrl``.
        """
        if event.type != pygame.KEYDOWN:
            return False
        key = event.key
        mod = int(getattr(event, "mod", 0) or 0)
        if key == pygame.K_F11:
            self.toggle_fullscreen()
            return True
        if key == pygame.K_ESCAPE:
            self.manager.handle_escape()
            return True
        if key == pygame.K_t and mod & pygame.KMOD_CTRL:
            self.advance_turn()
            return True
        if key == pygame.K_l and mod & pygame.KMOD_CTRL:
            self.open_turn_log()
            return True
        if key == pygame.K_F5:
            self.save_game("quicksave")
            return True
        return False

    def run(self):
        logger.info("Главный цикл запущен")
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif self.handle_global_key(event):
                    continue
                elif event.type == getattr(pygame, "WINDOWEVENT", -1):
                    inactive = {
                        getattr(pygame, "WINDOWEVENT_MINIMIZED", -2),
                        getattr(pygame, "WINDOWEVENT_FOCUS_LOST", -3),
                        getattr(pygame, "WINDOWEVENT_HIDDEN", -4),
                    }
                    active = {
                        getattr(pygame, "WINDOWEVENT_RESTORED", -5),
                        getattr(pygame, "WINDOWEVENT_FOCUS_GAINED", -6),
                        getattr(pygame, "WINDOWEVENT_SHOWN", -7),
                    }
                    if event.event in inactive:
                        self.active = False
                    elif event.event in active:
                        self.active = True
                    self.manager.handle_event(event)
                else:
                    self.manager.handle_event(event)
            dt = self.clock.tick(FPS) / 1000.0
            self.manager.update(dt)
            self.music.update()
            self.process_pending_storyline_outcome()
            self.process_pending_mandatory_scene()
            self.screen.fill(BG_COLOR)
            self.manager.draw(self.screen)
            if self.manager.has_time_hud_screen() and not getattr(
                self.manager.current, "hide_time_hud", False
            ):
                self.time_hud.draw(self.screen)
            pygame.display.flip()
        pygame.quit()
        return 0
