"""Хроника кампании: сюжет как проекция симуляции.

Модуль не содержит сюжетных строк и не знает кампаний. Он читает
структурированный журнал (кто, к кому, каким механизмом, с каким
результатом и дельтами состояния), группирует факты в эпизоды и
порождает текст из полей записи. Языковые конструкции здесь общие, как
и в остальном проекте: данные задают механику, а не последовательность
сцен.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .defaults import default_dict

FALLBACK_ASSET_LABELS = default_dict("asset_labels")
MAX_NARRATIVE = 400
DEFAULT_LIMIT = 12
PHRASES_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "campaigns"
    / "base"
    / "chronicle_phrases.json"
)


@lru_cache(maxsize=1)
def load_phrases():
    """Прочитать языковые шаблоны хроники; ошибка данных не ломает игру."""

    try:
        with PHRASES_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _phrase_list(key):
    value = load_phrases().get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return [
        str(item) for item in value if str(item or "").strip()
    ]


def _phrase_map(key):
    value = load_phrases().get(key)
    if not isinstance(value, dict):
        return {}
    result = {}
    for name, items in value.items():
        if not isinstance(items, (list, tuple)):
            continue
        cleaned = [
            str(item) for item in items if str(item or "").strip()
        ]
        if cleaned:
            result[str(name)] = cleaned
    return result


def _stable_choice(items, seed):
    """Выбрать вариант по идентификаторам фактов, а не случайно."""

    if not items:
        return ""
    text = str(seed or "")
    total = sum(
        (index + 1) * ord(char) for index, char in enumerate(text)
    )
    return items[total % len(items)]


def _magnitude_bucket(episode):
    value = _number(episode.get("magnitude"))
    chosen = ""
    for item in load_phrases().get("buckets") or ():
        if not isinstance(item, dict):
            continue
        if value >= _number(item.get("min")):
            chosen = str(item.get("id") or "")
    return chosen


def _format(pattern, values):
    try:
        return str(pattern).format(**values)
    except (KeyError, IndexError, ValueError):
        return str(pattern)


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def labels_for(*records, fallback=None):
    """Собрать подписи активов: локальные записи важнее общих."""

    labels = dict(fallback or FALLBACK_ASSET_LABELS)
    for record in records:
        local = (record or {}).get("asset_labels") or {}
        if isinstance(local, dict):
            for key, value in local.items():
                if value:
                    labels[str(key)] = str(value)
    return labels


def asset_label(key, labels=None):
    key = str(key or "")
    labels = labels or FALLBACK_ASSET_LABELS
    return str(labels.get(key) or key)


def magnitude(record):
    """Значимость факта: сумма модулей изменений состояния."""

    total = 0.0
    for item in record.get("assets") or ():
        if isinstance(item, dict):
            total += abs(_number(item.get("delta")))
    total += abs(_number(record.get("integrity_delta"))) * 4.0
    total += abs(
        _number(record.get("morale_after"))
        - _number(record.get("morale_before"))
    ) / 100.0
    total += abs(_number(record.get("morale_delta"))) / 100.0
    for item in record.get("needs") or ():
        if isinstance(item, dict):
            total += abs(_number(item.get("delta")))
    for item in record.get("relations") or ():
        if not isinstance(item, dict):
            continue
        for value in (item.get("axes") or {}).values():
            total += abs(_number(value))
    return round(total, 6)


def narrative_record(kind, turn, **fields):
    """Нормализовать запись журнала; текст здесь не создаётся."""

    record = {
        "id": str(fields.get("id") or ""),
        "cause_id": str(fields.get("cause_id") or ""),
        "cause_label": str(fields.get("cause_label") or ""),
        "kind": str(kind or ""),
        "turn": int(_number(turn)),
        "elapsed": round(_number(fields.get("elapsed")), 6),
        "actor": str(fields.get("actor") or ""),
        "actor_side": str(fields.get("actor_side") or ""),
        "target": str(fields.get("target") or ""),
        "target_side": str(fields.get("target_side") or ""),
        "action_id": str(fields.get("action_id") or ""),
        "label": str(fields.get("label") or ""),
        "success": fields.get("success"),
        "essence": str(fields.get("essence") or ""),
        "form": str(fields.get("form") or ""),
        "assets": [
            {
                "scope": str(item.get("scope") or ""),
                "key": str(item.get("key") or ""),
                "delta": round(_number(item.get("delta")), 6),
            }
            for item in fields.get("assets") or ()
            if isinstance(item, dict)
        ],
        "integrity_delta": (
            round(_number(fields.get("integrity_delta")), 6)
            if fields.get("integrity_delta") is not None
            else None
        ),
        "morale_before": (
            round(_number(fields.get("morale_before")), 3)
            if fields.get("morale_before") is not None
            else None
        ),
        "morale_after": (
            round(_number(fields.get("morale_after")), 3)
            if fields.get("morale_after") is not None
            else None
        ),
        "morale_delta": round(_number(fields.get("morale_delta")), 3),
        "needs": [
            {
                "key": str(item.get("key") or ""),
                "delta": round(_number(item.get("delta")), 6),
            }
            for item in fields.get("needs") or ()
            if isinstance(item, dict)
        ],
        "relations": [
            {
                "source": str(item.get("source") or ""),
                "target": str(item.get("target") or ""),
                "axes": {
                    str(key): round(_number(value), 6)
                    for key, value in (item.get("axes") or {}).items()
                },
            }
            for item in fields.get("relations") or ()
            if isinstance(item, dict)
        ],
        "organ_id": str(fields.get("organ_id") or ""),
        "character_id": str(fields.get("character_id") or ""),
        "report_id": str(fields.get("report_id") or ""),
    }
    record["magnitude"] = magnitude(record)
    return record


def _top_assets(record, labels, count=2):
    items = [
        item
        for item in record.get("assets") or ()
        if isinstance(item, dict) and _number(item.get("delta"))
    ]
    items.sort(
        key=lambda item: (
            -abs(_number(item.get("delta"))),
            str(item.get("key")),
        )
    )
    return [
        "%s %+.3f"
        % (asset_label(item.get("key"), labels), _number(item.get("delta")))
        for item in items[:count]
    ]


def headline(record, labels=None):
    """Текст одного факта из его полей, без сюжетных заготовок."""

    labels = labels or FALLBACK_ASSET_LABELS
    kind = str(record.get("kind") or "")
    actor = str(record.get("actor") or "")
    target = str(record.get("target") or "")
    label = str(record.get("label") or record.get("action_id") or "")
    if kind == "organ":
        parts = []
        delta = record.get("integrity_delta")
        if delta is not None:
            parts.append("целостность %+.3f" % _number(delta))
        tail = ("; " + ", ".join(parts)) if parts else ""
        return "%s → орган «%s»: «%s»%s" % (
            actor,
            target,
            label,
            tail,
        )
    if kind == "character":
        before = record.get("morale_before")
        after = record.get("morale_after")
        tail = ""
        if before is not None and after is not None:
            tail = "; мораль %.0f → %.0f" % (
                _number(before),
                _number(after),
            )
        return "%s → «%s»: «%s»%s" % (actor, target, label, tail)
    if kind == "report":
        tail = ""
        if record.get("success") is not None:
            tail = "; проверка: %s" % (
                "успех" if record.get("success") else "провал"
            )
        morale_delta = _number(record.get("morale_delta"))
        if morale_delta:
            tail += "; мораль %+.1f" % morale_delta
        return "%s: доклад «%s» от %s%s" % (
            actor,
            label,
            target,
            tail,
        )
    outcome = "успех" if record.get("success") else "провал"
    changes = _top_assets(record, labels)
    morale_delta = _number(record.get("morale_delta"))
    if morale_delta:
        changes.append("мораль %+.1f" % morale_delta)
    base = "%s → %s: «%s» — %s" % (actor, target, label, outcome)
    if changes:
        base += "; " + ", ".join(changes)
    essence = str(record.get("essence") or "")
    if essence:
        base += " [%s]" % essence
    return base


def _episode_key(record):
    return (
        str(record.get("actor_side") or ""),
        str(record.get("target_side") or ""),
        str(record.get("actor") or ""),
        str(record.get("target") or ""),
    )


def episodes(records, gap=1):
    """Сгруппировать факты в эпизоды по причинной связи.

    Факт, у которого есть ``cause_id``, попадает в эпизод причины даже
    через несколько циклов: это следствие, а не просто соседняя запись.
    Без причины остаётся прежняя эвристика — тот же актор, цель и
    соседние циклы.
    """

    ordered = sorted(
        (item for item in records or () if isinstance(item, dict)),
        key=lambda item: (
            int(_number(item.get("turn"))),
            _number(item.get("elapsed")),
        ),
    )
    result = []
    current = None
    episode_of = {}
    for record in ordered:
        record_id = str(record.get("id") or "")
        cause_id = str(record.get("cause_id") or "")
        key = _episode_key(record)
        turn = int(_number(record.get("turn")))
        target = None
        if cause_id:
            if current is not None and cause_id in current["ids"]:
                target = current
            else:
                target = episode_of.get(cause_id)
        if (
            target is None
            and current is not None
            and key == current["key"]
            and turn <= current["last_turn"] + int(gap)
        ):
            target = current
        if target is not None:
            target["records"].append(record)
            target["last_turn"] = max(target["last_turn"], turn)
            target["magnitude"] += _number(record.get("magnitude"))
            if record_id:
                target["ids"].add(record_id)
                episode_of[record_id] = target
            if target is current:
                current = target
            continue
        current = {
            "key": key,
            "records": [record],
            "first_turn": turn,
            "last_turn": turn,
            "magnitude": _number(record.get("magnitude")),
            "ids": {record_id} if record_id else set(),
        }
        result.append(current)
        if record_id:
            episode_of[record_id] = current
    return result


def episode_text(episode, labels=None):
    """Текст эпизода из агрегатов: без имён кампаний и готовых фраз."""

    labels = labels or FALLBACK_ASSET_LABELS
    all_records = episode.get("records") or []
    facts = [
        record
        for record in all_records
        if str(record.get("kind") or "") != "decision"
    ]
    if not facts:
        return ""
    strongest = max(
        facts,
        key=lambda item: (
            _number(item.get("magnitude")),
            -int(_number(item.get("turn"))),
        ),
    )
    actor = str(strongest.get("actor") or "")
    target = str(strongest.get("target") or "")
    totals = {}
    morale_total = 0.0
    needs_total = {}
    for record in facts:
        for item in record.get("assets") or ():
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            totals[key] = totals.get(key, 0.0) + _number(item.get("delta"))
        morale_total += _number(record.get("morale_delta"))
        for item in record.get("needs") or ():
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            needs_total[key] = needs_total.get(key, 0.0) + _number(
                item.get("delta")
            )
    top = sorted(totals.items(), key=lambda pair: (-abs(pair[1]), pair[0]))[:2]
    changes_list = [
        "%s %+.3f" % (asset_label(key, labels), value)
        for key, value in top
        if value
    ]
    if morale_total:
        changes_list.append("мораль %+.1f" % morale_total)
    top_needs = sorted(
        needs_total.items(), key=lambda pair: (-abs(pair[1]), pair[0])
    )[:1]
    for key, value in top_needs:
        if value:
            changes_list.append("%s %+.3f" % (key, value))
    changes = ", ".join(changes_list)
    first = int(_number(episode.get("first_turn")))
    last = int(_number(episode.get("last_turn")))
    span = (
        "цикл %d" % first if first == last else "циклы %d–%d" % (first, last)
    )
    if not actor:
        actor = str(load_phrases().get("empty_actor") or "")
    if not target:
        target = str(load_phrases().get("empty_target") or "")
    unit = str(load_phrases().get("facts_unit") or "факт(ов)")
    body = "%s → %s, %s: %d %s" % (
        actor,
        target,
        span,
        len(facts),
        unit,
    )
    if changes:
        body += str(load_phrases().get("changes_prefix") or "; ")
        body += changes
    strongest_label = (
        strongest.get("label") or strongest.get("action_id") or ""
    )
    body += _format(
        str(
            load_phrases().get("strongest_pattern")
            or "; сильнее всего «{label}»"
        ),
        {"label": strongest_label},
    )
    seed = "|".join(
        str(record.get("id") or "")
        for record in all_records
    )
    decision = next(
        (
            record
            for record in all_records
            if str(record.get("kind") or "") == "decision"
            and str(record.get("label") or "")
        ),
        None,
    )
    if decision is not None:
        pattern = _stable_choice(
            _phrase_list("decision_patterns"),
            seed + "|" + str(decision.get("label") or ""),
        )
        if pattern:
            return _format(
                pattern,
                {
                    "decision": str(decision.get("label") or ""),
                    "body": body,
                },
            )
        return "«%s» → %s" % (decision.get("label"), body)
    opening = _stable_choice(
        _phrase_map("openings").get(_magnitude_bucket(episode)) or (),
        seed,
    )
    text = opening + body
    external = []
    for record in facts:
        cause_id = str(record.get("cause_id") or "")
        if not cause_id or cause_id in episode.get("ids", set()):
            continue
        label = str(record.get("cause_label") or "")
        if label and label not in external:
            external.append(label)
    if external:
        pattern = _stable_choice(
            _phrase_list("cause_patterns"),
            seed + "|" + external[0],
        )
        if pattern:
            text += _format(pattern, {"cause": external[0]})
        else:
            text += "; причина: «%s»" % external[0]
    return text


def chronicle(records, limit=DEFAULT_LIMIT, labels=None):
    """Важнейшие эпизоды в хронологическом порядке."""

    labels = labels or FALLBACK_ASSET_LABELS
    items = [
        episode
        for episode in episodes(records)
        if _number(episode.get("magnitude")) > 0
    ]
    items.sort(
        key=lambda episode: (
            -_number(episode.get("magnitude")),
            int(_number(episode.get("first_turn"))),
        )
    )
    limit = int(limit) if int(limit or 0) > 0 else DEFAULT_LIMIT
    selected = items[:limit]
    selected.sort(
        key=lambda episode: (
            int(_number(episode.get("first_turn"))),
            int(_number(episode.get("last_turn"))),
        )
    )
    result = []
    for index, episode in enumerate(selected):
        result.append(
            {
                "id": "chronicle-%d" % index,
                "category": "chronicle",
                "title": "ХРОНИКА",
                "text": episode_text(episode, labels),
                "turn": int(_number(episode.get("first_turn"))),
                "last_turn": int(_number(episode.get("last_turn"))),
                "magnitude": round(_number(episode.get("magnitude")), 6),
            }
        )
    return result


def turning_points(records, count=3, labels=None):
    """Самые значимые эпизоды без привязки к порядку показа."""

    labels = labels or FALLBACK_ASSET_LABELS
    items = [
        episode
        for episode in episodes(records)
        if _number(episode.get("magnitude")) > 0
    ]
    items.sort(
        key=lambda episode: (
            -_number(episode.get("magnitude")),
            int(_number(episode.get("first_turn"))),
        )
    )
    return [
        episode_text(episode, labels)
        for episode in items[: max(0, int(count))]
    ]


def _faction_labels(faction, fallback):
    record = getattr(faction, "record", {}) or {}
    return labels_for(record, fallback=fallback)


def dominant_entries(faction, count=2):
    """Доминирующие подфракции и их активы — из состояния, не из сцены."""

    items = []
    for sub in getattr(faction, "subfactions", ()) or ():
        share = _number(getattr(sub, "share", 0.0))
        label = str(getattr(sub, "label", "") or getattr(sub, "id", ""))
        if not label:
            continue
        items.append(
            {
                "id": str(getattr(sub, "id", "") or ""),
                "label": label,
                "share": share,
                "assets": dict(getattr(sub, "assets", {}) or {}),
            }
        )
    items.sort(key=lambda item: (-item["share"], item["label"]))
    return items[: max(0, int(count))]


def _dominant(faction):
    return [
        (item["share"], item["label"])
        for item in dominant_entries(faction, 2)
    ]


def subfaction_goal(faction):
    """Курс правящей подфракции: её доля и самый сильный актив.

    Это не авторская ветка: цель меняется вместе с состоянием и
    исчезает, когда меняется доминирующая подфракция. Механически курс
    влияет на цену и силу работ её органов и на веса счёта.
    """

    course = (
        faction.course()
        if callable(getattr(faction, "course", None))
        else {}
    )
    if not course:
        entries = dominant_entries(faction, 1)
        if not entries:
            return ""
        entry = entries[0]
        return "%s %d%%" % (
            entry["label"],
            round(entry["share"] * 100.0),
        )
    label = str(course.get("label") or course.get("id") or "")
    share = _number(course.get("share"))
    asset = str(course.get("asset") or "")
    if not asset:
        return "%s %d%%" % (label, round(share * 100.0))
    labels = _faction_labels(faction, FALLBACK_ASSET_LABELS)
    return "%s %d%% · ставка на %s" % (
        label,
        round(share * 100.0),
        asset_label(asset, labels),
    )


def _limits_text(defeat, labels):
    return ", ".join(
        "%s ≤ %.2f" % (asset_label(key, labels), _number(value))
        for key, value in (defeat or {}).items()
    )


def risk_warning(campaign, ratio=1.25):
    """Предупреждение об активе, который подошёл к порогу поражения."""

    player = getattr(campaign, "player", None)
    if player is None:
        return ""
    rules = getattr(campaign, "outcome_rules", None) or {}
    defeat = (rules.get("defeat") or {}).get(
        getattr(campaign, "player_side", "")
    ) or {}
    labels = _faction_labels(player, FALLBACK_ASSET_LABELS)
    risks = []
    for key, limit in defeat.items():
        threshold = _number(limit)
        value = _number(player.asset(key))
        if threshold <= 0.0:
            continue
        if value <= threshold * max(1.0, float(ratio)):
            risks.append((value / threshold, key, value, threshold))
    if not risks:
        return ""
    risks.sort()
    _, key, value, threshold = risks[0]
    return "на грани: %s %.2f при пороге %.2f" % (
        asset_label(key, labels),
        value,
        threshold,
    )


def score_share(campaign, default=0.5):
    """Доля прогресса игрока в общем прогрессе — для полосы в шапке."""

    player = getattr(campaign, "player", None)
    rival = getattr(campaign, "rival", None)
    if player is None or rival is None:
        return float(default)
    own = _number(player.progress())
    other = _number(rival.progress())
    total = own + other
    if total <= 1e-9:
        return float(default)
    return max(0.0, min(1.0, own / total))


def briefing_slides(campaign):
    """Стартовая сводка из состояния кампании, а не из сцены."""

    player = getattr(campaign, "player", None)
    rival = getattr(campaign, "rival", None)
    if player is None:
        return []
    labels = _faction_labels(player, FALLBACK_ASSET_LABELS)
    rules = getattr(campaign, "outcome_rules", None) or {}
    defeat = (rules.get("defeat") or {}).get(
        getattr(campaign, "player_side", "")
    ) or {}
    role = str((getattr(player, "record", {}) or {}).get("role_title") or "")
    weights = ", ".join(
        "%s %.2f" % (asset_label(key, labels), _number(value))
        for key, value in (
            player.score_weights()
            if callable(getattr(player, "score_weights", None))
            else getattr(player, "score_assets", {})
        ).items()
    )
    lines = ["Кампания: %s." % getattr(campaign, "title", "")]
    if role:
        lines.append("Роль: %s." % role)
    if weights:
        lines.append("Счёт: %s." % weights)
    if defeat:
        lines.append("Провал при: %s." % _limits_text(defeat, labels))
    if rival is not None:
        lines.append("Соперник: %s." % getattr(rival, "name", ""))
    course = subfaction_goal(player)
    if course:
        lines.append("Курс: %s." % course)
    warning = risk_warning(campaign)
    if warning:
        lines.append("Внимание: %s." % warning)
    return [{"image": "campaign/briefing", "text": "\n".join(lines)}]


def ending_view(campaign):
    """Финал как функция конечного состояния и хроники."""

    player = getattr(campaign, "player", None)
    rival = getattr(campaign, "rival", None)
    if player is None or rival is None:
        return {"slides": [], "turning_points": [], "dominant": []}
    labels = _faction_labels(player, FALLBACK_ASSET_LABELS)
    rules = getattr(campaign, "outcome_rules", None) or {}
    defeat = (rules.get("defeat") or {}).get(
        getattr(campaign, "player_side", "")
    ) or {}
    outcome = str(getattr(campaign, "outcome", "") or "")
    verdict = (
        "преимущество"
        if outcome == "win"
        else "поражение" if outcome == "lose" else "ничья"
    )
    player_score = _number(player.score())
    rival_score = _number(rival.score())
    dominant = _dominant(player)
    top = turning_points(
        getattr(campaign, "narrative", ()), 3, labels=labels
    )
    lines = [
        "Кампания «%s» завершена за %d циклов." % (
            getattr(campaign, "title", ""),
            int(_number(getattr(campaign, "turn", 0))),
        ),
        "Итог: %s." % verdict,
    ]
    score_line = "Счёт: %s %.2f · %s %.2f." % (
        getattr(player, "name", ""),
        player_score,
        getattr(rival, "name", ""),
        rival_score,
    )
    limit_line = ""
    if defeat:
        limit_line = "Порог поражения: %s." % _limits_text(defeat, labels)
    forces = ", ".join(
        "%s %d%%" % (label, round(share * 100.0))
        for share, label in dominant
    )
    slides = [
        {
            "image": "campaign/ending",
            "text": "\n".join(lines),
        },
        {
            "image": "campaign/ending",
            "text": "\n".join(
                item for item in (score_line, limit_line) if item
            ),
        },
    ]
    if forces:
        slides.append(
            {
                "image": "campaign/ending",
                "text": "Доминирующие силы: %s." % forces,
            }
        )
    course = subfaction_goal(player)
    if course:
        slides.append(
            {
                "image": "campaign/ending",
                "text": "Курс победившей силы: %s." % course,
            }
        )
    if top:
        slides.append(
            {
                "image": "campaign/ending",
                "text": "Решающие эпизоды:\n%s"
                % "\n".join("— %s" % line for line in top),
            }
        )
    return {
        "outcome": outcome,
        "slides": slides,
        "turning_points": top,
        "dominant": [
            {"label": label, "share": round(share, 6)}
            for share, label in dominant
        ],
        "scores": {
            "player": round(player_score, 6),
            "rival": round(rival_score, 6),
        },
    }
