"""Базовый класс сцены (экрана) и менеджер навигации между сценами.

Стек сцен: ``go`` меняет «корневой» экран, ``push``/``pop`` накладывают и
снимают экран-оверлей (например, пауза поверх партии). Экземпляры сцен в стеке
сохраняются, поэтому партия продолжается после снятия паузы.

Модуль не зависит от pygame: сцены получают события уже разобранными из
``ui.app``. Это позволяет тестировать навигацию без графической подсистемы.
"""


class Scene:
    """Один экран. Наследники переопределяют ``layout``/``draw`` и, при
    необходимости, ``on_enter``/``on_exit``/``handle_event``/``update``."""

    #: Имя сцены в реестре (для ``SceneManager.find``).
    name = "scene"
    #: Прозрачная сцена (оверлей): рисуется поверх нижележащей, не скрывая её.
    overlay = False

    def __init__(self, app):
        self.app = app
        self.widgets = []

    # --- жизненный цикл ---
    def on_enter(self, **kwargs):
        """Сцена стала верхней (в т.ч. после ``pop``)."""

    def on_exit(self, **kwargs):
        """Сцена перестала быть верхней."""

    def on_resize(self, w, h):
        self.layout(w, h)

    def layout(self, w, h):
        """Пересобрать геометрию виджетов под размер ``w x h``."""

    # --- ввод / логика / отрисовка ---
    def handle_event(self, e):
        """Раздать событие виджетам. True — событие поглощено."""
        for wdg in self.widgets:
            if wdg.handle(e):
                return True
        return False

    def update(self, dt):
        """Логика кадра (секунды с прошлого кадра)."""

    def draw(self, s):
        raise NotImplementedError


class SceneManager:
    """Стек сцен + реестр фабрик по имени."""

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
        """Верхняя сцена с данным ``name`` в стеке (или ``None``)."""
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
        """Сменить корневой экран (очищает стек)."""
        while self.stack:
            self._pop()
        scene = self._spawn(name)
        self.stack.append(scene)
        scene.on_enter(**kwargs)
        scene.layout(*self.app.size)
        return scene

    def push(self, name, **kwargs):
        """Наложить экран поверх текущего (оверлей или временный раздел)."""
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
        """Снять верхний экран; вернуть (и пересобрать) нижележащий."""
        if len(self.stack) <= 1:
            return self.current
        self._pop()
        cur = self.current
        if cur is not None:
            cur.on_enter(**kwargs)
            cur.layout(*self.app.size)
        return cur

    def back(self, fallback="menu", **kwargs):
        """Универсальный «назад»: снять оверлей или уйти на ``fallback``."""
        if len(self.stack) > 1:
            return self.pop(**kwargs)
        return self.go(fallback, **kwargs)

    # --- цикл кадра ---
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
        # Рисуем от последней непрозрачной сцены вверх — оверлеи поверх неё.
        start = 0
        for i, scene in enumerate(self.stack):
            if not scene.overlay:
                start = i
        for scene in self.stack[start:]:
            scene.draw(s)
