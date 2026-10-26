"""
view/ui/asset_loader.py

Загрузчик графических ассетов с кэшированием, рекурсивным поиском
и автоматическим созданием плейсхолдеров при отсутствии файла.

Поддерживаемые форматы: PNG, JPG, JPEG.

Порядок поиска:
1. Прямой относительный путь внутри assets/images, включая
   вложенные директории, указанные в имени ассета;
2. Рекурсивный поиск по базовому имени во всех вложенных
   директориях assets/images.

Если файл не найден, создаётся полупрозрачный плейсхолдер
серо-синего цвета с рамкой.

События разрешения путей, загрузки и создания плейсхолдеров
записываются в журнал operation_ozverin.log в корне проекта
и дублируются в консоль.
"""

import json
import os
import logging

import pygame

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
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
    """
    Статический загрузчик изображений с кэшированием.

    Ищет изображения в директории assets/images. Сначала пытается
    использовать имя как прямой относительный путь (с подстановкой
    расширений .png, .jpg, .jpeg). Если файл не найден, выполняет
    рекурсивный поиск по базовому имени во всех вложенных
    директориях assets/images.

    Все загруженные изображения кэшируются по ключу (имя, размер).
    Разрешённые абсолютные пути кэшируются по имени, чтобы не
    выполнять повторный обход директорий.

    Class Attributes:
        BASE_DIR (str): Абсолютный путь к корню проекта.
        IMAGES_DIR (str): Абсолютный путь к директории с изображениями.
        _cache (dict): Кэш загруженных поверхностей по ключу (name, size).
        _path_cache (dict): Кэш разрешённых путей по имени (name -> path|None).
    """

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
        """
        Проверяет имя ассета как прямой относительный путь
        внутри assets/images.

        Если базовое имя содержит расширение, сначала проверяется
        точное совпадение пути. Затем последовательно пробуются
        расширения "", ".png", ".jpg", ".jpeg".

        Args:
            name (str): Имя ассета (относительный путь, возможно
                с расширением).

        Returns:
            str | None: Абсолютный путь к файлу или None.
        """
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
        """
        Выполняет рекурсивный поиск файла ассета по базовому имени
        во всех вложенных директориях assets/images.

        Обход детерминированный: директории и файлы обходятся в
        сортированном порядке, первое совпадение побеждает.

        Если имя содержит явное расширение, ищется точное совпадение
        базового имени с расширением. Иначе ищется файл с тем же
        стеблом и любым поддерживаемым расширением.

        Args:
            name (str): Имя ассета.

        Returns:
            str | None: Абсолютный путь к файлу или None.
        """
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
        """
        Разрешает имя ассета в абсолютный путь.

        Сначала проверяет прямой путь, затем рекурсивный поиск.
        Результат (включая None) кэшируется в _path_cache.

        Args:
            name (str): Имя ассета.

        Returns:
            str | None: Абсолютный путь к файлу или None.
        """
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
        """
        Загружает изображение по имени с опциональным масштабированием.

        Порядок поиска:
        1. Прямой относительный путь внутри assets/images.
        2. Рекурсивный поиск по базовому имени во всех вложенных
           директориях assets/images.

        Если файл не найден ни одним способом, создаётся плейсхолдер.
        Результат кэшируется. При повторном вызове с теми же
        аргументами возвращается кэшированная поверхность.

        Args:
            name (str): Имя ассета (относительный путь без расширения
                или с расширением).
            size (tuple[int, int] | None): Целевой размер (width, height).
                Если None, изображение не масштабируется
                (плейсхолдер создаётся размером 320x200).

        Returns:
            pygame.Surface: Загруженное или сгенерированное изображение.
        """
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