"""Тесты чистой логики игры «Престол» (без pygame)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from realm.content import ContentPack
from realm.model import CouncilGame, RealmError, STAT_KEYS


@pytest.fixture(scope="module")
def content():
    return ContentPack()


def _option_under_threshold(game):
    for petition in game.content.petitions:
        for option in petition["options"]:
            if game.option_support(option) < game.threshold:
                return petition, option
    return None, None


def _option_over_threshold(game):
    for petition in game.content.petitions:
        for option in petition["options"]:
            if game.option_support(option) >= game.threshold:
                return petition, option
    return None, None


# --------------------------------------------------------------------------
# Контент
# --------------------------------------------------------------------------

def test_content_is_complete(content):
    assert len(content.advisors) >= 5
    assert len(content.petitions) >= content.game["max_weeks"]
    assert len(content.mandates) >= 3
    assert len(content.events) >= content.game["max_weeks"] - 1
    assert content.story["intro"]
    assert content.story["about"]
    assert content.story["help"]
    assert len({item["key"] for item in content.assets}) == len(content.assets)


def test_content_references_are_valid(content):
    advisor_ids = {item["id"] for item in content.advisors}
    stat_keys = set(STAT_KEYS)
    axes = {"order", "wealth", "tradition", "freedom"}
    for petition in content.petitions:
        assert petition["id"] and petition["title"] and petition["body"]
        option_ids = set()
        for option in petition["options"]:
            assert option["id"] not in option_ids
            option_ids.add(option["id"])
            assert option["label"] and option["summary"]
            assert set(option.get("effects", {})) <= stat_keys
            assert set(option.get("trust", {})) <= advisor_ids
            assert set(option.get("axes", {})) <= axes
    for event in content.events:
        assert set(event.get("effects", {})) <= stat_keys
    for mandate in content.mandates:
        assert set(mandate.get("effects", {})) <= stat_keys
        assert set((mandate.get("trust_by_advisor") or {})) <= advisor_ids


def test_core_does_not_import_pygame():
    code = (
        "import sys; import realm.model; "
        "assert 'pygame' not in sys.modules, sorted(sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            cwd=str(__import__("pathlib").Path(__file__).parents[1]),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# Инициализация и детерминизм
# --------------------------------------------------------------------------

def test_mandates_change_start(content):
    heir = CouncilGame(content, seed=1, mandate_id="heir")
    council = CouncilGame(content, seed=1, mandate_id="council")
    popular = CouncilGame(content, seed=1, mandate_id="popular")
    assert heir.stats["legitimacy"] > council.stats["legitimacy"]
    assert council.stats["treasury"] > heir.stats["treasury"]
    assert popular.stats["unrest"] < heir.stats["unrest"]
    assert (sum(item["trust"] for item in council.advisors.values()) >
            sum(item["trust"] for item in heir.advisors.values()))


def test_seed_is_deterministic(content):
    first = CouncilGame(content, seed=42, mandate_id="heir")
    second = CouncilGame(content, seed=42, mandate_id="heir")
    other = CouncilGame(content, seed=43, mandate_id="heir")
    assert first.deck == second.deck
    assert first.event_deck == second.event_deck
    assert first.current_petition["id"] == second.current_petition["id"]
    assert first.deck != other.deck


def test_unknown_mandate_is_rejected(content):
    with pytest.raises(RealmError):
        CouncilGame(content, seed=1, mandate_id="no-such-mandate")


# --------------------------------------------------------------------------
# Совет и решения
# --------------------------------------------------------------------------

def test_council_vote_shape(content):
    game = CouncilGame(content, seed=7, mandate_id="heir")
    option = game.current_petition["options"][0]
    vote = game.council_vote(option)
    assert 0.0 <= vote["support"] <= 1.0
    assert set(vote["votes"]) == set(game.advisors)
    assert set(vote["stances"]) == set(game.advisors)
    assert vote["total_weight"] == pytest.approx(
        sum(item["influence"] for item in game.advisors.values())
    )
    assert abs(vote["support_weight"] / vote["total_weight"] -
               vote["support"]) < 1e-9


def test_decree_requires_council_support(content):
    game = CouncilGame(content, seed=0, mandate_id="heir")
    petition, option = _option_under_threshold(game)
    assert option is not None, "в контенте должен быть спорный вариант"
    # Поставить прошение с непроходным вариантом в текущую позицию.
    game.deck[game.petition_index] = petition["id"]
    with pytest.raises(RealmError):
        game.resolve(option["id"], "decree")
    assert game.phase == "audience"
    assert game.week == 1


def test_decree_advances_week_and_records_history(content):
    game = CouncilGame(content, seed=0, mandate_id="heir")
    option = game.current_petition["options"][0]
    mode = "decree" if game.can_decree(option) else "force"
    report = game.resolve(option["id"], mode)
    assert game.phase == "report"
    assert game.week == 2
    assert report["week"] == 1
    assert report["petition_id"] == game.deck[0]
    assert report["option_id"] == option["id"]
    assert report["mode"] == mode
    assert game.history and game.history[-1]["option_id"] == option["id"]
    assert game.continue_after_report() == "audience"
    assert game.current_petition["id"] == game.deck[1]


def test_force_costs_more_legitimacy_than_decree(content):
    probe = CouncilGame(content, seed=3, mandate_id="heir")
    option = max(probe.current_petition["options"],
                 key=probe.option_support)
    assert probe.can_decree(option)

    decree = CouncilGame(content, seed=3, mandate_id="heir")
    force = CouncilGame(content, seed=3, mandate_id="heir")
    decree.resolve(option["id"], "decree")
    force.resolve(option["id"], "force")
    assert force.stats["legitimacy"] <= decree.stats["legitimacy"] - 10
    assert force.stats["authority"] >= decree.stats["authority"]


def test_defer_is_a_decision_without_option_effects(content):
    game = CouncilGame(content, seed=5, mandate_id="heir")
    petition = game.current_petition
    before_unrest = game.stats["unrest"]
    report = game.resolve(petition["options"][0]["id"], "defer")
    assert report["mode"] == "defer"
    assert game.week == 2
    assert game.stats["unrest"] >= before_unrest + 6
    assert game.phase == "report"


def test_loss_after_forced_decision(content):
    game = CouncilGame(content, seed=2, mandate_id="heir")
    game.stats["legitimacy"] = 1
    option = next(
        (item for item in game.current_petition["options"]
         if item.get("effects", {}).get("legitimacy", 0) <= 0),
        game.current_petition["options"][0],
    )
    report = game.resolve(option["id"], "force")
    assert game.status == "lost"
    assert report["status"] == "lost"
    assert game.ending and game.ending["win"] is False
    assert game.phase == "report"
    assert game.continue_after_report() == "ended"


def test_unrest_loss(content):
    game = CouncilGame(content, seed=2, mandate_id="heir")
    game.stats["unrest"] = 100
    game.resolve(game.current_petition["options"][0]["id"], "defer")
    assert game.status == "lost"
    assert game.ending["id"] == "unrest"


def test_win_after_max_weeks(content):
    game = CouncilGame(content, seed=11, mandate_id="heir")
    game.max_weeks = 2
    while game.status == "active":
        option = game.current_petition["options"][0]
        mode = "decree" if game.can_decree(option) else "force"
        game.resolve(option["id"], mode)
        game.continue_after_report()
    assert game.status == "won"
    assert game.phase == "ended"
    assert game.ending["win"] is True
    assert game.ending["id"] in ("recognized", "fragile", "puppet")


# --------------------------------------------------------------------------
# Сохранения
# --------------------------------------------------------------------------

def test_snapshot_roundtrip(content):
    game = CouncilGame(content, seed=9, mandate_id="popular")
    first = game.current_petition["options"][0]
    mode = "decree" if game.can_decree(first) else "force"
    game.resolve(first["id"], mode)
    game.continue_after_report()
    snapshot = json.loads(json.dumps(game.snapshot(), ensure_ascii=False))
    loaded = CouncilGame.from_snapshot(content, snapshot)
    assert loaded.seed == game.seed
    assert loaded.mandate_id == game.mandate_id
    assert loaded.week == game.week
    assert loaded.stats == game.stats
    assert loaded.deck == game.deck
    assert loaded.event_deck == game.event_deck
    assert loaded.petition_index == game.petition_index
    assert loaded.phase == game.phase
    assert loaded.status == game.status
    assert loaded.history == game.history
    assert {
        key: item["trust"] for key, item in loaded.advisors.items()
    } == {
        key: item["trust"] for key, item in game.advisors.items()
    }
    # Загруженная партия продолжает жить с того же места.
    next_option = loaded.current_petition["options"][0]
    loaded.resolve(next_option["id"],
                   "decree" if loaded.can_decree(next_option) else "force")
    assert loaded.week == game.week + 1


def test_loaded_report_is_preserved(content):
    game = CouncilGame(content, seed=4, mandate_id="heir")
    option = game.current_petition["options"][0]
    game.resolve(option["id"],
                 "decree" if game.can_decree(option) else "force")
    loaded = CouncilGame.from_snapshot(
        content, json.loads(json.dumps(game.snapshot()))
    )
    assert loaded.phase == "report"
    assert loaded.last_result["option_id"] == option["id"]
    assert loaded.continue_after_report() == "audience"
