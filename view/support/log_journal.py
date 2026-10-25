"""Служебный журнал UI-слоя ``view``.

Пишет в ``operation_ozverin.log`` в корне проекта и дублирует сообщения
уровня INFO и выше в консоль. Журнал не является частью математической
модели: это только диагностика интерфейса.
"""

import logging
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_PATH = os.path.join(ROOT, "operation_ozverin.log")


def get_logger(name):
    """Вернуть именованный журнал с файловым и консольным обработчиками."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    try:
        file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        # Каталог только для чтения — интерфейс должен работать и без лога.
        pass
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger
