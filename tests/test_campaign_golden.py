"""Golden-снимок кампании автоматов.

Проверка фиксирует не отдельное поле, а весь детерминированный срез
кампании после шести суток: активы, оценки, работы, органы, подфракции
и ролевые события. Схемы и линтер не должны незаметно менять поведение.

Фикстура обновляется осознанно::

    OZVERIN_UPDATE_GOLDEN=1 venv/bin/python -m pytest \
        tests/test_campaign_golden.py -q
"""

import hashlib
import json
import os
from pathlib import Path

from campaign.automata import AutomataCampaign
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog
from systems.events import EventCatalog, EventEngine

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "empire_seed13.json"
SEED = 13
TURNS = 6


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _round_map(values, digits=6):
    return {
        str(key): round(float(value), digits)
        for key, value in sorted((values or {}).items())
    }


def _project(snapshot):
    """Компактный, но чувствительный срез полного снимка."""
    factions = {}
    for side in sorted(snapshot.get("factions") or {}):
        faction = snapshot["factions"][side]
        factions[side] = {
            "score": round(float(faction.get("score", 0.0)), 6),
            "dissolved": bool(faction.get("dissolved")),
            "assets": _round_map(faction.get("assets")),
            "action_uses": {
                str(key): int(value)
                for key, value in sorted(
                    (faction.get("action_uses") or {}).items()
                )
                if int(value) > 0
            },
            "organs": {
                str(organ.get("id")): {
                    "kind": str(organ.get("kind") or ""),
                    "subfaction_id": str(
                        organ.get("subfaction_id") or ""
                    ),
                    "integrity": round(
                        float(organ.get("integrity", 0.0)), 6
                    ),
                    "support": round(
                        float(organ.get("support", 0.0)), 6
                    ),
                    "status": str(organ.get("status") or ""),
                }
                for organ in sorted(
                    faction.get("organs") or (),
                    key=lambda item: str(item.get("id") or ""),
                )
            },
            "subfactions": {
                str(item.get("id")): round(
                    float(item.get("share", 0.0)), 6
                )
                for item in sorted(
                    faction.get("subfactions") or (),
                    key=lambda value: str(value.get("id") or ""),
                )
            },
            "characters": [
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "post_id": str(item.get("post_id") or ""),
                    "alive": not bool(
                        item.get("is_dead", item.get("dead", False))
                    ),
                    "force": round(float(item.get("force", 0.0)), 6),
                    "energy": round(float(item.get("energy", 0.0)), 6),
                    "morale": round(float(item.get("morale", 0.0)), 6),
                }
                for item in sorted(
                    faction.get("characters") or (),
                    key=lambda value: str(value.get("id") or ""),
                )
            ],
        }
    return {
        "digest": hashlib.sha256(_canonical(snapshot)).hexdigest(),
        "turn": int(snapshot.get("turn", 0)),
        "elapsed": round(float(snapshot.get("elapsed", 0.0)), 6),
        "actions_left": int(snapshot.get("actions_left", 0)),
        "outcome": snapshot.get("outcome"),
        "finished": bool(snapshot.get("finished")),
        "factions": factions,
        "story_events": [
            {
                "template_id": str(item.get("template_id") or ""),
                "title": str(item.get("title") or ""),
                "turn": int(item.get("turn", 0)),
            }
            for item in snapshot.get("story_events") or ()
        ],
    }


def build_golden():
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    )
    campaign = AutomataCampaign(generator.generate(seed=SEED), seed=SEED)
    # conftest подменяет контент на тестовый; golden обязан читать
    # настоящий каталог событий, иначе он не заметит правку сюжета.
    campaign.story_engine = EventEngine(
        catalog=EventCatalog.load(ROOT / "configs" / "systems"),
        seed=SEED,
    )
    for _ in range(TURNS):
        campaign.advance_simulation(86400, snapshot=False, tick=False)
        campaign.end_turn()
    return _project(campaign.snapshot())


def test_campaign_golden_is_stable():
    actual = build_golden()
    if os.environ.get("OZVERIN_UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert actual == expected
