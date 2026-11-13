"""
core/log_journal.py

Фабрика журналов событий.

Возвращает именованные журналы, которые пишут сообщения в файл
operation_ozverin.log в корне проекта и дублируют их в консоль.
Файловый обработчик принимает сообщения уровня DEBUG и выше,
консольный — уровня INFO и выше. Повторный запрос журнала с тем же
именем возвращает существующий журнал без дублирования обработчиков.
"""

import logging
import os

LOG_FILENAME = "operation_ozverin.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _log_path():
    """
    Возвращает абсолютный путь к файлу журнала в корне проекта.

    Вычисляет путь относительно расположения данного модуля,
    поднимаясь на два уровня вверх (core/ -> корень проекта)
    и добавляя имя файла журнала.

    Returns:
        str: Абсолютный путь к operation_ozverin.log.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, LOG_FILENAME)


def get_logger(name):
    """
    Возвращает именованный журнал с файловым и консольным обработчиками.

    При первом запросе создаёт журнал, устанавливает уровень DEBUG и
    добавляет два обработчика с единым форматом. При повторном запросе
    возвращает уже настроенный журнал без изменений.

    Args:
        name (str): Имя журнала.

    Returns:
        logging.Logger: Настроенный журнал.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = logging.FileHandler(_log_path(), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger