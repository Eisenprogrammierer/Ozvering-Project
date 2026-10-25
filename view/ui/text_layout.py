"""Автоподбор текста под прямоугольник.

Экраны ``view`` рисуют текст напрямую через ``pygame.font``. Этот модуль
даёт общий алгоритм: перенести строки по ширине, подобрать самый крупный
шрифт из набора и вернуть готовые строки. Благодаря этому длинные реплики
не обрезаются и не залезают под кнопки.

Модуль намеренно не зависит от ``App``: вызывающая сторона передаёт список
шрифтов от крупного к мелкому, например ``[app.font_body, app.font_small,
app.font_tiny]``.
"""

from __future__ import annotations

import pygame


def wrap_text(font, text, max_width):
    """Перенести текст по ширине с сохранением пустых абзацев.

    Переносы ``\\n`` в исходной строке трактуются как границы абзацев.
    Пустые абзацы сохраняются пустой строкой, чтобы не терять структуру
    документа.
    """
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
            # Очень длинное слово без пробелов (URL, идентификатор) тоже
            # должно помещаться по ширине, иначе оно вылезет за rect.
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
    """Вернуть комфортную высоту строки для шрифта."""
    return max(font.get_height(), int(font.get_height() * float(spacing)))


def fit_lines(fonts, text, rect, spacing=1.18):
    """Подобрать шрифт и строки, полностью помещающиеся в ``rect``.

    Args:
        fonts: Итерируемый набор шрифтов от крупного к мелкому.
        text: Исходный текст.
        rect: ``pygame.Rect`` доступной области.
        spacing: Множитель межстрочного интервала.

    Returns:
        tuple: ``(lines, font, line_height_px, overflow)``. Если даже самый
        мелкий шрифт не помещается, ``overflow`` равно True; строки при этом
        не обрезаются, чтобы вызывающая сторона могла включить прокрутку.
    """
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


def draw_fitted(surface, fonts, text, rect, color, spacing=1.18,
                align="left", valign="top", shadow=False):
    """Нарисовать текст, который гарантированно остаётся внутри ``rect``.

    Args:
        surface: Целевая поверхность.
        fonts: Набор шрифтов от крупного к мелкому.
        text: Исходный текст.
        rect: Доступная область (``pygame.Rect``).
        color: Цвет текста.
        spacing: Множитель межстрочного интервала.
        align: ``left``, ``center`` или ``right``.
        valign: ``top``, ``center`` или ``bottom``.
        shadow: Рисовать ли мягкую тень для читаемости на фоне.

    Returns:
        tuple: ``(lines, font, overflow)``.
    """
    rect = pygame.Rect(rect)
    lines, font, lh, overflow = fit_lines(fonts, text, rect, spacing)
    total_h = lh * len(lines)
    if overflow:
        # Даже самый мелкий шрифт не помещается: рисуем с верхней границы
        # и обрезаем по rect, чтобы текст не залез под кнопки. Для длинных
        # документов есть отдельные экраны с прокруткой.
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
