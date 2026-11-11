"""Проекции старых шкал кампании на ядро 4-2-1 и версия снимка.

Кампания исторически живёт на именах `standing`, `power`, `cohesion`,
`wealth`, `influence`, `favor`, `evidence` и `actions_left`. Это не
отдельная модель и не второй набор ресурсов: каждое имя — проекция
`F/E/S/H`, состояния, права или обязательства. Модуль фиксирует это
соответствие в одном месте, чтобы UI, контент и сейвы не расходились.

Правила (WORLD_CORE_MODEL §7.2 №9–13):

* `F` — сила позиции; `standing` — её алиас, запись меняет `F`;
* `E` — единая энергия; `actions_left` — проекция
  `floor(E / energy_per_action)`, `wealth` — денежная форма `E`;
* `H` — здоровье/состояние `S`, а не энергия; в BDI персонажа это
  желание `health` и условия, а смерть наступает при `force <= 0`;
* `legitimacy`/`cohesion` — состояния `S`, `power` — проекция `F` +
  полномочия + отношения;
* `influence`/`favor` — состояния/права, `evidence` — обязательство;
  они не являются вторым бюджетом действий;
* `reach`/`capacity` — ограничения канала/объёма, а не метрики.

Версия схемы нужна не для красоты: снимок мира и кампании автоматов
развиваются (появились оси отношений, раны, очередь намерений, стратегии
узлов). `schema_version` позволяет отличить старый снимок от снимка из
будущего и не загружать последний молча.
"""

from __future__ import annotations

from .errors import CampaignError

SCHEMA_VERSION = 1


PROJECTIONS = {
    "standing": {
        "core": "F",
        "kind": "alias",
        "note": "положение героя — сила позиции; запись меняет F",
    },
    "power": {
        "core": "F",
        "kind": "projection",
        "note": "F + полномочия + отношения; не отдельная метрика",
    },
    "wealth": {
        "core": "E",
        "kind": "projection",
        "note": "денежная форма энергии; не второй ресурс",
    },
    "actions_left": {
        "core": "E",
        "kind": "projection",
        "note": "floor(E / energy_per_action); не второй счётчик",
    },
    "health": {
        "core": "H",
        "kind": "state",
        "note": "состояние S/BDI; смерть при force <= 0, не по здоровью",
    },
    "legitimacy": {
        "core": "S",
        "kind": "state",
        "note": "состояние S: влияет на вход и обработчик",
    },
    "cohesion": {
        "core": "S",
        "kind": "state",
        "note": "целостность композиции; агрегат частей",
    },
    "reach": {
        "core": "O",
        "kind": "constraint",
        "note": "ограничение канала/выхода, а не метрика",
    },
    "capacity": {
        "core": "H",
        "kind": "constraint",
        "note": "ограничение объёма работы, а не метрика",
    },
    "influence": {
        "core": "state",
        "kind": "resource",
        "note": "политическое состояние/право, а не энергия",
    },
    "favor": {
        "core": "state",
        "kind": "resource",
        "note": "связи/право; доход зависит от standing, но это не бюджет",
    },
    "evidence": {
        "core": "obligation",
        "kind": "obligation",
        "note": "обязательство/право; требует отдельной механики",
    },
}

PROJECTION_NAMES = tuple(PROJECTIONS)


def projection(name):
    """Вернуть запись проекции или `None` для неизвестного имени."""
    return PROJECTIONS.get(str(name or ""))


def describe_projection(name):
    """Человекочитаемое объяснение проекции для UI и логов."""
    entry = projection(name)
    if entry is None:
        return str(name or "")
    return "%s → %s: %s" % (
        name,
        entry["core"],
        entry["note"],
    )


def core_state(condition):
    """Нормировать срез `F/E/H` из `player_condition()` или снимка.

    Принимает обычный mapping, поэтому годится и для живого движка, и для
    тестов, и для загруженного снимка. Возвращает и абсолютные значения,
    и доли — UI показывает первое, политика обычно второе.
    """
    condition = dict(condition or {})

    def number(key, default=0.0):
        try:
            return float(condition.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    force = max(0.0, number("force"))
    max_force = max(1e-9, number("max_force", 1.0))
    energy = max(0.0, number("energy"))
    max_energy = max(1e-9, number("max_energy", 1.0))
    health = max(0.0, number("health"))
    max_health = max(1e-9, number("max_health", 1.0))
    force_ratio = min(1.0, force / max_force)
    energy_ratio = min(1.0, energy / max_energy)
    health_ratio = min(1.0, health / max_health)
    return {
        "force": force,
        "max_force": max_force,
        "force_ratio": force_ratio,
        "energy": energy,
        "max_energy": max_energy,
        "energy_ratio": energy_ratio,
        "health": health,
        "max_health": max_health,
        "health_ratio": health_ratio,
        "sickness": max(0.0, number("sickness")),
        "wound": max(0.0, number("wound")),
        "fatigue": max(0.0, 1.0 - energy_ratio),
        "alive": bool(condition.get("alive", force > 0.0)),
    }


def player_core_state(engine):
    """Срез ядра для персонажа `WorldEngine`."""
    return core_state(engine.player_condition())


def player_projection_view(engine):
    """Совместимый вид персонажа: ядро + легаси-проекции + пояснения.

    Это единственная точка, где UI/политика могут получить и сырые
    `F/E/H`, и старые имена, не создавая второй модели. Порядок ключей
    стабилен, поэтому снимок вида можно сравнивать в тестах.
    """
    condition = engine.player_condition()
    core = core_state(condition)
    resources = dict(getattr(engine, "player_resources", {}) or {})
    legacy = {
        "standing": core["force"],
        "actions_left": int(condition.get("actions_left", 0) or 0),
        "health": core["health"],
        "influence": float(resources.get("influence", 0.0) or 0.0),
        "favor": float(resources.get("favor", 0.0) or 0.0),
        "evidence": float(resources.get("evidence", 0.0) or 0.0),
    }
    return {
        "core": core,
        "legacy": legacy,
        "notes": {
            name: describe_projection(name)
            for name in (
                "standing",
                "actions_left",
                "health",
                "influence",
                "favor",
                "evidence",
            )
        },
    }


def snapshot_version(snapshot):
    """Версия схемы снимка; отсутствие поля — старый снимок (0)."""
    if not isinstance(snapshot, dict):
        return 0
    try:
        return max(0, int(snapshot.get("schema_version", 0) or 0))
    except (TypeError, ValueError):
        return 0


def stamp_snapshot(snapshot, version=SCHEMA_VERSION):
    """Копия снимка с проставленной версией схемы.

    Исходный словарь не мутируется: вызывающий код может хранить его как
    `to_dict()` и сравнивать без неожиданных изменений.
    """
    data = dict(snapshot or {})
    data["schema_version"] = int(version)
    return data


def ensure_supported_snapshot(snapshot, current=SCHEMA_VERSION):
    """Проверить, что снимок не новее текущей схемы.

    Возвращает версию снимка. Снимок из будущего отвергается
    `CampaignError`: молчаливая загрузка потеряла бы незнакомые поля.
    """
    version = snapshot_version(snapshot)
    if version > int(current):
        raise CampaignError(
            "снимок схемы v%d новее поддерживаемой v%d"
            % (version, int(current))
        )
    return version


__all__ = [
    "PROJECTIONS",
    "PROJECTION_NAMES",
    "SCHEMA_VERSION",
    "core_state",
    "describe_projection",
    "ensure_supported_snapshot",
    "player_core_state",
    "player_projection_view",
    "projection",
    "snapshot_version",
    "stamp_snapshot",
]
