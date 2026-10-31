from .. import theme
from .base import MenuScene


class HelpScene(MenuScene):
    """B2: экран «Как играть» — onboarding для нового игрока.

    Кратко объясняет режимы игры и управление; возврат — в главное меню.
    Текст хранится парами (ru, en) и переводится через app.t при входе.
    """

    name = "help"
    hero_key = None
    btn_top_frac = 0.86

    PAIRS = [
        ("Режимы игры:", "Game modes:"),
        (
            "• Дуэль (Новая партия) — тактическая дуэль отрядов.",
            "- Duel (New game): a tactical squad duel.",
        ),
        (
            "  Действия отряда, мораль и здоровье решают исход.",
            "  Squad actions, morale and health decide the outcome.",
        ),
        (
            "• Поле боя (RTS) — бои на карте в реальном времени.",
            "- Battlefield (RTS): real-time battles on a map.",
        ),
        (
            "• Кампания — сюжетная стратегия «Операция Озверин»",
            "- Campaign - the story strategy 'Operation Ozverin'",
        ),
        (
            "  (запуск: python3 main.py --campaign).",
            "  (launch: python3 main.py --campaign).",
        ),
        ("", ""),
        ("Управление:", "Controls:"),
        (
            "• Мышь — выбор пунктов и действий.",
            "- Mouse: choose menu items and actions.",
        ),
        (
            "• ESC — пауза в партии / движение назад.",
            "- ESC: pause in a match / go back.",
        ),
        (
            "• F1 или H — справка поверх дуэли.",
            "- F1 or H: in-match help overlay.",
        ),
        (
            "Сохранения: автосейв + слоты в меню «Загрузить».",
            "Saves: autosave plus slots in the Load menu.",
        ),
    ]

    def on_enter(self, **kwargs):
        t = self.app.t
        self.title = t("Как играть", "How to play")
        self.lines = [t(ru, en) for ru, en in self.PAIRS]
        self.footer = t(
            "Назад — в главное меню.", "Back returns to the main menu."
        )

    def build_buttons(self):
        t = self.app.t
        return [
            (t("Назад", "Back"), lambda: self.app.go("menu"), True),
        ]

    def draw(self, s):
        super().draw(s)
        w, h = s.get_size()
        font = self.app.fonts.font
        y = int(h * 0.24)
        lh = font.size("Ag")[1] + 7
        for line in getattr(self, "lines", []):
            if not line:
                y += lh // 2
                continue
            theme.text(s, font, line, (w // 2, y), theme.TEXT, center=True)
            y += lh
