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
