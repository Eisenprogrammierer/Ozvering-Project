"""Константы и чистые помощники диспетчера докладов."""

from __future__ import annotations

from typing import Mapping


DISTORTION_DEFAULTS = {
    "enabled": True,
    "base": 0.06,
    "ambition": 0.22,
    "disloyalty": 0.18,
    "fear": 0.08,
    "grievance": 0.12,
    "shift": 1,
    "strong_shift": 2,
    "strong_at": 0.7,
    "motive_reveal": 0.75,
    "motives": {
        "ambitious": "полномочия",
        "hostile": "подрыв",
        "loyal_fearful": "страх",
        "loyal": "оправдание",
        "neutral": "выгода",
    },
}


AI_DEFAULTS = {
    "enabled": True,
    "trust_base": 0.35,
    "trust_relation": 0.45,
    "trust_loyalty": 0.20,
    "trust_history": 0.25,
    "trust_fear": -0.30,
    "verify_base": 0.10,
    "verify_anxiety": 0.35,
    "verify_discipline": 0.30,
    "verify_distrust": 0.30,
    "verify_history": 0.20,
    "ignore_base": 0.10,
    "ignore_fear": 0.35,
    "ignore_distrust": 0.25,
    "ignore_loyalty": 0.20,
    "noise": 0.0,
}


PROMISE_DEFAULTS = {
    "enabled": True,
    "chance": 0.30,
    "kind": "favor",
    "amount": 1.0,
    "due_days": 5,
    "tones": ["ambitious", "loyal_fearful", "neutral"],
    "request_text": "{source} просит не оставлять это без ответа.",
    "line": "Вы обещали {source} поддержку по «{asset_label}».",
    "overdue_line": (
        "Обещание по «{asset_label}» просрочено. "
        "{source} помнит об этом."
    ),
    "fulfilled_line": (
        "Обещание по «{asset_label}» исполнено. "
        "{source} отметил это."
    ),
}


BRIEFING_DEFAULTS = {
    "enabled": True,
    "trend_days": 30.0,
    "trend_min_samples": 2,
    "trend_step": 0.06,
    "trend_lines": {
        "up": "{asset_label} — «{band}», и за последние дни прибывает.",
        "down": "{asset_label} — «{band}», и за последние дни проседает.",
    },
    "trend_multi": True,
    "trend_max_assets": 3,
    "trend_multi_line": "За дни: {parts}.",
    "trend_join": ", ",
    "trend_short": {
        "up": "{asset_label} прибывает",
        "down": "{asset_label} проседает",
    },
}


MEMORY_DEFAULTS = {
    "enabled": True,
    "confidence_step": 0.04,
    "spread": {
        "enabled": True,
        "chance": 0.30,
        "weight": 0.5,
        "relation_weight": 0.40,
        "include_player": False,
        "distortion": {
            "enabled": True,
            "chance": 0.20,
            "source_chance": 0.10,
            "weight_scale": 1.5,
            "outcomes": {
                "trusted": "ignored",
                "ignored": "trusted",
                "verified_right": "verified_wrong",
                "verified_wrong": "verified_right",
                "lied": "verified_wrong",
            },
        },
    },
    "lines": {
        "trusted": (
            "В прошлый раз вы доверились мне насчёт {last_asset_label}."
        ),
        "ignored": (
            "В прошлый раз вы отложили мой доклад о {last_asset_label}."
        ),
        "verified_right": (
            "Мой прошлый доклад о {last_asset_label} подтвердился."
        ),
        "verified_wrong": (
            "В прошлый раз я ошибся с {last_asset_label} "
            "и стал осторожнее."
        ),
        "lied": (
            "В прошлый раз вы раскрыли мою подтасовку "
            "насчёт {last_asset_label}."
        ),
        "expired": (
            "Мой прошлый доклад о {last_asset_label} остался без ответа."
        ),
    },
}


MEMORY_OUTCOMES = (
    "trusted",
    "ignored",
    "verified_right",
    "verified_wrong",
    "lied",
)


NEWS_DEFAULTS = {
    "enabled": True,
    "interval_seconds": 86400.0,
    "delay_seconds": 21600.0,
    "max_pending": 8,
    "title": "Вести: {faction}",
    "texts": {},
    "city": {
        "enabled": True,
        "chance": 0.40,
        "title": "Городская сводка",
        "texts": {
            "mixed": (
                "В городе неровно: {weak_label} «{weak_band}», "
                "а {strong_label} «{strong_band}»."
            ),
            "calm": "В городе ровно: {asset_label} «{band}».",
        },
    },
    "prices": {
        "enabled": True,
        "chance": 0.35,
        "title": "Цены",
        "asset": "supply",
        "low": "На рынке тесно: цены растут.",
        "high": "На рынке людно: цены спадают.",
        "level": "На рынке цены держатся.",
    },
    "street": {
        "enabled": True,
        "chance": 0.30,
        "title": "Слухи улиц",
        "texts": {
            "has_broken_word": (
                "Улица помнит: {faction} не сдержала слово."
            ),
            "sees_as_threat": (
                "На улицах шепчутся: {faction} и {target} — враги."
            ),
            "feels_betrayed_by": (
                "Улица судачит: {faction} и {target} — не друзья."
            ),
            "trusts": (
                "Улица шепчет: {faction} и {target} — близки."
            ),
            "quiet": "На улицах гадают, что затевает {faction}.",
        },
    },
}


THREAT_DEFAULTS = {
    "enabled": True,
    "bands": ["critical", "low"],
    "predicate": "sees_as_threat",
    "strength": 0.8,
    "confidence": 0.7,
}


COUNTER_DEFAULTS = [
    {
        "id": "warn",
        "label": "Предупредить своего лидера",
        "benefit": (
            "Ваш лидер получит повод усилить силовые работы против "
            "фракции-источника: мораль лидера заметно растёт, "
            "отношение к источнику падает."
        ),
        "price_actions": 1,
        "belief": {
            "predicate": "sees_as_threat",
            "target": "origin_faction",
            "value": 0.7,
            "confidence": 0.8,
        },
        "morale": 0.5,
        "text": (
            "Ваш лидер предупреждён о замысле {faction}; "
            "источник теперь видится ему угрозой."
        ),
    },
    {
        "id": "expose",
        "label": "Подорвать доверие к источнику",
        "benefit": (
            "Лидер фракции {faction} получит повод не доверять "
            "своему источнику: доверие и расположение к нему падают, "
            "а слух о подлоге расходится по его окружению."
        ),
        "price_actions": 1,
        "requires_motive": True,
        "enemy_belief": {
            "predicate": "feels_betrayed_by",
            "target": "source",
            "value": 0.8,
            "confidence": 0.75,
        },
        "relation": {"trust": -0.06, "affinity": -0.04},
        "text": (
            "Слух о подлоге дошёл до {faction}: "
            "доверие к источнику пошатнулось."
        ),
    },
]


INTERCEPTION_DEFAULTS = {
    "enabled": True,
    "chance": 0.40,
    "influence_weight": 0.30,
    "delay_seconds": 7200.0,
    "expire_seconds": 259200.0,
    "max_pending": 6,
    "price_actions": 1,
    "title": "Перехват: {faction}",
    "open_title": "Перехват вскрыт: {faction}",
    "sealed_text": (
        "Перехваченное донесение. Шифр не вскрыт: видно только отправителя "
        "и тему."
    ),
    "in_transit_text": "Донесение ещё в пути: шифр доставят позже.",
    "open_text": "Шифр вскрыт. Донесение прочитано.",
    "source_unknown": "источник неизвестен",
    "decision_unknown": "решение фракции неизвестно",
    "countermeasures": COUNTER_DEFAULTS,
    "counter_used_text": "Контрмера: {label}.",
    "counter_disabled_motive": "Нужен раскрытый мотив подлога.",
    "counter_already_text": "По этому перехвату уже принята контрмера.",
    "retaliation": {
        "enabled": True,
        "chance": 0.30,
        "chances": {
            "warn": 0.45,
            "expose": 0.25,
        },
        "influence_weight": 0.30,
        "player_influence_weight": 0.30,
        "relation": {
            "trust": -0.08,
            "affinity": -0.05,
        },
        "belief": {
            "predicate": "sees_as_threat",
            "value": 0.70,
            "confidence": 0.75,
        },
        "texts": {
            "warn": "{faction}: замысел раскрыт. {player} под подозрением.",
            "expose": "{faction}: за слухом о подлоге стоит {player}.",
        },
        "fallback_text": "{faction} что-то заподозрила.",
    },
}


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _number(value, low)))


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _as_list(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _nested_tuple(value):
    if isinstance(value, (list, tuple)):
        return tuple(_nested_tuple(item) for item in value)
    return value


def _merged(defaults, raw):
    """Слить секцию конфига с умолчаниями, не теряя вложенные словари."""
    result = {}
    for key, value in defaults.items():
        result[key] = dict(value) if isinstance(value, Mapping) else value
    for key, value in _as_mapping(raw).items():
        if isinstance(value, Mapping) and isinstance(
            result.get(key), Mapping
        ):
            merged = dict(result[key])
            merged.update(value)
            result[key] = merged
        else:
            result[key] = value
    return result


class _Fields(dict):
    """Словарь для ``format_map``: пропуск остаётся видимым, а не падает."""

    def __missing__(self, key):
        return "{%s}" % key


def _render(template, values):
    try:
        return str(template).format_map(_Fields(values))
    except (KeyError, IndexError, ValueError, AttributeError):
        return str(template)


def _alive(character):
    if character is None:
        return False
    return not bool(
        getattr(
            character,
            "is_dead",
            getattr(character, "dead", False),
        )
    )


__all__ = [
    "DISTORTION_DEFAULTS",
    "AI_DEFAULTS",
    "PROMISE_DEFAULTS",
    "BRIEFING_DEFAULTS",
    "MEMORY_DEFAULTS",
    "MEMORY_OUTCOMES",
    "NEWS_DEFAULTS",
    "THREAT_DEFAULTS",
    "COUNTER_DEFAULTS",
    "INTERCEPTION_DEFAULTS",
    "_number",
    "_clamp",
    "_as_mapping",
    "_as_list",
    "_nested_tuple",
    "_merged",
    "_Fields",
    "_render",
    "_alive",
]
