import pygame

BG = (14, 16, 22)
BG_ALT = (20, 23, 30)
PANEL = (26, 29, 38)
PANEL_HI = (37, 41, 53)
BORDER = (60, 66, 80)
TEXT = (228, 228, 232)
TEXT_DIM = (150, 154, 164)
TEXT_MUTED = (105, 110, 122)
ACCENT = (255, 210, 90)
ACCENT2 = (110, 170, 255)
OK = (120, 200, 130)
WARN = (240, 150, 90)
DANGER = (225, 95, 95)


EDGE = 18
GAP = 12
BTN_H = 46
ROW_H = 62
RADIUS = 6
TITLE_PAD = 10


def mix(a, b, t):
    t = max(0.0, min(1.0, float(t)))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def panel(s, rect, fill=PANEL, border=BORDER, radius=RADIUS, width=1):
    pygame.draw.rect(s, fill, rect, border_radius=radius)
    if border is not None:
        pygame.draw.rect(s, border, rect, width=width, border_radius=radius)


def text(s, font, value, pos, color=TEXT, center=False, right=False):
    img = font.render(str(value), True, color)
    r = img.get_rect()
    if center:
        r.center = pos
    elif right:
        r.topright = pos
    else:
        r.topleft = pos
    s.blit(img, r)
    return r


def text_size(font, value):
    return font.size(str(value))


def wrap(font, value, max_w):
    lines = []
    for paragraph in str(value).split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            trial = (cur + " " + w).strip()
            if font.size(trial)[0] <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    return lines


def draw_placeholder(s, rect, key, fonts, caption="IMG", color=None):
    rect = pygame.Rect(rect)
    fill = color or (30, 33, 42)
    panel(s, rect, fill=fill, border=BORDER, radius=4)
    pygame.draw.line(s, BORDER, rect.topleft, rect.bottomright)
    pygame.draw.line(s, BORDER, rect.topright, rect.bottomleft)
    text(
        s,
        fonts.font_s,
        "[ %s: %s ]" % (caption, key),
        rect.center,
        TEXT_DIM,
        center=True,
    )


def draw_title(s, fonts, value, center_x, y, color=ACCENT):
    r = text(s, fonts.font_b, value, (center_x, y), color, center=True)
    return r.bottom


def draw_footer_hint(s, fonts, value, w, h):
    text(
        s,
        fonts.font_s,
        value,
        (w // 2, h - EDGE // 2),
        TEXT_MUTED,
        center=True,
    )
