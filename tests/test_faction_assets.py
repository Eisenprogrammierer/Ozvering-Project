"""Локальные активы фракции и проверка формул (G-10)."""

from __future__ import annotations

from campaign import content_lint
from campaign.faction_state import asset_keys, asset_terms, derived_asset


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
