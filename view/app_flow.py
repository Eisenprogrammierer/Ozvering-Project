"""Ходы, действия игрока, исходы и обязательные сцены."""

from __future__ import annotations

from .app_support import (
    logger,
)


class AppFlowMixin:

    def finish_storyline_outcome(self, outcome):
        if outcome not in ("win", "lose"):
            return False
        if self.storyline_interpreter is None:
            return False
        if self.pending_storyline_outcome is not None or getattr(
            self.storyline_interpreter, "finished", False
        ):
            return False
        self.pending_storyline_outcome = outcome
        self.storyline_interpreter.finished = True
        return True

    def check_storyline_end_of_day(self):
        if self.storyline_interpreter is None:
            return
        if getattr(self.storyline_interpreter, "finished", False):
            return
        lose = False
        win = False
        if hasattr(self.storyline_interpreter, "check_lose_conditions"):
            lose = self.storyline_interpreter.check_lose_conditions()
        if hasattr(self.storyline_interpreter, "check_win_conditions"):
            win = self.storyline_interpreter.check_win_conditions()
        if lose:
            self.finish_storyline_outcome("lose")
        elif win:
            self.finish_storyline_outcome("win")

    def advance_turn(self):
        if not self.engine:
            return
        self.engine.tick()
        st = self.engine.state
        if 0 <= st.player_idx < st.count:
            st.log_event(
                st.player_idx, f"Ход {self.engine.tick_count} обработан"
            )
        logger.info("Выполнен тик: %d", self.engine.tick_count)

    def open_turn_log(self):
        from .ui.overlays import TurnLogOverlay

        self.manager.push(TurnLogOverlay(self))
        logger.debug("Открыт оверлей лога тика")

    def execute_player_action(self, action_id, on_completed=None):
        if self.time_system is None:
            return
        result = self.time_system.execute_action(action_id)
        status = result.get("status")
        logger.info("Действие игрока: %s, статус: %s", action_id, status)
        if status == "interrupted":
            interrupt = result.get("interrupt")
            if interrupt is not None:
                from .screens.interrupt_modal import InterruptModal

                self.manager.push(InterruptModal(self, interrupt))
        elif status == "mandatory_scene":
            scene_id = result.get("mandatory_scene")
            if scene_id is not None:
                from .screens.mandatory_screen import MandatorySceneScreen

                self.manager.push(MandatorySceneScreen(self, scene_id))
        elif status == "blocked":
            scene_id = result.get("mandatory_scene")
            if result.get("reason") == "mandatory_scene_pending" and scene_id:
                from .screens.mandatory_screen import MandatorySceneScreen

                self.manager.push(MandatorySceneScreen(self, scene_id))
        elif status == "completed":
            if on_completed is not None:
                on_completed()

    def process_pending_storyline_outcome(self):
        outcome = self.pending_storyline_outcome
        if outcome is None:
            return
        self.pending_storyline_outcome = None
        if outcome == "lose":
            self._show_lose_scene()
        elif outcome == "win":
            self._show_win_scene()

    def process_pending_mandatory_scene(self):
        ts = self.time_system
        if ts is None:
            return
        scene_id = ts.pending_mandatory_scene
        if scene_id is None:
            return
        if not self.manager.has_time_hud_screen():
            return
        current = self.manager.current
        if current is None:
            return
        name = type(current).__name__
        if name in ("MandatorySceneScreen", "InterruptModal"):
            return
        from .screens.mandatory_screen import MandatorySceneScreen

        self.manager.push(MandatorySceneScreen(self, scene_id))
        logger.info("Выведена обязательная сцена: %s", scene_id)

    def _apply_offline_progress(self, world_snapshot):
        """Ограниченный оффлайн-догон после загрузки (§7 №31).

        Догон идёт только для прикреплённого незавершённого мира, только при
        `offline_progress` в конфиге и только в пределах `max_offline_days`.
        Старый сейв без `saved_at`, время из будущего и сломанные часы
        дают ноль дней.
        """
        world = self.world
        if world is None or not world.attached or world.finished:
            return 0
        if not world.offline_progress:
            return 0
        saved_at = (world_snapshot or {}).get("saved_at")
        if saved_at is None:
            return 0
        from campaign.clock import CampaignClock, offline_days

        clock = CampaignClock(
            seconds_per_day=world.seconds_per_day,
            max_catchup_days=world.max_offline_days,
            paused=False,
        )
        days = offline_days(saved_at, clock=clock)
        if days <= 0:
            return 0
        results = world.advance_days(days, max_days=world.max_offline_days)
        logger.info(
            "Оффлайн-догон: %d дн.; день=%d, завершено=%s",
            len(results),
            world.day,
            world.finished,
        )
        return len(results)
