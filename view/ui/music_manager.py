import os

import pygame

from view.support.log_journal import get_logger

logger = get_logger("view.music")

CATEGORIES = ("overture", "ambient", "victorious", "tragic")
SUPPORTED_EXT = (".ogg", ".mp3", ".wav")
FADE_OUT_MS = 1500


class MusicManager:

    def __init__(self, music_dir: str):
        self.music_dir = music_dir
        self.tracks: dict[str, list[str]] = {cat: [] for cat in CATEGORIES}
        self._index: dict[str, int] = {cat: 0 for cat in CATEGORIES}
        self.current_category: str | None = None
        self.pending_category: str | None = None
        self.fade_pending: bool = False
        self.enabled: bool = True
        self._scan()
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception as exc:
            logger.warning("Музыка отключена: %s", exc)
            self.enabled = False

    def _scan(self):
        if not os.path.isdir(self.music_dir):
            logger.warning("Директория музыки не найдена: %s", self.music_dir)
            self.enabled = False
            return
        for cat in CATEGORIES:
            cat_dir = os.path.join(self.music_dir, cat)
            if not os.path.isdir(cat_dir):
                continue
            files = [
                os.path.join(cat_dir, f)
                for f in sorted(os.listdir(cat_dir))
                if f.lower().endswith(SUPPORTED_EXT)
            ]
            self.tracks[cat] = files
            logger.info("Категория %s: треков=%d", cat, len(files))

    def _has_tracks(self, cat: str) -> bool:
        return bool(self.tracks.get(cat))

    def request_category(self, cat: str, fade: bool = False):
        if not self.enabled or not self._has_tracks(cat):
            return
        if self.current_category == cat and self.pending_category is None:
            return
        if fade:
            self.pending_category = cat
            if pygame.mixer.music.get_busy():
                self.fade_pending = True
                pygame.mixer.music.fadeout(FADE_OUT_MS)
                logger.info("Затухание и переход к %s", cat)
            return
        if pygame.mixer.music.get_busy():
            self.pending_category = cat
            logger.info("Очередь: после текущего трека -> %s", cat)
        else:
            self._start_category(cat)

    def _start_category(self, cat: str):
        self.current_category = cat
        self._index[cat] = 0
        self._play_track(cat, 0)

    def _play_track(self, cat: str, idx: int):
        files = self.tracks.get(cat, [])
        if not files:
            return
        idx = idx % len(files)
        path = files[idx]
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play(0)
            self.current_category = cat
            logger.info("Играет трек %s [%s]", os.path.basename(path), cat)
        except Exception as exc:
            logger.warning("Не удалось сыграть %s: %s", path, exc)

    def update(self):
        if not self.enabled:
            return
        if self.fade_pending:
            if not pygame.mixer.music.get_busy():
                self.fade_pending = False
                cat = self.pending_category
                self.pending_category = None
                if cat is not None:
                    self._start_category(cat)
            return
        if pygame.mixer.music.get_busy():
            return
        if self.pending_category is not None:
            cat = self.pending_category
            self.pending_category = None
            self._start_category(cat)
        elif self.current_category is not None:
            cat = self.current_category
            self._index[cat] += 1
            self._play_track(cat, self._index[cat])
