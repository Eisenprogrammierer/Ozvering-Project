"""Локальные активы фракции и проверка формул (G-10)."""

from __future__ import annotations

from pathlib import Path

from campaign import content_lint
from campaign.automata import AutomataCampaign
from campaign.faction_state import asset_keys, asset_terms, derived_asset
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]


class FakeFaction:
    def __init__(self, record):
        self.id = "faction_test"
        self.record = record
        self.characters = []
        self.organs = []
        self.subfactions = []
        self.context = {"myth": 0.7}
        self.score_assets = {}


def test_local_formula_overrides_global_and_adds_key():
    faction = FakeFaction(
        {
            "asset_formulas": {
                "myth": [{"metric": "context.myth", "weight": 1.0}]
            }
        }
    )
    assert "myth" in asset_keys(faction)
    assert asset_terms(faction, "myth") == [
        {"metric": "context.myth", "weight": 1.0}
    ]
    assert derived_asset(faction, "myth") == 0.7


def test_local_asset_passes_lint_with_own_label_and_formula():
    defaults = {
        "asset_labels": {"legitimacy": "законность"},
        "faction_state": {"assets": {}},
        "organ_kinds": {},
    }
    factions = {
        "factions": {
            "red": {
                "id": "faction_empire",
                "assets": {"myth": 0.6},
                "asset_labels": {"myth": "миф"},
                "asset_formulas": {
                    "myth": [
                        {"metric": "context.myth", "weight": 1.0}
                    ]
                },
            }
        }
    }
    assert content_lint.check_defaults(defaults, factions) == []


def test_bad_formula_metric_and_missing_label_are_reported():
    defaults = {
        "asset_labels": {},
        "faction_state": {"assets": {}},
        "organ_kinds": {},
    }
    factions = {
        "factions": {
            "red": {
                "id": "faction_empire",
                "assets": {"myth": 0.6},
                "asset_formulas": {
                    "myth": [
                        {"metric": "contextt.myth", "weight": 1.0}
                    ]
                },
            }
        }
    }
    problems = content_lint.check_defaults(defaults, factions)
    assert any("нет подписи" in item for item in problems)
    assert any("неизвестная метрика" in item for item in problems)


def test_preset_keeps_local_formulas_labels_and_orders():
    """Локальные блоки доезжают из lore_factions.json до рантайма.

    Юнит-тест на ``FakeFaction`` проверяет только чтение record; этот —
    что пресет не теряет данные фракции по дороге.
    """
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    )
    campaign = AutomataCampaign(generator.generate(seed=13), seed=13)
    empire = campaign.faction("red")
    assert empire.record.get("asset_labels", {}).get("myth") == "миф"
    assert "myth" in asset_keys(empire)
    assert empire.asset("myth") > 0.0
    assert [item["id"] for item in empire.orders]
