"""Smoke-тесты CLI `agents.train`.

Python 3.14 валидирует help-строки argparse и падает на одиночном `%`.
CI на 3.12 этого не ловит, поэтому проверяем и `--help`, и короткий
нулевой запуск прямо в тестах.
"""

import json

import pytest

from agents import QTablePolicy
from agents.train import main, train, train_seeds, wilson_interval


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
    assert payload["with_env"] is True
    assert path.exists()


def test_train_cli_can_disable_environment(capsys):
    code = main(
        [
            "--episodes",
            "0",
            "--eval-episodes",
            "0",
            "--no-with-env",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["with_env"] is False


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


def test_wilson_interval_is_bounded_and_handles_zero_trials():
    assert wilson_interval(0, 0) == (0.0, 1.0)
    low, high = wilson_interval(5, 10)
    assert 0.0 <= low < 0.5 < high <= 1.0
    low, high = wilson_interval(0, 10)
    assert low == 0.0
    assert 0.0 < high < 1.0


def test_train_seeds_aggregates_runs_sequentially():
    result = train_seeds(
        seeds=3,
        workers=1,
        base_seed=7,
        episodes=0,
        max_steps=5,
        eval_episodes=0,
    )
    aggregate = result["aggregate"]
    assert aggregate["seeds"] == [7, 8, 9]
    assert aggregate["runs"] == 3
    assert aggregate["episodes"] == 0
    assert aggregate["win_rate"] == 0.0
    assert len(aggregate["win_rate_ci"]) == 2
    assert [run["stats"]["seed"] for run in result["runs"]] == [7, 8, 9]
    assert all("policy_state" in run for run in result["runs"])


def test_train_seeds_parallel_matches_sequential_aggregate():
    kwargs = dict(episodes=0, max_steps=5, eval_episodes=0)
    sequential = train_seeds(seeds=2, workers=1, base_seed=11, **kwargs)
    parallel = train_seeds(seeds=2, workers=2, base_seed=11, **kwargs)
    assert parallel["aggregate"]["seeds"] == sequential["aggregate"]["seeds"]
    assert parallel["aggregate"]["episodes"] == sequential["aggregate"]["episodes"]
    assert parallel["aggregate"]["wins"] == sequential["aggregate"]["wins"]
    assert parallel["aggregate"]["win_rate_ci"] == sequential["aggregate"]["win_rate_ci"]


def test_train_cli_parallel_seeds_writes_per_seed_checkpoints(tmp_path, capsys):
    path = tmp_path / "bdi.json"
    code = main(
        [
            "--seeds",
            "2",
            "--workers",
            "1",
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
    assert payload["runs"] == 2
    assert payload["seeds"] == [0, 1]
    assert (tmp_path / "bdi.seed0.json").exists()
    assert (tmp_path / "bdi.seed1.json").exists()


def test_train_save_best_writes_checkpoint(tmp_path):
    path = tmp_path / "best.json"
    _policy, stats = train(
        episodes=2,
        seed=1,
        max_steps=5,
        eval_episodes=0,
        best_out=str(path),
        best_every=1,
        best_eval_episodes=1,
    )
    assert path.exists()
    assert stats["best_out"] == str(path)
    assert stats["best_episode"] in (1, 2)
    assert stats["best_win_rate"] is not None


def test_train_campaign_baselines_adds_warmed_rows():
    _policy, stats = train(
        episodes=0,
        seed=2,
        policy_name="bdi",
        max_steps=3,
        env_name="campaign",
        eval_episodes=1,
        eval_opponents=("qtable-campaign", "mlp"),
        eval_baseline_episodes=1,
        eval_campaign_baselines=True,
    )
    rows = stats["eval"]
    assert len(rows) == 3
    assert {row["opponent"] for row in rows} == {"world"}
    assert {row["policy"] for row in rows} == {"bdi", "qtable-campaign", "mlp"}
    assert all(row["trained_episodes"] >= 0 for row in rows)
