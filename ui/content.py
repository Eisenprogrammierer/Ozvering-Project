TITLE = "OZVERING PROJECT"
SUBTITLE = ("Арена IPO-автоматов", "IPO Automata Arena")
TAGLINE = (
    "Математическая дуэль автоматов: сила, энергия, конъюнктура.",
    "A mathematical duel of automata: force, energy, conjuncture.",
)


INTRO_PAGES = [
    {
        "image": "intro_arena",
        "title": ("Две силы, один такт", "Two forces, one tick"),
        "body": (
            "На арене сходятся два автомата IPO: обучающийся RLAgent и "
            "утилитарный UtilityAI. У каждого две метрики - сила (накопленный "
            "ресурс и цель) и энергия (расходуемый запас способности сообщать "
            "работу).",
            "Two IPO automata meet on the arena: the learning RLAgent and the "
            "utilitarian UtilityAI. Each has two metrics - force (accumulated "
            "resource and goal) and energy (a spendable pool of the ability "
            "to "
            "communicate work).",
        ),
    },
    {
        "image": "intro_transfer",
        "title": ("Передача энергии", "Transfer of energy"),
        "body": (
            "Взаимодействие сводится к передаче энергии: работа либо "
            "увеличивает, либо уменьшает силу. Тип энергии не хранится - это "
            "контекстная фаза такта; успех и мощность зависят от напора, "
            "открытости входа адресата и объёма работы.",
            "Interaction reduces to energy transfer: work either increases or "
            "decreases force. Energy type is not stored - it is a contextual "
            "phase of the tick; success and power depend on drive, the "
            "addressee's input openness, and the amount of work.",
        ),
    },
    {
        "image": "intro_conjuncture",
        "title": ("Открытая среда", "The open environment"),
        "body": (
            "Среда - тоже автомат того же кодекса (открытая "
            "система-суперсистема). Её конъюнктура открывает окна: пока окно "
            "открыто, удачные передачи приносят больше силы. Партия "
            "завершается устойчивым доминированием (capture).",
            "The environment is also an automaton of the same codex (an open "
            "system-supersystem). Its conjuncture opens windows: while a "
            "window "
            "is open, successful transfers yield more force. The match ends "
            "by "
            "stable dominance (capture).",
        ),
    },
]

ABOUT_LINES = [
    (
        "Ozvering-Project - иерархическая мультиагентная марковская игра с "
        "частичной наблюдаемостью, символьным состоянием и обучением с "
        "подкреплением.",
        "Ozvering-Project - a hierarchical multi-agent Markov game with "
        "partial "
        "observability, symbolic state, and reinforcement learning.",
    ),
    (
        "Рабочая модель - simulation.py; этот экранный слой (ui/) добавляет "
        "традиционную оболочку: меню, настройки, сохранения, нарратив.",
        "The working model is simulation.py; this screen layer (ui/) adds a "
        "traditional shell: menu, settings, saves, narrative.",
    ),
    (
        "2-D ассеты и 3-D сцены (персонажи, локации) - отдельные задачи; "
        "сейчас "
        "вместо арта используются плейсхолдеры.",
        "2-D assets and 3-D scenes (characters, locations) are separate "
        "tasks; "
        "placeholders stand in for art for now.",
    ),
]

HELP_LINES = [
    (
        "SPACE - старт/пауза партии, S/вправо - один такт, [ и ] - темп.",
        "SPACE - start/pause, S/Right - one tick, [ and ] - speed.",
    ),
    (
        "M - режим наблюдатель/игрок, 1..7 - выбор действия, R - новая "
        "партия.",
        "M - observe/player mode, 1..7 - pick an action, R - new match.",
    ),
    (
        "F1/H - справка, ESC - пауза и меню, F11 - полный экран.",
        "F1/H - help, ESC - pause and menu, F11 - fullscreen.",
    ),
]
