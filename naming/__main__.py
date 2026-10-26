"""CLI: предпросмотр названий и онтологий.

    python3 -m naming --list
    python3 -m naming --mode order --need fear --level 3 --count 5 --seed 7
    python3 -m naming --interaction coercion --count 5 --seed 7
    python3 -m naming --mode order --ontology
"""

from __future__ import annotations

import argparse
import json

from .catalog import NamingError, default_catalog
from .generator import NameGenerator


def main(argv=None):
    catalog = default_catalog()
    parser = argparse.ArgumentParser(
        prog="python3 -m naming",
        description="Генератор естественных названий автоматов")
    parser.add_argument("--mode", choices=catalog.class_ids(),
                        help="класс автомата (функция организации)")
    parser.add_argument("--need", default=None,
                        help="каноническая потребность, например fear")
    parser.add_argument("--level", type=int, default=1,
                        help="уровень организации, 1..3+")
    parser.add_argument("--theme", default=None,
                        help="явная тема класса")
    parser.add_argument("--interaction", choices=catalog.interaction_ids(),
                        help="тип взаимодействия")
    parser.add_argument("--count", type=int, default=1,
                        help="сколько названий показать")
    parser.add_argument("--seed", type=int, default=0,
                        help="seed генератора")
    parser.add_argument("--json", action="store_true",
                        help="печатать JSON")
    parser.add_argument("--ontology", action="store_true",
                        help="напечатать онтологию класса")
    parser.add_argument("--list", action="store_true",
                        help="список классов и типов взаимодействий")
    args = parser.parse_args(argv)

    if args.list or (not args.mode and not args.interaction):
        print("Классы автоматов:")
        for class_id in catalog.class_ids():
            profile = catalog.class_profile(class_id)
            print("  %-12s %s" % (class_id, profile.label))
        print("Типы взаимодействий:")
        for type_id in catalog.interaction_ids():
            item = catalog.interaction(type_id)
            print("  %-16s %s" % (type_id, item.label))
        return 0

    if args.ontology:
        if not args.mode:
            parser.error("--ontology требует --mode")
        print(json.dumps(catalog.ontology_for(args.mode),
                         ensure_ascii=False, indent=2))
        return 0

    generator = NameGenerator(catalog, seed=args.seed)
    if args.interaction:
        results = [generator.interaction_name(args.interaction)
                   for _ in range(max(1, args.count))]
    else:
        results = generator.generate_many(
            args.mode, need=args.need, level=args.level, theme=args.theme,
            count=max(1, args.count), seed=args.seed)
    if args.json:
        print(json.dumps([item.as_dict() for item in results],
                         ensure_ascii=False, indent=2))
    else:
        for item in results:
            suffix = " [%s, %s слов]" % (item.theme or item.mode, item.words)
            print(item.text + suffix)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except NamingError as exc:
        raise SystemExit("ошибка конфигурации: %s" % exc)
