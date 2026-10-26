"""Общие ошибки кампанийного слоя."""

from __future__ import annotations


class CampaignError(ValueError):
    """Базовая ошибка ролей, пресетов и кампанийного хранилища."""


__all__ = ["CampaignError"]
