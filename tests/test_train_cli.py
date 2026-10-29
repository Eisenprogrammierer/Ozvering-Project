"""Smoke-тесты CLI `agents.train`.

Python 3.14 валидирует help-строки argparse и падает на одиночном `%`.
CI на 3.12 этого не ловит, поэтому проверяем и `--help`, и короткий
нулевой запуск прямо в тестах.
"""

import json

import pytest

from agents.train import main


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
