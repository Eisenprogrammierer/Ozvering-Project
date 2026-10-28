import game_engine as ge

from .. import theme
from ..scene import Scene


class GameScene(Scene):
    name = "game"

    def __init__(self, app):
        super().__init__(app)
        self.view = None
        self._autosaved = False

    def on_enter(self, save_data=None, new=False, seed=None, **kwargs):
        if self.view is not None:

            self.view.screen = self.app.screen
            self.on_resize(*self.app.size)
            return
        progress_seed = None
        resume_tick = 0
        if save_data:
            progress_seed = int(save_data.get("seed", 0))
            if not save_data.get("finished"):
                resume_tick = int(save_data.get("tick", 0))
        if seed is not None:
            progress_seed = int(seed)
        if new or progress_seed is None:
            progress_seed = self.app.new_seed()
            resume_tick = 0
        ge.LOG.info(
            "GameScene: старт партии seed=%s resume_tick=%s (new=%s)"
            % (progress_seed, resume_tick, new)
        )
        speed = getattr(self.app, "speed", None)
        if speed is None and save_data:
            speed = save_data.get("speed")
        if speed is None:
            speed = ge.DEFAULT_SPEED
        sickness = getattr(self.app, "sickness", None)
        if sickness is None and save_data:
            sickness = save_data.get("sickness")
        if sickness is None:
            sickness = 0.0
        condition_rl = None
        condition_ai = None
        if save_data:
            if "health_rl" in save_data or "sickness_rl" in save_data:
                condition_rl = {
                    "health": save_data.get("health_rl"),
                    "sickness": save_data.get("sickness_rl"),
                }
            if "health_ai" in save_data or "sickness_ai" in save_data:
                condition_ai = {
                    "health": save_data.get("health_ai"),
                    "sickness": save_data.get("sickness_ai"),
                }
        self.view = ge.GameApp(
            fonts=self.app.fonts,
            screen=self.app.screen,
            on_escape=self._on_escape,
            seed=progress_seed,
            checkpoint=getattr(self.app, "checkpoint", ""),
            health_factors=getattr(self.app, "health_factors", {}),
            sickness=sickness,
            speed=speed,
            auto_pause=getattr(self.app, "auto_pause", True),
        )
        if resume_tick > 0:
            self.view.start_match(seed=progress_seed, resume_tick=resume_tick)
        if condition_rl is not None or condition_ai is not None:
            self.view.restore_conditions(condition_rl, condition_ai)
        self._autosaved = False
        if self.app.save.settings.get("autosave", True):
            self.app.save.autosave(self.save_data())

    def _on_escape(self):
        self.app.push("pause")

    def on_resize(self, w, h):
        if self.view is not None:
            self.view.screen = self.app.screen
            self.view.on_resize(w, h)

    def handle_event(self, e):
        if self.view is not None:
            self.view.handle_events([e])
        return True

    def update(self, dt):
        if self.view is None:
            return
        self.view.update(dt)
        if self.view.match.finished and not self._autosaved:
            if self.app.save.settings.get("autosave", True):
                self.app.save.autosave(self.save_data())
            self._autosaved = True

    def save_data(self):
        data = {"name": "match"}
        if self.view is not None:
            data.update(self.view.progress())
        return data

    def draw(self, s):
        if self.view is not None:
            self.view.draw(s)
        else:
            s.fill(theme.BG)
