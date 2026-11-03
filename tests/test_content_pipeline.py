"""Проверки JSON-контента: добавление, правка и удаление без кода."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from automata.model import Automaton
from automata.storage import AutomataStore
from campaign.__main__ import main as campaign_main
from campaign.preset import generate_preset, list_templates
from campaign.roles import RoleCatalog
from campaign.storage import list_presets, save_preset
from campaign.world import list_worlds, load_world
from naming.catalog import NamingCatalog
from systems.events import EventCatalog, EventError
from view.support.content import Content
from view.support.storyline import list_storylines, load_storyline


ROOT = Path(__file__).resolve().parents[1]


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_config_json_files_are_parseable():
    broken = []
    for path in sorted((ROOT / "configs").rglob("*.json")):
        try:
            _read(path)
        except Exception as exc:  # pragma: no cover - диагностика
            broken.append("%s: %s" % (path, exc))
    assert not broken, "битый JSON в configs:\n" + "\n".join(broken)


def test_world_folder_add_edit_remove(tmp_path):
    world = load_world()
    path = tmp_path / "alpha.json"
    _write(path, world)
    # Биография не является миром и не должна попадать в выдачу.
    _write(tmp_path / "biography.json", {"origins": []})

    entries = list_worlds(tmp_path)
    assert [item["world_id"] for item in entries] == [world["id"]]

    data = _read(path)
    data["title"] = "Новый заголовок"
    _write(path, data)
    assert list_worlds(tmp_path)[0]["title"] == "Новый заголовок"

    path.unlink()
    assert list_worlds(tmp_path) == []


def test_role_folder_add_edit_remove(tmp_path):
    _write(
        tmp_path / "roles.json",
        {
            "schema": 1,
            "roles": [
                {
                    "id": "alpha",
                    "label": "Первая",
                    "sort_order": 0,
                }
            ],
        },
    )
    extra = tmp_path / "beta.json"
    _write(
        extra,
        {
            "id": "beta",
            "label": "Вторая",
            "sort_order": 10,
        },
    )

    catalog = RoleCatalog.load(tmp_path)
    assert [role.id for role in catalog.all_roles()] == ["alpha", "beta"]

    data = _read(extra)
    data["label"] = "Вторая (правка)"
    _write(extra, data)
    catalog = RoleCatalog.load(tmp_path)
    assert catalog.role("beta").label == "Вторая (правка)"

    extra.unlink()
    catalog = RoleCatalog.load(tmp_path)
    assert [role.id for role in catalog.all_roles()] == ["alpha"]


def test_storyline_folder_add_edit_remove(tmp_path):
    _write(
        tmp_path / "mini.json",
        {
            "storyline_id": "mini",
            "title": "Мини-сюжет",
            "description": "Проверка",
            "character_creation": "mini_char",
            "scenes": "mini_scenes",
        },
    )
    _write(tmp_path / "mini_char.json", {"steps": [{"id": "step"}]})
    _write(tmp_path / "mini_scenes.json", {"sequence": [{"id": "scene"}]})

    listed = list_storylines(tmp_path)
    assert [item["storyline_id"] for item in listed] == ["mini"]

    loaded = load_storyline("mini", tmp_path)
    assert loaded["character_creation"] == {"steps": [{"id": "step"}]}
    assert loaded["scenes"] == [{"id": "scene"}]

    data = _read(tmp_path / "mini.json")
    data["title"] = "Мини-сюжет (правка)"
    _write(tmp_path / "mini.json", data)
    assert list_storylines(tmp_path)[0]["title"] == "Мини-сюжет (правка)"

    (tmp_path / "mini.json").unlink()
    assert list_storylines(tmp_path) == []
    assert load_storyline("mini", tmp_path) is None


def test_content_folder_is_generic_and_reloadable(tmp_path):
    _write(tmp_path / "orders.json", [{"id": "order"}])
    _write(tmp_path / "custom.json", {"value": 1})

    content = Content(tmp_path)
    assert content.order_types == [{"id": "order"}]
    assert content.get("custom") == {"value": 1}
    assert content.get("custom.json") == {"value": 1}
    assert content.names() == ["custom", "orders"]

    _write(tmp_path / "later.json", {"value": 2})
    assert Content(tmp_path).get("later") == {"value": 2}

    _write(tmp_path / "orders.json", [{"id": "order"}, {"id": "new"}])
    assert len(Content(tmp_path).order_types) == 2

    (tmp_path / "custom.json").unlink()
    assert Content(tmp_path).get("custom") is None
    assert Content(tmp_path).get("orders") == [
        {"id": "order"},
        {"id": "new"},
    ]


def test_naming_class_folder_add_remove(tmp_path):
    root = tmp_path / "naming"
    shutil.copytree(ROOT / "configs" / "naming", root)
    catalog = NamingCatalog.load(root)
    before = catalog.class_ids()

    source = _read(root / "classes" / "care.json")
    source["class"] = "extra_class"
    source["label"] = "Дополнительный класс"
    _write(root / "classes" / "extra.json", source)

    catalog = NamingCatalog.load(root)
    assert "extra_class" in catalog.class_ids()
    assert set(before) < set(catalog.class_ids())

    (root / "classes" / "extra.json").unlink()
    assert NamingCatalog.load(root).class_ids() == before


def test_event_catalog_add_edit_remove(tmp_path):
    path = tmp_path / "events.json"
    _write(
        path,
        {
            "schema": 1,
            "categories": {"court": {"label": "Двор", "weight": 1.0}},
            "events": [
                {
                    "id": "court_intrigue",
                    "category": "court",
                    "title": "Интрига",
                    "templates": ["При дворе случилась {cause}."],
                }
            ],
        },
    )
    catalog = EventCatalog.load(tmp_path)
    assert catalog.event("court_intrigue").title == "Интрига"

    data = _read(path)
    data["events"][0]["title"] = "Интрига (правка)"
    _write(path, data)
    assert EventCatalog.load(tmp_path).event("court_intrigue").title == (
        "Интрига (правка)"
    )

    data["events"] = []
    _write(path, data)
    with pytest.raises(EventError):
        EventCatalog.load(tmp_path)


def test_template_and_preset_folders_add_remove(tmp_path):
    template = tmp_path / "templates"
    _write(
        template / "mini.json",
        {
            "template_id": "mini",
            "title": "Мини-шаблон",
            "factions": {"red": {}},
        },
    )
    assert [item["template_id"] for item in list_templates(template)] == [
        "mini"
    ]
    (template / "mini.json").unlink()
    assert list_templates(template) == []

    preset = save_preset(
        generate_preset(seed=7),
        directory=tmp_path / "presets",
    )
    presets = list_presets(tmp_path / "presets")
    assert [item["preset_id"] for item in presets] == [
        "test_skirmish_seed7"
    ]
    Path(preset).unlink()
    assert list_presets(tmp_path / "presets") == []


def test_automata_folder_add_edit_remove(tmp_path):
    store = AutomataStore(tmp_path)
    automaton = Automaton("Контент")
    automaton.add_state("Старт", initial=True)
    slug = store.save(automaton)
    assert [item["slug"] for item in store.list_entries()] == [slug]

    loaded = store.load(slug)
    loaded.name = "Контент (правка)"
    store.save(loaded, slug)
    assert store.load(slug).name == "Контент (правка)"

    assert store.delete(slug) is True
    assert store.list_entries() == []


def test_real_content_folders_are_non_empty():
    assert list_worlds()
    assert list_templates()
    assert [item["slug"] for item in AutomataStore().list_entries()]
    assert NamingCatalog.load().class_ids()
    assert Content().names()
    assert list_storylines()


def test_campaign_cli_lists_templates_and_resolves_them(capsys, tmp_path):
    assert campaign_main(["--list-templates"]) == 0
    out = capsys.readouterr().out
    assert "test_skirmish" in out

    out_path = tmp_path / "generated.json"
    code = campaign_main(
        [
            "--generate",
            "--template",
            "test_skirmish",
            "--role",
            "faction_leader",
            "--out",
            str(out_path),
        ]
    )
    assert code == 0
    assert out_path.is_file()
    assert _read(out_path)["preset_id"].startswith("test_skirmish")
