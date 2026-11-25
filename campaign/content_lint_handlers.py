"""Проверка JSON-обработчиков работ и явных карт потребностей.

Обработчик — данные: ``rules[].receiver.effect``, ``sender`` и ветки
``failure``. Эффект может менять активы фракции (``assets``), потребности
персонажей (``needs``), отношения и другие структурные области. Плоский
ключ, совпадающий с именем потребности, исторически попадал в
``_apply_assets`` и создавал невидимый актив вместо изменения BDI.
Линтер запрещает такую неоднозначную запись: имя потребности должно быть
явно в ``needs``, а настоящий актив — явно в ``assets``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import List

import bdi

NEED_KEYS = frozenset(bdi.NEEDS)


def _lint_effect_need_keys(source, effect, problems):
    """Найти плоские ключи-потребности в одном словаре эффекта."""
    if not isinstance(effect, Mapping):
        return
    for key in effect:
        if str(key) in NEED_KEYS:
            problems.append(
                "%s.%s: плоский ключ-потребность %r; используйте "
                "вложенный needs или явный assets"
                % (source, key, key)
            )
    if "if" in effect:
        for key in ("then", "else"):
            part = effect.get(key)
            if isinstance(part, Mapping):
                _lint_effect_need_keys(
                    "%s.%s" % (source, key), part, problems
                )


def _lint_handler_rule(source, rule, seen_ids):
    problems: List[str] = []
    if not isinstance(rule, Mapping):
        return ["%s: правило должно быть объектом" % source]
    when = rule.get("when")
    if not isinstance(when, Mapping):
        when = {}
    action_id = when.get("id")
    if action_id is not None:
        action_id = str(action_id)
        if not action_id.strip():
            problems.append("%s.when.id: пустой id" % source)
        elif action_id in seen_ids:
            problems.append("%s.when.id: повтор id %r" % (source, action_id))
        else:
            seen_ids.add(action_id)
    for branch_name in ("receiver", "failure"):
        branch = rule.get(branch_name)
        if branch is None:
            continue
        if not isinstance(branch, Mapping):
            problems.append("%s.%s: ожидался объект" % (source, branch_name))
            continue
        effect = branch.get("effect")
        if effect is not None and not isinstance(effect, Mapping):
            problems.append(
                "%s.%s.effect: ожидался объект" % (source, branch_name)
            )
        elif effect is not None:
            _lint_effect_need_keys(
                "%s.%s.effect" % (source, branch_name), effect, problems
            )
            if "if" in effect:
                for key in ("then", "else"):
                    part = effect.get(key)
                    if part is not None and not isinstance(part, Mapping):
                        problems.append(
                            "%s.%s.effect.%s: ожидался объект"
                            % (source, branch_name, key)
                        )
        branch_sender = branch.get("sender")
        if branch_sender is not None:
            if not isinstance(branch_sender, Mapping):
                problems.append(
                    "%s.%s.sender: ожидался объект"
                    % (source, branch_name)
                )
            else:
                _lint_effect_need_keys(
                    "%s.%s.sender" % (source, branch_name),
                    branch_sender,
                    problems,
                )
    sender = rule.get("sender")
    if sender is not None:
        if not isinstance(sender, Mapping):
            problems.append("%s.sender: ожидался объект" % source)
        else:
            _lint_effect_need_keys("%s.sender" % source, sender, problems)
    return problems


def lint_handlers_data(path, data):
    """Проверить JSON обработчика работ: форму, правила и их ветки.

    И кампания, и дневной мир используют один формат: файл
    ``handlers/<form>.json`` с ``rules`` и ``default``. Линтер ловит
    структурные ошибки, повторяющиеся ``when.id`` и плоские ключи-потребности;
    содержание эффектов проверяет тот слой, который их исполняет.
    """
    source = str(path)
    if not isinstance(data, Mapping):
        return ["%s: обработчик должен быть объектом" % source]
    problems: List[str] = []
    form = data.get("form")
    if not isinstance(form, str) or not form.strip():
        problems.append("%s.form: не задана форма" % source)
    elif Path(path).stem not in (form, "__init__"):
        problems.append(
            "%s.form: %r не совпадает с именем файла" % (source, form)
        )
    rules = data.get("rules")
    if not isinstance(rules, (list, tuple)):
        problems.append("%s.rules: ожидался список" % source)
        rules = ()
    seen_ids = set()
    for index, rule in enumerate(rules):
        source_rule = "%s.rules[%d]" % (source, index)
        problems.extend(
            _lint_handler_rule(source_rule, rule, seen_ids)
        )
    default = data.get("default")
    if default is not None:
        problems.extend(
            _lint_handler_rule("%s.default" % source, default, set())
        )
    return problems


__all__ = [
    "NEED_KEYS",
    "lint_handlers_data",
]
