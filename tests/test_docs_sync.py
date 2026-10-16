"""Проверка «документация ↔ код» (пункт B4 ревью).

Первопричина расхождений раздела C ревью — согласованность документации ничем
не проверялась. Здесь автоматизированы две проверки:

  1. Таблица констант в ``docs/MODEL.md`` (§8) сверяется со значениями в
     ``simulation.py``: документированное число обязано совпадать с кодом.
  2. Все скрипты ``experiments/*.py``, упомянутые в ``docs/MODEL.md`` и
     ``README.md``, существуют на диске.

Чего тест не проверяет (по-прежнему требует ревью) — смысловую согласованность
формулировок; для этого — чек-лист в ``.github/pull_request_template.md``.
"""

import pathlib
import re

import simulation as S

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_MD = ROOT / "docs" / "MODEL.md"
README_MD = ROOT / "README.md"

# В таблице MODEL.md часть имён сокращена (группа «Поражение»):
# STREAK / FRAC — это CAPTURE_STREAK / CAPTURE_FRAC.
ALIASES = {"STREAK": "CAPTURE_STREAK", "FRAC": "CAPTURE_FRAC"}

# Строка таблицы вида «| группа | `A / B` | 1.5 / 2 | смысл |».
_ROW = re.compile(r"^\|[^|]*\|\s*`(?P<names>[^`]*)`\s*\|\s*(?P<values>[^|]*?)\s*\|")

# Ссылка на скрипт эксперимента: experiments/<имя>.py (без подкаталогов).
_EXP_REF = re.compile(r"experiments/([A-Za-z0-9_]+\.py)")


def _documented_constants():
    """Пары ``(имя_константы, документированное_значение)`` из таблицы MODEL.md."""
    pairs = []
    for line in MODEL_MD.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        names = [n.strip() for n in m.group("names").split("/")]
        nums = re.findall(r"-?\d+(?:\.\d+)?", m.group("values"))
        if not names or len(names) != len(nums):
            continue  # не строка «имена / значения» (заголовок, разделитель и т.п.)
        for name, num in zip(names, nums):
            pairs.append((ALIASES.get(name, name), float(num)))
    return pairs


def test_model_constants_match_code():
    """Таблица констант MODEL.md §8 совпадает со значениями в simulation.py."""
    pairs = _documented_constants()
    assert len(pairs) >= 25, (
        f"таблица констант MODEL.md не распознана (найдено {len(pairs)} пар) — "
        "проверьте формат таблицы")
    bad = []
    for name, doc in pairs:
        code = getattr(S, name, None)
        if code is None or float(code) != doc:
            bad.append(f"{name}: docs={doc}, код={code}")
    assert not bad, "расхождение документации и кода:\n  " + "\n  ".join(bad)


def test_referenced_experiments_exist():
    """Скрипты experiments/*.py, упомянутые в доках, существуют."""
    text = MODEL_MD.read_text(encoding="utf-8") + README_MD.read_text(encoding="utf-8")
    missing = sorted(
        ref for ref in set(_EXP_REF.findall(text))
        if not (ROOT / "experiments" / ref).is_file())
    assert not missing, "в доках упомянуты отсутствующие скрипты: " + ", ".join(missing)
