"""Проверки ключевых фигур лорных кампаний.

Тест проходит по всем четырём шаблонам, генерирует production-пресет и
проверяет, что лидеры фракций и ключевые посты описаны данными: у них есть
все 16 потребностей, все 12 черт характера и корректные архетипы из
``configs/campaigns/base/lore_factions.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog
from naming.people import PersonNameGenerator, PersonPolicyCatalog

import warfare as W


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ("empire", "republic", "cult", "corporation")
SIDES = ("red", "blue", "green", "amber")
LEADER_ARCHETYPE = {
    "red": "veteran",
    "blue": "veteran",
    "green": "chaplain",
    "amber": "scout",
}


def _lore_factions():
    path = ROOT / "configs" / "campaigns" / "base" / "lore_factions.json"
    return json.loads(path.read_text(encoding="utf-8"))["factions"]


def _preset(template_id):
    return CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns"
        / ("%s_campaign.json" % template_id),
    ).generate(seed=11)


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_faction_leaders_have_sixteen_needs_and_twelve_traits(template_id):
    preset = _preset(template_id)
    lore = _lore_factions()

    leaders = [c for c in preset.characters if c.get("is_faction_leader")]
    assert len(leaders) == 4
    assert {c["side"] for c in leaders} == set(SIDES)

    for leader in leaders:
        side = leader["side"]
        assert leader["id"] == "char_%s_001" % side
        assert set(leader["needs"]) == set(W.NEEDS)
        assert len(leader["needs"]) == 16
        assert set(leader["personality"]) == set(W.TRAITS)
        assert len(leader["personality"]) == 12
        assert leader["archetype"] == lore[side]["posts"][0]["archetype"]
        assert leader["archetype"] == LEADER_ARCHETYPE[side]
        assert leader["post"] == lore[side]["posts"][0]["title"]
        assert all(0.0 <= float(v) <= 1.0 for v in leader["needs"].values())
        assert all(
            0.0 <= float(v) <= 1.0 for v in leader["personality"].values()
        )

    for character in preset.characters:
        assert set(character["needs"]) == set(W.NEEDS)
        assert set(character["personality"]) == set(W.TRAITS)


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_lore_character_names_follow_faction_policy(template_id):
    preset = _preset(template_id)
    policies = PersonPolicyCatalog.load()
    generator = PersonNameGenerator(seed=0)
    for character in preset.characters:
        data = character["name_data"]
        policy = policies.resolve(character["faction_id"])
        assert policy is not None
        assert character["gender"] == data["gender"]
        if policy.mode == "epithets":
            assert data["style"] == "epithet"
            assert data["given"] == ""
            assert data["family"] == ""
            assert data["epithet"] in policy.epithets
            assert data["full"] == data["epithet"]
            continue
        assert data["epithet"] == ""
        assert data["gender"] in ("m", "f")
        if data["culture"]:
            profile = generator.catalog.culture(data["culture"])
        else:
            profile = generator.catalog.theme(data["theme"])
        assert data["given"] in profile.given[data["gender"]]
        if data["family"]:
            assert data["family"] in profile.family[data["gender"]]
        if policy.cultures and "*" not in policy.cultures:
            assert (
                data["culture"] in policy.cultures
                or data["theme"] in policy.themes
            )


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_key_posts_and_organizations_reference_leaders(template_id):
    preset = _preset(template_id)
    lore = _lore_factions()
    characters = {c["id"]: c for c in preset.characters}
    leaders = {
        c["side"]: c for c in preset.characters if c.get("is_faction_leader")
    }

    for side in SIDES:
        expected_posts = {p["id"]: p for p in lore[side]["posts"]}
        actual = {
            c["post_id"]: c
            for c in preset.characters
            if c.get("side") == side and c.get("post_id") in expected_posts
        }
        assert set(actual) == set(expected_posts), side
        for post_id, post in expected_posts.items():
            assert actual[post_id]["archetype"] == post["archetype"]
            assert actual[post_id]["post"] == post["title"]
            assert set(actual[post_id]["needs"]) == set(W.NEEDS)
            assert set(actual[post_id]["personality"]) == set(W.TRAITS)

        leader = leaders[side]
        organizations = [
            item
            for item in preset.organizations
            if item.get("side") == side
        ]
        assert organizations, side
        for organization in organizations:
            assert organization["leader_id"] == leader["id"]
            assert organization["leader_name"] == leader["name"]
            assert leader["id"] in organization["member_ids"]

        faction = next(
            item for item in preset.factions if item.get("side") == side
        )
        assert faction["leader_id"] == leader["id"]
        assert leader["id"] in faction["character_ids"]
        assert characters[faction["leader_id"]]["is_faction_leader"]
