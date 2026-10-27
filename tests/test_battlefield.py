import random

import simulation as S
from ui import battlefield as B


def test_iso_grid_roundtrip():
    origin = (100, 50)
    for col in range(B.GRID_W):
        for row in range(B.GRID_H):
            x, y = B.grid_to_screen(col, row, origin)
            assert B.screen_to_grid(x, y, origin) == (col, row)


def test_iso_grid_outside_is_none():
    assert B.screen_to_grid(-10_000, -10_000, (0, 0)) is None


def test_model_starts_in_intro_and_out_of_contact():
    m = B.BattlefieldModel(seed=0)
    assert m.roleplay.active == "intro"
    assert not m.contact
    assert m.objective_owner is None
    assert set(m.units) == {"player", "enemy"}
    assert (5, 5) in m.move_targets("player")
    assert (7, 3) not in m.move_targets("player")


def test_move_is_bounded_by_range_and_cp():
    m = B.BattlefieldModel(seed=0)
    far = B.chebyshev(m.player_unit.pos, (10, 0)) > B.MOVE_RANGE
    assert far
    ok, _, _ = m.move_unit("player", 10, 0)
    assert not ok
    ok, _, _ = m.move_unit("player", 5, 5)
    assert ok
    assert m.player_unit.pos == (5, 5)
    assert m.turn == 2


def test_attack_requires_contact_and_resolves_model_tick():
    m = B.BattlefieldModel(seed=0)
    ok, _, _ = m.issue_order("ATTACK")
    assert not ok
    m.player_unit.col, m.player_unit.row = 5, 4
    m.enemy_unit.col, m.enemy_unit.row = 6, 4
    m.command_points = 3
    before = (m.player.force, m.enemy.force)
    ok, _, _ = m.issue_order("ATTACK")
    assert ok
    after = (m.player.force, m.enemy.force)
    assert after != before
    assert m.turn >= 2


def test_roleplay_choice_changes_cp_profile_and_trait():
    m = B.BattlefieldModel(seed=0)
    cp = m.command_points
    choice = m.roleplay.choose(0)
    assert choice is not None
    assert m.command_points == min(m.max_command_points, cp + 1)
    assert m.player.profile == "ZEALOT"
    assert ("Дерзость", "Audacity") in m.roleplay.traits
    assert m.roleplay.active is None


def test_objective_owner_and_bonus():
    m = B.BattlefieldModel(seed=0)
    m.player_unit.col, m.player_unit.row = m.objective
    m._update_objective()
    assert m.objective_owner == "player"
    cp = m.command_points
    m._end_turn()
    assert m.command_points > cp
