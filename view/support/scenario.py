"""Сборка мира для UI-каркаса и загрузка карты.

Кампанийный UI играет за стрелковую бригаду: 16 рот против 32 рот
противника (двукратное общее превосходство). Математическое ядро остаётся
каноническим ``warfare``; геометрия четырёх проекций и исторические
суточные потери живут в ``view.support.geometry``.

Канонический ``warfare.build_demo_scenario`` не используется для UI-боя:
он остаётся эталонным демо-сценарием и не должен менять поведение при
изменениях интерфейса.
"""

from pathlib import Path

import numpy as np

import warfare as W
from .geometry import SECTORS
from .log_journal import get_logger
from .world import CampaignState

logger = get_logger("view.scenario")
ROOT = Path(__file__).resolve().parents[2]
STUB_ROWS = 256
STUB_COLS = 256

# Семь кампанийных суток. В ``time_system`` день длится 15 часов, поэтому
# запас в 2016 тактов гарантирует, что условие «день 7» успеет сработать
# раньше, чем симуляция закончится по ``max_turns``.
CAMPAIGN_TURNS = 7 * 24 * 12
PLAYER_COMPANIES = 16
ENEMY_COMPANIES = 32

# Состав бригады и группировки противника по проекциям. Общее соотношение
# 1:2, но на каждом участке разворачивается не больше фронтажной ёмкости.
PLAYER_SECTORS = (
    ["front"] * 8 + ["left"] * 3 + ["right"] * 3 + ["rear"] * 2
)
ENEMY_SECTORS = (
    ["front"] * 12 + ["left"] * 8 + ["right"] * 8 + ["rear"] * 4
)

_RED_FRONT_POSITIONS = [
    (10, 3), (11, 5), (10, 7), (11, 9),
    (10, 11), (11, 13), (10, 15), (11, 17),
]
_RED_LEFT_POSITIONS = [(6, 2), (7, 4), (6, 6)]
_RED_RIGHT_POSITIONS = [(6, 18), (7, 20), (6, 22)]
_RED_REAR_POSITIONS = [(3, 10), (3, 14)]

_BLUE_FRONT_POSITIONS = [
    (14 + (i % 2), 1 + i * 2) for i in range(12)
]
_BLUE_LEFT_POSITIONS = [
    (18 + (i % 2), 1 + i) for i in range(8)
]
_BLUE_RIGHT_POSITIONS = [
    (18 + (i % 2), 16 + i) for i in range(8)
]
_BLUE_REAR_POSITIONS = [
    (21 + (i % 2), 6 + i * 4) for i in range(4)
]


def load_map(map_name):
    """Загрузить ``scenarios/maps/<map_name>.npz`` или вернуть заглушку."""
    path = ROOT / "scenarios" / "maps" / f"{map_name}.npz"
    if not path.exists():
        logger.warning("Карта не найдена: %s — используется заглушка", path)
        rng = np.random.default_rng(1)
        return (
            rng.random((STUB_ROWS, STUB_COLS)).astype(np.float32),
            np.full((STUB_ROWS, STUB_COLS), 2, np.int8),
        )
    data = np.load(path)
    return data["heights"], data["biomes"]


def _archetypes_for(side, index, sector):
    """Четыре человека в роте; состав зависит от роли и проекции."""
    if side == "red":
        options = {
            "front": ["rifleman", "veteran", "machinegunner", "conscript"],
            "left": ["rifleman", "scout", "machinegunner", "medic"],
            "right": ["rifleman", "scout", "machinegunner", "medic"],
            "rear": ["conscript", "rifleman", "medic", "commissar"],
        }
    else:
        options = {
            "front": ["veteran", "rifleman", "scout", "machinegunner"],
            "left": ["veteran", "rifleman", "scout", "conscript"],
            "right": ["veteran", "rifleman", "scout", "conscript"],
            "rear": ["veteran", "commissar", "scout", "conscript"],
        }
    base = list(options[sector])
    # Небольшая вариативность, чтобы роты не были полными клонами.
    if index % 5 == 0:
        base[0] = "veteran"
    elif index % 7 == 0:
        base[-1] = "commissar"
    return base


def _positions_for(side):
    if side == "red":
        return (
            _RED_FRONT_POSITIONS + _RED_LEFT_POSITIONS +
            _RED_RIGHT_POSITIONS + _RED_REAR_POSITIONS
        )
    return (
        _BLUE_FRONT_POSITIONS + _BLUE_LEFT_POSITIONS +
        _BLUE_RIGHT_POSITIONS + _BLUE_REAR_POSITIONS
    )


def _make_company(side, index, sector, position, seed):
    number = index + 1
    prefix = "Р-%02d" % number if side == "red" else "С-%02d" % number
    archetypes = _archetypes_for(side, index, sector)
    chars = W._character_roster(
        side, prefix, archetypes, seed + index * 97 + (0 if side == "red" else 5000)
    )
    doctrine = "assault" if side == "blue" else "defensive"
    det = W.Detachment(
        prefix, side, chars, position=position, doctrine=doctrine,
    )
    # ``sector`` здесь — только роль для подбора архетипов. Боевую проекцию
    # всегда вычисляет ``FrontGeometry`` из позиции роты и фронта армии.
    # Кампанийное истощение считает ``FrontGeometry``; случайный обмен
    # ударами не должен дублировать суточные потери.
    det.combat_loss_scale = 0.0
    return det


def build_brigade_scenario(seed=7, turns=CAMPAIGN_TURNS):
    """Собрать UI-сценарий: 16 рот игрока против 32 рот бота.

    Штатная сила роты из четырёх человек — 14. Итого у игрока 224, у
    противника 448: ровно 1:2. Для прорыва подготовленной обороны этого
    недостаточно; на каждом участке фронтаж ограничивает одновременный
    ввод сил.
    """
    seed = int(seed)
    sim = W.WarfareSimulation(seed=seed, turns=turns)
    sim.engage_range = 3

    created = []
    for side, count, sectors in (
        ("red", PLAYER_COMPANIES, PLAYER_SECTORS),
        ("blue", ENEMY_COMPANIES, ENEMY_SECTORS),
    ):
        positions = _positions_for(side)
        for i in range(count):
            sector = sectors[i]
            det = _make_company(
                side, i, sector, positions[i], seed + (0 if side == "red" else 9000)
            )
            sim.add_detachment(det)
            created.append(det)

    reds = [det for det in created if det.side == "red"]
    blues = [det for det in created if det.side == "blue"]
    sim.issue_order(W.Order(
        "Бригада: держать рубеж", W.OrderSignal(
            aggression=0.02, discipline=0.12, morale=1.0,
            retreat_allowed=True, label="удержание",
        ),
        duration=5000, targets=reds, side="red",
    ))
    sim.issue_order(W.Order(
        "Противник: наступать", W.OrderSignal(
            aggression=0.16, morale=1.5, fanaticism=0.06,
            retreat_allowed=True, label="наступление",
        ),
        duration=5000, targets=blues, side="blue",
    ))
    logger.info(
        "Бригадный сценарий: игрок=%d рот (%.0f силы), противник=%d рот "
        "(%.0f силы), секторы=%s",
        len(reds), sum(d.force for d in reds),
        len(blues), sum(d.force for d in blues),
        {sector: PLAYER_SECTORS.count(sector) for sector in SECTORS},
    )
    return sim


def build_world(scenario_path=None, campaign_snapshot=None, content=None,
                seed=7):
    """Собрать ``CampaignState`` из бригадного UI-сценария.

    ``scenario_path`` принимается ради совместимости с сюжетными конфигами,
    но не подменяет математическую модель. Снимок кампании применяется
    поверх восстановленного на нужный такт мира.
    """
    seed = int((campaign_snapshot or {}).get("seed", seed))
    sim = build_brigade_scenario(seed=seed)
    snapshot_turn = int((campaign_snapshot or {}).get("turn", 0))
    if snapshot_turn > 0:
        sim.run(turns=min(snapshot_turn, sim.max_turns))
    state = CampaignState(sim, player_side="red", content=content)
    if campaign_snapshot:
        state.apply_snapshot(campaign_snapshot)
    logger.info(
        "Мир UI собран: seed=%s, такт=%s, отделений=%s, сценарий=%s",
        seed, sim.turn, state.count, scenario_path or "brigade",
    )
    return state
