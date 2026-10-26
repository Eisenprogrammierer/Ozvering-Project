"""Тесты войсковых автоматов: персонаж, отделение, стан, приказ, заградотряд.

Модуль ``warfare.py`` надстраивается над каноном и не меняет ``simulation.py``.
Здесь проверяются онтология (16 потребностей, BDI, суперсистемы), пассивный
приказ, принуждение заградотряда, задержка подкрепления и детерминированный
демонстрационный сценарий с паникой/отходом и банзай-атакой.
"""

import random

import simulation as S
import warfare as W


def _char(name, side="red", seed=0, archetype="rifleman"):
    return W.Character(name, side, seed=seed, archetype=archetype)


def _det(name, side="red", n=3, seed=0, archetype="rifleman", **kwargs):
    chars = [_char(f"{name}-{i}", side, seed + i, archetype)
             for i in range(n)]
    return W.Detachment(name, side, chars, **kwargs)


# --- онтология -------------------------------------------------------------

def test_sixteen_needs_exactly():
    assert len(W.NEEDS) == 16
    assert len(set(W.NEEDS)) == 16
    assert set(W.NEEDS) == {
        "hunger", "thirst", "fatigue", "health", "fear", "anxiety",
        "loneliness", "reproduction", "knowledge", "creativity", "boredom",
        "status", "spirituality", "skill", "love", "friendship",
    }
    assert set(W.NEEDS_RU) == set(W.NEEDS)


def test_character_has_bdi_and_needs_outside_canonical_state():
    c = _char("bdi", seed=5, archetype="veteran")
    # BDI: beliefs / desires / intentions — все три компонента присутствуют.
    assert isinstance(c.beliefs, dict)
    assert set(c.needs) == set(W.NEEDS)
    intent = c.deliberate()
    assert isinstance(intent, W.Intention)
    assert intent.kind in {
        "assault", "fire", "hold", "rest", "retreat", "banzai"}
    assert c.intentions and c.intentions[-1] is intent
    assert set(c.desires) >= set(W.NEEDS)
    # Потребности — BDI-слой, а не третья метрика модели.
    assert "needs" not in c.state
    assert set(c.state) >= {"force", "energy_pool", "rest_units"}


def test_personality_seed_is_reproducible_and_mutable_by_archetype():
    a = W.Personality.from_seed(seed=42, archetype="rifleman")
    b = W.Personality.from_seed(seed=42, archetype="rifleman")
    assert a.as_dict() == b.as_dict()
    c = W.Personality.from_seed(seed=42, archetype="commissar")
    assert c["discipline"] >= a["discipline"]
    assert all(0.0 <= v <= 1.0 for v in c.as_dict().values())
    assert set(a.as_dict()) == set(W.TRAITS)


# --- приказ ----------------------------------------------------------------

def test_order_is_passive_and_modulates_targets_for_duration():
    det = _det("ord", n=2)
    order = W.Order("Наступление", W.OrderSignal(
        aggression=0.2, morale=2.0, retreat_allowed=False),
        duration=2, targets=[det])
    assert order.active
    mod = det.modulation()
    assert mod.aggression == 0.2
    assert mod.retreat_allowed is False
    assert all(mod.retreat_allowed is False
               for c in det.characters if (mod := c.modulation()) is not None)
    # Приказ касается и отделения, и его персонажей.
    assert all(order in c.orders for c in det.characters)
    order.tick()
    assert order.active
    order.tick()
    assert not order.active
    assert det.modulation().retreat_allowed is True


def test_order_can_touch_character_directly():
    c = _char("solo")
    order = W.Order("Приказ", {"fear": 0.1, "needs": {"hunger": 0.2}},
                    duration=3, targets=[c])
    assert order in c.orders
    mod = c.modulation()
    assert mod.fear == 0.1
    assert mod.needs["hunger"] == 0.2


def test_deferred_order_waits_for_issue():
    det = _det("deferred", n=2)
    order = W.Order("Артобстрел", W.OrderSignal(fear=0.2), duration=2,
                    targets=[det], defer=True)
    # Отложенный приказ не касается адресата до ввода в силу.
    assert det.modulation().fear == 0.0
    assert order not in det.orders
    sim = W.WarfareSimulation(seed=0, turns=1)
    sim.issue_order(order)
    assert det.modulation().fear == 0.2
    assert order in det.orders


# --- отделение -------------------------------------------------------------

def test_detachment_is_one_combat_unit_over_many_characters():
    a = _det("A", "red", n=4, seed=10)
    b = _det("B", "blue", n=5, seed=20)
    assert len(a.members) == 4 and len(b.members) == 5
    # Наружу — одна сила/пул (не сумма персональных сил персонажей).
    assert a.force == min(34.0, 6.0 + 2.0 * 4)
    personal = [c.force for c in a.characters]
    before = (a.force, b.force)
    work_a, work_b = S.run_tick(
        a, b,
        lambda me, opp, rng: a.choose_intent(opp, rng),
        lambda me, opp, rng: b.choose_intent(opp, rng),
        random.Random(1))
    assert isinstance(work_a, int) and isinstance(work_b, int)
    assert (a.force, b.force) != before
    # Персонажи не получают удары отдельно: отделение — единая боевая единица.
    assert [c.force for c in a.characters] == personal


def test_character_panic_and_fanatical_are_periodic_states():
    p = _char("panic", seed=1, archetype="conscript")
    p.morale = 20
    p.needs.update({"fear": 0.9, "anxiety": 0.9,
                    "fatigue": 0.8, "health": 0.8})
    p.tick_needs(in_combat=True, under_fire=1.0, rng=random.Random(0))
    assert p.mind == "panicked" and p.panicked

    f = _char("fan", "blue", seed=3, archetype="commissar")
    f.morale = 90
    f.needs.update({"fear": 0.0, "anxiety": 0.0})
    f.tick_needs(in_combat=True, under_fire=0.0, rng=random.Random(0))
    assert f.mind == "fanatical" and f.fanatical
    # Кулдаун: на следующем такте без новых причин состояние снимается.
    f.tick_needs(in_combat=True, under_fire=0.0, rng=random.Random(1))
    assert not f.fanatical


def test_barrier_stops_retreating_detachment():
    target = _det("line", "red", n=3, seed=30)
    barrier = W.BarrierDetachment(
        "zagrad", "red", [_char("z1", "red", 40), _char("z2", "red", 41)],
        targets=[target.name])
    target.retreating = True
    target.panicked = True
    target.morale = 30
    out = barrier.enforce([target], rng=random.Random(0), turn=1)
    assert out
    assert not target.retreating
    assert target.coerced_by == "zagrad"
    assert target.modulation().retreat_allowed is False
    assert barrier.stopped == 1
    # Заградотряд сам не отступает.
    assert barrier.retreat_allowed is False


# --- стан и подкрепление ---------------------------------------------------

def test_stan_spawns_on_interval():
    reserve = _det("reserve", "red", n=2, seed=50)
    stan = W.Stan("stan", "red", reserve=[reserve], spawn_interval=3)
    assert stan.drain_spawns() == []
    stan.tick()
    stan.tick()
    assert stan.drain_spawns() == []
    stan.tick()
    out = stan.drain_spawns()
    assert out == [reserve]
    assert reserve.position == stan.rally
    assert stan.spawned == [reserve]


def test_reinforcement_arrives_only_after_delay():
    det = _det("reinf", "blue", n=2, seed=60)
    r = W.Reinforcement("reinf-sys", "blue", [det], delay=4)
    for _ in range(3):
        r.tick()
        assert r.drain_arrivals() == []
    assert not r.ready
    r.tick()
    assert r.ready
    assert r.drain_arrivals() == [det]
    assert r.deployed
    assert r.drain_arrivals() == []


# --- демонстрационный сценарий --------------------------------------------

def test_other_needs_multiply_health_degradation():
    """Критические нужды ускоряют рост health, закрытые — замедляют."""
    low = _char("low", seed=1)
    high = _char("high", seed=1)
    for need in W.HEALTH_NEED_WEIGHTS:
        low.needs[need] = 0.0
        high.needs[need] = 1.0
    assert high.health_degradation_multiplier() > 1.0
    assert low.health_degradation_multiplier() < 1.0
    after_low = low.needs["health"]
    after_high = high.needs["health"]
    low.tick_needs(seconds=1800, rng=random.Random(0))
    high.tick_needs(seconds=1800, rng=random.Random(0))
    assert (
        high.needs["health"] - after_high >
        low.needs["health"] - after_low
    )


def test_character_dies_when_health_reaches_critical_value():
    c = _char("doomed", seed=3)
    c.needs["health"] = 0.999
    c.tick_needs(seconds=1800, rng=random.Random(0))
    assert c.dead
    assert c.is_dead
    assert c.needs["health"] == W.HEALTH_DEATH_THRESHOLD
    # Смерть необратима: обычное лечение не воскрешает.
    assert c.satisfy({"health": 0.5}) == {}
    assert c.is_dead


def test_demo_scenario_is_deterministic_and_has_war_events():
    first = W.build_demo_scenario(seed=7, turns=140).run()
    second = W.build_demo_scenario(seed=7, turns=140).run()
    assert first["counts"] == second["counts"]
    assert first["winner"] == second["winner"]
    assert first["turn"] == second["turn"]
    counts = first["counts"]
    # Обе стороны, персонажи внутри отделений, паники/отходы, банзай,
    # заградотряд, выход из стана и подкрепление с задержкой.
    assert first["sides"]["red"] and first["sides"]["blue"]
    assert counts.get("panic", 0) > 0
    assert counts.get("retreat", 0) > 0
    assert counts.get("banzai", 0) > 0
    assert counts.get("barrier", 0) > 0
    assert counts.get("barrier_fire", 0) > 0
    assert counts.get("spawn", 0) > 0
    assert counts.get("reinforcement", 0) > 0
    assert counts.get("support", 0) > 0
    side = first["sides"]["red"][0]
    assert side["characters"]
    assert set(side["characters"][0]["needs"]) == set(W.NEEDS)
    assert side["characters"][0]["personality"]
