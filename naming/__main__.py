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
from .people import PeopleError, PersonNameGenerator, default_catalog as \
    default_people_catalog


def _print_people_catalog(catalog):
    print("Реальные культуры:")
    for culture_id in catalog.culture_ids():
        profile = catalog.culture(culture_id)
        print("  %-16s %s" % (culture_id, profile.label))
    print("Фэнтезийные темы:")
    for theme_id in catalog.theme_ids():
        profile = catalog.theme(theme_id)
        print("  %-16s %s" % (theme_id, profile.label))


def main(argv=None):
    catalog = default_catalog()
    people_catalog = default_people_catalog()
    parser = argparse.ArgumentParser(
        prog="python3 -m naming",
        description="Генератор естественных названий и имён")
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
    parser.add_argument("--person", action="store_true",
                        help="генерировать имя персонажа")
    parser.add_argument("--culture", choices=people_catalog.culture_ids(),
                        help="реальная культура имени")
    parser.add_argument("--fantasy", choices=people_catalog.theme_ids(),
                        help="фэнтезийная тема имени")
    parser.add_argument("--gender", choices=("m", "f", "any"), default=None,
                        help="пол имени персонажа")
    parser.add_argument("--count", type=int, default=1,
                        help="сколько названий показать")
    parser.add_argument("--seed", type=int, default=0,
                        help="seed генератора")
    parser.add_argument("--json", action="store_true",
                        help="печатать JSON")
    parser.add_argument("--ontology", action="store_true",
                        help="напечатать онтологию класса")
    parser.add_argument("--list", action="store_true",
                        help="список классов, взаимодействий и культур")
    parser.add_argument("--list-people", action="store_true",
                        help="только список культур и фэнтезийных тем")
    args = parser.parse_args(argv)

    if args.list_people:
        _print_people_catalog(people_catalog)
        return 0

    if args.list or (
            not args.mode and not args.interaction and not args.person and
            not args.culture and not args.fantasy and not args.gender):
        print("Классы автоматов:")
        for class_id in catalog.class_ids():
            profile = catalog.class_profile(class_id)
            print("  %-12s %s" % (class_id, profile.label))
        print("Типы взаимодействий:")
        for type_id in catalog.interaction_ids():
            item = catalog.interaction(type_id)
            print("  %-16s %s" % (type_id, item.label))
        _print_people_catalog(people_catalog)
        return 0

    if args.culture and args.fantasy:
        parser.error("нельзя одновременно указать --culture и --fantasy")

    if args.person or args.culture or args.fantasy or args.gender:
        generator = PersonNameGenerator(people_catalog, seed=args.seed)
        results = generator.generate_many(
            count=max(1, args.count),
            culture=args.culture,
            theme=args.fantasy,
            gender=args.gender,
            seed=args.seed,
        )
        if args.json:
            print(json.dumps([item.as_dict() for item in results],
                             ensure_ascii=False, indent=2))
        else:
            for item in results:
                origin = item.culture or item.theme or "—"
                print("%s [%s, %s]" % (item.text, origin, item.gender))
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
    except (NamingError, PeopleError) as exc:
        raise SystemExit("ошибка конфигурации: %s" % exc)
