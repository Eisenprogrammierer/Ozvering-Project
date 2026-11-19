"""P7: регрессии лорных кампаний, BDI и эффектов.

Гибкость персонажа не должна ломать четыре кампании-лидера, 16
потребностей и мягкую обработку незнакомых эффектов.
"""

from __future__ import annotations

from pathlib import Path

import bdi
from campaign.effects import apply_effects
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = ROOT / "configs" / "campaigns"


def test_sixteen_canonical_needs_are_unchanged():
    model = bdi.load_bdi()
    assert len(model.needs) == 16
    assert {"health", "friendship", "knowledge", "creativity"} <= set(
        model.needs
    )


def test_four_lore_campaigns_still_generate():
    roles = RoleCatalog.load(ROOT / "configs" / "roles")
    lore = {
        role.id: role
        for role in roles.available_roles()
        if "lore" in role.tags
    }
    assert set(lore) == {
        "empire_leader",
        "republic_leader",
        "cult_leader",
        "corporation_leader",
    }

    for role_id, role in lore.items():
        template = CAMPAIGNS / ("%s.json" % role.storyline_id)
        assert template.is_file(), role_id
        generator = CampaignPresetGenerator(
            catalog=roles,
            template_path=template,
        )
        preset = generator.generate(role_id=role_id, seed=7)
        assert preset.player_side
        assert preset.factions


def test_unknown_effect_is_ignored_not_fatal():
    applied = apply_effects(
        None,
        {"relations": {"target": {"trust": 0.1}}},
        target=None,
    )
    # Без фракции отношения писать некуда, но эффект не роняет кампанию.
    assert applied["ignored"]
    assert applied["ignored"][0]["reason"] == "no_store"
