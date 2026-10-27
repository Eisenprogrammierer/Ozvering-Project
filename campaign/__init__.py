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
from .strategy import (
    DEFAULT_STRATEGY_PATH,
    StrategyEngine,
    StrategyError,
    build_strategy,
    load_strategy,
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
    "DEFAULT_STRATEGY_PATH",
    "StrategyEngine",
    "StrategyError",
    "build_strategy",
    "load_strategy",
]
