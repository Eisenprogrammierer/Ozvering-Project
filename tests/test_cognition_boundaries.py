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
        if "cognition" in path.parts or path.resolve() == this_file:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in OPTIONAL_IMPORTS:
            if needle in text:
                offenders.append("%s: %s" % (path, needle))
    assert offenders == []


def test_cognition_package_has_no_optional_dependency_yet():
    for path in (ROOT / "campaign" / "cognition").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in OPTIONAL_IMPORTS:
            assert needle not in text, "%s: %s" % (path, needle)
