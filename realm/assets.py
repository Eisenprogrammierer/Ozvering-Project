"""Плейсхолдеры и будущие ассеты игры «Престол».

Реальные изображения пока не нужны: ``configs/realm/assets.json`` перечисляет
ключи, а ``assets/realm/`` может оставаться пустым. Если файл по пути из
манифеста появится, он будет загружен и вписан в прямоугольник; иначе
интерфейс рисует явный плейсхолдер. Логика игры от наличия арта не зависит.
"""

from __future__ import annotations

import os
from pathlib import Path

import pygame

from ui import theme

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets" / "realm"


class RealmAssets:
    """Ленивый загрузчик ассетов с честным fallback-плейсхолдером."""

    def __init__(self, content):
        self.content = content
        self._cache = {}
        self._failed = set()

    def manifest(self, key):
        return self.content.asset(key) or {
            "key": key,
            "caption": "АССЕТ",
            "path": "assets/realm/%s.png" % key,
        }

    def surface(self, key):
        if key in self._cache:
            return self._cache[key]
        if key in self._failed:
            return None
        item = self.manifest(key)
        path = ROOT / item.get("path", "")
        if not path.exists():
            self._failed.add(key)
            return None
        try:
            image = pygame.image.load(str(path)).convert_alpha()
        except Exception:
            self._failed.add(key)
            return None
        self._cache[key] = image
        return image

    def draw(self, screen, rect, key, fonts, caption=None, tint=None):
        """Нарисовать ассет или плейсхолдер в ``rect``."""
        rect = pygame.Rect(rect)
        image = self.surface(key)
        item = self.manifest(key)
        if image is not None:
            scaled = pygame.transform.smoothscale(
                image, (max(1, rect.width), max(1, rect.height))
            )
            screen.blit(scaled, rect.topleft)
            return rect
        theme.draw_placeholder(
            screen,
            rect,
            key,
            fonts,
            caption=caption or item.get("caption", "АССЕТ"),
            color=tint,
        )
        return rect

    def draw_portrait(self, screen, rect, key, fonts):
        """Портрет: ассет, если он есть, иначе рамка с силуэтом и подписью."""
        rect = pygame.Rect(rect)
        image = self.surface(key)
        if image is not None:
            scaled = pygame.transform.smoothscale(
                image, (max(1, rect.width), max(1, rect.height))
            )
            screen.blit(scaled, rect.topleft)
            return rect
        theme.panel(screen, rect, fill=(32, 31, 42), border=theme.BORDER,
                    radius=5)
        # Силуэт — не арт, а маркер места под портрет.
        head_r = max(4, min(rect.width, rect.height) // 6)
        head_c = (rect.centerx, rect.top + rect.height // 3)
        pygame.draw.circle(screen, (54, 52, 68), head_c, head_r)
        body = pygame.Rect(0, 0, rect.width // 2, rect.height // 3)
        body.midtop = (rect.centerx, head_c[1] + head_r + 2)
        pygame.draw.ellipse(screen, (54, 52, 68), body)
        if rect.width >= 80 and rect.height >= 80:
            theme.text(
                screen,
                fonts.font_s,
                "[ ПОРТРЕТ: %s ]" % key,
                (rect.centerx, rect.bottom - 10),
                theme.TEXT_MUTED,
                center=True,
            )
        return rect


def asset_path(item):
    """Абсолютный путь ассета из манифеста (для тестов/документации)."""
    return os.path.normpath(os.path.join(ROOT, item.get("path", "")))
