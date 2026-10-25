"""Сборка мира для UI-каркаса и загрузка карты.

Источник состояния — ``warfare.build_demo_scenario``. Легаси-сценарии
``scenarios/*.json`` сохранены как контент интерфейса, но их математическое
ядро не используется.
"""

import os
from pathlib import Path

import numpy as np

import warfare as W
from .log_journal import get_logger
from .world import CampaignState

logger = get_logger("view.scenario")
ROOT = Path(__file__).resolve().parents[2]
STUB_ROWS = 256
STUB_COLS = 256


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


def build_world(scenario_path=None, campaign_snapshot=None, content=None,
                seed=7):
    """Собрать ``CampaignState`` из демо-сценария ``warfare``.

    ``scenario_path`` принимается ради совместимости с сюжетными конфигами,
    но не подменяет математическую модель. Снимок кампании применяется
    поверх восстановленного на нужный такт мира.
    """
    seed = int((campaign_snapshot or {}).get("seed", seed))
    sim = W.build_demo_scenario(seed=seed, turns=140)
    snapshot_turn = int((campaign_snapshot or {}).get("turn", 0))
    if snapshot_turn > 0:
        sim.run(turns=min(snapshot_turn, sim.max_turns))
    state = CampaignState(sim, player_side="red", content=content)
    if campaign_snapshot:
        state.apply_snapshot(campaign_snapshot)
    logger.info(
        "Мир UI собран: seed=%s, такт=%s, отделений=%s, сценарий=%s",
        seed, sim.turn, state.count, scenario_path or "demo",
    )
    return state
