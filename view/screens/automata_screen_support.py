from __future__ import annotations

import time

import pygame

from campaign.faction_state import derived_assets
from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import fit_line, wrap_text
from view.support.log_journal import get_logger
from view.support.metrics import (
    amount_phrase,
    chance_phrase,
    cost_phrase,
    effect_phrase,
    efficiency_phrase,
    metric_phrase,
    progress_phrase,
    relation_phrase,
    share_phrase,
)

logger = get_logger("view.automata")

WIDTH, HEIGHT = 1280, 720
TOP_H = 104
LEFT_RECT = pygame.Rect(24, TOP_H, 344, 520)
MID_RECT = pygame.Rect(388, TOP_H, 420, 520)
RIGHT_RECT = pygame.Rect(828, TOP_H, 428, 520)
BOTTOM_RECT = pygame.Rect(24, 646, 1232, 54)
CHAT_RECT = pygame.Rect(1136, 14, 120, 40)
ACTION_ROW_H = 52
DESCRIPTION_H = 184
OPTIONS_TTL = 0.35
FACTION_TTL = 0.50
PANEL_BG = (18, 23, 33, 238)
PANEL_BORDER = (58, 70, 92)
TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
BAD = (226, 112, 112)
WARN = (230, 184, 96)
ASSET_LABELS = {
    "legitimacy": "законность",
    "influence": "влияние",
    "cohesion": "сплочённость",
    "supply": "снабжение",
    "fear": "страх",
    "morale": "мораль",
    "energy": "энергия",
}
try:
    from campaign.defaults import default_dict

    ASSET_LABELS = default_dict("asset_labels")
except Exception:  # pragma: no cover - UI не должен падать без конфига
    pass


def _relation_line(campaign, faction):
    rival = campaign.faction(campaign.rival_of(faction.side))
    if rival is None or rival.id == faction.id:
        return ""
    view = campaign.relation_view(faction.id, rival.id)
    labels = view.get("labels") or {}
    parts = []
    for axis, value in (view.get("outgoing") or {}).items():
        if abs(float(value)) < 0.01:
            continue
        parts.append(
            relation_phrase(labels.get(axis, axis), float(value))
        )
    if not parts:
        return "с %s: нейтрально" % rival.name
    return "с %s: %s" % (rival.name, " · ".join(parts[:2]))


def _panel(surface, rect):
    shape = pygame.Surface(rect.size, pygame.SRCALPHA)
    shape.fill(PANEL_BG)
    surface.blit(shape, rect.topleft)
    pygame.draw.rect(surface, PANEL_BORDER, rect, 2, border_radius=8)


def _asset_labels(faction):
    labels = dict(ASSET_LABELS)
    labels.update(
        (getattr(faction, "record", {}) or {}).get("asset_labels") or {}
    )
    return labels


def _asset_line(assets, keys=None, labels=None):
    labels = labels or ASSET_LABELS
    items = []
    for key, value in assets.items():
        if keys is not None and key not in keys:
            continue
        label = labels.get(key, key)
        items.append(metric_phrase(label, float(value)))
    return " · ".join(items)


def _target_name(campaign, action):
    target = str(action.get("target") or "rival")
    if target == "self":
        return "себя"
    if target == "rival":
        faction = campaign.faction(campaign.rival_of(campaign.player_side))
    elif target in ("any", "all", "all_rivals", "other"):
        return "любую фракцию"
    elif target == "strongest":
        return "сильнейшего"
    elif target == "weakest":
        return "слабейшего"
    else:
        faction = campaign.faction(target)
        if faction is None:
            for item in campaign.factions.values():
                if target in (item.id, item.name):
                    faction = item
                    break
    return getattr(faction, "name", target)


def _effect_to_text(effect):
    """Плоский словарь эффекта в «ключ ±0.00 · ключ ±0.00»."""
    if not isinstance(effect, dict) or not effect:
        return ""
    parts = []
    for key, value in effect.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            parts.append("%s %s" % (ASSET_LABELS.get(key, key), value))
            continue
        label = ASSET_LABELS.get(key, key)
        parts.append(effect_phrase(label, number))
    return " · ".join(parts)


def _projection_text(projections):
    """Проекции ``{self: {...}, target: {...}}`` в читаемую строку."""
    if not isinstance(projections, dict) or not projections:
        return ""
    parts = []
    self_part = _effect_to_text(projections.get("self"))
    target_part = _effect_to_text(projections.get("target"))
    if self_part:
        parts.append("вы: %s" % self_part)
    if target_part:
        parts.append("цель: %s" % target_part)
    return "; ".join(parts)


def _preview_report(campaign, action):
    """Симулировать обработчик на текущем снимке для превью эффекта.

    Строит ``WorkPlan`` через ``build_work`` и зовёт ``handlers.receive``
    с ``success=True`` и ``success=False``. Возвращает
    ``(plan, report_ok, report_fail)`` или ``None``, если ``template`` нет
    (legacy-контент). Ничего не применяет.
    """
    actor = campaign.faction(campaign.player_side)
    if actor is None:
        return None
    target_side = campaign._target_side(
        campaign.player_side, action
    )
    target = campaign.faction(target_side)
    if target is None:
        return None
    try:
        from campaign.work import build_work
        from campaign.handlers import receive as handler_receive
    except Exception:
        return None
    try:
        plan = build_work(action, actor, target, campaign)
    except Exception:
        plan = None
    if plan is None:
        return None
    work = plan.to_work()
    reports = {}
    for success in (True, False):
        try:
            reports[success] = handler_receive(
                work, plan, actor, target, campaign, success=success
            )
        except Exception:
            reports[success] = None
    if reports.get(True) is None and reports.get(False) is None:
        return None
    return plan, reports.get(True), reports.get(False)


__all__ = [
    'logger',
    'TOP_H',
    'LEFT_RECT',
    'MID_RECT',
    'RIGHT_RECT',
    'BOTTOM_RECT',
    'CHAT_RECT',
    'ACTION_ROW_H',
    'DESCRIPTION_H',
    'OPTIONS_TTL',
    'FACTION_TTL',
    'PANEL_BG',
    'PANEL_BORDER',
    'TEXT',
    'MUTED',
    'DIM',
    'ACCENT',
    'GOOD',
    'BAD',
    'WARN',
    'ASSET_LABELS',
    '_relation_line',
    '_panel',
    '_asset_labels',
    '_asset_line',
    '_target_name',
    '_effect_to_text',
    '_projection_text',
    '_preview_report',
]
