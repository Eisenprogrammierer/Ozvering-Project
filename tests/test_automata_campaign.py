import json
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog
from organizations.model import _stable_jitter

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = ROOT / "configs" / "campaigns"
STORYLINES = ROOT / "configs" / "storylines"
LORE_TEMPLATES = (
    "empire_campaign",
    "republic_campaign",
    "cult_campaign",
    "corporation_campaign",
)


def _preset(template_id, seed=7):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=CAMPAIGNS / ("%s.json" % template_id),
    )
    return generator.generate(seed=seed)


def test_lore_templates_are_automata_and_have_four_factions():
    for template_id in LORE_TEMPLATES:
        preset = _preset(template_id)
        scenario = preset.scenario
        assert scenario["mode"] == "automata", template_id
        assert not scenario.get("companies"), template_id
        assert not scenario.get("units"), template_id
        assert len(preset.factions) == 4, template_id
        assert len(preset.organizations) == 4, template_id
        assert len(preset.automata) == 8, template_id
        assert preset.player_character is not None, template_id
        assert preset.player_faction is not None, template_id
        assert set(scenario["populations"]) == {
            "red",
            "blue",
            "green",
            "amber",
        }
        for faction in preset.factions:
            assert faction["actions"], template_id
            assert faction["assets"], template_id
            assert faction["character_ids"], template_id


def test_automata_campaign_is_deterministic_and_logs_every_work():
    first = AutomataCampaign(_preset("empire_campaign", seed=13))
    second = AutomataCampaign(_preset("empire_campaign", seed=13))
    for _ in range(8):
        first.advance(player_action=first.auto_action(first.player_side))
        second.advance(player_action=second.auto_action(second.player_side))
    assert first.snapshot() == second.snapshot()
    assert first.turn == 8
    assert first.log
    required = {
        "turn",
        "actor_name",
        "target_name",
        "label",
        "form",
        "chance",
        "roll",
        "success",
        "attack_asset",
        "attack_value",
        "defense_asset",
        "defense_value",
    }
    assert required <= set(first.log[0])
    assert first.audit() == []


def test_lore_scores_and_runtime_are_data_driven():
    preset = _preset("republic_campaign", seed=7)
    campaign = AutomataCampaign(preset, seed=7)
    for side, faction in campaign.factions.items():
        assert faction.score_assets, side
        record = next(
            item for item in preset.factions if item["side"] == side
        )
        assert faction.score_assets == record["score_assets"]
        assert faction.organization is not None
    # Значение из runtime-конфига организации должно доехать до движка.
    organization = preset.organizations[0]
    organization["runtime"]["parameters"]["outside_base"] = 0.44
    campaign = AutomataCampaign(preset, seed=7)
    assert (
        campaign.factions[organization["side"]].organization.parameters.outside_base
        == 0.44
    )


def test_automata_save_snapshot_roundtrip_keeps_state_and_rng():
    preset = _preset("empire_campaign", seed=11)
    campaign = AutomataCampaign(preset, seed=11)
    for _ in range(6):
        campaign.advance(player_action=campaign.auto_action(campaign.player_side))
    snapshot = campaign.save_snapshot()
    restored = AutomataCampaign(preset, snapshot=snapshot)
    assert restored.turn == campaign.turn
    assert restored.outcome == campaign.outcome
    assert restored.log == campaign.log
    assert restored.snapshot() == campaign.snapshot()
    for _ in range(3):
        action = campaign.auto_action(campaign.player_side)
        expected = campaign.perform(campaign.player_side, action)
        action_restored = restored.auto_action(restored.player_side)
        actual = restored.perform(restored.player_side, action_restored)
        assert actual["action_id"] == expected["action_id"]
        assert actual["roll"] == expected["roll"]
        assert actual["success"] == expected["success"]
    for _ in range(3):
        campaign.advance()
        restored.advance()
    assert restored.snapshot() == campaign.snapshot()
    assert restored.log == campaign.log


def test_automata_save_snapshot_keeps_defeat_streaks():
    preset = _preset("empire_campaign", seed=11)
    campaign = AutomataCampaign(preset, seed=11)
    campaign.factions["red"].low_streaks["red:legitimacy"] = 2
    restored = AutomataCampaign(preset, snapshot=campaign.save_snapshot())
    assert restored.factions["red"].low_streaks == {
        "red:legitimacy": 2
    }
    # Следующий ход продолжает серию, а не начинает её заново.
    campaign.factions["red"].set_asset("legitimacy", 0.0)
    restored.factions["red"].set_asset("legitimacy", 0.0)
    campaign.advance()
    restored.advance()
    assert campaign.outcome == restored.outcome
    assert (
        restored.factions["red"].low_streaks["red:legitimacy"]
        == campaign.factions["red"].low_streaks["red:legitimacy"]
    )


def test_lore_progress_outcome_is_reachable_after_full_run():
    preset = _preset("empire_campaign", seed=11)
    campaign = AutomataCampaign(preset, seed=11)
    campaign.run()
    assert campaign.turn == campaign.max_turns
    assert campaign.outcome in ("win", "lose", "stalemate")
    assert campaign.player.progress() != 0.0
    assert campaign.rival.progress() != 0.0


def test_automata_campaign_rejects_actions_without_resources():
    campaign = AutomataCampaign(_preset("cult_campaign", seed=19))
    player = campaign.player
    assert player is not None
    expensive = next(
        action for action in player.actions if action.get("cost")
    )
    for key in expensive["cost"]:
        player.set_asset(key, 0.0)
    result = campaign.perform(player.side, expensive["id"])
    assert result["ok"] is False
    assert result["reason"]


def test_outside_jitter_is_deterministic_and_salted():
    first = _stable_jitter("org_empire:participant", 0.02)
    second = _stable_jitter("org_empire:participant", 0.02)
    other = _stable_jitter("org_republic:participant", 0.02)
    assert first == second
    assert first != other
    assert -0.02 <= first <= 0.02
    assert _stable_jitter("org_empire:participant", 0.0) == 0.0


def test_lore_participation_uses_original_faction_size():
    campaign = AutomataCampaign(_preset("empire_campaign", seed=11), seed=11)
    original = len(campaign.factions["red"].characters)
    assert original > 0
    for _ in range(12):
        campaign.advance(player_action=campaign.auto_action(campaign.player_side))
        snapshot = campaign.factions["red"].snapshot()
        assert snapshot["initial_count"] == original
        assert snapshot["willing_count"] <= snapshot["active_count"]
        assert snapshot["active_count"] <= snapshot["initial_count"]
        assert snapshot["willing_share"] == pytest.approx(
            snapshot["willing_count"] / float(original)
        )


def test_allow_rejoin_lets_exited_participants_return():
    def active_series(rejoin):
        preset = _preset("empire_campaign", seed=11)
        for organization in preset.organizations:
            organization["runtime"]["allow_rejoin"] = rejoin
        campaign = AutomataCampaign(preset, seed=11)
        series = []
        for _ in range(15):
            campaign.advance(
                player_action=campaign.auto_action(campaign.player_side)
            )
            series.append(
                campaign.factions["red"].snapshot()["active_count"]
            )
        return series

    frozen = active_series(False)
    returning = active_series(True)
    assert max(frozen) == min(frozen)
    assert max(returning) > min(returning)


def test_lore_actions_have_cooldowns_and_engine_enforces_them():
    for template_id in LORE_TEMPLATES:
        for faction in _preset(template_id).factions:
            for action in faction["actions"]:
                assert action.get("cooldown", 0) > 0, (
                    template_id,
                    action["id"],
                )
    campaign = AutomataCampaign(_preset("empire_campaign", seed=3), seed=3)
    assert campaign.perform("red", "imperial_edict")["ok"]
    options = {
        item["id"]: item for item in campaign.action_options("red")
    }
    assert options["imperial_edict"]["enabled"] is False
    assert "перезарядка" in options["imperial_edict"]["reason"]
    assert "imperial_edict" not in campaign.available_actions("red")
    campaign.advance(player_action="garrison_network")
    assert "imperial_edict" not in campaign.available_actions("red")
    campaign.advance(player_action="imperial_edict")
    assert any(
        item["action_id"] == "imperial_edict" and item["turn"] == campaign.turn
        for item in campaign.log
        if item["actor_side"] == "red"
    )


def test_cooldowns_prevent_automata_from_repeating_a_work_next_turn():
    campaign = AutomataCampaign(_preset("empire_campaign", seed=5), seed=5)
    last = {}
    for _ in range(20):
        campaign.advance()
        for item in campaign.log:
            if item.get("turn") != campaign.turn:
                continue
            side = item["actor_side"]
            if last.get(side) == item["action_id"]:
                raise AssertionError(
                    "работа %s повторилась два хода подряд у %s"
                    % (item["action_id"], side)
                )
            last[side] = item["action_id"]


def test_score_bias_shifts_progress_outcome_boundary():
    preset = _preset("empire_campaign", seed=11)
    preset.scenario["outcome"]["score_margin"] = 0.0
    preset.scenario["outcome"]["score_bias"] = 0.0
    baseline = AutomataCampaign(preset, seed=11)
    baseline.run()
    difference = baseline.player.progress() - baseline.rival.progress()
    assert difference != 0.0
    for bias, expected in (
        (abs(difference) + 0.001, "win"),
        (-abs(difference) - 0.001, "lose"),
    ):
        preset.scenario["outcome"]["score_bias"] = bias
        probe = AutomataCampaign(preset, seed=11)
        probe.run()
        assert probe.outcome == expected


def test_lore_storylines_use_automata_outcomes_not_manpower():
    for template_id in LORE_TEMPLATES:
        data = json.loads(
            (STORYLINES / ("%s.json" % template_id)).read_text(
                encoding="utf-8"
            )
        )
        assert data["win_conditions"] == [
            {"type": "automata_outcome", "value": "win"}
        ]
        assert data["lose_conditions"] == [
            {"type": "automata_outcome", "value": "lose"}
        ]
        scene_text = (
            STORYLINES / ("%s_scenes.json" % template_id)
        ).read_text(encoding="utf-8")
        for legacy in ("16 рот", "32 рот", "шестнадцать", "тридцати двух"):
            assert legacy not in scene_text.lower()
