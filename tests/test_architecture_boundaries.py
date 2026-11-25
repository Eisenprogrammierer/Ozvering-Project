"""Границы архитектуры: кампания не тянет легаси-бой на импорте."""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaign"


def _top_level_legacy_imports(path):
    """Вернуть импорты warfare/simulation на верхнем уровне модуля."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"warfare", "simulation"}:
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module in {"warfare", "simulation"}:
                found.append(node.module)
    return found


def test_campaign_modules_do_not_import_legacy_battle_at_top_level():
    offenders = {}
    for path in sorted(CAMPAIGN.rglob("*.py")):
        imports = _top_level_legacy_imports(path)
        if imports:
            offenders[str(path.relative_to(ROOT))] = imports
    assert not offenders, (
        "кампания не должна импортировать warfare/simulation на верхнем "
        "уровне; легаси-персонаж создаётся лениво: %s" % offenders
    )


def test_campaign_automata_import_does_not_load_warfare():
    code = (
        "import sys\n"
        "import campaign.automata\n"
        "assert 'warfare' not in sys.modules, 'warfare загружен на импорте'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


ACTIVE_ROOTS = (
    "campaign",
    "view",
    "core41",
    "agents",
    "organizations",
    "automata",
)
ACTIVE_FILES = (
    "bdi.py",
    "warfare.py",
    "warfare_core.py",
    "warfare_character.py",
)
MAX_MODULE_LINES = 1500
LEGACY_MODULES = ("ui", "simulation", "game_engine")


def _active_modules():
    for root in ACTIVE_ROOTS:
        yield from sorted((ROOT / root).rglob("*.py"))
    for name in ACTIVE_FILES:
        yield ROOT / name


def test_active_modules_stay_under_line_budget():
    offenders = {}
    for path in _active_modules():
        if "__pycache__" in path.parts:
            continue
        count = len(path.read_text(encoding="utf-8").splitlines())
        if count > MAX_MODULE_LINES:
            offenders[str(path.relative_to(ROOT))] = count
    assert not offenders, (
        "активные модули должны быть меньше %d строк (W4): %s"
        % (MAX_MODULE_LINES, offenders)
    )


def test_campaign_and_view_do_not_import_legacy_clients():
    offenders = {}
    for root in ("campaign", "view"):
        for path in sorted((ROOT / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found = []
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in LEGACY_MODULES:
                            found.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        continue
                    module = str(node.module or "").split(".")[0]
                    if module in LEGACY_MODULES:
                        found.append(module)
            if found:
                offenders[str(path.relative_to(ROOT))] = found
    assert not offenders, (
        "активный слой не должен импортировать легаси-клиент: %s"
        % offenders
    )
