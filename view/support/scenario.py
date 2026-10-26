"""Сборка мира для UI-каркаса и загрузка карты.

Кампанийный UI играет за стрелковую бригаду: 16 рот против 32 рот
противника (двукратное общее превосходство). Математическое ядро остаётся
каноническим ``warfare``; геометрия четырёх проекций и исторические
суточные потери живут в ``view.support.geometry``.

Канонический ``warfare.build_demo_scenario`` не используется для UI-боя:
он остаётся эталонным демо-сценарием и не должен менять поведение при
изменениях интерфейса.
"""

from collections.abc import Mapping
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


def _number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _characters_from_roster(roster, side, prefix, index, sector, seed):
    """Собрать четырёх персонажей роты из пресета кампании.

    Пресет задаёт имя, seed, архетип и стартовые потребности. Если в ростере
    меньше четырёх человек (старый/неполный пресет), недостающих добирает
    штатный генератор архетипов — сценарий не должен ломаться.
    """
    archetypes = _archetypes_for(side, index, sector)
    base_seed = seed + index * 97 + (0 if side == "red" else 5000)
    roster = list(roster or ())
    chars = []
    for position in range(4):
        item = roster[position] if position < len(roster) else None
        if isinstance(item, Mapping):
            char_seed = int(item.get("seed", base_seed + position * 37))
            archetype = item.get("archetype") or archetypes[position]
            role = item.get("post_id") or item.get("role") or archetype
            name = item.get("name") or "%s-%d" % (prefix, position + 1)
            char = W.Character(
                name, side, seed=char_seed, archetype=archetype, role=role,
            )
            needs = item.get("needs")
            if isinstance(needs, Mapping):
                for need, value in needs.items():
                    if need in char.needs:
                        char.needs[need] = max(
                            0.0, min(1.0, _number(value, char.needs[need]))
                        )
            char.desires = char.weighted_urgency()
            if item.get("morale") is not None:
                char.morale = max(0.0, min(100.0, _number(
                    item.get("morale"), char.morale)))
            # Идентификаторы пресета нужны UI/сохранениям, но канонический
            # Character не обязан знать о кампанийном слое.
            char.campaign_id = item.get("id")
            char.campaign_faction_id = item.get("faction_id")
            char.campaign_post = item.get("post")
            char.campaign_role_id = item.get("campaign_role_id", "")
            char.campaign_leader = bool(item.get("is_faction_leader"))
            chars.append(char)
        else:
            archetype = archetypes[position]
            chars.append(W.Character(
                "%s-%d" % (prefix, position + 1), side,
                seed=base_seed + position * 37,
                archetype=archetype, role=archetype,
            ))
    return chars


def _make_company(side, index, sector, position, seed, roster=None):
    number = index + 1
    prefix = "Р-%02d" % number if side == "red" else "С-%02d" % number
    archetypes = _archetypes_for(side, index, sector)
    if roster is None:
        chars = W._character_roster(
            side, prefix, archetypes,
            seed + index * 97 + (0 if side == "red" else 5000),
        )
    else:
        chars = _characters_from_roster(
            roster, side, prefix, index, sector, seed,
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


def build_brigade_scenario(seed=7, turns=CAMPAIGN_TURNS, rosters=None):
    """Собрать UI-сценарий: 16 рот игрока против 32 рот бота.

    Штатная сила роты из четырёх человек — 14. Итого у игрока 224, у
    противника 448: ровно 1:2. Для прорыва подготовленной обороны этого
    недостаточно; на каждом участке фронтаж ограничивает одновременный
    ввод сил.

    ``rosters`` — необязательный словарь ``{side: [[character, ...], ...]}``
    из пресета кампании. Он подменяет только имена, seed, архетипы и
    стартовые потребности персонажей; численность и баланс рот остаются
    штатными.
    """
    seed = int(seed)
    sim = W.WarfareSimulation(seed=seed, turns=turns)
    sim.engage_range = 3
    rosters = rosters or {}

    created = []
    for side, count, sectors in (
        ("red", PLAYER_COMPANIES, PLAYER_SECTORS),
        ("blue", ENEMY_COMPANIES, ENEMY_SECTORS),
    ):
        positions = _positions_for(side)
        side_rosters = rosters.get(side) or ()
        for i in range(count):
            sector = sectors[i]
            roster = side_rosters[i] if i < len(side_rosters) else None
            det = _make_company(
                side, i, sector, positions[i],
                seed + (0 if side == "red" else 9000),
                roster=roster,
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
        "Бригадный сценарий: красные=%d рот (%.0f силы), синие=%d рот "
        "(%.0f силы), секторы=%s",
        len(reds), sum(d.force for d in reds),
        len(blues), sum(d.force for d in blues),
        {sector: PLAYER_SECTORS.count(sector) for sector in SECTORS},
    )
    return sim


def _coerce_preset(value):
    """Принять пресет объектом, словарём или путём к JSON."""
    if value is None:
        return None
    from campaign.preset import CampaignPreset

    if isinstance(value, CampaignPreset):
        return value
    if isinstance(value, Mapping):
        return CampaignPreset.from_dict(value)
    if isinstance(value, (str, Path)):
        return CampaignPreset.load(value)
    if hasattr(value, "as_dict"):
        return CampaignPreset.from_dict(value.as_dict())
    raise TypeError("не удалось распознать пресет кампании")


def _coerce_role(value):
    if value is None:
        return None
    if hasattr(value, "as_dict"):
        return dict(value.as_dict())
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        return {"id": value}
    raise TypeError("не удалось распознать роль игрока")


def _attach_preset_organizations(sim, preset, state):
    """Подключить организации пресета к канонической симуляции."""
    from organizations.runtime import OrganizationRuntime

    runtimes = []
    for record in preset.organizations:
        side = record.get("side")
        detachments = [det for det in sim.all_detachments
                       if det.side == side]
        if not detachments:
            continue
        runtime_cfg = record.get("runtime") or {}
        runtime = OrganizationRuntime(
            name=record.get("name") or record.get("id"),
            side=side,
            detachments=detachments,
            complete_weight=_number(
                runtime_cfg.get("complete_weight"), 0.84),
            leader_id=(runtime_cfg.get("leader_id")
                       or record.get("leader_name")),
        )
        sim.add_organization(runtime)
        runtimes.append(runtime)
    state.organization_runtimes = runtimes
    return runtimes


def build_world(scenario_path=None, campaign_snapshot=None, content=None,
                seed=7, campaign_preset=None, campaign_role=None):
    """Собрать ``CampaignState`` из бригадного UI-сценария.

    ``scenario_path`` принимается ради совместимости с сюжетными конфигами,
    но не подменяет математическую модель. Снимок кампании применяется
    поверх восстановленного на нужный такт мира.

    ``campaign_preset`` — необязательный пресет (``CampaignPreset``, dict или
    путь). Он добавляет имена/потребности персонажей, организации-автоматы и
    метаданные роли, не меняя штатное соотношение 16 против 32.
    """
    preset = _coerce_preset(campaign_preset)
    if preset is None and isinstance(campaign_snapshot, Mapping):
        preset = _coerce_preset(campaign_snapshot.get("campaign_preset"))
    role = _coerce_role(campaign_role)
    if role is None and preset is not None:
        role = preset.role.as_dict()

    scenario = preset.scenario if preset is not None else {}
    preset_seed = int(scenario.get("seed", seed))
    seed = int((campaign_snapshot or {}).get("seed", preset_seed))
    turns = int(scenario.get("turns", CAMPAIGN_TURNS))
    rosters = preset.roster_by_side() if preset is not None else None
    player_side = preset.player_side if preset is not None else "red"
    map_name = scenario.get("map_name", "valley_01")
    sim = build_brigade_scenario(seed=seed, turns=turns, rosters=rosters)
    snapshot_turn = int((campaign_snapshot or {}).get("turn", 0))
    if snapshot_turn > 0:
        sim.run(turns=min(snapshot_turn, sim.max_turns))
    state = CampaignState(sim, player_side=player_side, content=content,
                          map_name=map_name)
    if campaign_snapshot:
        state.apply_snapshot(campaign_snapshot)
    if preset is not None:
        state.campaign_preset = preset.as_dict()
        state.campaign_preset_id = preset.preset_id
        state.campaign_role = role
        state.campaign_role_id = (role or {}).get("id", preset.role.id)
        state.player_faction_id = preset.player_faction_id
        state.campaign_factions = {
            item.get("id"): item for item in preset.factions if item.get("id")
        }
        state.campaign_organizations = {
            item.get("id"): item for item in preset.organizations
            if item.get("id")
        }
        state.campaign_automata = {
            item.get("id"): item for item in preset.automata if item.get("id")
        }
        _attach_preset_organizations(sim, preset, state)
    logger.info(
        "Мир UI собран: seed=%s, такт=%s, отделений=%s, сценарий=%s, роль=%s",
        seed, sim.turn, state.count, scenario_path or "brigade",
        (role or {}).get("id", "—"),
    )
    return state
