import json

import pytest

from agents import BDIPolicy, MLPPolicy, QTablePolicy, load_policy
from core41 import Action, Observation
from core41.types import Transition
from ui.battlefield import BattlefieldModel


def _observation():
    return Observation(
        self_force=50.0,
        self_energy=40.0,
        self_max_force=100.0,
        self_max_energy=100.0,
        opponent_force=60.0,
        opponent_energy=30.0,
        opponent_max_force=100.0,
        opponent_max_energy=100.0,
        opponent_pressure=4.0,
        opponent_open=False,
        time=0.0,
        forms=("force", "info"),
    )


def _save_bdi(path):
    policy = BDIPolicy(seed=3)
    policy.weights = [0.125] * len(policy.weights)
    policy.updates = 11
    policy.save(str(path))
    return policy


def test_load_policy_detects_bdi_checkpoint(tmp_path):
    path = tmp_path / "bdi.json"
    source = _save_bdi(path)

    loaded = load_policy(str(path), seed=9)

    assert isinstance(loaded, BDIPolicy)
    assert loaded.weights == source.weights
    assert loaded.updates == source.updates


def test_load_policy_detects_qtable_checkpoint(tmp_path):
    observation = _observation()
    action = Action("WORK", form="force", fraction=0.3)
    source = QTablePolicy(seed=3)
    source.table[source.key(observation, action)] = 1.25
    path = tmp_path / "qtable.json"
    path.write_text(
        json.dumps(source.state_dict(), ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_policy(str(path), seed=9)

    assert isinstance(loaded, QTablePolicy)
    assert loaded.table[loaded.key(observation, action)] == pytest.approx(
        1.25
    )


def test_load_policy_detects_mlp_checkpoint(tmp_path):
    observation = _observation()
    action = Action("WORK", form="force", fraction=0.3)
    source = MLPPolicy(seed=3, epsilon=0.0)
    source.observe(
        Transition(
            observation=observation,
            action=action,
            reward=0.2,
            next_observation=observation,
            done=False,
            next_actions=(action,),
        )
    )
    path = tmp_path / "mlp.json"
    source.save(str(path))

    loaded = load_policy(str(path), seed=9)

    assert isinstance(loaded, MLPPolicy)
    assert loaded.weights1 == source.weights1
    assert loaded.score(observation, action) == pytest.approx(
        source.score(observation, action)
    )


def test_load_policy_rejects_unknown_kind(tmp_path):
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps({"kind": "mystery"}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_policy(str(path))


def test_match_engine_loads_bdi_checkpoint(tmp_path):
    pytest.importorskip("pygame")
    import game_engine as ge

    path = tmp_path / "bdi.json"
    source = _save_bdi(path)

    match = ge.MatchEngine(seed=2, steps=4, checkpoint=str(path))

    assert isinstance(match.ai.policy, BDIPolicy)
    assert match.ai.policy.weights == source.weights


def test_battlefield_loads_bdi_checkpoint(tmp_path):
    path = tmp_path / "bdi.json"
    source = _save_bdi(path)

    model = BattlefieldModel(seed=3, checkpoint=str(path))

    assert isinstance(model.enemy.agent.policy, BDIPolicy)
    assert model.enemy.agent.policy.weights == source.weights


# ---------------------------------------------------------------------------
# Production-автопоиск чекпойнта (P2)
# ---------------------------------------------------------------------------


def _write_policy(path, kind="bdi", version=None, mtime=None):
    import os

    if kind == "bdi":
        policy = BDIPolicy(seed=1)
        state = policy.state_dict()
    elif kind == "qtable":
        state = QTablePolicy(seed=1).state_dict()
    elif kind == "mlp":
        state = MLPPolicy(seed=1).state_dict()
    else:
        state = {"kind": kind}
    if version is not None:
        state["version"] = version
    path.write_text(json.dumps(state), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_find_checkpoint_prefers_best_then_latest(tmp_path):
    from agents.checkpoints import find_checkpoint

    _write_policy(tmp_path / "other.json", "bdi", mtime=3000)
    _write_policy(tmp_path / "latest.json", "qtable", mtime=2000)
    _write_policy(tmp_path / "best.json", "mlp", mtime=1000)

    assert find_checkpoint(directory=tmp_path) == str(tmp_path / "best.json")
    (tmp_path / "best.json").unlink()
    assert find_checkpoint(directory=tmp_path) == str(
        tmp_path / "latest.json"
    )
    (tmp_path / "latest.json").unlink()
    assert find_checkpoint(directory=tmp_path) == str(tmp_path / "other.json")


def test_find_checkpoint_falls_back_to_newest_json(tmp_path):
    from agents.checkpoints import find_checkpoint

    _write_policy(tmp_path / "old.json", "bdi", mtime=100)
    _write_policy(tmp_path / "new.json", "bdi", mtime=500)
    assert find_checkpoint(directory=tmp_path) == str(tmp_path / "new.json")


def test_find_checkpoint_skips_broken_unknown_and_future_files(tmp_path):
    from agents.checkpoints import find_checkpoint

    (tmp_path / "best.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "unknown.json").write_text(
        json.dumps({"kind": "mystery"}), encoding="utf-8"
    )
    _write_policy(tmp_path / "future.json", "bdi", version=999)
    _write_policy(tmp_path / "good.json", "bdi", mtime=10)

    assert find_checkpoint(directory=tmp_path) == str(tmp_path / "good.json")
    assert find_checkpoint(directory=tmp_path / "missing") == ""


def test_find_checkpoint_filters_by_kind(tmp_path):
    from agents.checkpoints import find_checkpoint

    _write_policy(tmp_path / "best.json", "bdi", mtime=900)
    _write_policy(tmp_path / "mlp.json", "mlp", mtime=10)

    assert find_checkpoint(directory=tmp_path, kind="mlp") == str(
        tmp_path / "mlp.json"
    )
    assert find_checkpoint(directory=tmp_path, kind="qtable") == ""


def test_resolve_checkpoint_explicit_wins_and_auto_can_be_disabled(tmp_path):
    from agents.checkpoints import resolve_checkpoint

    _write_policy(tmp_path / "best.json", "bdi")
    explicit = tmp_path / "explicit.json"

    assert resolve_checkpoint(
        str(explicit), directory=tmp_path
    ) == str(explicit)
    assert resolve_checkpoint(
        directory=tmp_path, auto=False
    ) == ""
    assert resolve_checkpoint(directory=tmp_path) == str(
        tmp_path / "best.json"
    )


def test_checkpoint_dir_env_override(tmp_path, monkeypatch):
    from agents import checkpoints

    monkeypatch.setenv(checkpoints.CHECKPOINT_DIR_ENV, str(tmp_path))
    _write_policy(tmp_path / "best.json", "bdi")

    assert checkpoints.default_checkpoint_dir() == tmp_path
    assert checkpoints.find_checkpoint() == str(tmp_path / "best.json")


def test_list_checkpoints_reports_kind_and_order(tmp_path):
    from agents.checkpoints import list_checkpoints

    _write_policy(tmp_path / "latest.json", "qtable", mtime=10)
    _write_policy(tmp_path / "best.json", "bdi", mtime=20)
    _write_policy(tmp_path / "older.json", "mlp", mtime=1)

    rows = list_checkpoints(directory=tmp_path)
    assert [row["name"] for row in rows] == [
        "best.json",
        "latest.json",
        "older.json",
    ]
    assert [row["kind"] for row in rows] == ["bdi", "qtable", "mlp"]
    assert all(row["size"] > 0 for row in rows)


def test_game_engine_lists_checkpoints_without_opening_window(
    tmp_path, monkeypatch, capsys
):
    pytest.importorskip("pygame")
    import sys

    import game_engine as ge

    _write_policy(tmp_path / "best.json", "bdi")
    monkeypatch.setattr(
        sys, "argv", ["game_engine.py", "--checkpoints-dir", str(tmp_path),
                      "--list-checkpoints"]
    )

    assert ge.main() == 0
    out = capsys.readouterr().out
    assert "bdi" in out
    assert str(tmp_path / "best.json") in out


def test_view_main_lists_checkpoints_without_creating_app(
    tmp_path, capsys
):
    pytest.importorskip("pygame")
    import view.app as view_app

    _write_policy(tmp_path / "best.json", "mlp")

    assert view_app.main(
        ["--checkpoints-dir", str(tmp_path), "--list-checkpoints"]
    ) == 0
    out = capsys.readouterr().out
    assert "mlp" in out
    assert str(tmp_path / "best.json") in out


# --- A9: production-чекпойнт duel-mlp ------------------------------------


def test_duel_mlp_checkpoint_is_autodiscoverable(tmp_path):
    """A9: каталог чекпойнтов игры должен находить `duel-mlp` (v4).

    До A9 `KNOWN_KINDS` не включал `duel-mlp`, и автопоиск
    (`find_checkpoint` в `game_engine`) молча отвергал production-файл —
    игра всегда падала на BDI.
    """
    from agents.checkpoints import find_checkpoint, is_loadable
    from agents.policies import DuelMLPPolicy

    policy = DuelMLPPolicy(seed=5)
    path = tmp_path / "duel_mlp_production.json"
    policy.save(str(path))

    assert is_loadable(str(path))
    assert find_checkpoint(directory=tmp_path) == str(path)

    loaded = load_policy(str(path), seed=6)
    assert isinstance(loaded, DuelMLPPolicy)


def test_shipped_production_checkpoint_loads():
    """В репозитории лежит загружаемый production-чекпойнт (A9)."""
    from agents import checkpoints as ck
    from agents.policies import DuelMLPPolicy

    path = ck.find_checkpoint()
    assert path.endswith("duel_mlp_production.json"), path
    policy = load_policy(path)
    assert isinstance(policy, DuelMLPPolicy)
    # Вектор duel-политики — расширенный (базовые признаки + статистика оппонента).
    from agents.policies import DUEL_FEATURE_COUNT

    state = ck.read_checkpoint(path)
    assert state["version"] == 4
    assert state["feature_count"] == DUEL_FEATURE_COUNT
