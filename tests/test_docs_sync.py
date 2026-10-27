import pathlib
import re

import simulation as S

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_MD = ROOT / "docs" / "MODEL.md"
README_MD = ROOT / "README.md"


ALIASES = {"STREAK": "CAPTURE_STREAK", "FRAC": "CAPTURE_FRAC"}


_ROW = re.compile(
    r"^\|[^|]*\|\s*`(?P<names>[^`]*)`\s*\|\s*(?P<values>[^|]*?)\s*\|"
)


_EXP_REF = re.compile(r"experiments/([A-Za-z0-9_]+\.py)")


def _documented_constants():
    pairs = []
    for line in MODEL_MD.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        names = [n.strip() for n in m.group("names").split("/")]
        nums = re.findall(r"-?\d+(?:\.\d+)?", m.group("values"))
        if not names or len(names) != len(nums):
            continue
        for name, num in zip(names, nums):
            pairs.append((ALIASES.get(name, name), float(num)))
    return pairs


def test_model_constants_match_code():
    pairs = _documented_constants()
    assert len(pairs) >= 25, (
        f"таблица констант MODEL.md не распознана (найдено {len(pairs)} пар) "
        f"— "
        "проверьте формат таблицы"
    )
    bad = []
    for name, doc in pairs:
        code = getattr(S, name, None)
        if code is None or float(code) != doc:
            bad.append(f"{name}: docs={doc}, код={code}")
    assert not bad, "расхождение документации и кода:\n  " + "\n  ".join(bad)


def test_referenced_experiments_exist():
    text = MODEL_MD.read_text(encoding="utf-8") + README_MD.read_text(
        encoding="utf-8"
    )
    missing = sorted(
        ref
        for ref in set(_EXP_REF.findall(text))
        if not (ROOT / "experiments" / ref).is_file()
    )
    assert (
        not missing
    ), "в доках упомянуты отсутствующие скрипты: " + ", ".join(missing)
