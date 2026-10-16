"""F1, структурный сторож: в ядре взаимодействия нет доменной ветки (docs/TODO.md → F1).

РОЛЬ И ГРАНИЦЫ. Это ОПРЕДЕЛЕНИЕ «единого закона» (предметная область — не
переменная механизма) и СТОРОЖ РЕГРЕССИЙ — НЕ свидетельство: аудит проходит по
построению (области в коде нет) и не должен выдаваться за измерение.
Свидетельство поставляет ``experiments/exp_domain_invariance.py`` (мощность
различителя + инерция доменного индекса); см. разделение ролей в его докстроке.

МЕТОД. Разбор ``simulation.py`` через ``ast``. В телах функций ядра
взаимодействия не должно быть идентификаторов или имён аргументов, помечающих
предметную область. Строки документации и комментарии ``ast`` не видит как имена
— в докстроках области упомянуты законно (нейтральная терминология) и проверку
не ломают. Токен ``type`` сознательно НЕ запрещён: тип энергии — часть единого
закона, а не предметная область.
"""

import ast
import pathlib

SIM = pathlib.Path(__file__).resolve().parents[1] / "simulation.py"

# Функции ядра взаимодействия (единый закон и сквозной такт).
CORE = ("resolve_attack", "_apply_transfer", "run_tick", "play_game")

# Токены предметной области. Регистр не важен; подстрока.
DOMAIN_TOKENS = (
    "domain", "competition", "physical", "informational", "information",
    "economic", "economy", "semantic", "meaning", "front", "campaign",
)


def _functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _identifiers(node):
    """Имена аргументов, ``Name`` и ``Attribute`` в поддереве (без докстрок/комментариев)."""
    found = set()
    for n in ast.walk(node):
        if isinstance(n, ast.arg):
            found.add(n.arg)
        elif isinstance(n, ast.Name):
            found.add(n.id)
        elif isinstance(n, ast.Attribute):
            found.add(n.attr)
    return found


def test_core_has_no_domain_branch():
    """Ядро взаимодействия не содержит доменных идентификаторов (F1, определение)."""
    funcs = _functions(SIM)
    offenders = {}
    for name in CORE:
        assert name in funcs, f"ядро изменилось: в simulation.py нет функции {name!r}"
        bad = sorted(
            ident for ident in _identifiers(funcs[name])
            if any(tok in ident.lower() for tok in DOMAIN_TOKENS))
        if bad:
            offenders[name] = bad
    assert not offenders, (
        "в ядре взаимодействия появился доменный идентификатор — F1 нарушен "
        "(область не должна быть переменной механизма). Если это осознанная "
        "доменная ветка, F1 нужно переоткрыть, а не пропускать тест: "
        f"{offenders}")
