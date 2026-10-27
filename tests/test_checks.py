import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


CHECK_SCRIPTS = [
    "exp_balance_ci",
    "exp_hierarchy_depth",
    "exp_retaliation_faithful",
    "exp_domain_invariance",
    "exp_warfare",
]


@pytest.mark.parametrize("name", CHECK_SCRIPTS)
def test_check_script_passes(name):
    r = subprocess.run(
        [sys.executable, f"experiments/{name}.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert (
        r.returncode == 0
    ), f"{name}: rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_canon_independent_of_hashseed():
    outs = []
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                "import simulation as S; print(S.run_batch(10, "
                "quiet=True)[2])",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        assert r.returncode == 0, r.stderr
        outs.append(r.stdout.strip())
    assert outs[0] == outs[1], f"исход зависит от PYTHONHASHSEED: {outs}"
