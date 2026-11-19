"""Маленькие квадратные портреты персонажей.

Реальные ассеты лежат в ``assets/images/characters/<id>.png``. Пока их
нет, рисуется аккуратный плейсхолдер с инициалами и устойчивым цветом
от id персонажа — так список людей остаётся читаемым и не зависит от
внешних файлов. Игрок или контент-мейкер может просто положить файл с
нужным именем, и он подхватится без правок кода.
"""

from __future__ import annotations

import hashlib

import pygame

from .asset_loader import AssetLoader

PORTRAIT_SIZE = 26
PORTRAIT_BORDER = (74, 96, 124)
_CACHE = {}

_PALETTES = (
    ((28, 44, 68), (82, 138, 196)),
    ((50, 34, 28), (176, 112, 70)),
    ((28, 52, 40), (78, 148, 104)),
    ((46, 30, 58), (140, 96, 180)),
    ((54, 44, 24), (176, 142, 66)),
    ((36, 38, 44), (124, 132, 148)),
)


def _digest(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).digest()


def _palette(key):
    return _PALETTES[_digest(key)[0] % len(_PALETTES)]


def _initials(name):
    words = [part for part in str(name or "").split() if part]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][:1] + words[1][:1]).upper()


def _placeholder(key, name, size):
    top, accent = _palette(key)
    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    surface.fill(top)
    pygame.draw.polygon(
        surface,
        accent,
        [(0, size), (size, 0), (size, size)],
    )
    pygame.draw.rect(
        surface,
        (220, 228, 240),
        (2, 2, size - 4, size - 4),
        1,
        border_radius=max(2, size // 10),
    )
    font_size = max(10, int(size * 0.44))
    try:
        font = pygame.font.Font(None, font_size)
    except Exception:
        return surface
    text = font.render(_initials(name), True, (238, 243, 250))
    surface.blit(text, text.get_rect(center=(size // 2, size // 2)))
    return surface


def portrait_surface(key, name="", size=PORTRAIT_SIZE):
    """Вернуть квадратный портрет: ассет, если он есть, иначе плейсхолдер."""
    size = max(16, int(size))
    cache_key = (str(key or ""), str(name or ""), size)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached
    key = str(key or "")
    surface = None
    if key and AssetLoader.asset_exists(key):
        try:
            surface = AssetLoader.load_asset(key, (size, size))
        except Exception:
            surface = None
    if surface is None:
        source = key or name or "character"
        surface = _placeholder(source, name or source, size)
    _CACHE[cache_key] = surface
    return surface


def draw_portrait(
    screen,
    key,
    name="",
    rect=None,
    size=PORTRAIT_SIZE,
    border=PORTRAIT_BORDER,
):
    """Нарисовать портрет в ``rect`` (или квадрат ``size`` слева сверху)."""
    if rect is None:
        rect = pygame.Rect(0, 0, size, size)
    else:
        rect = pygame.Rect(rect)
        size = max(16, min(rect.width, rect.height))
    surface = portrait_surface(key, name, size)
    target = pygame.Rect(0, 0, size, size)
    target.center = rect.center
    screen.blit(surface, target.topleft)
    if border is not None:
        pygame.draw.rect(
            screen,
            border,
            target,
            1,
            border_radius=max(2, size // 10),
        )


__all__ = [
    "PORTRAIT_BORDER",
    "PORTRAIT_SIZE",
    "draw_portrait",
    "portrait_surface",
]
