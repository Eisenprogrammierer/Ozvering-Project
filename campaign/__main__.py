"""CLI кампанийного слоя.

    python3 -m campaign --list-roles
    python3 -m campaign --list-presets
    python3 -m campaign --generate --seed 7
    python3 -m campaign --generate --seed 7 --out campaigns/test.json
    python3 -m campaign --show campaigns/test.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .errors import CampaignError
from .preset import CampaignPresetGenerator
from .roles import RoleCatalog
from .storage import (
    default_presets_dir,
    list_presets,
    load_preset,
    save_preset,
)


def _template_path(value):
    if value is None:
        return None
    path = Path(value)
    if path.exists():
        return path
    name = value if str(value).endswith(".json") else "%s.json" % value
    candidate = default_presets_dir() / name
    return candidate if candidate.exists() else path


def _print_summary(preset):
    print(json.dumps(preset.summary(), ensure_ascii=False, indent=2))


def _cmd_list_roles(args):
    catalog = RoleCatalog.load()
    for role in catalog.all_roles():
        mark = "доступна" if role.available else "недоступна"
        print("%-20s %-8s %s" % (role.id, mark, role.label))
        if role.description:
            print("  %s" % role.description)
    return 0


def _cmd_list_presets(args):
    items = list_presets(args.directory)
    if not items:
        print("Пресетов пока нет: %s" % default_presets_dir(args.directory))
        return 0
    for item in items:
        print("%-32s seed=%-6s role=%-16s %s" % (
            item.get("preset_id"), item.get("seed"),
            item.get("role_id"), item.get("title")))
        print("  %s" % item.get("path"))
    return 0


def _cmd_show(args):
    preset = load_preset(args.show, directory=args.directory)
    _print_summary(preset)
    if args.full:
        print(json.dumps(preset.as_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_generate(args):
    template_path = _template_path(args.template)
    generator = CampaignPresetGenerator(template_path=template_path)
    preset = generator.generate(
        role_id=args.role, seed=args.seed, preset_id=args.preset_id,
    )
    if args.out:
        path = preset.save(Path(args.out))
    else:
        path = save_preset(preset, directory=args.directory)
    _print_summary(preset)
    print("JSON: %s" % path)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python3 -m campaign",
        description="Роли игрока и детерминированные пресеты кампаний.",
    )
    parser.add_argument("--list-roles", action="store_true",
                        help="показать каталог ролей")
    parser.add_argument("--list-presets", action="store_true",
                        help="показать пресеты в campaigns/")
    parser.add_argument("--generate", action="store_true",
                        help="сгенерировать тестовый пресет")
    parser.add_argument("--show", metavar="FILE",
                        help="показать сводку пресета")
    parser.add_argument("--full", action="store_true",
                        help="с --show: вывести весь JSON пресета")
    parser.add_argument("--role", default="faction_leader",
                        help="id роли (по умолчанию faction_leader)")
    parser.add_argument("--seed", type=int, default=None,
                        help="seed генерации (по умолчанию из шаблона)")
    parser.add_argument("--preset-id", default=None,
                        help="явный id сгенерированного пресета")
    parser.add_argument("--template", default=None,
                        help="шаблон в configs/campaigns/ или путь к JSON")
    parser.add_argument("--out", default=None,
                        help="путь для сгенерированного JSON")
    parser.add_argument("--directory", default=None,
                        help="каталог пресетов (по умолчанию campaigns/)")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.list_roles:
            return _cmd_list_roles(args)
        if args.list_presets:
            return _cmd_list_presets(args)
        if args.show:
            return _cmd_show(args)
        if args.generate:
            return _cmd_generate(args)
    except CampaignError as exc:
        print("Ошибка кампании: %s" % exc, file=sys.stderr)
        return 2
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
