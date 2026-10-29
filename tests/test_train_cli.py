"""Smoke-тесты CLI `agents.train`.

Python 3.14 валидирует help-строки argparse и падает на одиночном `%`.
CI на 3.12 этого не ловит, поэтому проверяем и `--help`, и короткий
нулевой запуск прямо в тестах.
"""

import json

import pytest

from agents import QTablePolicy
from agents.train import main, train


def test_train_cli_help_is_valid():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_train_cli_zero_episodes_runs(tmp_path, capsys):
    path = tmp_path / "bdi.json"
    code = main(
        [
            "--episodes",
            "0",
            "--eval-episodes",
            "0",
            "--out",
            str(path),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["episodes"] == 0
    assert path.exists()


def test_held_out_matrix_warms_learnable_baselines():
    _policy, stats = train(
        episodes=0,
        seed=4,
        policy_name="bdi",
        opponent_name="bdi",
        max_steps=6,
        eval_episodes=1,
        eval_seed=91000,
        eval_opponents=("qtable", "mlp", "random"),
        eval_baseline_episodes=3,
    )
    rows = {row["opponent"]: row for row in stats["eval"]}
    assert rows["qtable"]["trained_episodes"] == 3
    assert rows["qtable"]["policy_source"] == "warmup"
    assert rows["mlp"]["trained_episodes"] == 3
    assert rows["random"]["trained_episodes"] == 0
    assert rows["random"]["policy_source"] == "builtin"


def test_held_out_matrix_uses_explicit_baseline_checkpoint(tmp_path):
    path = tmp_path / "qtable.json"
    policy = QTablePolicy(seed=5)
    path.write_text(json.dumps(policy.state_dict()), encoding="utf-8")

    _policy, stats = train(
        episodes=0,
        seed=4,
        policy_name="bdi",
        opponent_name="bdi",
        max_steps=6,
        eval_episodes=1,
        eval_seed=92000,
        eval_opponents=("qtable",),
        eval_baseline_episodes=9,
        eval_checkpoints={"qtable": str(path)},
    )
    row = stats["eval"][0]
    assert row["trained_episodes"] == -1
    assert row["policy_source"] == str(path)
