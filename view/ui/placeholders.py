import hashlib

import pygame

_PALETTES = (
    ((18, 28, 48), (62, 106, 156), (126, 176, 220)),
    ((38, 24, 20), (126, 74, 46), (214, 152, 92)),
    ((24, 38, 30), (58, 112, 78), (140, 196, 142)),
    ((34, 22, 42), (104, 68, 138), (188, 150, 220)),
    ((42, 34, 18), (132, 104, 44), (220, 190, 108)),
    ((30, 30, 34), (92, 96, 108), (176, 184, 196)),
)


def _digest(name):
    return hashlib.sha256(str(name).encode("utf-8")).digest()


def _palette(name):
    return _PALETTES[_digest(name)[0] % len(_PALETTES)]


def _font(size):
    return pygame.font.Font(None, max(12, int(size)))


def _fit(text, font, max_width):
    text = str(text)
    if font.size(text)[0] <= max_width:
        return text
    while len(text) > 4 and font.size(text + "…")[0] > max_width:
        text = text[:-1]
    return text + "…"


def _draw_glyph(surface, name, color, rect):
    digest = _digest(name)
    x, y, w, h = rect
    cx, cy = x + w // 2, y + h // 2
    kind = name.split("/", 1)[0] if "/" in name else "asset"
    if kind == "items":
        pygame.draw.rect(
            surface,
            color,
            (cx - w // 5, cy - h // 6, w // 3, h // 3),
            3,
            border_radius=6,
        )
        pygame.draw.line(
            surface,
            color,
            (cx + w // 10, cy - h // 6),
            (cx + w // 5, cy - h // 3),
            3,
        )
    elif kind in ("scenes", "campaign"):
        points = [
            (cx - w // 4, cy + h // 6),
            (cx - w // 10, cy - h // 5),
            (cx + w // 14, cy + h // 20),
            (cx + w // 4, cy - h // 7),
        ]
        pygame.draw.lines(surface, color, False, points, 3)
        pygame.draw.circle(
            surface, color, (cx + w // 5, cy - h // 5), max(4, w // 55), 2
        )
    elif kind == "menus":
        pygame.draw.circle(surface, color, (cx, cy), min(w, h) // 5, 3)
        pygame.draw.line(
            surface,
            color,
            (cx - w // 5, cy + h // 8),
            (cx + w // 5, cy - h // 8),
            3,
        )
    else:
        for index in range(3):
            offset = index * max(6, h // 18)
            pygame.draw.rect(
                surface,
                color,
                (cx - w // 6 + offset, cy - h // 6 + offset, w // 4, h // 5),
                2,
                border_radius=4,
            )
    for bit in range(6):
        px = x + 20 + (digest[bit + 1] * (w - 40)) // 255
        py = y + 20 + (digest[bit + 7] * (h - 40)) // 255
        pygame.draw.circle(surface, color, (px, py), 2)


def make_placeholder(name, size=None, label="PLACEHOLDER"):
    width, height = size or (320, 200)
    width = max(32, int(width))
    height = max(32, int(height))
    top, accent, light = _palette(name)
    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    for y in range(height):
        blend = y / max(1, height - 1)
        color = tuple(
            int(top[i] * (1.0 - blend) + accent[i] * blend * 0.55)
            for i in range(3)
        )
        pygame.draw.line(surface, color, (0, y), (width, y))
    step = max(18, min(width, height) // 8)
    grid = tuple(min(255, value + 22) for value in accent)
    for x in range(0, width, step):
        pygame.draw.line(surface, grid, (x, 0), (x, height), 1)
    for y in range(0, height, step):
        pygame.draw.line(surface, grid, (0, y), (width, y), 1)
    margin = max(8, min(width, height) // 24)
    frame = pygame.Rect(
        margin, margin, width - 2 * margin, height - 2 * margin
    )
    pygame.draw.rect(
        surface,
        light,
        frame,
        max(1, margin // 4),
        border_radius=max(4, margin),
    )
    for corner in (
        (frame.left, frame.top),
        (frame.right, frame.top),
        (frame.left, frame.bottom),
        (frame.right, frame.bottom),
    ):
        pygame.draw.circle(surface, light, corner, max(2, margin // 3))
    _draw_glyph(
        surface,
        name,
        light,
        (
            frame.left + margin,
            frame.top + margin,
            frame.width - 2 * margin,
            max(24, frame.height // 2),
        ),
    )
    title_size = max(14, min(30, height // 13))
    title_font = _font(title_size)
    small_font = _font(max(12, title_size * 2 // 3))
    title = _fit(
        str(name).replace("/", " / ").replace("_", " ").upper(),
        title_font,
        max(20, width - 2 * margin * 3),
    )
    title_surf = title_font.render(title, True, light)
    title_rect = title_surf.get_rect(
        center=(width // 2, frame.top + frame.height - 42)
    )
    surface.blit(title_surf, title_rect)
    label_surf = small_font.render(str(label).upper(), True, light)
    label_rect = label_surf.get_rect(
        center=(width // 2, frame.top + frame.height - 18)
    )
    surface.blit(label_surf, label_rect)
    return surface
