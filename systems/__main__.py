"""CLI системных автоматов.

    python3 -m systems --list
    python3 -m systems --environment river
    python3 -m systems --environment river --interact ford --seed 7
    python3 -m systems --event birth_child --seed 7
    python3 -m systems --event --category war --count 3 --seed 7
    python3 -m systems --playwright --turns 20 --seed 7
"""

from __future__ import annotations

import argparse
import json

from naming import NameGenerator
from naming.people import PeopleError, PersonNameGenerator

from .environment import EnvironmentCatalog, EnvironmentRuntime
from .events import EventCatalog, EventTextGenerator, EventError
from .playwright import (
    DramaActor,
    Playwright,
    PlaywrightConfig,
    PlaywrightError,
)


def _json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _list_all(env_catalog, event_catalog, config):
    print("Особенности среды:")
    for feature_id in env_catalog.feature_ids():
        feature = env_catalog.feature(feature_id)
        action_labels = ", ".join(item.label for item in feature.actions)
        print("  %-16s %-22s %s" % (
            feature_id, feature.state().name, action_labels))
    print("Категории событий:")
    for category_id in event_catalog.category_ids():
        events = event_catalog.events_in(category=category_id)
        label = event_catalog.categories[category_id]["label"]
        print("  %-14s %-24s событий: %d" % (
            category_id, label, len(events)))
    print("Шаблоны драматурга:")
    for template in config.templates:
        print("  %-22s %s" % (template.id, template.label))


def _environment(args):
    catalog = EnvironmentCatalog.load()
    runtime = EnvironmentRuntime(catalog, seed=args.seed)
    feature_id = args.feature or (args.environment or None)
    if feature_id:
        feature = catalog.feature(feature_id)
        if args.interact:
            result = runtime.interact(
                args.actor, feature.id, args.interact, seed=args.seed)
            if result is None:
                print("действие недоступно или не выбрано")
                return 2
            if args.json:
                _json(result.as_dict())
            else:
                print(result.text)
                for key in sorted(result.effects):
                    print("  %s: %s" % (key, result.effects[key]))
            return 0
        if args.tick:
            shifts = []
            for _ in range(args.tick):
                shifts.extend(runtime.tick())
            if args.json:
                _json([item.as_dict() for item in shifts])
            else:
                for item in shifts:
                    print(item.text)
            return 0
        if args.json:
            _json(feature.as_dict())
        else:
            print("%s (%s)" % (feature.name, feature.id))
            print("  состояние: %s" % feature.state().name)
            print("  теги: %s" % ", ".join(feature.tags))
            print("  действия:")
            for action in feature.as_target().actions:
                print("    %-18s %s" % (action.id, action.label))
                for outcome in action.outcomes:
                    print("      %-16s p=%.2f %s" % (
                        outcome.id, outcome.probability, outcome.label))
        return 0
    if args.json:
        _json(catalog.as_dict())
    else:
        for feature_id in catalog.feature_ids():
            feature = catalog.feature(feature_id)
            print("%-16s %-22s действий: %d" % (
                feature_id, feature.state().name, len(feature.actions)))
    return 0


def _events(args):
    catalog = EventCatalog.load()
    generator = EventTextGenerator(catalog, seed=args.seed)
    if args.event is not None:
        if args.event:
            result = generator.render(args.event, seed=args.seed)
            items = [result]
        else:
            items = [generator.generate(
                category=args.category,
                tags=args.tags or None,
                seed=args.seed)]
    else:
        items = generator.generate_many(
            count=max(1, args.count),
            category=args.category,
            tags=args.tags or None,
            seed=args.seed,
        )
    if args.json:
        _json([item.as_dict() for item in items])
    else:
        for item in items:
            print("[%s] %s" % (item.category, item.title))
            print(item.text)
    return 0


def _sample_actors(seed=0, count=4):
    people = PersonNameGenerator(seed=seed)
    names = people.generate_many(count=count, seed=seed)
    organizations = NameGenerator(seed=seed)
    modes = ("order", "meaning", "exchange", "care", "knowledge", "status")
    actors = []
    tags = (
        ("war", "ambition"), ("trade", "secret"), ("faith", "duty"),
        ("love", "family"), ("knowledge", "risk"), ("power", "fear"),
    )
    for index, person in enumerate(names):
        mode = modes[index % len(modes)]
        try:
            org = organizations.automaton_name(
                mode, level=index % 3 + 1, seed=seed + index * 17).text
        except Exception:
            org = "Организация %d" % (index + 1)
        actors.append(DramaActor(
            id="actor-%d" % (index + 1),
            name=person.text,
            organization=org,
            tags=tags[index % len(tags)],
            stakes=0.45 + 0.1 * (index % 5),
        ))
    return actors


def _playwright(args):
    config = PlaywrightConfig.load()
    event_catalog = EventCatalog.load()
    events = EventTextGenerator(event_catalog, seed=args.seed)
    playwright = Playwright(config, seed=args.seed, event_generator=events)
    actors = _sample_actors(seed=args.seed)
    candidates = playwright.spawn_candidates(actors)
    if args.json:
        result = {
            "actors": [actor.as_dict() for actor in actors],
            "candidates": [item.as_dict() for item in candidates],
            "pushes": [],
        }
        for turn in range(max(1, args.turns)):
            push = playwright.tick(turn, actors, candidates)
            if push is not None:
                result["pushes"].append(push.as_dict())
        result["state"] = playwright.machine.current
        result["final_cooldown"] = playwright.cooldown
        _json(result)
        return 0
    print("Акторы:")
    for actor in actors:
        print("  %s — %s [%s]" % (
            actor.name, actor.organization, ", ".join(actor.tags)))
    print("Эпизоды:")
    for turn in range(max(1, args.turns)):
        push = playwright.tick(turn, actors, candidates)
        if push is None:
            continue
        score = push.score
        print("  такт %d: %s → %s" % (
            turn, push.candidate.actor_id, push.candidate.action))
        print("    оценка %.3f (неопр. %.2f, связн. %.2f, нов. %.2f, ставки %.2f)" % (
            score.total, score.uncertainty, score.coherence,
            score.novelty, score.stakes))
        print("    %s" % push.text)
    return 0


def main(argv=None):
    env_catalog = EnvironmentCatalog.load()
    event_catalog = EventCatalog.load()
    config = PlaywrightConfig.load()
    parser = argparse.ArgumentParser(
        prog="python3 -m systems",
        description="Системные автоматы: среда, драматург и события")
    parser.add_argument("--list", action="store_true",
                        help="список особенностей, категорий и шаблонов")
    parser.add_argument("--environment", nargs="?", const="", default=None,
                        help="показать среду или конкретную особенность")
    parser.add_argument("--feature", default=None,
                        help="id особенности для --environment")
    parser.add_argument("--interact", default=None,
                        help="id действия для --environment --feature")
    parser.add_argument("--actor", default="actor", help="id актора")
    parser.add_argument("--tick", type=int, default=0,
                        help="сколько тактов дрейфа среды проиграть")
    parser.add_argument("--event", nargs="?", const="", default=None,
                        help="id события; без id — случайное событие")
    parser.add_argument("--category", default=None,
                        help="категория события")
    parser.add_argument("--tags", nargs="*", default=None,
                        help="теги события")
    parser.add_argument("--playwright", action="store_true",
                        help="прогон драматурга на демонстрационных акторах")
    parser.add_argument("--turns", type=int, default=20,
                        help="число тактов драматурга")
    parser.add_argument("--count", type=int, default=1,
                        help="сколько событий показать")
    parser.add_argument("--seed", type=int, default=0, help="seed")
    parser.add_argument("--json", action="store_true", help="печатать JSON")
    args = parser.parse_args(argv)

    if args.list or (args.environment is None and args.event is None and
                     not args.playwright):
        _list_all(env_catalog, event_catalog, config)
        return 0
    if args.environment is not None:
        return _environment(args)
    if args.event is not None:
        return _events(args)
    if args.playwright:
        return _playwright(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PlaywrightError, EventError, PeopleError) as exc:
        raise SystemExit("ошибка систем: %s" % exc)
