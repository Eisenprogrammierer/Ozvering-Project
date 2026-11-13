"""
core/traits.py

Система черт персонажа.

Определяет механические эффекты черт, полученных при создании
персонажа. Черты модифицируют длительность действий, скорость
накопления усталости, эффективность снабжения, потери снабжения
при casualties, точность докладов и силу дебаффов.

Модификаторы применяются через функции-аксессоры, которые
читают текущую черту из storyline_interpreter приложения.
Если интерпретатор отсутствует или черта не установлена,
возвращаются нейтральные значения (1.0 для множителей,
0.0 для коэффициентов потерь).

События модуля записываются в журнал operation_ozverin.log
и дублируются в консоль средствами core.log_journal.
"""

from .log_journal import get_logger

logger = get_logger("core.traits")

TRAITS = {
    "general_scholar": {
        "label": "Генерал-учёный",
        "action_duration_mult": 0.8,
        "fatigue_mult": 1.3,
        "supply_mult": 1.0,
        "supply_loss_on_casualties": 0.0,
        "report_noise_mult": 1.0,
        "debuff_mult": 1.0,
    },
    "knight": {
        "label": "Рыцарь",
        "action_duration_mult": 1.2,
        "fatigue_mult": 0.7,
        "supply_mult": 1.0,
        "supply_loss_on_casualties": 0.0,
        "report_noise_mult": 1.0,
        "debuff_mult": 1.0,
    },
    "mercenary": {
        "label": "Наёмник",
        "action_duration_mult": 1.0,
        "fatigue_mult": 1.0,
        "supply_mult": 1.2,
        "supply_loss_on_casualties": 0.5,
        "report_noise_mult": 1.0,
        "debuff_mult": 1.0,
    },
    "truth_teller": {
        "label": "Правдоруб",
        "action_duration_mult": 1.0,
        "fatigue_mult": 1.0,
        "supply_mult": 0.9,
        "supply_loss_on_casualties": 0.0,
        "report_noise_mult": 0.5,
        "debuff_mult": 1.0,
    },
    "pretty_eyes": {
        "label": "Красивые глазки",
        "action_duration_mult": 1.0,
        "fatigue_mult": 1.0,
        "supply_mult": 1.1,
        "supply_loss_on_casualties": 0.0,
        "report_noise_mult": 1.5,
        "debuff_mult": 1.0,
    },
    "freeloader": {
        "label": "Халявщик",
        "action_duration_mult": 1.1,
        "fatigue_mult": 1.1,
        "supply_mult": 0.9,
        "supply_loss_on_casualties": 0.1,
        "report_noise_mult": 1.1,
        "debuff_mult": 0.9,
    },
}

DEFAULT_MODIFIERS = {
    "label": "Без черты",
    "action_duration_mult": 1.0,
    "fatigue_mult": 1.0,
    "supply_mult": 1.0,
    "supply_loss_on_casualties": 0.0,
    "report_noise_mult": 1.0,
    "debuff_mult": 1.0,
}


def get_trait_modifiers(trait_name):
    """
    Возвращает модификаторы для указанной черты.

    Ищет черту по имени в словаре TRAITS. Если черта не найдена
    или trait_name равен None, возвращает нейтральные модификаторы
    по умолчанию (все множители 1.0, потери 0.0).

    Args:
        trait_name: Имя черты (ключ в TRAITS) или None.

    Returns:
        dict: Словарь модификаторов с ключами label,
            action_duration_mult, fatigue_mult, supply_mult,
            supply_loss_on_casualties, report_noise_mult,
            debuff_mult.
    """
    if trait_name is not None and trait_name in TRAITS:
        return TRAITS[trait_name]
    return dict(DEFAULT_MODIFIERS)


def _get_active_modifiers(app):
    """
    Читает активную черту из storyline_interpreter и возвращает
    соответствующие модификаторы.

    Если app равен None, интерпретатор отсутствует или переменная
    trait не установлена, возвращает модификаторы по умолчанию.

    Args:
        app: Экземпляр приложения или None.

    Returns:
        dict: Словарь модификаторов активной черты.
    """
    if app is None:
        return dict(DEFAULT_MODIFIERS)
    interp = getattr(app, "storyline_interpreter", None)
    if interp is None:
        return dict(DEFAULT_MODIFIERS)
    trait = interp.get_variable("trait", None)
    return get_trait_modifiers(trait)


def get_action_duration_modifier(app):
    """
    Возвращает модификатор длительности действий игрока.

    Множитель меньше 1.0 ускоряет действия, больше 1.0 замедляет.
    Читается из черты персонажа через storyline_interpreter.

    Args:
        app: Экземпляр приложения или None.

    Returns:
        float: Множитель длительности действий.
    """
    return _get_active_modifiers(app)["action_duration_mult"]


def get_fatigue_modifier(app):
    """
    Возвращает модификатор скорости накопления усталости.

    Множитель больше 1.0 ускоряет утомление, меньше 1.0 замедляет.
    Читается из черты персонажа через storyline_interpreter.

    Args:
        app: Экземпляр приложения или None.

    Returns:
        float: Множитель накопления усталости.
    """
    return _get_active_modifiers(app)["fatigue_mult"]


def get_supply_modifier(app):
    """
    Возвращает модификатор эффективности снабжения.

    Множитель больше 1.0 увеличивает получаемое снабжение,
    меньше 1.0 уменьшает. Читается из черты персонажа через
    storyline_interpreter.

    Args:
        app: Экземпляр приложения или None.

    Returns:
        float: Множитель снабжения.
    """
    return _get_active_modifiers(app)["supply_mult"]


def get_supply_loss_on_casualties(app):
    """
    Возвращает коэффициент потери снабжения при casualties.

    Определяет долю снабжения, теряемую пропорционально уровню
    потерь личного состава. Для наёмника значение выше (0.5),
    что означает большую чувствительность логистики к потерям.
    Читается из черты персонажа через storyline_interpreter.

    Args:
        app: Экземпляр приложения или None.

    Returns:
        float: Коэффициент потери снабжения [0, 1].
    """
    return _get_active_modifiers(app)["supply_loss_on_casualties"]


def get_report_noise_modifier(app):
    """
    Возвращает модификатор шума в докладах разведки.

    Множитель меньше 1.0 делает доклады точнее (правдоруб),
    больше 1.0 добавляет шум (красивые глазки). Читается из
    черты персонажа через storyline_interpreter.

    Args:
        app: Экземпляр приложения или None.

    Returns:
        float: Множитель шума докладов.
    """
    return _get_active_modifiers(app)["report_noise_mult"]


def get_debuff_modifier(app):
    """
    Возвращает модификатор силы дебаффов.

    Множитель меньше 1.0 ослабляет дебаффы (халявщик),
    больше 1.0 усиливает. Читается из черты персонажа через
    storyline_interpreter.

    Args:
        app: Экземпляр приложения или None.

    Returns:
        float: Множитель дебаффов.
    """
    return _get_active_modifiers(app)["debuff_mult"]