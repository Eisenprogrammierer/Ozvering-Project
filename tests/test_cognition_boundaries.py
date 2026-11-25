"""Границы когнитивного слоя: опциональные зависимости не протекают."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPTIONAL_IMPORTS = (
    "import rivescript",
    "from rivescript",
    "import soar",
    "from soar",
    "import sml",
    "from sml",
)


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
        for needle in OPTIONAL_IMPORTS:
            if needle in text:
                offenders.append("%s: %s" % (path, needle))
    assert offenders == []


def test_optional_dependencies_are_confined_to_runtime_modules():
    allowed = {"rive_runtime.py": ("import rivescript", "from rivescript")}
    for path in (ROOT / "campaign" / "cognition").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in OPTIONAL_IMPORTS:
            if needle in allowed.get(path.name, ()):
                continue
            assert needle not in text, "%s: %s" % (path, needle)
