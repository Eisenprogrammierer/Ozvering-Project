from __future__ import annotations

import hashlib
import json

from .needs import MODE_RU


def _fmt(value, digits=2):
    try:
        return ("%." + str(digits) + "f") % float(value)
    except (TypeError, ValueError):
        return "0"


def _capitalize(text):
    text = str(text or "")
    if not text:
        return text
    return text[:1].upper() + text[1:]


def _summary(analysis):
    return _capitalize("; ".join(analysis.summary_lines()))


def _mode_line(analysis):
    weights = analysis.mode_weights or {}
    parts = [
        "%s %s" % (MODE_RU.get(mode, mode), _fmt(weights.get(mode, 0.0)))
        for mode in sorted(weights, key=lambda key: (-weights[key], key))
        if weights.get(mode, 0.0) >= 0.05
    ]
    return ", ".join(parts) if parts else "—"


def _description(analysis):
    if analysis.dissolved:
        return (
            "Организация не состоялась аналитически: при заданных "
            "потребностях, энергии и плотности связей не осталось ни одного "
            "участника с неотрицательным выигрышем участия. "
            + _summary(analysis)
            + ". Автомат показывает распад, а не шаблон организации."
        )
    return (
        "Аналитическая организация-суперсистема, выведенная из приоритетной "
        "потребности и масштаба её удовлетворения. "
        + _summary(analysis)
        + ". Режимы: "
        + _mode_line(analysis)
        + ". Взносы: "
        + analysis.contribution
        + "; принуждение: "
        + analysis.coercion
        + "; легитимация: "
        + analysis.legitimation
        + "; воспроизводство: "
        + analysis.reproduction
        + ". Участие: участник считается желающим, если выгода внутри минус "
        "взносы, риск и внешняя альтернатива неотрицательна; организация "
        "живёт, пока есть хотя бы один желающий. Ярлык — производная режимов "
        "и уровня, а не ручной шаблон."
    )


def _analysis_seed(analysis):
    payload = analysis.to_dict()
    payload.pop("assessments", None)
    text = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _natural_name(analysis, seed=None):
    mode = analysis.top_mode
    if not mode or analysis.dissolved:
        return None
    name_seed = _analysis_seed(analysis) if seed is None else int(seed)
    try:
        from naming import NameGenerator
        from naming.catalog import NamingError

        result = NameGenerator(seed=name_seed).automaton_name(
            mode,
            need=analysis.priority_need,
            level=analysis.level,
            seed=name_seed,
        )
        return result.text or None
    except (NamingError, ValueError, KeyError):
        return None


def _legacy_title(analysis):
    return "%s — %s" % (_capitalize(analysis.archetype), analysis.need_ru)


def build_automaton(analysis, name=None, seed=None):
    if analysis.dissolved:
        return _build_dissolved(analysis, name=name)
    return _build_active(analysis, name=name, seed=seed)


def _build_dissolved(analysis, name=None):
    from automata.model import Automaton

    title = name or "Распущена — %s" % analysis.need_ru
    automaton = Automaton(title, _description(analysis))
    need = analysis.need_ru
    latent = automaton.add_state(
        "Потребность: %s" % need, x=120, y=180, initial=True
    )
    dissolved = automaton.add_state(
        "Распад: нет желающих", x=480, y=180, final=True
    )
    automaton.add_transition(
        latent.id, dissolved.id, "мобилизация не состоялась", "willing = 0"
    )
    return automaton


def _build_active(analysis, name=None, seed=None):
    from automata.model import Automaton

    title = (
        name or _natural_name(analysis, seed=seed) or _legacy_title(analysis)
    )
    automaton = Automaton(title, _description(analysis))

    latent = automaton.add_state(
        "Потребность: %s" % analysis.need_ru, x=80, y=80, initial=True
    )
    mobilizing = automaton.add_state(
        "Мобилизация: %s" % analysis.contribution, x=340, y=80
    )
    producing = automaton.add_state(
        "Производство: %s" % analysis.goods, x=600, y=80
    )
    distributing = automaton.add_state(
        "Распределение: %s" % analysis.goods, x=860, y=80
    )
    enforcing = automaton.add_state(
        "Принуждение: %s" % analysis.coercion, x=860, y=280
    )
    legitimating = automaton.add_state(
        "Легитимация: %s" % analysis.legitimation, x=600, y=280
    )
    reproducing = automaton.add_state(
        "Воспроизводство: %s" % analysis.reproduction, x=340, y=280
    )
    crisis = automaton.add_state("Кризис участия", x=340, y=480)
    dissolved = automaton.add_state(
        "Распад: нет желающих", x=80, y=480, final=True
    )

    automaton.add_transition(
        latent.id,
        mobilizing.id,
        "потребность осознана",
        "доля приоритета %.2f > 0" % analysis.priority_share,
    )
    automaton.add_transition(
        mobilizing.id,
        producing.id,
        "взносы собраны",
        "собрано ≥ %.2f" % analysis.contribution_rate,
    )
    automaton.add_transition(
        producing.id,
        distributing.id,
        "благо готово",
        "выпуск покрывает потребность",
    )
    automaton.add_transition(
        distributing.id,
        reproducing.id,
        "благо распределено",
        "доля willing ≥ 0.50",
    )
    automaton.add_transition(
        reproducing.id, mobilizing.id, "смена и набор", "есть желающие"
    )
    automaton.add_transition(
        distributing.id,
        enforcing.id,
        "уклонение от взносов",
        "доля уклоняющихся > 0.10",
    )
    automaton.add_transition(
        enforcing.id,
        legitimating.id,
        "санкция применена",
        "принуждение > легитимности",
    )
    automaton.add_transition(
        legitimating.id,
        reproducing.id,
        "порядок подтверждён",
        "легитимность восстановлена",
    )
    automaton.add_transition(
        reproducing.id, crisis.id, "выход участников", "доля willing < 0.50"
    )
    automaton.add_transition(
        crisis.id, reproducing.id, "реформа участия", "доля willing ≥ 0.50"
    )
    automaton.add_transition(
        crisis.id, dissolved.id, "нет желающих", "willing = 0"
    )
    return automaton


def save_automaton(analysis, store, slug=None, name=None, seed=None):
    automaton = build_automaton(analysis, name=name, seed=seed)
    if slug is None:
        slug = store.unique_slug(automaton.name)
    return store.save(automaton, slug)


__all__ = ["build_automaton", "save_automaton"]
