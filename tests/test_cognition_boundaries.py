"""Границы когнитивного слоя: опциональные зависимости не протекают."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OPTIONAL_MODULES = frozenset(("rivescript", "soar", "soar_sml", "sml"))
IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", re.MULTILINE
)


def _imports(text):
    """Корневые имена модулей из обычных ``import``/``from`` строк."""

    return {match.group(1) for match in IMPORT_RE.finditer(text)}


def _python_files():
    for path in ROOT.rglob("*.py"):
        parts = set(path.parts)
        if parts & {"venv", "__pycache__", "build", "dist"}:
            continue
        yield path


def test_optional_backends_are_imported_only_in_cognition():
    offenders = []
    this_file = Path(__file__).resolve()
    for path in _python_files():
        if "cognition" in path.parts or "tests" in path.parts:
            continue
        if path.resolve() == this_file:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for module in sorted(_imports(text) & OPTIONAL_MODULES):
            offenders.append("%s: %s" % (path, module))
    assert offenders == []


def test_optional_dependencies_are_confined_to_runtime_modules():
    allowed = {
        "rive_runtime.py": frozenset(("rivescript",)),
        "soar_runtime.py": frozenset(("soar_sml",)),
    }
    for path in (ROOT / "campaign" / "cognition").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        forbidden = (
            _imports(text) & OPTIONAL_MODULES
        ) - allowed.get(path.name, frozenset())
        assert not forbidden, "%s: %s" % (path, sorted(forbidden))
