import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulation as S

GAMES = 10
STEPS = 1000

STATS = {}
_orig_env_init = S.Environment.__init__
_orig_resolve_attack = S.resolve_attack


def _reset_stats():
    STATS.clear()
    STATS.update(
        {
            "direct": 0.0,
            "direct_calls": 0,
            "aggregate": 0.0,
            "aggregate_calls": 0,
            "attack": 0.0,
            "attack_calls": 0,
            "ticks": 0,
            "open_ticks": 0,
        }
    )


def _instrument_env(env):
    orig_tick, orig_rp = env.tick, env.receive_pressure
    flag = {"in_tick": False}

    def tick():
        flag["in_tick"] = True
        try:
            orig_tick()
        finally:
            flag["in_tick"] = False
        STATS["ticks"] += 1
        if env.in_open:
            STATS["open_ticks"] += 1

    def receive_pressure(w):
        src = "aggregate" if flag["in_tick"] else "direct"
        STATS[src] += w
        STATS[src + "_calls"] += 1
        return orig_rp(w)

    env.tick = tick
    env.receive_pressure = receive_pressure


def _env_init(self, *args, **kwargs):
    _orig_env_init(self, *args, **kwargs)
    _instrument_env(self)


def _resolve_attack(att, dfn, work, rng, env=None):
    if env is not None and work:
        STATS["attack"] += work
        STATS["attack_calls"] += 1
    return _orig_resolve_attack(att, dfn, work, rng, env)


def measure(members_fn):
    _reset_stats()
    results = S.run_batch(GAMES, quiet=True, env_members_fn=members_fn)[2]
    return results, dict(STATS)


def _pct(part, whole):
    return f"{100.0 * part / whole:.1f}%" if whole else "—"


def main():
    S.Environment.__init__ = _env_init
    S.resolve_attack = _resolve_attack
    try:
        flat_results, flat = measure(None)
        dbl_results, dbl = measure(lambda rl, ai: [rl, ai])
    finally:
        S.Environment.__init__ = _orig_env_init
        S.resolve_attack = _orig_resolve_attack

    print("=" * 70)
    print(
        f"  A6. Вход среды: канон RL vs UtilityAI, {GAMES} партий, до {STEPS} "
        f"тактов"
    )
    print("=" * 70)

    print("\n[1] Источники входного давления среды (сумма w)")
    for label, s in (
        ("плоская (members=None)     ", flat),
        ("удвоенная (members=[rl,ai])", dbl),
    ):
        total = s["direct"] + s["aggregate"]
        attack = s["attack"]
        retaliate = s["direct"] - s["attack"]
        print(f"\n  {label}: всего {total:8.0f}")
        print(f"      прямой удар  : {attack:8.0f}  ({_pct(attack, total)})")
        print(
            f"      возмездие    : {retaliate:8.0f}  "
            f"({_pct(retaliate, total)})"
        )
        print(
            f"      агрегат труда: {s['aggregate']:8.0f}  "
            f"({_pct(s['aggregate'], total)})"
        )
        if s["aggregate"] and attack:
            print(
                f"      → агрегат/удар = {s['aggregate'] / attack:.2f} "
                f"(пересчёт уже учтённых передач тем же тактом)"
            )
        print(
            f"      окно среды открыто: {s['open_ticks']}/{s['ticks']} тактов "
            f"({_pct(s['open_ticks'], s['ticks'])})"
        )

    print("\n[2] Следствие: исходы партий")
    print(f"  плоская   (members=None)     : {flat_results}")
    print(f"  удвоенная (members=[rl,ai])  : {dbl_results}")

    print("\n[3] Покой среды: do_rest(chosen=False) против осознанного")
    full = S.Environment(start_force=30)
    half = S.Environment(start_force=30)
    f0, e0 = full.force, full.energy_pool
    full.do_rest(chosen=True)
    half.do_rest(chosen=False)
    print(
        f"      осознанный (chosen=True ) : ΔF={full.force - f0:+.2f}  "
        f"ΔE={full.energy_pool - e0:+d}"
    )
    print(
        f"      среды      (chosen=False) : ΔF={half.force - f0:+.2f}  "
        f"ΔE={half.energy_pool - e0:+d}"
    )
    print(
        "      (доля прибыли силы — 1/2, пополнение пула — +1 вместо max(2, "
        "regen))"
    )

    print("\n" + "=" * 70)
    print("  Вывод: канал входа при members=[rl,ai] дублируется агрегатом;")
    print("  возмездие нагружает вход среды наравне с ударами (см. [1]).")
    print("=" * 70)


if __name__ == "__main__":
    main()
