"""Автотест ГЛУБИНЫ ``Environment`` (P2, docs/TODO.md).

``exp_hierarchy.py`` показывает иерархию ярусов, но только визуально/численно;
здесь те же свойства проверяются УТВЕРЖДЕНИЯМИ с кодом возврата — чтобы
регрессию по глубине ловил CI, а не глаз.

Что проверяется (самоподобие кодекса на всех ярусах, docs/MODEL.md, раздел 14):

  D1. ОНТОЛОГИЯ НЕ РАСШИРЯЕТСЯ — у среды любого яруса (0/1/2/3) состав полей
      ``state`` совпадает с автоматом ``Agent``: ни одной новой переменной.
  D2. ЕДИНЫЙ ЗАКОН ТИПА — ``context_base``/``receptive_type`` не переопределены
      у ``Environment``: на сетке контекстов вывод совпадает с ``Agent``. И
      производное ``defense`` живого яруса совпадает с законом (тип контекстный,
      не хранится в ``state``).
  D3. РЕКУРСИЯ ТАКТА — ``top.tick()`` доходит до яруса глубины ≥2: труд члена
      самого нижнего яруса нагружает вход именно нижнего яруса, а не только
      верхнего.
  D4. РЕКУРСИЯ АГРЕГАЦИИ — ``member_output`` транзитивен: агрегат нижнего яруса
      входит в выход верхнего (иначе глубина ≥2 разорвана по входу).
  D5. СНИМОК РЕКУРСИВЕН — ``snapshot()`` вкладывает ``members`` до самого низа.
  D6. ГРАНИЦА КОМПЕТЕНЦИИ — тактуются ТОЛЬКО ярусы-``Environment``; автоматы-
      члены (вне дуэли) такта не имеют и не меняются от ``tick()`` среды.

Запуск из корня репозитория (0 — все утверждения верны, 1 — есть регрессия):
    python3 experiments/exp_hierarchy_depth.py
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulation as S
from simulation import Agent, Environment, TYPES

FAILURES = []


def check(cond, msg):
    """Одна проверка: печатает verdict, копит провалы."""
    print(f"  [{'ok' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)
    return cond


def chain_depth(n):
    """Цепочка сред глубины ``n``: top(env)->...->leaf(env)->[Agent-работник].

    Возвращает ``(top, leaf, worker)``. ``worker`` — автомат-член нижнего яруса
    с фиктивной передачей ``last_work``; агенты вне дуэли такта не имеют, но их
    работа входит в ``member_output`` (см. D4).
    """
    worker = Agent()
    worker.last_act, worker.last_work = TYPES[0], 3.0
    node = Environment(start_force=8.0, members=[worker])
    leaf = node
    for _ in range(n - 1):
        node = Environment(start_force=8.0, members=[node])
    return node, leaf, worker


def d1_ontology():
    print("D1. Онтология не расширяется на глубине")
    base = set(Agent().state)
    ok = True
    for d in range(0, 4):
        top, _, _ = chain_depth(d)
        keys = set(top.state)
        ok &= check(keys == base, f"глубина {d}: state == Agent (лишних полей нет)")
    return ok


def d2_type_law():
    print("D2. Единый закон рецептивного типа на всех ярусах")
    grid = itertools.product((0.0, 3.0, 12.0), (0.0, 2.0, 9.0),
                             (False, True), (5.0, 60.0), (0, 1, 2))
    same = True
    for ep, wa, op, fr, hid in grid:
        a = Agent.receptive_type(ep, wa, op, fr, hid)
        e = Environment.receptive_type(ep, wa, op, fr, hid)
        same &= (a == e)
        cb = Agent.context_base(ep, wa, op, fr)
        same &= (cb == Environment.context_base(ep, wa, op, fr))
    check(same, "context_base/receptive_type не переопределены у Environment")

    top, _, _ = chain_depth(2)
    law = Agent.receptive_type(top.energy_pool, top.w_adopt, top.in_open,
                               top.force, TYPES.index(top.last_act)
                               if top.last_act in TYPES else 0)
    check(top.defense == law, "defense яруса выводится законом (не хранится)")
    check("defense" not in top.state, "поля defense в state нет")
    return same


def d3_tick_recursion():
    print("D3. Рекурсия такта доходит до глубины ≥2")
    top, leaf, worker = chain_depth(3)
    before = leaf.w_adopt
    for _ in range(5):
        top.tick()
    check(leaf.w_adopt > before,
          f"труд члена нижнего яруса нагрузил ЕГО вход (w_adopt {before:.2f}"
          f" -> {leaf.w_adopt:.2f})")
    check(top.w_adopt > 0, "верхний вход тоже нагружен (через агрегацию)")
    return True


def d4_output_recursion():
    print("D4. Рекурсия агрегации выхода")
    top, leaf, worker = chain_depth(3)
    check(abs(leaf.member_output() - 3.0) < 1e-9,
          f"нижний ярус видит работу члена ({leaf.member_output():.2f})")
    check(abs(top.member_output() - leaf.member_output()) < 1e-9,
          f"верхний выход = агрегат нижнего ({top.member_output():.2f})")
    bare = Environment(start_force=8.0)              # цепочка без работников
    for _ in range(2):
        bare = Environment(start_force=8.0, members=[bare])
    check(bare.member_output() == 0.0, "без труда членов выход 0 (не выдуман)")
    return True


def d5_snapshot():
    print("D5. Снимок рекурсивен")
    top, _, _ = chain_depth(3)

    def depth(s):
        return 1 if not s.get("members") else 1 + max(depth(m) for m in s["members"])

    got = depth(top.snapshot())
    check(got >= 3, f"snapshot вкладывает members до низа (глубина {got})")
    return got >= 3


def d6_agent_boundary():
    print("D6. Тактуются только ярусы-Environment")
    worker = Agent()
    node = Environment(start_force=8.0, members=[worker])
    top = Environment(start_force=8.0, members=[node])
    ep, fi = worker.energy_pool, worker.force
    for _ in range(5):
        top.tick()
    check(worker.energy_pool == ep and worker.force == fi,
          "автомат-член вне дуэли такта не имеет (состояние неизменно)")
    return True


def main():
    print("Автотест глубины Environment (P2)")
    d1_ontology()
    d2_type_law()
    d3_tick_recursion()
    d4_output_recursion()
    d5_snapshot()
    d6_agent_boundary()
    print("\n=== ИТОГ ===")
    if FAILURES:
        print(f"НАРУШЕНО утверждений: {len(FAILURES)}")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("Все утверждения верны: кодекс самоподобен на всех ярусах.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
