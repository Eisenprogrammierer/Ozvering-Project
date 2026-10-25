"""Тесты новых слоёв: энтропия смысла, лоссовая наблюдаемость, LOD.

Все слои по умолчанию выключены (``entropy=False``, ``lossy=False``, LOD-1),
поэтому канон ``run_batch`` остаётся неизменным. Здесь проверяются контракты
самих слоёв и их безопасность для канона.
"""

import math
import random

import pytest

import information
import lod
import observability
import simulation as S


# --- Энтропия смысла -------------------------------------------------------

def test_entropy_bounds_and_ratchet():
    e = information.BeliefEntropy()
    prev = e.H_cum
    for i in range(50):
        base = 3 if i % 3 == 0 else (i % 2)
        e.observe(base, base == 3)
        assert -1e-9 <= e.H_local <= information.H_MAX + 1e-9
        assert e.H_cum + 1e-12 >= prev
        assert 0.0 <= e.noise_floor <= 1.0
        prev = e.H_cum


def test_entropy_no_reverse_across_lineage():
    e = information.BeliefEntropy()
    # Сначала «смысл» уплотняется, затем размывается — H_cum растёт.
    for _ in range(30):
        e.observe(0, False)
    for i in range(30):
        e.observe(3 if i % 2 else 0, i % 2 == 1)
    cum = e.H_cum
    assert cum > 0.0

    # Новая линия: локальный отсчёт заново, глобальный износ — нет.
    e.new_lineage(reset_counts=True)
    assert e.H_cum == pytest.approx(cum)
    for _ in range(5):
        e.observe(0, False)
    assert e.H_cum == pytest.approx(cum)


def test_heavy_tail_deterministic():
    # Один и тот же seed на двух независимых объектах даёт один и тот же ряд.
    a = information.BeliefEntropy(deadband=0.0)
    b = information.BeliefEntropy(deadband=0.0)
    a.noise_floor = b.noise_floor = 1.0
    r1, r2 = random.Random(42), random.Random(42)
    seq_a = [a.next_factor(r1) for _ in range(20)]
    seq_b = [b.next_factor(r2) for _ in range(20)]
    assert seq_a == seq_b
    assert all(0.5 <= f <= 2.0 for f in seq_a)
    assert max(abs(math.log(f)) for f in seq_a) > 0.1  # тяжёлые хвосты


def test_hysteresis_keeps_factor():
    e = information.BeliefEntropy(deadband=10.0)
    e.noise_floor = 1.0
    r = random.Random(1)
    assert all(e.next_factor(r) == 1.0 for _ in range(10))


def test_perturb_only_beliefs():
    a = S.Agent()
    a.info.deadband = 0.0
    a.info.noise_floor = 1.0
    a.beliefs["opp_energy"] = 50
    a.beliefs["opp_force"] = 50
    a.beliefs["opp_w_adopt"] = 10.0
    force0, pool0 = a.force, a.energy_pool
    a.info.perturb(a.beliefs, random.Random(3))
    # Физические метрики не тронуты: шум работает на информации, не энергии.
    assert a.force == force0 and a.energy_pool == pool0
    assert a.beliefs["belief_noise_factor"] != 1.0


# --- Лоссовая наблюдаемость ------------------------------------------------

def test_lossy_channel_quantizes_and_loses_identity():
    ch = observability.LossyChannel(resolution=1.0, delay=0)
    ch.push(2.5)
    ch.push(3.7)
    obs = ch.drain()
    assert obs.work == pytest.approx(6.0)
    assert obs.count == 2
    assert not hasattr(obs, "source")          # identity/тип не сохраняются
    assert ch.drain().work == pytest.approx(0.0, abs=1e-9)


def test_lossy_channel_delay():
    ch = observability.LossyChannel(resolution=1.0, delay=1)
    ch.push(5)
    assert ch.drain().work == 0.0
    assert ch.drain().work == 5.0


def test_public_window_lag():
    env = S.Environment(lossy=True)
    env._public_window = True
    env._public_window_prev = False
    assert env.public_window() is False
    env._public_window_prev = True
    assert env.public_window() is True


def test_flags_off_keep_canon():
    _, (w1, h1, _, e1), r1 = S.run_batch(1, quiet=True)
    _, (w2, h2, _, e2), r2 = S.run_batch(1, quiet=True, entropy=False, lossy=False)
    assert (w1, h1, e1, r1) == (w2, h2, e2, r2)


def test_entropy_smoke():
    _, _, res = S.run_batch(1, quiet=True, entropy=True)
    assert sum(res.values()) == 1


# --- LOD -------------------------------------------------------------------

def test_lod_integrate_time_close_to_ticks():
    a = S.Agent()
    a.force, a.energy_pool = 50, 5
    b = S.Agent()
    b.force, b.energy_pool = 50, 5
    for _ in range(5):
        a.upkeep()
        a.tick_energy()
        a.tick_input_state()
        a.do_rest(chosen=True)
    lod.integrate_time(b, 5)
    assert abs(a.force - b.force) <= 2.0
    assert abs(a.energy_pool - b.energy_pool) <= 5.0


def test_lod_level_selection():
    c = lod.LodController()
    a, b = S.Agent(), S.Agent()
    for x in (a, b):
        x.force, x.energy_pool, x.w_adopt, x.in_open = 100, 100, 0.0, False
    assert c.level(a, b) == lod.LOD3
    a.w_adopt = a.schmitt_on() * 0.9
    assert c.level(a, b) == lod.LOD1
    a.w_adopt = a.schmitt_on() * 2.0
    assert c.level(a, b) == lod.LOD2


def test_lod_runner_deterministic():
    def rest(me, opp, rng):
        return "REST", 0

    a, b = S.Agent(), S.Agent()
    ha, hb, lv = lod.run_duel_lod(a, b, rest, rest, random.Random(0), None, 20)
    c, d = S.Agent(), S.Agent()
    hc, hd, lv2 = lod.run_duel_lod(c, d, rest, rest, random.Random(0), None, 20)
    assert (ha, hb, lv) == (hc, hd, lv2)
