"""Журнал мира: важность событий, сводка, сжатие и авто-пауза.

Закрывает §7.5 №32 и §7.7 №41.

Журнал остаётся списком словарей `{day, kind, text, ...}` — это публичный
формат сейва и UI. Модуль не меняет записи задним числом, а добавляет
**производный слой**:

* `severity_for(kind)` — важность события (`debug/info/notice/critical`);
* `log_view()` — отфильтрованное и размеченное представление для UI;
* `digest()` — сводка по дням/видам, чтобы тысячи записей не нужно было
  читать построчно;
* `compact()` — сжатие журнала с сохранением критических событий;
* `pause_reason()` — какие критические события должны остановить фон.

Правила важности и авто-паузы можно переопределить блоком `logging` в
конфиге мира. По умолчанию включены только безопасные правила: смерть,
распад, увольнение и финал. Долги, контакты и экономика — `notice`/`info`,
они не останавливают игру без явного требования контента.
"""

SEVERITIES = ("debug", "info", "notice", "critical")
SEVERITY_RANK = {
    "debug": 0,
    "info": 1,
    "notice": 2,
    "critical": 3,
}

# Виды событий, которые уже существуют в журнале кампании. Неизвестный вид
# получает `info`: журнал не должен падать из-за нового контента.
DEFAULT_KIND_SEVERITY = {
    "death": "critical",
    "player_death": "critical",
    "collapse": "critical",
    "dismissal": "critical",
    "reassign": "notice",
    "ending": "critical",
    "health_critical": "critical",
    "sickness_critical": "critical",
    "wound": "notice",
    "infection": "notice",
    "obligation": "notice",
    "coalition": "notice",
    "constraint": "notice",
    "negotiation": "notice",
    "horizon": "notice",
    "storyline": "notice",
    "strategy": "info",
    "career": "notice",
    "contact": "info",
    "intent": "info",
    "intent_skipped": "debug",
    "intent_cancelled": "debug",
    "day": "info",
    "opening": "info",
    "economy": "info",
    "resource": "debug",
    "projection": "debug",
    "state": "debug",
    "success": "debug",
    "world": "info",
}

# Какие события ставят фон на паузу. Состояние героя (смерть, H/sickness,
# завершённый сюжет, отсутствие должности) проверяется ещё и напрямую в
# `campaign.clock`: журнал — дополнительный, а не единственный источник.
DEFAULT_PAUSE_REASONS = {
    "death": "dead",
    "player_death": "dead",
    "collapse": "collapsed",
    "dismissal": "unattached",
    "ending": "finished",
    "health_critical": "health",
    "sickness_critical": "sickness",
}

# Сжатие журнала. Критические события сохраняются всегда; давние
# информационные записи сворачиваются, иначе бесконечная симуляция
# растёт в сейве линейно.
LOG_MAX_ENTRIES = 5000
LOG_RECENT_DAYS = 30
LOG_CRITICAL_KEEP = 200


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_text(value, default=""):
    if value is None:
        return default
    text = str(value)
    return text if text else default


def rules_from_config(raw):
    """Собрать правила журнала из блока `logging` конфига мира.

    Поддерживаются:

    ```json
    {
      "severity": {"obligation": "critical"},
      "critical": ["obligation"],
      "pause": {"obligation": "obligation_due"},
      "compact": true,
      "max_entries": 5000,
      "recent_days": 30,
      "critical_keep": 200
    }
    ```

    `severity` расширяет/переопределяет карту видов; `critical` добавляет
    виды в критический уровень; `pause` задаёт собственные причины
    авто-паузы. Пустой/неизвестный блок не ломает старые сейвы.
    """
    raw = raw if isinstance(raw, dict) else {}
    severity = dict(DEFAULT_KIND_SEVERITY)
    for kind, level in (raw.get("severity") or {}).items():
        level = _as_text(level).lower()
        if level in SEVERITY_RANK:
            severity[_as_text(kind)] = level
    for kind in raw.get("critical") or ():
        severity[_as_text(kind)] = "critical"
    pause = dict(DEFAULT_PAUSE_REASONS)
    for kind, reason in (raw.get("pause") or {}).items():
        reason = _as_text(reason)
        if reason:
            pause[_as_text(kind)] = reason
            severity[_as_text(kind)] = "critical"
    return {
        "severity": severity,
        "pause": pause,
        "compact": bool(raw.get("compact", False)),
        "max_entries": max(
            1, _as_int(raw.get("max_entries"), LOG_MAX_ENTRIES)
        ),
        "recent_days": max(
            0, _as_int(raw.get("recent_days"), LOG_RECENT_DAYS)
        ),
        "critical_keep": max(
            0, _as_int(raw.get("critical_keep"), LOG_CRITICAL_KEEP)
        ),
    }


def severity_for(kind, rules=None):
    severity = (rules or {}).get("severity") or DEFAULT_KIND_SEVERITY
    return severity.get(_as_text(kind), "info")


def is_critical(entry, rules=None):
    return severity_for((entry or {}).get("kind"), rules) == "critical"


def classify(entry, rules=None):
    """Копия записи с производными полями `severity` и `critical`.

    Исходный словарь не меняется: сейв и сравнение журналов остаются
    прежними, а UI получает разметку по требованию.
    """
    result = dict(entry or {})
    severity = severity_for(result.get("kind"), rules)
    result["severity"] = severity
    result["critical"] = severity == "critical"
    result["rank"] = SEVERITY_RANK[severity]
    return result


def _entry_day(entry):
    return _as_int((entry or {}).get("day"), 0)


def log_view(
    entries,
    *,
    limit=None,
    min_severity=None,
    max_severity=None,
    kinds=None,
    since_day=None,
    until_day=None,
    rules=None,
):
    """Отфильтровать журнал для UI, не меняя исходный список.

    `limit` применяется к последним записям после фильтрации. Порядок
    сохраняется исходный (от старых к новым).
    """
    min_rank = (
        -1
        if min_severity is None
        else SEVERITY_RANK.get(_as_text(min_severity).lower(), -1)
    )
    max_rank = (
        99
        if max_severity is None
        else SEVERITY_RANK.get(_as_text(max_severity).lower(), 99)
    )
    wanted = None
    if kinds is not None:
        wanted = {_as_text(kind) for kind in kinds}
    result = []
    for entry in entries or ():
        if wanted is not None and _as_text(entry.get("kind")) not in wanted:
            continue
        day = _entry_day(entry)
        if since_day is not None and day < _as_int(since_day):
            continue
        if until_day is not None and day > _as_int(until_day):
            continue
        item = classify(entry, rules)
        if not (min_rank <= item["rank"] <= max_rank):
            continue
        result.append(item)
    if limit is not None:
        limit = max(0, _as_int(limit))
        result = result[-limit:] if limit else []
    return result


def digest(entries, *, day=None, rules=None):
    """Сводка журнала: счётчики по дням/видам и последнее критическое.

    Сводка — ответ на «как не читать тысячи событий»: UI показывает
    `counts`, `critical` и `last_critical`, а полный журнал остаётся
    доступен по запросу.
    """
    counts = {}
    by_severity = {severity: 0 for severity in SEVERITIES}
    per_day = {}
    critical = []
    last_critical = None
    for entry in entries or ():
        item = classify(entry, rules)
        kind = _as_text(item.get("kind"), "unknown")
        counts[kind] = counts.get(kind, 0) + 1
        by_severity[item["severity"]] += 1
        entry_day = _entry_day(item)
        per_day[entry_day] = per_day.get(entry_day, 0) + 1
        if item["critical"]:
            critical.append(item)
            last_critical = item
    result = {
        "total": sum(counts.values()),
        "counts": counts,
        "by_severity": by_severity,
        "per_day": per_day,
        "critical": len(critical),
        "last_critical": last_critical,
        "day": day,
    }
    if day is not None:
        result["today"] = per_day.get(_as_int(day), 0)
        result["recent"] = [
            item
            for item in (entries or ())
            if _entry_day(item) >= _as_int(day)
        ]
    return result


def summary_text(entries, *, day=None, rules=None):
    """Короткая русская строка сводки для HUD."""
    report = digest(entries, day=day, rules=rules)
    parts = ["событий: %d" % report["total"]]
    if report["critical"]:
        parts.append("критических: %d" % report["critical"])
    if day is not None:
        parts.append("сегодня: %d" % report.get("today", 0))
    top = sorted(
        report["counts"].items(), key=lambda item: (-item[1], item[0])
    )[:3]
    if top:
        parts.append(
            "чаще всего: "
            + ", ".join("%s×%d" % (kind, count) for kind, count in top)
        )
    return "; ".join(parts)


def compact(
    entries,
    *,
    max_entries=LOG_MAX_ENTRIES,
    recent_days=LOG_RECENT_DAYS,
    critical_keep=LOG_CRITICAL_KEEP,
    day=None,
    rules=None,
):
    """Сжать журнал, сохранив критические записи и недавнюю историю.

    Возвращает `(kept, removed)`; исходный список не меняется. Сначала
    сохраняются все критические записи (последние `critical_keep`), затем
    записи за последние `recent_days`, затем — самые новые из остатка до
    `max_entries`. Порядок восстанавливается по исходной позиции, поэтому
    журнал остаётся хронологическим.
    """
    items = list(entries or ())
    max_entries = max(1, _as_int(max_entries, LOG_MAX_ENTRIES))
    if len(items) <= max_entries:
        return items, 0
    recent_days = max(0, _as_int(recent_days, LOG_RECENT_DAYS))
    critical_keep = max(0, _as_int(critical_keep, LOG_CRITICAL_KEEP))
    current_day = (
        max((_entry_day(item) for item in items), default=0)
        if day is None
        else _as_int(day)
    )
    keep = set()
    # 1. Все критические записи, но не больше лимита.
    critical_indexes = [
        index
        for index, item in enumerate(items)
        if is_critical(item, rules)
    ]
    for index in critical_indexes[-critical_keep:] if critical_keep else ():
        keep.add(index)
    # 2. Недавняя история целиком.
    if recent_days:
        for index, item in enumerate(items):
            if _entry_day(item) >= current_day - recent_days:
                keep.add(index)
    # 3. Добить до лимита самыми новыми записями.
    if len(keep) < max_entries:
        for index in range(len(items) - 1, -1, -1):
            if len(keep) >= max_entries:
                break
            keep.add(index)
    # 4. Если критические сами превысили лимит, оставить последние.
    if len(keep) > max_entries:
        ordered = sorted(keep)
        keep = set(ordered[-max_entries:])
    kept = [item for index, item in enumerate(items) if index in keep]
    return kept, len(items) - len(kept)


def pause_reason(entries, *, day=None, rules=None):
    """Причина авто-паузы по последним критическим событиям.

    Учитываются только записи указанного дня (или последнего дня журнала),
    поэтому старая смерть/распад не держат игру на паузе вечно. Пустая
    строка — пауза по журналу не требуется.
    """
    pause = (rules or {}).get("pause") or DEFAULT_PAUSE_REASONS
    items = list(entries or ())
    if not items:
        return ""
    current_day = (
        max((_entry_day(item) for item in items), default=0)
        if day is None
        else _as_int(day)
    )
    for entry in reversed(items):
        entry_day = _entry_day(entry)
        if entry_day < current_day:
            break
        if entry_day > current_day:
            continue
        reason = pause.get(_as_text(entry.get("kind")))
        if reason:
            return reason
    return ""


__all__ = [
    "DEFAULT_KIND_SEVERITY",
    "DEFAULT_PAUSE_REASONS",
    "LOG_CRITICAL_KEEP",
    "LOG_MAX_ENTRIES",
    "LOG_RECENT_DAYS",
    "SEVERITIES",
    "SEVERITY_RANK",
    "classify",
    "compact",
    "digest",
    "is_critical",
    "log_view",
    "pause_reason",
    "rules_from_config",
    "severity_for",
    "summary_text",
]
