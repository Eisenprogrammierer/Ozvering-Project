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


CAMPAIGN_TURNS = 7 * 24 * 12


def _side_lane(side, order):
    """Полоса развёртывания: чётные стороны слева, нечётные справа."""
    try:
        index = list(order).index(side)
    except ValueError:
        index = 0
    return index % 2


def _is_inner_lane(lane):
    return lane == 0


def _sector_plan(count):
    """Разбить произвольное число подразделений по секторам."""
    count = max(0, int(count))
    if count <= 0:
        return []
    rear = max(1, count // 8)
    if count < 4:
        rear = 0
    remaining = count - rear
    left = max(0, remaining // 3)
    right = max(0, remaining // 3)
    front = remaining - left - right
    return ["front"] * front + ["left"] * left + ["right"] * right + ["rear"] * rear


def _positions_for(side, count, order):
    """Построить позиции из данных, не из зашитых 16/32 рот."""
    count = max(0, int(count))
    if count == 0:
        return []
    lane = _side_lane(side, order)
    inner = _is_inner_lane(lane)
    sectors = _sector_plan(count)
    positions = []
    counters = {"front": 0, "left": 0, "right": 0, "rear": 0}
    for sector in sectors:
        index = counters[sector]
        counters[sector] += 1
        if sector == "front":
            x = (10 if inner else 14) + (index % 2)
            y = 1 + (index * 2) % 23
        elif sector == "left":
            x = (6 if inner else 18) + (index % 2)
            y = 1 + (index * 2) % 23
        elif sector == "right":
            x = (7 if inner else 19) + (index % 2)
            y = 14 + (index * 2) % 9
        else:
            x = (3 if inner else 21) + (index % 2)
            y = 6 + (index * 4) % 19
        positions.append((x, y))
    return list(zip(sectors, positions))


def _archetypes_for(faction_cfg, sector):
    options = (faction_cfg or {}).get("archetypes") or {}
    values = options.get(sector) or options.get("front") or ()
    return [str(item) for item in values if item] or ["rifleman"]


def _number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def load_map(map_name):
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


def _characters_from_roster(
    roster, side, prefix, index, sector, seed, faction_cfg=None
):
    archetypes = _archetypes_for(faction_cfg, sector)
    base_seed = seed + index * 97
    roster = list(roster or ())
    per_company = max(1, len(roster)) if roster else 4
    chars = []
    for position in range(per_company):
        item = roster[position] if position < len(roster) else None
        if isinstance(item, Mapping):
            char_seed = int(item.get("seed", base_seed + position * 37))
            archetype = item.get("archetype") or archetypes[
                position % len(archetypes)
            ]
            role = item.get("post_id") or item.get("role") or archetype
            name = item.get("name") or "%s-%d" % (prefix, position + 1)
            char = W.Character(
                name,
                side,
                seed=char_seed,
                archetype=archetype,
                role=role,
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
                char.morale = max(
                    0.0, min(100.0, _number(item.get("morale"), char.morale))
                )

            char.campaign_id = item.get("id")
            char.campaign_faction_id = item.get("faction_id")
            char.campaign_post = item.get("post")
            char.campaign_role_id = item.get("campaign_role_id", "")
            char.campaign_leader = bool(item.get("is_faction_leader"))
            chars.append(char)
        else:
            archetype = archetypes[position % len(archetypes)]
            chars.append(
                W.Character(
                    "%s-%d" % (prefix, position + 1),
                    side,
                    seed=base_seed + position * 37,
                    archetype=archetype,
                    role=archetype,
                )
            )
    return chars


def _unit_prefix(side, faction_cfg, index):
    base = str((faction_cfg or {}).get("unit_prefix") or side[:1]).upper()
    return "%s-%02d" % (base, index + 1)


def _make_company(
    side,
    index,
    sector,
    position,
    seed,
    roster=None,
    faction_cfg=None,
    doctrine="",
    combat_loss_scale=0.0,
):
    prefix = _unit_prefix(side, faction_cfg, index)
    archetypes = _archetypes_for(faction_cfg, sector)
    if roster is None:
        chars = W._character_roster(
            side,
            prefix,
            archetypes,
            seed + index * 97,
        )
    else:
        chars = _characters_from_roster(
            roster,
            side,
            prefix,
            index,
            sector,
            seed,
            faction_cfg=faction_cfg,
        )
    det = W.Detachment(
        prefix,
        side,
        chars,
        position=position,
        doctrine=str(doctrine or ""),
    )
    det.combat_loss_scale = float(combat_loss_scale)
    return det


def _factions_by_side(preset):
    if preset is None:
        return {}
    return {
        str(item.get("side")): dict(item)
        for item in (preset.factions or ())
        if item.get("side")
    }


def _side_order(preset):
    sides = [str(item.get("side")) for item in (preset.factions or ())]
    known = [side for side in ("red", "blue") if side in sides]
    known.extend(sorted(side for side in sides if side not in ("red", "blue")))
    return known


def _build_orders(sim, scenario, detachments):
    for order_cfg in scenario.get("orders") or ():
        if not isinstance(order_cfg, Mapping):
            continue
        side = str(order_cfg.get("side") or "")
        targets = [
            det for det in detachments if not side or det.side == side
        ]
        if not targets:
            continue
        signal_cfg = dict(order_cfg.get("signal") or {})
        signal = W.OrderSignal(**signal_cfg)
        sim.issue_order(
            W.Order(
                str(order_cfg.get("name") or "Приказ"),
                signal,
                duration=int(order_cfg.get("duration") or 5000),
                targets=targets,
                side=side,
            )
        )


def build_scenario(
    preset=None,
    seed=7,
    turns=None,
    rosters=None,
    side_limits=None,
):
    """Собрать военный сценарий из данных пресета.

    Числа сторон, секторы, позиции, доктрины и приказы берутся из
    ``scenario``/``factions``. Функция не содержит зашитых 16/32 рот.
    """
    if preset is None:
        from campaign.preset import CampaignPresetGenerator

        preset = CampaignPresetGenerator().generate(seed=seed)
    scenario = dict(getattr(preset, "scenario", {}) or {})
    seed = int(scenario.get("seed", seed))
    if turns is None:
        turns = int(scenario.get("turns", CAMPAIGN_TURNS))
    sim = W.WarfareSimulation(seed=seed, turns=int(turns))
    sim.engage_range = int(scenario.get("engage_range") or 3)
    rosters = rosters or {}
    factions = _factions_by_side(preset)
    sides = _side_order(preset) or list(rosters)
    counts = dict(scenario.get("companies") or {})
    for side in sides:
        if side not in counts:
            counts[side] = len(rosters.get(side) or ())
    combat_loss_scale = _number(scenario.get("combat_loss_scale"), 0.0)
    created = []
    for side in sides:
        count = max(0, int(counts.get(side) or 0))
        if side_limits and side in side_limits:
            count = min(count, max(0, int(side_limits[side])))
        faction_cfg = factions.get(side) or {}
        positions = _positions_for(side, count, sides)
        side_rosters = rosters.get(side) or ()
        doctrine = str(faction_cfg.get("doctrine") or "")
        for index in range(count):
            sector, position = positions[index]
            roster = (
                side_rosters[index] if index < len(side_rosters) else None
            )
            det = _make_company(
                side,
                index,
                sector,
                position,
                seed + index * 97,
                roster=roster,
                faction_cfg=faction_cfg,
                doctrine=doctrine,
                combat_loss_scale=combat_loss_scale,
            )
            sim.add_detachment(det)
            created.append(det)
    _build_orders(sim, scenario, created)
    logger.info(
        "Сценарий из данных: стороны=%s, отделений=%d, сила=%s",
        sides,
        len(created),
        {
            side: round(
                sum(det.force for det in created if det.side == side), 2
            )
            for side in sides
        },
    )
    return sim


def build_brigade_scenario(seed=7, turns=CAMPAIGN_TURNS, rosters=None):
    """Совместимый вход для старых вызовов без пресета."""
    return build_scenario(seed=seed, turns=turns, rosters=rosters)


def _coerce_preset(value):
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
    from organizations.runtime import OrganizationRuntime

    runtimes = []
    for record in preset.organizations:
        side = record.get("side")
        detachments = [det for det in sim.all_detachments if det.side == side]
        if not detachments:
            continue
        runtime_cfg = record.get("runtime") or {}
        runtime = OrganizationRuntime(
            name=record.get("name") or record.get("id"),
            side=side,
            detachments=detachments,
            complete_weight=_number(runtime_cfg.get("complete_weight"), 0.84),
            leader_id=(
                runtime_cfg.get("leader_id") or record.get("leader_name")
            ),
        )
        sim.add_organization(runtime)
        runtimes.append(runtime)
    state.organization_runtimes = runtimes
    return runtimes


def _apply_initial_facing(state, scenario, player_side):
    """Задать начальное направление из данных, не фиксируя его навсегда.

    ``FrontGeometry`` хранит явные направления отдельно: прямая запись в
    ``facing`` оставляет возможность пересчитывать его по движению армии.
    """
    geometry = getattr(state, "geometry", None)
    if geometry is None:
        return
    configured = {
        str(side): vector
        for side, vector in (scenario.get("facing") or {}).items()
    }
    sides = [str(getattr(item, "side", "")) for item in state.units]
    sides = [side for side in sides if side]
    order = [side for side in ("red", "blue") if side in sides]
    order.extend(sorted({side for side in sides if side not in order}))
    for side in dict.fromkeys(sides):
        vector = configured.get(side)
        if not vector:
            lane = _side_lane(side, order or [side])
            vector = (1.0, 0.0) if lane == 0 else (-1.0, 0.0)
        try:
            x, y = float(vector[0]), float(vector[1])
        except (TypeError, ValueError, IndexError):
            continue
        length = (x * x + y * y) ** 0.5
        if length < 1e-9:
            continue
        geometry.facing[side] = (x / length, y / length)
    geometry.refresh_sectors()
    geometry.recompute()


def build_world(
    scenario_path=None,
    campaign_snapshot=None,
    content=None,
    seed=7,
    campaign_preset=None,
    campaign_role=None,
):
    preset = _coerce_preset(campaign_preset)
    explicit_preset = preset is not None
    if preset is None and isinstance(campaign_snapshot, Mapping):
        preset = _coerce_preset(campaign_snapshot.get("campaign_preset"))
        explicit_preset = preset is not None
    if preset is None:
        from campaign.preset import CampaignPresetGenerator

        preset = CampaignPresetGenerator().generate(seed=seed)
    role = _coerce_role(campaign_role)
    if role is None and explicit_preset:
        role = preset.role.as_dict()

    scenario = preset.scenario if preset is not None else {}
    preset_seed = int(scenario.get("seed", seed))
    seed = int((campaign_snapshot or {}).get("seed", preset_seed))
    turns = int(scenario.get("turns", CAMPAIGN_TURNS))
    rosters = preset.roster_by_side() if preset is not None else None
    player_side = preset.player_side if preset is not None else "red"
    map_name = scenario.get("map_name", "valley_01")
    mode = str(scenario.get("mode") or "")
    if mode == "automata":
        raise ValueError(
            "кампания автоматов не использует военный мир; "
            "создайте view.support.automata_campaign"
        )
    strategy_mode = mode == "strategy"
    if strategy_mode:
        sim = W.WarfareSimulation(seed=seed, turns=turns)
    else:
        sim = build_scenario(
            preset=preset, seed=seed, turns=turns, rosters=rosters
        )
    snapshot_turn = int((campaign_snapshot or {}).get("turn", 0))
    if snapshot_turn > 0 and not strategy_mode:
        sim.run(turns=min(snapshot_turn, sim.max_turns))
    state = CampaignState(
        sim, player_side=player_side, content=content, map_name=map_name
    )
    _apply_initial_facing(state, scenario, player_side)
    if campaign_snapshot:
        state.apply_snapshot(campaign_snapshot)
    if explicit_preset and preset is not None:
        state.campaign_preset = preset.as_dict()
        state.campaign_preset_id = preset.preset_id
        state.campaign_role = role
        state.campaign_role_id = (role or {}).get("id", preset.role.id)
        state.player_faction_id = preset.player_faction_id
        state.campaign_factions = {
            item.get("id"): item for item in preset.factions if item.get("id")
        }
        state.campaign_organizations = {
            item.get("id"): item
            for item in preset.organizations
            if item.get("id")
        }
        state.campaign_automata = {
            item.get("id"): item for item in preset.automata if item.get("id")
        }
        _attach_preset_organizations(sim, preset, state)
    logger.info(
        "Мир UI собран: seed=%s, такт=%s, отделений=%s, сценарий=%s, роль=%s",
        seed,
        sim.turn,
        state.count,
        scenario_path or "brigade",
        (role or {}).get("id", "—"),
    )
    return state
