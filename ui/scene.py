class Scene:

    name = "scene"

    overlay = False

    def __init__(self, app):
        self.app = app
        self.widgets = []

    def on_enter(self, **kwargs):
        pass

    def on_exit(self, **kwargs):
        pass

    def on_resize(self, w, h):
        self.layout(w, h)

    def layout(self, w, h):
        pass

    def handle_event(self, e):
        for wdg in self.widgets:
            if wdg.handle(e):
                return True
        return False

    def update(self, dt):
        pass

    def draw(self, s):
        raise NotImplementedError


class SceneManager:

    def __init__(self, app):
        self.app = app
        self.registry = {}
        self.stack = []

    def register(self, name, cls):
        self.registry[name] = cls
        return cls

    @property
    def current(self):
        return self.stack[-1] if self.stack else None

    @property
    def depth(self):
        return len(self.stack)

    def find(self, name):
        for scene in reversed(self.stack):
            if getattr(scene, "name", None) == name:
                return scene
        return None

    def _spawn(self, name):
        cls = self.registry.get(name)
        if cls is None:
            raise KeyError("сцена не зарегистрирована: %r" % (name,))
        return cls(self.app)

    def go(self, name, **kwargs):
        while self.stack:
            self._pop()
        scene = self._spawn(name)
        self.stack.append(scene)
        scene.on_enter(**kwargs)
        scene.layout(*self.app.size)
        return scene

    def push(self, name, **kwargs):
        scene = self._spawn(name)
        self.stack.append(scene)
        scene.on_enter(**kwargs)
        scene.layout(*self.app.size)
        return scene

    def _pop(self):
        scene = self.stack.pop()
        try:
            scene.on_exit()
        except Exception:
            pass

    def pop(self, **kwargs):
        if len(self.stack) <= 1:
            return self.current
        self._pop()
        cur = self.current
        if cur is not None:
            cur.on_enter(**kwargs)
            cur.layout(*self.app.size)
        return cur

    def back(self, fallback="menu", **kwargs):
        if len(self.stack) > 1:
            return self.pop(**kwargs)
        return self.go(fallback, **kwargs)

    def handle_event(self, e):
        cur = self.current
        return cur.handle_event(e) if cur else False

    def update(self, dt):
        if self.current is not None:
            self.current.update(dt)

    def resize(self, w, h):
        for scene in self.stack:
            scene.on_resize(w, h)

    def draw(self, s):
        if not self.stack:
            return

        start = 0
        for i, scene in enumerate(self.stack):
            if not scene.overlay:
                start = i
        for scene in self.stack[start:]:
            scene.draw(s)
