"""P7: новый контент добавляется данными, без правки Python.

Фикстура собирает отдельный мир, форму, действие, сцену, архетип, сюжет,
речевой акт и тип ответа. Затем мир загружается, сцена входит в
``WorldEngine``, а новое действие выполняется по адресату-персонажу.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from campaign.dialogue.loader import load_social, load_synthesis
from campaign.identity import load_archetypes_catalog
from campaign.scenes import SceneCatalog
from campaign.world import WorldEngine, build_player_profile, load_world
from view.support.storyline import list_storylines, load_storyline

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_WORLD = (
    ROOT / "tests" / "fixtures" / "content" / "configs" / "worlds"
    / "agora_world.json"
)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_content_only_extension_starts_and_executes(tmp_path):
    raw_world = _read(FIXTURE_WORLD)
    node_id = raw_world["nodes"][0]["id"]
    office_id = ""
    probe_world = load_world(FIXTURE_WORLD)
    probe = WorldEngine(
        probe_world,
        profile=build_player_profile({"name": "Тест"}, seed=7),
        seed=7,
    )
    for option in probe.office_options(node_id):
        candidate = WorldEngine(
            probe_world,
            profile=build_player_profile({"name": "Тест"}, seed=7),
            node_id=node_id,
            office_id=option["id"],
            seed=7,
        )
        if candidate.attach(node_id, option["id"])["ok"]:
            office_id = option["id"]
            break
    assert office_id

    forms = _read(ROOT / "configs" / "campaigns" / "forms.json")
    forms["forms"].append(
        {
            "id": "gratitude",
            "label": "Благодарность",
            "description": "Новая форма из JSON.",
            "payload_kinds": ["info"],
            "target_kinds": ["character"],
            "default_handler": False,
        }
    )
    forms_path = tmp_path / "forms.json"
    _write(forms_path, forms)

    raw_world["forms_path"] = str(forms_path)
    raw_world["actions"].append(
        {
            "id": "thank_person",
            "label": "Поблагодарить",
            "form": "gratitude",
            "target": {
                "required": True,
                "kinds": ["character"],
                "exclude_self": True,
            },
            "template": {
                "form": "gratitude",
                "payload": {
                    "kind": "info",
                    "topic": "thanks",
                    "confidence": 0.8,
                },
            },
            "success": {
                "chance": 1.0,
                "text": "Человек улыбается в ответ.",
                "effects": {"target": {"trust": 0.05}},
            },
            "failure": {
                "chance": 0.0,
                "text": "Слова остаются неуслышанными.",
                "effects": {},
            },
        }
    )
    raw_world["scenes"] = [
        {
            "id": "thanks",
            "label": "Место благодарности",
            "location": node_id,
            "tags": ["free", "thanks"],
            "public": [
                {
                    "id": "new_friend",
                    "name": "Новый друг",
                    "trust": 0.1,
                }
            ],
            "works": ["thank_person"],
            "time": {"slots": 2},
        }
    ]
    world_path = tmp_path / "mini_world.json"
    _write(world_path, raw_world)

    world = load_world(world_path)
    assert "gratitude" in {
        item["id"] for item in _read(forms_path)["forms"]
    }
    assert any(
        action["id"] == "thank_person" for action in world["actions"]
    )

    engine = WorldEngine(
        world,
        profile=build_player_profile({"name": "Тест"}, seed=7),
        node_id=node_id,
        office_id=office_id,
        seed=7,
    )
    assert engine.attach(node_id, office_id)["ok"] is True
    engine._roll = lambda token: 0.0

    assert engine.enter_scene("thanks")["ok"] is True
    friend = engine.characters["new_friend"]
    before = float(friend["trust"])
    result = engine.execute(
        "thank_person",
        target_ref={"kind": "character", "id": "new_friend"},
    )
    assert result["ok"] is True
    assert result["outcome"] == "success"
    assert float(friend["trust"]) > before

    scenes = SceneCatalog.from_list(world["scenes"])
    assert scenes.get("thanks").allows_action("thank_person")

    story_dir = tmp_path / "storylines"
    _write(
        story_dir / "mini.json",
        {
            "storyline_id": "mini",
            "title": "Мини-сюжет",
            "storyline_tags": ["free", "thanks"],
            "world_path": str(world_path),
            "free_start": {
                "thankful": {
                    "node_id": node_id,
                    "office_id": office_id,
                }
            },
        },
    )
    listed = list_storylines(story_dir, tags=["thanks"])
    assert listed[0]["storyline_id"] == "mini"
    assert load_storyline("mini", story_dir)["storyline_tags"] == [
        "free",
        "thanks",
    ]

    archetypes_path = tmp_path / "archetypes.json"
    _write(
        archetypes_path,
        {
            "schema": 1,
            "archetypes": [
                {
                    "id": "thankful",
                    "label": "Благодарный",
                    "social_layer": "street",
                    "storyline_tags": ["free", "thanks"],
                    "identity_sections": ["values"],
                    "priority_needs": ["friendship"],
                    "needs": {"friendship": 0.1},
                    "traits": {"sociability": 0.1},
                }
            ],
        },
    )
    catalog = load_archetypes_catalog(archetypes_path, use_cache=False)
    assert catalog.get("thankful").storyline_tags == ("free", "thanks")

    dialogue = tmp_path / "dialogue"
    dialogue.mkdir()
    shutil.copy(ROOT / "configs" / "dialogue" / "social.json", dialogue)
    shutil.copy(ROOT / "configs" / "dialogue" / "synthesis.json", dialogue)
    social = _read(dialogue / "social.json")
    social["acts"]["thank"] = {
        "id": "thank",
        "label": "благодарность",
        "match": {"kind": "social", "act": "thank"},
        "interaction": "",
        "reactions": ["accept"],
    }
    _write(dialogue / "social.json", social)
    synthesis = _read(dialogue / "synthesis.json")
    synthesis["answers"]["custom_thanks"] = {"construction": "clause_asset"}
    _write(dialogue / "synthesis.json", synthesis)

    assert load_social(dialogue).acts["thank"].label == "благодарность"
    assert load_synthesis(dialogue)["answers"]["custom_thanks"]
