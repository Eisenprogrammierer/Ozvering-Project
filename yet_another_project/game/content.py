"""
game/content.py

Загрузчик контента пользовательских интерфейсов.

Читает JSON-файлы контентной директории (обычно configs/content/)
и предоставляет их данные в виде структурированных Python-объектов.

Загружаемые коллекции:
order_types: список типов приказов (orders.json);
notebook: блокнот с вкладками (notebook.json);
documents: список документов (documents.json);
dialogues: граф диалоговых узлов (dialogues.json);
decisions: список решений игрока (decisions.json).

Если файл отсутствует, коллекция инициализируется значением
по умолчанию, а событие записывается в журнал operation_ozverin.log
в корне проекта и дублируется в консоль.
"""

import json
import logging
import os
from pathlib import Path

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "operation_ozverin.log",
)


def _build_logger(name):
    """
    Создаёт и возвращает журнал с файловым и консольным обработчиками.

    Файловый обработчик пишет в operation_ozverin.log в корне проекта
    с уровнем DEBUG, консольный — с уровнем INFO.
    Обработчики создаются один раз для каждого имени журнала.

    Args:
        name (str): Имя журнала.

    Returns:
        logging.Logger: Настроенный журнал.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.propagate = False
    return logger


logger = _build_logger("game.content")


class Content:
    """
    Контейнер контентных данных интерфейсов.

    При создании экземпляра читает все JSON-файлы из указанной
    корневой директории и сохраняет их как атрибуты.

    Attributes:
        order_types (list): Список типов приказов из orders.json.
            Каждый элемент — словарь с полями id, label, firepower,
            vulnerability, move_speed, can_fight, can_barrage,
            retreat, recovers, color, dashed.
        notebook (dict): Блокнот из notebook.json.
            Содержит ключ "tabs" со списком вкладок.
        documents (list): Список документов из documents.json.
            Каждый элемент — словарь с полями title и lines.
        dialogues (dict): Граф диалогов из dialogues.json.
            Ключи — идентификаторы узлов, значения — словари
            с полями speaker, text, choices.
        decisions (list): Список решений из decisions.json.
            Каждый элемент — словарь с полями label, rule, effect.
    """

    def __init__(self, root="configs/content"):
        """
        Инициализирует загрузчик контента.

        Читает все JSON-файлы из корневой директории. Если файл
        не найден, соответствующий атрибут получает значение
        по умолчанию.

        Args:
            root (str): Путь к директории с контентными JSON-файлами.
        """
        root = Path(root)
        self.order_types = self._load(root / "orders.json", [])
        self.notebook = self._load(root / "notebook.json", {"tabs": []})
        self.documents = self._load(root / "documents.json", [])
        self.dialogues = self._load(root / "dialogues.json", {})
        self.decisions = self._load(root / "decisions.json", [])
        logger.info(
            "Контент загружен: order_types=%d, documents=%d, "
            "dialogues=%d, decisions=%d",
            len(self.order_types),
            len(self.documents),
            len(self.dialogues),
            len(self.decisions),
        )

    @staticmethod
    def _load(path, default):
        """
        Читает JSON-файл по указанному пути.

        Если файл не существует, возвращает значение по умолчанию
        и записывает предупреждение в журнал и консоль.

        Args:
            path (Path): Путь к JSON-файлу.
            default: Значение, возвращаемое при отсутствии файла.

        Returns:
            Данные из JSON-файла или default, если файл не найден.
        """
        if not path.exists():
            logger.warning("Контент не найден: %s", path)
            return default
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        logger.debug("Контент прочитан: %s", path)
        return data