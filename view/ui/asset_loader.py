import json
import os
import logging

import pygame

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
IMAGES_DIR = os.path.join(BASE_DIR, "assets", "images")
SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg")
PRESENTATION_PATH = os.path.join(
    BASE_DIR, "configs", "view", "presentation.json"
)
LOG_PATH = os.path.join(BASE_DIR, "operation_ozverin.log")


def _load_presentation():
    try:
        with open(PRESENTATION_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_PRESENTATION = _load_presentation()

logger = logging.getLogger("asset_loader")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    _file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(_file_handler)
    _console_handler = logging.StreamHandler()
    _console_handler.setLevel(logging.INFO)
    _console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(_console_handler)
    logger.propagate = False


class AssetLoader:

    BASE_DIR = BASE_DIR
    IMAGES_DIR = IMAGES_DIR
    USE_PLACEHOLDERS = bool(_PRESENTATION.get("use_placeholders", True))
    PLACEHOLDER_LABEL = str(
        _PRESENTATION.get("placeholder_label", "PLACEHOLDER")
    )
    _cache = {}
    _path_cache = {}

    @staticmethod
    def _direct_path(name):
        if "." in os.path.basename(name):
            path = os.path.join(AssetLoader.IMAGES_DIR, name)
            if os.path.exists(path):
                logger.debug("Прямой путь найден: %s", path)
                return path
        for ext in ("",) + SUPPORTED_EXTENSIONS:
            path = os.path.join(AssetLoader.IMAGES_DIR, name + ext)
            if os.path.exists(path):
                logger.debug("Прямой путь найден: %s", path)
                return path
        return None

    @staticmethod
    def _recursive_path(name):
        stem, explicit_ext = os.path.splitext(os.path.basename(name))
        if not os.path.isdir(AssetLoader.IMAGES_DIR):
            return None
        for root, dirs, files in os.walk(AssetLoader.IMAGES_DIR):
            dirs.sort()
            for f in sorted(files):
                fstem, fext = os.path.splitext(f)
                if fext.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                if explicit_ext and f == os.path.basename(name):
                    logger.debug(
                        "Рекурсивный путь найден: %s",
                        os.path.join(root, f),
                    )
                    return os.path.join(root, f)
                if not explicit_ext and fstem == stem:
                    logger.debug(
                        "Рекурсивный путь найден: %s",
                        os.path.join(root, f),
                    )
                    return os.path.join(root, f)
        return None

    @staticmethod
    def _resolve_path(name):
        if name in AssetLoader._path_cache:
            return AssetLoader._path_cache[name]
        path = AssetLoader._direct_path(name)
        if path is None:
            path = AssetLoader._recursive_path(name)
        AssetLoader._path_cache[name] = path
        logger.debug("Путь разрешён: %s -> %s", name, path)
        return path

    @staticmethod
    def load(name, size=None):
        key = (name, size)
        if key in AssetLoader._cache:
            logger.debug("Кэш: %s", name)
            return AssetLoader._cache[key]
        if AssetLoader.USE_PLACEHOLDERS:
            from .placeholders import make_placeholder

            img = make_placeholder(
                name,
                size or (320, 200),
                AssetLoader.PLACEHOLDER_LABEL,
            )
            AssetLoader._cache[key] = img
            logger.info("Плейсхолдер: %s", name)
            return img
        path = AssetLoader._resolve_path(name)
        img = None
        if path is not None:
            try:
                img = pygame.image.load(path).convert_alpha()
            except Exception:
                img = pygame.image.load(path).convert()
        if img is None:
            from .placeholders import make_placeholder

            logger.warning(
                "Не найден ассет: %s в %s — создан плейсхолдер",
                name,
                AssetLoader.IMAGES_DIR,
            )
            img = make_placeholder(
                name,
                size or (320, 200),
                AssetLoader.PLACEHOLDER_LABEL,
            )
        else:
            logger.info("Загружен ассет: %s", name)
        if size is not None and img.get_size() != tuple(size):
            img = pygame.transform.smoothscale(img, size)
        AssetLoader._cache[key] = img
        return img
