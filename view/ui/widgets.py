import pygame

from view.support.log_journal import get_logger

logger = get_logger("view.widgets")

COLOR_TEXT = (220, 220, 230)
COLOR_ACCENT = (80, 140, 220)
COLOR_BTN = (50, 90, 160)
COLOR_BTN_HOVER = (70, 120, 200)
COLOR_BORDER = (60, 60, 90)
COLOR_PANEL = (25, 25, 40, 230)


class Button:

    def __init__(self, rect, text, font, callback=None, alpha=255):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.font = font
        self.callback = callback
        self.alpha = alpha
        self.hovered = False

    def draw(self, screen):
        if self.alpha >= 255:
            color = COLOR_BTN_HOVER if self.hovered else COLOR_BTN
            pygame.draw.rect(screen, color, self.rect, border_radius=6)
        else:
            surf = pygame.Surface(self.rect.size, pygame.SRCALPHA)
            fill = (70, 120, 200, 160) if self.hovered else (20, 20, 30, 110)
            surf.fill(fill)
            screen.blit(surf, self.rect.topleft)
        pygame.draw.rect(screen, COLOR_BORDER, self.rect, 2, border_radius=6)
        surf = self.font.render(self.text, True, COLOR_TEXT)

        max_w = max(1, self.rect.width - 12)
        max_h = max(1, self.rect.height - 6)
        if surf.get_width() > max_w or surf.get_height() > max_h:
            scale = min(
                max_w / max(1, surf.get_width()),
                max_h / max(1, surf.get_height()),
                1.0,
            )
            surf = pygame.transform.smoothscale(
                surf,
                (
                    max(1, int(surf.get_width() * scale)),
                    max(1, int(surf.get_height() * scale)),
                ),
            )
        screen.blit(surf, surf.get_rect(center=self.rect.center))

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos) and self.callback:
                logger.info("Клик по кнопке: %s", self.text)
                self.callback()
                return True
        return False


class Panel:

    def __init__(self, rect):
        self.rect = pygame.Rect(rect)

    def draw(self, screen):
        surf = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        surf.fill(COLOR_PANEL)
        screen.blit(surf, self.rect.topleft)
        pygame.draw.rect(screen, COLOR_BORDER, self.rect, 2, border_radius=8)


class TabBar:

    def __init__(self, rect, tabs, font, active=0):
        self.rect = pygame.Rect(rect)
        self.tabs = tabs
        self.font = font
        self.active = active

    def draw(self, screen):
        w = self.rect.width // len(self.tabs)
        for i, name in enumerate(self.tabs):
            r = pygame.Rect(
                self.rect.x + i * w, self.rect.y, w, self.rect.height
            )
            color = COLOR_ACCENT if i == self.active else COLOR_BTN
            pygame.draw.rect(screen, color, r, border_radius=4)
            surf = self.font.render(name, True, COLOR_TEXT)
            screen.blit(surf, surf.get_rect(center=r.center))

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            w = self.rect.width // len(self.tabs)
            for i in range(len(self.tabs)):
                r = pygame.Rect(
                    self.rect.x + i * w, self.rect.y, w, self.rect.height
                )
                if r.collidepoint(event.pos):
                    self.active = i
                    logger.info("Переключена вкладка: %s", self.tabs[i])
                    return True
        return False
