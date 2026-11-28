"""RL-предпочтения Soar: компилятор, обучение и сравнение."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition.errors import BackendError, SoarError
from campaign.cognition.rl_compiler import (
    RlModel,
    check_policy,
    load_model,
    model_from_dict,
    render_policy,
)
from campaign.cognition.soar_rl import (
    RlEpisode,
    SoarRlPolicy,
    SoarRlTrainer,
    compare_episodes,
)
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]


def _preset(seed=11):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    )
    return generator.generate(seed=seed)


def _campaign(seed=11):
    return AutomataCampaign(_preset(seed), seed=seed)


def _episodes(count=24):
    result = []
    for index in range(count):
        chosen = "a" if index % 2 == 0 else "b"
        reward = 1.0 if chosen == "a" else -1.0
        result.append(RlEpisode("ctx", ("a", "b"), chosen, reward))
    return result


def test_rl_policy_matches_config():
    model = check_policy()
    assert isinstance(model, RlModel)
    assert model.digest()
    text = render_policy(load_model())
    assert "source_digest:" in text
    assert ":template" in text
    assert "rl*finish" in text


def test_rl_model_rejects_unknown_version():
    with pytest.raises(SoarError):
        model_from_dict({"version": 99})


def test_rl_episode_validates_candidates():
    with pytest.raises(BackendError):
        RlEpisode("ctx", (), "a", 0.0)
    with pytest.raises(BackendError):
        RlEpisode("ctx", ("a", "b"), "c", 0.0)
    with pytest.raises(BackendError):
        RlEpisode("ctx", ("a", "a"), "a", 0.0)


def test_trainer_learns_best_action():
    pytest.importorskip("soar_sml")
    episodes = _episodes(24)
    trainer = SoarRlTrainer(seed=3)
    try:
        assert trainer.train(episodes) == 24
        table = trainer.learn_policy(episodes)
        assert table == {"ctx": "a"}
        assert trainer.queries >= 25
        assert trainer.errors == 0
        report = trainer.report()
        assert report["trained"] == 24
        assert report["elapsed_ms"] >= 0.0
    finally:
        trainer.close()


def test_compare_episodes_passes_when_rl_beats_logged_choice():
    pytest.importorskip("soar_sml")
    report = compare_episodes(
        _episodes(40),
        config={
            "min_episodes": 10,
            "coverage_threshold": 0.5,
            "reward_tolerance": 0.0,
        },
    )
    assert report["available"] is True
    assert report["train"] == 28
    assert report["eval"] == 12
    assert report["policy"] == {"ctx": "a"}
    assert report["coverage"] == 1.0
    assert report["lift"] > 0.0
    assert report["passed"] is True
    assert report["ok"] is True


def test_compare_episodes_needs_enough_history():
    pytest.importorskip("soar_sml")
    report = compare_episodes(
        _episodes(6),
        config={"min_episodes": 20, "coverage_threshold": 0.5},
    )
    assert report["passed"] is False
    assert "эпизодов" in report["reason"]


def test_compare_episodes_without_soar_is_explicit(monkeypatch):
    import campaign.cognition.soar_rl as soar_rl

    monkeypatch.setattr(soar_rl, "soar_available", lambda: False)
    report = compare_episodes(_episodes(24))
    assert report["available"] is False
    assert report["unavailable"] is True
    assert report["ok"] is False


def test_policy_roundtrip_and_unknown_context():
    policy = SoarRlPolicy({"ctx": "a"})
    assert policy.choose("ctx", ["a", "b"]) == "a"
    assert policy.choose("ctx", ["b"]) is None
    assert policy.choose("other", ["a"]) is None
    restored = SoarRlPolicy.from_dict(policy.to_dict())
    assert restored.policy == policy.policy
    with pytest.raises(BackendError):
        SoarRlPolicy({}, version=99)


def test_rl_disabled_by_default():
    campaign = _campaign(11)
    report = campaign.rl_episode_report()
    assert report["enabled"] is False
    assert report["episodes"] == 0
    assert report["ok"] is True
    assert campaign.npc_outcome_report()["rl"]["enabled"] is False


def test_campaign_collects_rl_episodes_and_resets_on_snapshot():
    campaign = _campaign(11)
    campaign.ai_model["npc_policy"]["rl"] = {
        "enabled": True,
        "seed": 11,
        "min_episodes": 8,
        "max_episodes": 512,
    }
    campaign.run(turns=4)
    report = campaign.rl_episode_report()
    assert report["enabled"] is True
    assert report["episodes"] > 0
    assert report["contexts"] >= 1
    outcome = campaign.npc_outcome_report()
    assert outcome["rl"]["episodes"] == report["episodes"]
    assert outcome["rl"]["ok"] is True

    snapshot = campaign.save_snapshot()
    restored = AutomataCampaign(_preset(11), seed=11, snapshot=snapshot)
    restored.ai_model["npc_policy"]["rl"] = {
        "enabled": True,
        "seed": 11,
    }
    assert restored.rl_episode_report()["episodes"] == 0
    assert restored.rl_episode_report()["pending"] == 0
