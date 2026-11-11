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
        organs = [
            organ
            for faction in preset.factions
            for organ in faction.get("organs") or ()
        ]
        assert organs, template_id
        assert len(preset.automata) == 8 + len(organs), template_id
        kinds = {item["kind"] for item in preset.automata}
        assert kinds == {"organization", "faction", "organ"}, template_id
        ids = [item["id"] for item in preset.automata]
        assert len(ids) == len(set(ids)), template_id
        for faction in preset.factions:
            assert any(
                organ["action_ids"] for organ in faction["organs"]
            ), template_id
            for organ in faction["organs"]:
                assert organ["automaton_id"] in ids, template_id
            for action in faction["actions"]:
                assert action["organ_id"], template_id
                assert action["organ"], template_id
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


def test_lore_characters_seed_beliefs_and_intentions():
    for template_id in LORE_TEMPLATES:
        preset = _preset(template_id)
        records = {item["id"]: item for item in preset.characters}
        for faction in preset.factions:
            leader = records[faction["leader_id"]]
            assert leader["beliefs"], template_id
            assert leader["intentions"], template_id
            assert leader["deliberate_target"], template_id


def test_automata_campaign_keeps_seeded_beliefs():
    campaign = AutomataCampaign(_preset("empire_campaign", seed=13))
    leader = campaign.faction("red").characters[0]
    assert leader.bdi.beliefs
    assert leader.bdi.latest_intention().target == "faction.republic"


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
    organization = preset.organizations[0]
    organization["runtime"]["parameters"]["outside_base"] = 0.44
    campaign = AutomataCampaign(preset, seed=7)
    faction = campaign.factions[organization["side"]]
    assert faction.organization.parameters.outside_base == 0.44


def test_automata_save_snapshot_roundtrip_keeps_state_and_rng():
    preset = _preset("empire_campaign", seed=11)
    campaign = AutomataCampaign(preset, seed=11)
    for _ in range(6):
        action = campaign.auto_action(campaign.player_side)
        campaign.advance(player_action=action)
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
    assert campaign.max_turns is None
    campaign.run(turns=72)
    assert campaign.turn == 72 or campaign.finished
    assert campaign.outcome in (None, "win", "lose", "stalemate")
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
        action = campaign.auto_action(campaign.player_side)
        campaign.advance(player_action=action)
        snapshot = campaign.factions["red"].snapshot()
        assert snapshot["initial_count"] == original
        assert snapshot["willing_count"] <= snapshot["active_count"]
        assert snapshot["active_count"] <= snapshot["initial_count"]
        assert snapshot["willing_share"] == pytest.approx(
            snapshot["willing_count"] / float(original)
        )


def test_allow_rejoin_lets_exited_participants_return():
    def exited_series(rejoin):
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
                campaign.factions["red"]
                .snapshot()["organization"]
                .get("exited", 0)
            )
        return series

    frozen = exited_series(False)
    returning = exited_series(True)
    # Без повторного входа состав «замерзает»: вышедшие остаются в архиве.
    assert max(frozen) > 0
    assert max(frozen) == min(frozen)
    # С ``allow_rejoin`` архив выходов очищается каждый тик, поэтому
    # участники снова доступны организации.
    assert max(returning) == 0


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
    assert options["imperial_edict"]["reason"] == "уже выполнено"
    assert options["imperial_edict"]["uses"] == 1
    assert options["imperial_edict"]["max_uses"] == 1
    assert "imperial_edict" not in campaign.available_actions("red")
    campaign.end_turn()
    campaign.begin_turn()
    assert "imperial_edict" not in campaign.available_actions("red")
    campaign.end_turn()
    campaign.begin_turn()
    assert "imperial_edict" not in campaign.available_actions("red")
    blocked = campaign.perform("red", "imperial_edict")
    assert blocked["ok"] is False
    assert blocked["reason"] == "уже выполнено"
    assert any(
        item["action_id"] == "imperial_edict" and item["turn"] == 1
        for item in campaign.log
        if item["actor_side"] == "red"
    )


def test_action_use_limits_mark_repeatable_work_as_exhausted():
    campaign = AutomataCampaign(_preset("empire_campaign", seed=3), seed=3)
    faction = campaign.faction("red")
    faction.action_uses["enemy_of_state"] = 2
    options = {
        item["id"]: item for item in campaign.action_options("red")
    }
    assert options["enemy_of_state"]["enabled"] is False
    assert options["enemy_of_state"]["reason"] == "исчерпано (2 из 2)"
    assert options["enemy_of_state"]["max_uses"] == 2
    assert "enemy_of_state" not in campaign.available_actions("red")


def test_repeated_action_effects_decay():
    campaign = AutomataCampaign(_preset("empire_campaign", seed=3), seed=3)
    first = campaign.perform("red", "show_of_force")
    assert first["ok"] is True
    assert first["repeat_scale"] == pytest.approx(1.0)
    campaign.faction("red").cooldowns.clear()
    second = campaign.perform("red", "show_of_force")
    assert second["ok"] is True
    assert second["repeat_scale"] == pytest.approx(0.7)
    assert second["uses"] == 2


def test_action_requirements_block_unavailable_work():
    campaign = AutomataCampaign(_preset("empire_campaign", seed=3), seed=3)
    options = {
        item["id"]: item for item in campaign.action_options("red")
    }
    assert options["terror_bombing"]["enabled"] is False
    assert "сначала нужно: enemy_of_state" in (
        options["terror_bombing"]["reason"]
    )
    assert options["panzer_breakthrough"]["enabled"] is False
    assert "доступно с цикла 2" in options["panzer_breakthrough"]["reason"]
    campaign.begin_turn()
    assert campaign.perform("red", "enemy_of_state")["ok"]
    options = {
        item["id"]: item for item in campaign.action_options("red")
    }
    assert options["terror_bombing"]["enabled"] is True
    assert options["terror_bombing"]["reason"] == ""


def test_action_requirements_check_target_assets():
    campaign = AutomataCampaign(_preset("empire_campaign", seed=3), seed=3)
    rival = campaign.faction("red")
    rival.assets["supply"] = 0.1
    options = {
        item["id"]: item for item in campaign.action_options("amber")
    }
    assert options["embargo"]["enabled"] is False
    assert "цель: снабжение ≥ 0.20" in options["embargo"]["reason"]


def test_cooldowns_prevent_automata_from_repeating_a_work_next_turn():
    campaign = AutomataCampaign(_preset("empire_campaign", seed=5), seed=5)
    last = {}
    for _ in range(20):
        if campaign.finished:
            break
        campaign.advance()
        for item in campaign.log:
            if item.get("turn") != campaign.turn:
                continue
            side = item["actor_side"]
            key = (side, item["action_id"])
            previous = last.get(key)
            if previous is not None and campaign.turn - previous == 1:
                raise AssertionError(
                    "работа %s повторилась два хода подряд у %s"
                    % (item["action_id"], side)
                )
            last[key] = campaign.turn


def test_score_bias_shifts_progress_outcome_boundary():
    preset = _preset("empire_campaign", seed=11)
    outcome = preset.scenario["outcome"]
    outcome["score_margin"] = 0.0
    outcome["score_after"] = 0
    outcome["score_streak"] = 1
    outcome["defeat"] = {}

    for bias, expected in ((1.0, "win"), (-3.0, "lose")):
        outcome["score_bias"] = bias
        campaign = AutomataCampaign(preset, seed=11)
        campaign.begin_turn()
        for key in campaign.player.score_assets:
            campaign.player.set_asset(key, 1.0)
            campaign.rival.set_asset(key, 0.0)
        campaign._check_outcome()
        assert campaign.outcome == expected


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


def test_lore_actions_have_player_facing_descriptions():
    for template_id in LORE_TEMPLATES:
        preset = _preset(template_id)
        for faction in preset.factions:
            for action in faction["actions"]:
                description = str(action.get("description") or "")
                assert description, (template_id, action["id"])
                assert description != action["label"], (
                    template_id,
                    action["id"],
                )


def test_lore_storylines_have_no_document_scene_and_use_role_title():
    for template_id in LORE_TEMPLATES:
        data = json.loads(
            (STORYLINES / ("%s_scenes.json" % template_id)).read_text(
                encoding="utf-8"
            )
        )
        types = [scene.get("type") for scene in data["sequence"]]
        assert "document" not in types, template_id
        text = json.dumps(data, ensure_ascii=False)
        assert "hands" not in text.lower(), template_id
        assert "{player_role_title}" in text, template_id


def test_fractal_organs_are_runtime_nodes_and_snapshot_roundtrip():
    preset = _preset("empire_campaign", seed=11)
    campaign = AutomataCampaign(preset, seed=11)
    assert campaign.player.organs
    organ = campaign.player.organs[0]
    assert 0.0 <= organ.integrity <= 1.0
    for key in ("legitimacy", "cohesion", "morale", "supply", "influence"):
        campaign.player.set_asset(key, 0.05)
    organ.integrity = 0.95
    campaign._tick_organizations()
    assert organ.integrity < 0.95
    organ.integrity = 0.321
    restored = AutomataCampaign(
        preset, snapshot=campaign.save_snapshot()
    )
    assert restored.player.organs[0].integrity == pytest.approx(0.321)
    assert restored.snapshot() == campaign.snapshot()
    assert campaign.audit() == []


def test_faction_assets_are_projections_not_an_independent_wallet():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    faction = campaign.player
    before = faction.asset("legitimacy")
    for character in faction.characters:
        character.needs["status"] = 1.0
    assert faction.asset("legitimacy") < before

    # Запись в assets не создаёт отдельное хранилище: она раскладывается
    # в контекст взаимодействий, откуда актив снова считается формулой.
    faction.assets["legitimacy"] = 0.2
    assert faction.asset("legitimacy") == pytest.approx(0.2, abs=1e-6)
    assert "legitimacy" in faction.context

    # Механическое изменение связей/целостности сети тоже видно в активе.
    coercion = next(
        organ for organ in faction.organs if organ.kind == "coercion"
    )
    fear_before = faction.asset("fear")
    coercion.integrity = 0.0
    assert faction.asset("fear") < fear_before


def test_organ_interaction_changes_organ_faction_and_cooldown():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    organ = campaign.player.organs[0]
    organ.integrity = 0.3
    cohesion = campaign.player.asset("cohesion")
    supply = campaign.player.asset("supply")
    result = campaign.perform_organ_interaction(
        "red", organ.id, "reinforce"
    )
    assert result["ok"] is True
    assert organ.integrity > 0.3
    assert campaign.player.asset("cohesion") > cohesion
    assert campaign.player.asset("supply") < supply
    options = {
        item["id"]: item
        for item in campaign.organ_interaction_options(
            "red", organ.id
        )
    }
    assert options["reinforce"]["enabled"] is False
    assert "перезарядка" in options["reinforce"]["reason"]


def test_advance_accepts_organ_action_and_logs_it():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    organ = campaign.player.organs[0]
    before = campaign.turn
    snapshot = campaign.advance(
        organ_action=(organ.id, "resupply")
    )
    assert snapshot["turn"] == before + 1
    assert campaign.last_organ_result
    assert campaign.last_organ_result["ok"] is True
    assert any(
        event.get("kind") == "organ"
        and event.get("organ_id") == organ.id
        for event in campaign.events
    )


def test_organ_network_is_data_driven_and_bidirectional():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    organs = {organ.id: organ for organ in campaign.player.organs}
    assert "wehrmacht" in organs["panzerwaffe"].links
    assert "panzerwaffe" in organs["wehrmacht"].links
    assert "imperial_staff" in organs["wehrmacht"].links
    assert "wehrmacht" in organs["imperial_staff"].links
    snapshot = campaign.player.snapshot()
    by_id = {item["id"]: item for item in snapshot["organs"]}
    assert by_id["panzerwaffe"]["links"] == sorted(
        organs["panzerwaffe"].links
    )
    assert by_id["panzerwaffe"]["degree"] == len(
        organs["panzerwaffe"].links
    )
    # Сеть допускает циклы и не требует единственного корня.
    assert any(
        item["degree"] > 2 for item in snapshot["organs"]
    )
    assert campaign.audit() == []


def test_composite_view_aggregates_organ_network():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    composite = campaign.composite()
    assert composite is not None
    assert composite.id == "%s:faction" % campaign.player_side
    # Узлы сети висят под корнем плоско: связи остаются в данных органа,
    # но не превращаются в вертикаль подчинения.
    assert composite.part("imperial_staff").path_depth() == 1
    assert composite.part("wehrmacht").path_depth() == 1
    assert composite.part("panzerwaffe").path_depth() == 1

    organs = {organ.id: organ for organ in campaign.player.organs}
    expected_force = sum(
        organ.integrity * 100.0 * max(1e-9, organ.weight)
        for organ in organs.values()
    )
    expected_weight = sum(
        max(1e-9, organ.weight) for organ in organs.values()
    )
    expected_health = sum(
        organ.integrity * max(1e-9, organ.weight)
        for organ in organs.values()
    ) / expected_weight
    state = composite.aggregate_state()
    assert state["force"] == pytest.approx(expected_force)
    assert state["health_ratio"] == pytest.approx(expected_health)
    assert state["parts"] == len(organs) + 1
    assert state["alive"] is True
    rival = campaign.composite(campaign.rival_side)
    assert rival is not None
    assert rival.id == "%s:faction" % campaign.rival_side


def test_weakening_one_organ_lowers_composite_integrity():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    for organ in campaign.player.organs:
        organ.integrity = 1.0
    before = campaign.composite().aggregate_state()
    organ = next(
        item for item in campaign.player.organs
        if item.id == "panzerwaffe"
    )
    organ.integrity = 0.2
    after = campaign.composite().aggregate_state()
    assert after["force"] < before["force"]
    assert after["health_ratio"] < before["health_ratio"]
    assert after["alive"] is True
    assert after["health_ratio"] == pytest.approx(
        before["health_ratio"]
        - (1.0 - 0.2)
        * max(1e-9, organ.weight)
        / sum(max(1e-9, item.weight) for item in campaign.player.organs)
    )


def test_composite_distribution_reaches_the_weakened_organ():
    from core41 import Work

    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    composite = campaign.composite()
    leaves = [node.id for node in composite.leaves()]
    assert "panzerwaffe" in leaves
    report = composite.distribute(Work(amount=10.0, form="info"),
                                  strategy="even")
    assert report["accepted"] is True
    assert sum(
        item["amount"] for item in report["shares"].values()
    ) == pytest.approx(10.0)
    assert report["stored"] + report["loss"] + report["entropy"] == (
        pytest.approx(10.0)
    )


def test_action_budget_allows_several_actions_then_requires_end_turn():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    assert campaign.actions_per_turn == 3
    assert campaign.actions_left == 0
    available = campaign.available_actions(campaign.player_side)
    performed = []
    for action_id in available[:3]:
        result = campaign.perform(campaign.player_side, action_id)
        assert result["ok"], result.get("reason")
        performed.append(action_id)
    assert campaign.turn == 1
    assert campaign.actions_left == 0
    assert len(performed) == 3
    blocked = campaign.perform(
        campaign.player_side, available[3]
    )
    assert blocked["ok"] is False
    assert "бюджет" in blocked["reason"].lower()
    campaign.end_turn()
    assert campaign.turn == 1
    assert campaign.actions_left == 0
    campaign.begin_turn()
    assert campaign.turn == 2
    assert campaign.actions_left == 3


def test_character_interaction_changes_selected_character_and_spends_budget():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    character = campaign.character_options(campaign.player_side)[1]
    before = campaign.character(campaign.player_side, character["id"])
    morale_before = before.morale
    status_before = before.needs["status"]
    result = campaign.perform_character_interaction(
        campaign.player_side, character["id"], "promote"
    )
    assert result["ok"] is True
    assert result["character_id"] == character["id"]
    assert before.morale > morale_before
    assert before.needs["status"] < status_before
    assert campaign.actions_left == campaign.actions_per_turn - 1
    options = {
        item["id"]: item
        for item in campaign.character_interaction_options(
            campaign.player_side, character["id"]
        )
    }
    assert options["promote"]["enabled"] is False
    assert "перезарядка" in options["promote"]["reason"]
    assert any(
        event.get("kind") == "character"
        and event.get("character_id") == character["id"]
        for event in campaign.events
    )


def test_advance_without_explicit_action_autoplays_player_budget():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    campaign.advance()
    assert campaign.turn == 1
    player_actions = [
        item
        for item in campaign.log
        if item.get("turn") == 1
        and item.get("actor_side") == campaign.player_side
    ]
    assert player_actions, "advance() без работы должен играть за игрока"
    assert campaign.actions_left == 0


def test_realtime_advances_clock_and_regenerates_actions():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    assert campaign.elapsed == 0.0
    assert campaign.speed == 1
    campaign.begin_turn()
    campaign.actions_left = 0
    campaign.advance_time(0)
    assert campaign.elapsed == 0.0
    campaign.advance_time(-5)
    assert campaign.elapsed == 0.0
    campaign.advance_time(campaign.action_interval_seconds)
    assert campaign.elapsed == pytest.approx(
        campaign.action_interval_seconds
    )
    assert campaign.actions_left == 1
    campaign.advance_time(
        campaign.turn_seconds - campaign.action_interval_seconds
    )
    assert campaign.elapsed == pytest.approx(campaign.turn_seconds)
    assert campaign.actions_left == campaign.actions_per_turn
    assert campaign.turn >= 1


def test_full_action_budget_takes_more_than_two_minutes():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    refill = (
        campaign.action_interval_seconds * campaign.actions_per_turn
    )
    assert refill > 120.0
    campaign.begin_turn()
    campaign.actions_left = 0
    campaign.advance_time(120.0)
    assert campaign.actions_left < campaign.actions_per_turn
    campaign.advance_time(refill - 120.0)
    assert campaign.actions_left == campaign.actions_per_turn


def test_speed_can_be_increased_and_cancelled_but_not_slowed_below_one():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    assert campaign.speed_cap() == 32
    assert campaign.can_speed_up() is True
    assert campaign.can_slow_down() is False
    assert campaign.set_speed(0) is False
    assert campaign.set_speed(1) is True
    assert campaign.speed == 1
    campaign.speed_up()
    assert campaign.speed == 2
    campaign.speed_up()
    assert campaign.speed == 4
    campaign.advance_time(4.0)
    assert campaign.elapsed == pytest.approx(16.0)
    assert campaign.can_slow_down() is True
    assert campaign.slow_down() == 2
    assert campaign.slow_down() == 1
    assert campaign.slow_down() == 1
    assert campaign.can_slow_down() is False
    assert campaign.reset_speed() == 1
    assert campaign.set_speed(0) is False
    assert campaign.speed == 1
    while campaign.can_speed_up():
        campaign.speed_up()
    assert campaign.speed == 32
    assert campaign.speed_up() == 32
    assert campaign.slow_down() == 16
    assert campaign.set_speed(8) is True
    assert campaign.speed == 8


def test_realtime_state_survives_snapshot_roundtrip():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    campaign.advance_time(10.0)
    campaign.speed_up()
    campaign.speed_up()
    campaign.advance_time(5.0)
    snapshot = campaign.snapshot()
    assert snapshot["elapsed"] > 0.0
    assert snapshot["speed"] == 4
    clone = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    clone.load_snapshot(json.loads(json.dumps(snapshot)))
    assert clone.elapsed == pytest.approx(campaign.elapsed)
    assert clone.speed == campaign.speed
    assert clone.turn == campaign.turn


def test_realtime_and_interactions_come_from_config():
    from campaign.defaults import default_dict, default_list

    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    defaults = default_dict("realtime")
    assert campaign.turn_seconds == float(defaults["turn_seconds"])
    assert campaign.action_interval_seconds == float(
        defaults["action_interval_seconds"]
    )
    assert campaign.ai_interval_seconds == float(
        defaults["ai_interval_seconds"]
    )
    assert campaign.speed_levels == sorted(defaults["speeds"])
    configured = {
        item["id"] for item in default_list("automaton_interactions")
    }
    faction = campaign.faction(campaign.player_side)
    assert configured
    assert configured.issubset(
        {str(item.get("id")) for item in faction.automaton_interactions}
    )


def test_core_rejects_self_character_interactions():
    campaign = AutomataCampaign(
        _preset("empire_campaign", seed=11), seed=11
    )
    player = next(
        item
        for item in campaign.character_options(campaign.player_side)
        if item["is_player"]
    )
    options = campaign.character_interaction_options(
        campaign.player_side, player["id"]
    )
    assert options
    assert all(option["enabled"] is False for option in options)
    assert all(
        option["reason"] == "нельзя применять к самому себе"
        for option in options
    )
    result = campaign.perform_character_interaction(
        campaign.player_side, player["id"], options[0]["id"]
    )
    assert result["ok"] is False
