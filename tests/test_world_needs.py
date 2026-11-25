"""W1: 16 потребностей BDI у героя и персонажей мира.

Проверяется контракт, который связывает дневной мир с ареной: у игрока
(``CampaignActor``) и у каждого персонажа (``CampaignCharacter``) ровно те
же 16 желаний, запущенные желания давят на ``F/E``, суточная рутина
закрывает базовые нужды, а снимок мира сохраняет шкалы.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from campaign.actor import DAY_SECONDS, CampaignActor
from campaign.character import CampaignCharacter
from campaign.world import (
    WorldEngine,
    build_player_profile,
    load_biography,
    load_world,
)

NEEDS = (
    "hunger",
    "thirst",
    "fatigue",
    "health",
    "fear",
    "anxiety",
    "loneliness",
    "reproduction",
    "knowledge",
    "creativity",
    "boredom",
    "status",
    "spirituality",
    "skill",
    "love",
    "friendship",
)

VARIABLES = {
    "name": "Ирина Свет",
    "gender": "female",
    "origin": "port",
    "family": "clerk",
    "education": "academy",
    "formative": "harbor_fire",
    "vocation": "state",
    "value": "order",
    "value2": "knowledge",
    "flaw": "ambition",
    "patron": "minister",
    "reputation": "respectable",
}


def _profile():
    return build_player_profile(
        VARIABLES, biography=load_biography(), seed=7
    )


def _engine(seed=7):
    return WorldEngine(
        load_world(),
        profile=_profile(),
        node_id="agora_government",
        office_id="head_of_government",
        seed=seed,
    )


def test_actor_and_character_have_the_same_sixteen_needs():
    actor = CampaignActor(actions_per_day=3)
    character = CampaignCharacter({"id": "npc", "alive": True})
    assert tuple(actor.needs) == NEEDS
    assert tuple(character.needs) == NEEDS
    assert set(character.needs) == set(actor.needs)


def test_neglected_actor_needs_drain_force_and_energy():
    actor = CampaignActor(actions_per_day=3, standing=1.0)
    actor.bdi.needs = {key: 1.0 for key in NEEDS}
    energy_before = actor.energy
    force_before = actor.force
    deltas = actor.tick_needs(DAY_SECONDS)
    assert deltas["force"] < 0.0
    assert deltas["energy"] < 0.0
    assert actor.force < force_before
    assert actor.energy < energy_before


def test_character_satisfy_closes_love_and_reproduction():
    character = CampaignCharacter(
        {
            "id": "npc",
            "affinity": 0.0,
            "trust": 0.0,
            "alive": True,
            "needs": {"love": 1.0, "reproduction": 1.0},
        }
    )
    restored = character.satisfy({"love": 0.4, "reproduction": 0.25})
    assert restored["love"] == pytest.approx(0.4)
    assert restored["reproduction"] == pytest.approx(0.25)
    assert character.needs["love"] == pytest.approx(0.6)
    assert character.needs["reproduction"] == pytest.approx(0.75)


def test_world_day_runs_routine_for_player_and_characters():
    engine = _engine()
    # Общий тестовый мир намеренно минимален; включаем слой ровно так, как
    # это делает production-конфиг `agora_world.json`.
    engine.config["bdi_routine"] = {"enabled": True}
    character = engine.characters[engine.character_order[0]]
    player_before = dict(engine.player.needs)
    character_before = dict(character.needs)
    engine.end_day()
    assert engine.player.needs != player_before
    assert character.needs != character_before
    # Рутина не обнуляет желания: шкалы остаются рабочими мотиваторами.
    assert all(0.0 <= value <= 1.0 for value in engine.player.needs.values())
    assert all(0.0 <= value <= 1.0 for value in character.needs.values())


def test_production_world_enables_daily_needs_routine():
    root = pathlib.Path(__file__).resolve().parents[1]
    data = json.loads(
        (root / "configs" / "worlds" / "agora_world.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["bdi_routine"]["enabled"] is True


def test_world_snapshot_roundtrip_preserves_needs():
    engine = _engine()
    character = engine.characters[engine.character_order[0]]
    for key in NEEDS:
        engine.player.needs[key] = 0.125
        character.needs[key] = 0.875
    snapshot = engine.to_dict()
    restored = WorldEngine(load_world(), snapshot=snapshot)
    restored_character = restored.characters[
        restored.character_order[0]
    ]
    for key in NEEDS:
        assert restored.player.needs[key] == pytest.approx(0.125)
        assert restored_character.needs[key] == pytest.approx(0.875)


def _content_satisfiers():
    root = pathlib.Path(__file__).resolve().parents[1]
    found = set()
    for path in (root / "configs" / "campaigns").rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        def walk(value):
            if isinstance(value, dict):
                effect = value.get("effects") or value.get("effect")
                if isinstance(effect, dict):
                    needs = effect.get("needs")
                    if isinstance(needs, dict):
                        for key, amount in needs.items():
                            if (
                                key in NEEDS
                                and isinstance(amount, (int, float))
                                and amount < 0
                            ):
                                found.add(key)
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(data)
    return found


def test_every_need_has_a_satisfier_in_campaign_content():
    from campaign.routine import DEFAULTS

    satisfied = set(DEFAULTS["satisfy"]) | _content_satisfiers()
    missing = [key for key in NEEDS if key not in satisfied]
    assert not missing, "потребности без действия/рутины: %s" % missing
