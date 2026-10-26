"""Тесты runtime-слоя организаций и его интеграции с ``warfare``.

Аналитическое ядро проверяется отдельно в ``test_organizations.py``. Здесь
важно, что организация:

* собирает Population из живых персонажей на каждом такте;
* применяет мягкие эффекты к существующим BDI-потребностям, а не вводит новые
  метрики в ``Agent.state``;
* исключает вышедших участников и распадается без желающих;
* остаётся полностью опциональной для ``WarfareSimulation``.
"""

from __future__ import annotations

import simulation as S
import warfare as W
from organizations import OrganizationRuntime
from organizations.runtime import MODE_EFFECTS, PHASE_ORDER


def _all_needs(character, value=0.0):
    for need in W.NEEDS:
        character.needs[need] = value
    return character


def _character(name, seed=0, fear=0.85, anxiety=0.55):
    character = W.Character(name, "red", seed=seed)
    _all_needs(character, 0.0)
    character.needs["fear"] = fear
    character.needs["anxiety"] = anxiety
    return character


def _detachment(name="линия", count=6, fear=0.85):
    characters = [
        _character("%s-%d" % (name, index), seed=index, fear=fear)
        for index in range(count)
    ]
    return W.Detachment(name, "red", characters)


def test_runtime_effects_use_only_canonical_needs():
    assert set(MODE_EFFECTS) <= {
        "order", "meaning", "provision", "status",
        "knowledge", "care", "exchange",
    }
    for items in MODE_EFFECTS.values():
        for need, _factor in items:
            assert need in W.NEEDS


def test_runtime_is_an_environment_and_applies_effects():
    det = _detachment(count=8)
    before = det.needs_summary()
    organization = OrganizationRuntime("государство", "red",
                                       detachments=[det])

    assert isinstance(organization, S.Environment)
    update = organization.tick(turn=1)

    assert organization.active is True
    assert update["active"] is True
    assert update["phase"] == "mobilizing"
    assert update["priority_need"] == "fear"
    assert update["active_count"] > 0
    assert update["last_effects"]["fear"] > 0.0
    after = det.needs_summary()
    assert after["fear"] < before["fear"]
    # Взнос в организацию — это не новая метрика, а рост усталости/голода.
    assert after["fatigue"] > before["fatigue"]


def test_runtime_phase_cycle_is_deterministic():
    def phases():
        det = _detachment(count=6)
        organization = OrganizationRuntime("порядок", "red",
                                           detachments=[det])
        return [organization.tick(turn=index + 1)["phase"]
                for index in range(4)]

    first = phases()
    second = phases()
    assert first == second
    assert first[0] == "mobilizing"
    assert set(first) <= set(PHASE_ORDER) | {"crisis"}


def test_runtime_exits_are_one_way_by_default():
    active = _character("активный", fear=0.9)
    idle = _all_needs(_character("инертный"), 0.0)
    det = W.Detachment("линия", "red", [active, idle])
    organization = OrganizationRuntime("государство", "red",
                                       detachments=[det])

    first = organization.tick(turn=1)
    assert first["active_count"] == 1
    assert "линия/инертный" in organization.exited
    assert any(event["kind"] == "organization_exit"
               for event in first["events"])

    second = organization.tick(turn=2)
    assert second["initial_count"] == 1
    assert second["active_count"] == 1
    assert all(member_id != "линия/инертный"
               for member_id, _character, _det
               in organization._character_bindings())


def test_runtime_dissolves_without_willing_members():
    det = _detachment(count=3, fear=0.0)
    for character in det.characters:
        _all_needs(character, 0.0)
    organization = OrganizationRuntime("пустое", "red",
                                       detachments=[det])

    update = organization.tick(turn=1)
    assert update["active"] is False
    assert update["phase"] == "dissolved"
    assert update["active_count"] == 0
    assert any(event["kind"] == "organization_dissolved"
               for event in update["events"])
    assert organization.exited

    again = organization.tick(turn=2)
    assert again["active"] is False
    assert again["events"] == []


def test_warfare_simulation_runs_optional_organization():
    sim = W.WarfareSimulation(seed=7, turns=2)
    det = _detachment(count=4)
    sim.add_detachment(det)
    organization = OrganizationRuntime("государство", "red",
                                       detachments=[det])
    assert sim.add_organization(organization) is organization

    sim.tick()
    summary = sim.summary()
    assert summary["organizations"][0]["name"] == "государство"
    assert summary["organizations"][0]["phase"] == "mobilizing"
    assert any(event["kind"] == "organization" for event in summary["events"])


def test_warfare_without_organizations_is_unchanged():
    sim = W.WarfareSimulation(seed=7, turns=2)
    sim.add_detachment(_detachment(count=3))
    sim.tick()
    summary = sim.summary()
    assert summary["organizations"] == []
    assert not any(event["kind"].startswith("organization")
                   for event in summary["events"])


def test_public_snapshot_hides_exact_weights_and_exits():
    det = _detachment(count=3)
    organization = OrganizationRuntime("государство", "red",
                                       detachments=[det])
    organization.tick(turn=1)
    public = organization.public_snapshot()
    assert public["name"] == "государство"
    assert public["active"] is True
    assert public["phase"] == "mobilizing"
    assert "mode_weights" not in public
    assert "exited" not in public
    assert "last_effects" not in public
