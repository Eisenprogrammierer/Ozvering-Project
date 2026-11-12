"""Контракт семантической геометрии автоматов.

Первый этап гибрида: метрический граф без глобальных координат, локальные
углы между соседями и композиция дальних расстояний/направлений по
кратчайшему пути. Тесты держат схему, детерминизм, ошибки данных и связку
с кампанией.
"""

from __future__ import annotations

import math
from pathlib import Path

import bdi
import pytest

from campaign import content_lint
from campaign.automata import AutomataCampaign, AutomataCampaignError
from campaign.conditions import check_conditions
from campaign.geometry import GeometryError, MetricGraph, edge_key
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TAU = math.tau


def _campaign_preset(seed=7):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT
        / "configs"
        / "campaigns"
        / "empire_campaign.json",
    )
    return generator.generate(seed=seed)


def _linear_record():
    return {
        "schema": 1,
        "model": "metric_graph",
        "dimension": 2,
        "angle_unit": "radian",
        "composition": "shortest_path",
        "edges": [
            {"from": "a", "to": "b", "length": 2.0},
            {"from": "b", "to": "c", "length": 3.0},
        ],
        "orientation": {
            "a": [{"to": "b", "turn": TAU}],
            "b": [
                {"to": "c", "turn": math.pi},
                {"to": "a", "turn": math.pi},
            ],
            "c": [{"to": "b", "turn": TAU}],
        },
    }


def test_nearest_distance_and_local_angle():
    graph = MetricGraph.from_record(_linear_record())
    assert graph.length("a", "b") == 2.0
    assert graph.degree("b") == 2
    assert [item["node"] for item in graph.nearest("b")] == ["c", "a"]
    assert graph.angle("b", "a", "c") == pytest.approx(math.pi)
    assert graph.turn("b", "a", "c") == pytest.approx(0.0)


def test_right_angle_is_local_and_signed():
    graph = MetricGraph.from_record(
        {
            "schema": 1,
            "edges": [
                {"from": "a", "to": "b", "length": 1.0},
                {"from": "b", "to": "c", "length": 1.0},
            ],
            "orientation": {
                "b": [
                    {"to": "c", "turn": math.pi / 2},
                    {"to": "a", "turn": 3 * math.pi / 2},
                ],
            },
        }
    )
    assert graph.angle("b", "a", "c") == pytest.approx(math.pi / 2)
    assert abs(graph.turn("b", "a", "c")) == pytest.approx(math.pi / 2)
    assert graph.path("a", "c").bearing == pytest.approx(
        graph.turn("b", "a", "c")
    )


def test_far_distance_is_shortest_path_and_ties_are_canonical():
    record = {
        "schema": 1,
        "edges": [
            {"from": "a", "to": "b", "length": 1.0},
            {"from": "b", "to": "d", "length": 1.0},
            {"from": "a", "to": "c", "length": 1.0},
            {"from": "c", "to": "d", "length": 1.0},
            {"from": "a", "to": "d", "length": 3.0},
        ],
    }
    graph = MetricGraph.from_record(record)
    path = graph.path("a", "d")
    assert path.nodes == ("a", "b", "d")
    assert graph.distance("a", "d") == 2.0
    assert graph.travel_time("a", "d") == 0.0


def test_far_angle_composes_turns_along_geodesic():
    record = {
        "schema": 1,
        "edges": [
            {"from": "o", "to": "p", "length": 1.0},
            {"from": "o", "to": "a", "length": 1.0},
            {"from": "a", "to": "b", "length": 1.0},
        ],
        "orientation": {
            "o": [
                {"to": "p", "turn": math.pi / 2},
                {"to": "a", "turn": 3 * math.pi / 2},
            ],
            "a": [
                {"to": "o", "turn": math.pi},
                {"to": "b", "turn": math.pi},
            ],
        },
    }
    graph = MetricGraph.from_record(record)
    local = graph.angle("o", "p", "a")
    assert local == pytest.approx(math.pi / 2)
    assert graph.angle_between_targets("o", "p", "b") == pytest.approx(
        math.pi / 2
    )
    turn = graph.turn("a", "o", "b")
    assert turn == pytest.approx(0.0)


def test_layout_is_not_part_of_semantics():
    record = _linear_record()
    record["layout"] = {
        "a": {"x": 0, "y": 0},
        "b": {"x": 100, "y": 900},
        "c": {"x": -500, "y": 20},
    }
    graph = MetricGraph.from_record(record)
    assert graph.distance("a", "c") == 5.0
    assert "x" not in graph.to_dict()
    assert "layout" not in graph.to_dict()


@pytest.mark.parametrize(
    "record, fragment",
    [
        (
            {
                "edges": [{"from": "a", "to": "missing", "length": 1}],
            },
            "неизвестный узел",
        ),
        (
            {
                "edges": [
                    {"from": "a", "to": "b", "length": 1},
                    {"from": "b", "to": "a", "length": 1},
                ],
            },
            "повторяющееся ребро",
        ),
        (
            {
                "edges": [{"from": "a", "to": "b", "length": 0}],
            },
            "длина должна быть > 0",
        ),
        (
            {
                "edges": [{"from": "a", "to": "b", "length": 1}],
                "orientation": {
                    "a": [{"to": "b", "turn": TAU / 2}],
                },
            },
            "сумма поворотов",
        ),
        (
            {
                "schema": 2,
                "edges": [{"from": "a", "to": "b", "length": 1}],
            },
            "схема геометрии",
        ),
        (
            {
                "dimension": 3,
                "edges": [{"from": "a", "to": "b", "length": 1}],
            },
            "только 2D",
        ),
        (
            {
                "composition": "euclid",
                "edges": [{"from": "a", "to": "b", "length": 1}],
            },
            "композиция",
        ),
        (
            {
                "default_length": 1,
                "lengths": {"a|missing": 2},
            },
            "отсутствует в связях",
        ),
    ],
)
def test_broken_geometry_is_loud(record, fragment):
    with pytest.raises(GeometryError) as error:
        MetricGraph.from_record(record, nodes=["a", "b"])
    assert fragment in str(error.value)


def test_derived_links_and_roundtrip():
    links = {
        "a": ["b"],
        "b": ["a", "c"],
        "c": ["b"],
    }
    graph = MetricGraph.from_links(
        ["a", "b", "c"], links, default_length=2.5
    )
    assert graph.source == "derived"
    assert graph.distance("a", "c") == 5.0
    restored = MetricGraph.from_record(
        graph.to_dict(), nodes=graph.nodes
    )
    assert restored.distance("a", "c") == 5.0
    assert restored.angle("b", "a", "c") == pytest.approx(math.pi)
    assert restored.to_dict()["curvature"] == {
        "a": 0.0,
        "b": 0.0,
        "c": 0.0,
    }


def test_degree_angles_use_degrees_when_requested():
    graph = MetricGraph.from_record(
        {
            "schema": 1,
            "angle_unit": "degree",
            "edges": [
                {"from": "a", "to": "b", "length": 1},
                {"from": "b", "to": "c", "length": 1},
            ],
            "orientation": {
                "b": [
                    {"to": "c", "turn": 90},
                    {"to": "a", "turn": 270},
                ],
            },
        }
    )
    assert graph.angle("b", "a", "c") == pytest.approx(math.pi / 2)


def _declared_geometry_for(faction):
    organs = faction.get("organs") or []
    node_ids = [str(item["id"]) for item in organs]
    links = {node: set() for node in node_ids}
    for organ in organs:
        source = str(organ["id"])
        for target in organ.get("links") or ():
            target = str(target)
            if target in links and target != source:
                links[source].add(target)
                links[target].add(source)
    edges = []
    seen = set()
    for source in sorted(links):
        for target in sorted(links[source]):
            key = edge_key(source, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {"from": source, "to": target, "length": 2.0}
            )
    return {
        "schema": 1,
        "model": "metric_graph",
        "dimension": 2,
        "composition": "shortest_path",
        "edges": edges,
    }


def test_campaign_builds_declared_geometry_and_conditions_read_it():
    preset = _campaign_preset()
    faction = next(
        item for item in preset.factions if item["side"] == "red"
    )
    faction["geometry"] = _declared_geometry_for(faction)
    campaign = AutomataCampaign(preset)
    graph = campaign.geometry("red")
    assert graph is not None and graph.source == "declared"
    assert campaign.geometry_distance(
        "red", "imperial_staff", "wehrmacht"
    ) == 2.0
    assert campaign.geometry_angle(
        "red", "imperial_staff", "wehrmacht", "abwehr"
    ) > 0

    faction_runtime = campaign.faction("red")
    context = {"faction": faction_runtime, "turn": 1}
    assert (
        check_conditions(
            {
                "kind": "distance",
                "from": "imperial_staff",
                "to": "wehrmacht",
                "op": "<=",
                "value": 2.0,
            },
            context,
        )
        == ""
    )
    assert check_conditions(
        {
            "kind": "distance",
            "from": "imperial_staff",
            "to": "wehrmacht",
            "op": "<",
            "value": 2.0,
        },
        context,
    )
    assert (
        check_conditions(
            {
                "kind": "angle",
                "node": "imperial_staff",
                "from": "wehrmacht",
                "to": "abwehr",
                "op": ">",
                "value": 0.0,
            },
            context,
        )
        == ""
    )


def test_campaign_rejects_broken_declared_geometry():
    preset = _campaign_preset()
    faction = next(
        item for item in preset.factions if item["side"] == "red"
    )
    faction["geometry"] = {
        "schema": 1,
        "edges": [
            {"from": "imperial_staff", "to": "missing", "length": 1}
        ],
    }
    with pytest.raises(AutomataCampaignError):
        AutomataCampaign(preset)


def test_linter_accepts_and_rejects_geometry():
    assert content_lint.check_geometry(
        "geometry",
        _linear_record(),
        ["a", "b", "c"],
    ) == []
    problems = content_lint.check_geometry(
        "geometry",
        {
            "schema": 1,
            "edges": [{"from": "a", "to": "b", "length": -1}],
        },
        ["a", "b"],
    )
    assert any("длина" in item for item in problems)
    problems = content_lint.check_geometry("geometry", {}, ["a"])
    assert any("непустым объектом" in item for item in problems)


def test_linter_checks_top_level_geometry_against_faction_organs():
    config = bdi.load_bdi()
    data = {
        "factions": {
            "red": {
                "id": "faction.a",
                "organs": [
                    {"id": "staff", "links": ["field"]},
                    {"id": "field", "links": ["staff"]},
                ],
            }
        },
        "geometry": {
            "red": {
                "schema": 1,
                "edges": [
                    {"from": "staff", "to": "missing", "length": 1}
                ],
            }
        },
    }
    problems = content_lint.lint_factions_data(data, config)
    assert any("неизвестный узел" in item for item in problems)


def test_distance_condition_requires_endpoints():
    problems = content_lint._condition_problems(
        "when",
        [{"kind": "distance", "op": "<", "value": 2}],
    )
    assert any("нужны from и to" in item for item in problems)
    problems = content_lint._condition_problems(
        "when",
        [{"kind": "angle", "node": "a", "op": ">", "value": 0}],
    )
    assert any("нужны node, from и to" in item for item in problems)
