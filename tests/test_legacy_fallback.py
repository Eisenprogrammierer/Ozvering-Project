"""Legacy-модули остаются явно помеченным fallback, а не вторым путём.

Phase 6a: пока покрытие языка и RL-сравнение не доказаны, `ChartParser`,
`InferenceEngine` и `NeedPolicy` нельзя удалять — они держат режим
`legacy` и платформы без `soar-sml`. Но и вторым когнитивным путём они
быть не должны, поэтому роль каждого зафиксирована машинно.
"""

from __future__ import annotations

from pathlib import Path

from campaign import npc_policy
from campaign.dialogue import inference, parser

ROOT = Path(__file__).resolve().parents[1]
MODULES = (parser, inference, npc_policy)


def test_legacy_modules_declare_their_role():
    assert parser.LEGACY_ROLE == "deep-fallback"
    assert inference.LEGACY_ROLE == "deep-fallback"
    assert npc_policy.LEGACY_ROLE == "decision-fallback"


def test_legacy_modules_explain_the_role_in_docstring():
    for module in MODULES:
        text = (module.__doc__ or "").lower()
        assert "fallback" in text, module.__name__
        assert "статус" in text, module.__name__


def test_legacy_roles_are_documented():
    text = (
        ROOT / "docs" / "SOAR_RIVESCRIPT_MIGRATION.md"
    ).read_text(encoding="utf-8")
    assert "deep-fallback" in text
    assert "decision-fallback" in text
