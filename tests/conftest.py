"""Общая настройка тестов: изолированный JSON-контент.

Рабочие каталоги `configs/` и `campaigns/` содержат игровой контент, но
тесты подменяют их небольшим стабильным набором в
`tests/fixtures/content/`. Это держит проверки механик независимыми от
сюжетного наполнения и не смешивает тестовые шаблоны с игровыми.
"""

from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "content"


@pytest.fixture(scope="session", autouse=True)
def isolated_json_content():
    """Подменить корни контента на тестовый набор на всю сессию."""
    import automata.storage as automata_storage
    import campaign.__main__ as campaign_cli
    import campaign.preset as campaign_preset
    import campaign.roles as campaign_roles
    import campaign.strategy as campaign_strategy
    import campaign.world as campaign_world
    import naming.catalog as naming_catalog
    import naming.people as naming_people
    import systems.environment as systems_environment
    import systems.events as systems_events
    import systems.playwright as systems_playwright
    import view.support.config_loader as view_config_loader
    import view.support.content as view_content
    import view.support.storyline as view_storyline
    import view.support.time_system as view_time_system

    configs = FIXTURE_ROOT / "configs"
    patch = pytest.MonkeyPatch()
    patch.setattr(
        campaign_world,
        "DEFAULT_WORLD_PATH",
        configs / "worlds" / "agora_world.json",
    )
    patch.setattr(
        campaign_world,
        "DEFAULT_BIOGRAPHY_PATH",
        configs / "worlds" / "biography.json",
    )
    patch.setattr(campaign_roles, "default_root", lambda: configs / "roles")
    patch.setattr(campaign_roles, "_DEFAULT", None)
    patch.setattr(
        campaign_strategy,
        "DEFAULT_STRATEGY_PATH",
        configs / "strategy" / "agora_charter.json",
    )
    patch.setattr(
        campaign_preset,
        "default_root",
        lambda: configs / "campaigns",
    )
    patch.setattr(
        campaign_cli,
        "default_templates_root",
        lambda: configs / "campaigns",
    )
    patch.setattr(automata_storage, "ROOT", configs / "automata")
    patch.setattr(
        systems_events,
        "default_root",
        lambda: configs / "systems",
    )
    patch.setattr(systems_events, "_DEFAULT", None)
    patch.setattr(
        systems_environment,
        "default_root",
        lambda: configs / "systems",
    )
    patch.setattr(systems_environment, "_DEFAULT", None)
    patch.setattr(
        systems_playwright,
        "default_root",
        lambda: configs / "systems",
    )
    patch.setattr(systems_playwright, "_DEFAULT_CONFIG", None)
    patch.setattr(
        naming_catalog,
        "default_root",
        lambda: configs / "naming",
    )
    patch.setattr(
        naming_people,
        "default_root",
        lambda: configs / "naming",
    )
    patch.setattr(naming_people, "_DEFAULT", None)
    naming_catalog.default_catalog.cache_clear()
    patch.setattr(view_config_loader, "ROOT", FIXTURE_ROOT)
    patch.setattr(view_content, "ROOT", FIXTURE_ROOT)
    patch.setattr(
        view_storyline,
        "STORYLINES_DIR",
        str(configs / "storylines"),
    )
    patch.setattr(view_time_system, "ROOT", FIXTURE_ROOT)

    yield

    naming_catalog.default_catalog.cache_clear()
    patch.undo()
