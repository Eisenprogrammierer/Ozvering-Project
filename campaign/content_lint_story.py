"""Линтер сюжетов, сцен и automata-специфики контента."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping

from .scenes import SceneError, SceneSpec

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _storyline_path(value):
    path = pathlib.Path(str(value))
    if not path.is_absolute():
        path = ROOT / path
    return path


AUTOMATA_FORBIDDEN_STORY_KEYS = ("arc", "win_scene", "lose_scene")


def _campaign_mode(data):
    """Режим шаблона кампании, если он указан и читается."""

    value = data.get("campaign_template")
    if not value:
        return ""
    path = _storyline_path(value)
    try:
        template = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(template, Mapping):
        return ""
    scenario = template.get("scenario")
    if not isinstance(scenario, Mapping):
        return ""
    return str(scenario.get("mode") or "")


def _storyline_sequence(path, data):
    """Вернуть имя источника и последовательность сцен сюжета.

    Сцены можно задать ссылкой на соседний файл (``"scenes": "name"``) или
    прямо в сюжете (``"scenes": [...]``). Второй вид позволяет держать
    свободный режим в специфике одного сюжета без отдельного файла сцен.
    """

    scenes = data.get("scenes")
    if isinstance(scenes, (list, tuple)):
        return str(path.name), list(scenes)
    if not scenes:
        return str(path.name), None
    scenes_path = pathlib.Path(path).parent / ("%s.json" % scenes)
    if not scenes_path.is_file():
        return scenes_path.name, None
    try:
        catalog = json.loads(scenes_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return scenes_path.name, None
    sequence = (
        catalog.get("sequence") if isinstance(catalog, Mapping) else None
    )
    if not isinstance(sequence, (list, tuple)):
        return scenes_path.name, None
    return scenes_path.name, list(sequence)


def _lint_automatic_storyline(path, data, problems):
    """Запретить авторский сюжет там, где сюжет обязан быть симуляцией."""

    if _campaign_mode(data) != "automata":
        return
    source = str(path.name)
    for key in AUTOMATA_FORBIDDEN_STORY_KEYS:
        if key in data:
            problems.append(
                "%s.%s: сюжет automata-кампании задаётся симуляцией, "
                "а не сценой или финалом в данных" % (source, key)
            )
    source_name, sequence = _storyline_sequence(path, data)
    if sequence is None:
        return
    for index, scene in enumerate(sequence):
        if not isinstance(scene, Mapping):
            problems.append(
                "%s.sequence[%d]: сцена должна быть объектом"
                % (source_name, index)
            )
            continue
        scene_type = str(scene.get("type") or "")
        if scene_type != "gameplay":
            problems.append(
                "%s.sequence[%d]: для automata-кампании допустима только "
                "сцена gameplay, а не %r"
                % (source_name, index, scene_type)
            )
        if scene.get("slides") or scene.get("choices"):
            problems.append(
                "%s.sequence[%d]: слайды и выборы запрещены"
                % (source_name, index)
            )


def lint_storylines_data(path, data):
    """Проверить основной сюжет: теги и ссылки на соседние данные."""
    if not isinstance(data, Mapping):
        return ["сюжет должен быть объектом"]
    if not any(
        key in data
        for key in ("storyline_id", "world_path", "campaign_template")
    ):
        return []
    path = pathlib.Path(path)
    problems = []
    source = str(path.name)
    _lint_automatic_storyline(path, data, problems)
    storyline_id = str(data.get("storyline_id") or "")
    if storyline_id and storyline_id != path.stem:
        problems.append(
            "storyline_id %r не совпадает с именем файла %r"
            % (storyline_id, path.stem)
        )
    tags = data.get("storyline_tags")
    if tags is not None:
        if not isinstance(tags, (list, tuple)):
            problems.append("storyline_tags должен быть списком")
        else:
            cleaned = [str(tag) for tag in tags if str(tag)]
            if len(cleaned) != len(tags):
                problems.append(
                    "storyline_tags не может содержать пустые теги"
                )
            if len(set(cleaned)) != len(cleaned):
                problems.append("storyline_tags повторяются")
    for key in ("world_path", "campaign_template"):
        value = data.get(key)
        if value and not _storyline_path(value).is_file():
            problems.append("%s: файл не найден: %s" % (key, value))
    for key in ("character_creation", "scenes"):
        value = data.get(key)
        if not value or not isinstance(value, str):
            continue
        target = path.parent / ("%s.json" % value)
        if not target.is_file():
            problems.append("%s: файл не найден: %s" % (key, target.name))
    free_start = data.get("free_start")
    if isinstance(free_start, Mapping) and free_start:
        from .identity import load_archetypes_catalog

        catalog = load_archetypes_catalog()
        if catalog is not None:
            unknown = [
                str(archetype_id)
                for archetype_id in free_start
                if catalog.get(str(archetype_id)) is None
            ]
            if unknown:
                problems.append(
                    "free_start: неизвестные архетипы %s"
                    % ", ".join(sorted(unknown))
                )
    return problems


def lint_scenes_data(data):
    """Проверить каталог сцен без привязки к узлам и работам мира.

    Ссылки на локации и работы проверяет ``validate_world``: вне мира у
    сцены нет способа отличить опечатку от ссылки на другой мир.
    """
    if isinstance(data, Mapping):
        entries = data.get("scenes")
        if entries is None and "id" in data:
            entries = [data]
        if entries is None:
            return []
    elif isinstance(data, (list, tuple)):
        entries = data
    else:
        return ["каталог сцен должен быть объектом или списком"]
    if not isinstance(entries, (list, tuple)):
        return ["scenes должен быть списком"]
    problems = []
    seen = set()
    public_ids = set()
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            problems.append("сцена[%d] должна быть объектом" % index)
            continue
        try:
            scene = SceneSpec.from_dict(raw)
        except SceneError as exc:
            problems.append(str(exc))
            continue
        if scene.id in seen:
            problems.append("%s: сцена объявлена дважды" % scene.id)
        seen.add(scene.id)
        if not scene.works:
            problems.append("%s: не заданы работы сцены" % scene.id)
        works = [item for item in scene.works if item]
        if len(set(works)) != len(works):
            problems.append("%s: работы сцены повторяются" % scene.id)
        for person in scene.public:
            if person.id in public_ids:
                problems.append(
                    "%s: публика %r объявлена в нескольких сценах"
                    % (scene.id, person.id)
                )
            public_ids.add(person.id)
        slots = scene.time.get("slots")
        if slots is not None:
            try:
                if int(slots) < 1:
                    problems.append(
                        "%s: time.slots должен быть не меньше 1" % scene.id
                    )
            except (TypeError, ValueError):
                problems.append("%s: time.slots должен быть числом" % scene.id)
    return problems
