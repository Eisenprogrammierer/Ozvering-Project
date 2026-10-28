"""Сверка констант здоровья/болезни core41 с проектными документами."""

import pathlib
import re

import core41

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = (
    ROOT / "docs" / "WORLD_CORE_MODEL.md",
    ROOT / "docs" / "AGENTS.md",
)

_CONSTANT_ROW = re.compile(
    r"^\|\s*`(?P<name>HEALTH_[A-Z_]+|SICKNESS_[A-Z_]+)`\s*\|"
    r"(?P<value>[^|]*)\|"
)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_PREFIXES = ("HEALTH_", "SICKNESS_")


def _documented_constants(path):
    pairs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _CONSTANT_ROW.match(line)
        if not match:
            continue
        number = _NUMBER.search(match.group("value"))
        if number is None:
            continue
        pairs.append((match.group("name"), float(number.group(0))))
    return pairs


def test_documented_health_and_sickness_constants_match_code():
    documented = {}
    for path in DOCS:
        for name, value in _documented_constants(path):
            documented[name] = value

    assert documented, "в документах не найдены таблицы HEALTH_/SICKNESS_"

    bad = []
    for name, value in documented.items():
        code = getattr(core41, name, None)
        if code is None or float(code) != value:
            bad.append(f"{name}: docs={value}, код={code}")
    assert not bad, "расхождение документации и core41:\n  " + "\n  ".join(bad)


def test_all_exported_health_and_sickness_constants_are_documented():
    exported = {
        name
        for name in core41.__all__
        if name.startswith(_PREFIXES)
    }
    documented = {
        name
        for path in DOCS
        for name, _value in _documented_constants(path)
    }
    missing = sorted(exported - documented)
    assert not missing, (
        "константы core41 не описаны в WORLD_CORE_MODEL.md/AGENTS.md: "
        + ", ".join(missing)
    )
