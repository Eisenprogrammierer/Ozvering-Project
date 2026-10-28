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
