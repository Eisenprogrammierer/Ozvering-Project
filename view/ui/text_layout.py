from __future__ import annotations

import pygame


def wrap_text(font, text, max_width):
    text = str(text).replace("\\n", "\n")
    width = max(1, int(max_width))
    lines = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():

            while font.size(word)[0] > width:
                cut = len(word)
                while cut > 1 and font.size(word[:cut])[0] > width:
                    cut -= 1
                if current:
                    lines.append(current)
                    current = ""
                lines.append(word[:cut])
                word = word[cut:]
            candidate = (current + " " + word).strip()
            if current and font.size(candidate)[0] > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines or [""]


def line_height(font, spacing=1.18):
    return max(font.get_height(), int(font.get_height() * float(spacing)))


def fit_lines(fonts, text, rect, spacing=1.18):
    candidates = [f for f in fonts if f is not None]
    if not candidates:
        raise ValueError("fit_lines: нужен хотя бы один шрифт")
    best = None
    for font in candidates:
        lines = wrap_text(font, text, rect.width)
        lh = line_height(font, spacing)
        best = (lines, font, lh, lh * len(lines) > rect.height)
        if not best[3]:
            return best
    return best


def draw_fitted(
    surface,
    fonts,
    text,
    rect,
    color,
    spacing=1.18,
    align="left",
    valign="top",
    shadow=False,
):
    rect = pygame.Rect(rect)
    lines, font, lh, overflow = fit_lines(fonts, text, rect, spacing)
    total_h = lh * len(lines)
    if overflow:

        y = rect.top
    elif valign == "center":
        y = rect.centery - total_h // 2
    elif valign == "bottom":
        y = rect.bottom - total_h
    else:
        y = rect.top

    old_clip = surface.get_clip()
    surface.set_clip(rect)
    for line in lines:
        if not line:
            y += lh
            continue
        surf = font.render(line, True, color)
        if shadow:
            shadow_surf = font.render(line, True, (0, 0, 0))
            if align == "center":
                x = rect.centerx - surf.get_width() // 2
            elif align == "right":
                x = rect.right - surf.get_width()
            else:
                x = rect.left
            surface.blit(shadow_surf, (x + 2, y + 2))
        if align == "center":
            x = rect.centerx - surf.get_width() // 2
        elif align == "right":
            x = rect.right - surf.get_width()
        else:
            x = rect.left
        surface.blit(surf, (x, y))
        y += lh
    surface.set_clip(old_clip)
    return lines, font, overflow
