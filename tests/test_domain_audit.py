import ast
import pathlib

SIM = pathlib.Path(__file__).resolve().parents[1] / "simulation.py"


CORE = ("resolve_attack", "_apply_transfer", "run_tick", "play_game")


DOMAIN_TOKENS = (
    "domain",
    "competition",
    "physical",
    "informational",
    "information",
    "economic",
    "economy",
    "semantic",
    "meaning",
    "front",
    "campaign",
)


def _functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
    }


def _identifiers(node):
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
    funcs = _functions(SIM)
    offenders = {}
    for name in CORE:
        assert (
            name in funcs
        ), f"ядро изменилось: в simulation.py нет функции {name!r}"
        bad = sorted(
            ident
            for ident in _identifiers(funcs[name])
            if any(tok in ident.lower() for tok in DOMAIN_TOKENS)
        )
        if bad:
            offenders[name] = bad
    assert not offenders, (
        "в ядре взаимодействия появился доменный идентификатор — F1 нарушен "
        "(область не должна быть переменной механизма). Если это осознанная "
        "доменная ветка, F1 нужно переоткрыть, а не пропускать тест: "
        f"{offenders}"
    )
