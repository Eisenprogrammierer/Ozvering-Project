from ..support.log_journal import get_logger

logger = get_logger("view.screen_manager")


class BaseScreen:

    escape_action = "pop"
    show_time_hud = False

    def __init__(self, app):
        self.app = app

    def handle_event(self, event):
        pass

    def on_escape(self):
        pass

    def update(self, dt):
        pass

    def draw(self, screen):
        pass


class ScreenManager:

    def __init__(self):
        self.stack = []

    @property
    def current(self):
        return self.stack[-1] if self.stack else None

    def push(self, screen):
        self.stack.append(screen)
        logger.info(
            "push: %s (глубина стека %d)",
            type(screen).__name__,
            len(self.stack),
        )

    def pop(self):
        if len(self.stack) > 1:
            removed = self.stack.pop()
            logger.info(
                "pop: %s (глубина стека %d)",
                type(removed).__name__,
                len(self.stack),
            )
            return removed
        logger.debug("pop: стек содержит один экран, удаление пропущено")
        return None

    def replace_all(self, screen):
        self.stack = [screen]
        logger.info("replace_all: %s", type(screen).__name__)

    def handle_escape(self):
        current = self.current
        if current is None:
            return
        action = getattr(current, "escape_action", "pop")
        if action == "none":
            logger.debug(
                "ESC: игнорируется экраном %s", type(current).__name__
            )
            return
        if action == "custom":
            logger.info(
                "ESC: custom-обработка экраном %s", type(current).__name__
            )
            current.on_escape()
            return
        if len(self.stack) > 1:
            removed = self.stack.pop()
            logger.info(
                "ESC: pop %s (глубина стека %d)",
                type(removed).__name__,
                len(self.stack),
            )

    def handle_event(self, event):
        if self.current:
            self.current.handle_event(event)

    def update(self, dt):
        if self.current:
            self.current.update(dt)

    def draw(self, screen):
        for s in self.stack:
            s.draw(screen)

    def has_time_hud_screen(self):
        return any(getattr(s, "show_time_hud", False) for s in self.stack)
