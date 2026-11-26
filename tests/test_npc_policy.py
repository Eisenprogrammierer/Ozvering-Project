"""W2: политика выбора работы поверх BDI-потребностей NPC.

Политика не заменяет BDI: она получает уже посчитанную важность
потребности и веса работ кампании, а затем детерминированно выбирает
работу. Тесты фиксируют контракт весов, сохранение состояния и то, что
слой по умолчанию выключен.
"""

from __future__ import annotations

import json

import pytest

from campaign.npc_policy import NeedPolicy


def test_policy_prefers_work_closing_the_most_urgent_need():
    policy = NeedPolicy({"hunger": 2.0}, seed=1)
    choice = policy.choose(
        [("eat", "hunger", 1.0), ("rest", "fatigue", 1.0)],
        {"hunger": 0.9, "fatigue": 0.1},
    )
    assert choice == "eat"


def test_policy_without_weights_keeps_base_ranking():
    policy = NeedPolicy()
    choice = policy.choose(
        [("weak", "hunger", 1.0), ("strong", "hunger", 1.5)],
        {"hunger": 0.5},
    )
    assert choice == "strong"


def test_policy_observe_updates_weight_and_roundtrips(tmp_path):
    policy = NeedPolicy(learning_rate=0.5)
    assert policy.weight("love") == 0.0
    policy.observe("love", 2.0)
    assert policy.weight("love") == pytest.approx(1.0)
    state = policy.state_dict()
    path = tmp_path / "npc_policy.json"
    path.write_text(json.dumps(state), encoding="utf-8")

    restored = NeedPolicy(learning_rate=0.5)
    restored.load_state_dict(json.loads(path.read_text(encoding="utf-8")))
    assert restored.weight("love") == pytest.approx(1.0)
    assert restored.updates == 1


def test_policy_from_config_ignores_missing_checkpoint(tmp_path):
    policy = NeedPolicy.from_config(
        {
            "weights": {"fear": 1.5},
            "checkpoint": str(tmp_path / "missing.json"),
        },
        seed=3,
    )
    assert policy.weight("fear") == pytest.approx(1.5)
    assert policy.epsilon == 0.0


def _campaign(seed=7):
    from pathlib import Path

    from campaign.automata import AutomataCampaign
    from campaign.preset import CampaignPresetGenerator
    from campaign.roles import RoleCatalog

    root = Path(__file__).resolve().parents[1]
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(root / "configs" / "roles"),
        template_path=(
            root / "configs" / "campaigns" / "empire_campaign.json"
        ),
    )
    return AutomataCampaign(generator.generate(seed=seed), seed=seed)


def test_policy_layer_can_be_disabled_and_overrides_heuristic_when_on():
    campaign = _campaign()
    side = [
        item
        for item in campaign.factions
        if item != campaign.player_side
    ][0]
    campaign.ai_model["npc_policy"] = {"enabled": False}
    campaign._npc_policy_obj = None
    assert campaign._npc_policy() is None

    campaign.ai_model["npc_policy"] = {"enabled": True}
    campaign._npc_policy_obj = None
    assert campaign._npc_policy() is not None

    weighted = campaign._ai_weighted_options(side, exclude_active=True)
    chosen = weighted[-1][0]["id"]
    campaign._policy_choice = (
        lambda side, weighted, leader=None: chosen
    )
    assert campaign.auto_action(side) == chosen
