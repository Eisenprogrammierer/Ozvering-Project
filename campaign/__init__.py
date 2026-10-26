"""Кампанийный слой: роли игрока и детерминированные пресеты.

Пакет не импортирует pygame. Его можно использовать из тестов, CLI и
headless-сценариев:

    python3 -m campaign --list-roles
    python3 -m campaign --generate --seed 7 --out campaigns/test.json
"""

from .errors import CampaignError
from .roles import (
    ROLE_ID_RE,
    RoleCatalog,
    RoleError,
    RoleSpec,
    default_catalog as default_role_catalog,
    default_root as default_roles_root,
)
from .preset import (
    SCHEMA,
    CampaignPreset,
    CampaignPresetError,
    CampaignPresetGenerator,
    default_root as default_presets_root,
    default_template_path,
    generate_preset,
    load_template,
)

__all__ = [
    "SCHEMA",
    "CampaignError",
    "RoleError",
    "RoleSpec",
    "RoleCatalog",
    "ROLE_ID_RE",
    "default_role_catalog",
    "default_roles_root",
    "CampaignPresetError",
    "CampaignPreset",
    "CampaignPresetGenerator",
    "default_presets_root",
    "default_template_path",
    "generate_preset",
    "load_template",
]
