"""Обёртка ключевых автотестов-скриптов в pytest (пункт B3 ревью).

Скрипты ``experiments/exp_*`` — самодостаточные проверки с кодом возврата
(``0`` — норма, ``1`` — регрессия). Pytest запускает их подпроцессом — тем же
путём, что и CI (``.github/workflows/ci.yml``), — и требует ``rc=0``.

Детерминизм канона по ``PYTHONHASHSEED`` тоже проверяется подпроцессом:
хэш-сид фиксируется при старте интерпретатора и в процессе не меняется.
"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Индекс-скрипты с кодом возврата (см. experiments/README.md).
CHECK_SCRIPTS = [
    "exp_balance_ci",            # критерий недоминирования (docs/BASELINE.md)
    "exp_hierarchy_depth",       # самоподобие кодекса на всех ярусах (§14)
    "exp_retaliation_faithful",  # верность оценки возмездия (§7, пункт A3)
]


@pytest.mark.parametrize("name", CHECK_SCRIPTS)
def test_check_script_passes(name):
    """Скрипт-проверка ``experiments/<name>.py`` завершается с кодом 0."""
    r = subprocess.run([sys.executable, f"experiments/{name}.py"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, f"{name}: rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_canon_independent_of_hashseed():
    """Канон не зависит от рандомизации хэшей строк (иначе — перебор по ``set()``)."""
    outs = []
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run(
            [sys.executable, "-c",
             "import simulation as S; print(S.run_batch(10, quiet=True)[2])"],
            cwd=ROOT, capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        outs.append(r.stdout.strip())
    assert outs[0] == outs[1], f"исход зависит от PYTHONHASHSEED: {outs}"
