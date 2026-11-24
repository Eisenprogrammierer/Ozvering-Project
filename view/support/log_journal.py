"""Единая настройка журнала игры.

Файл журнала создаётся только при явном флаге ``--log`` (или
``--log-file``). Каждый запуск перезаписывает файл, а размер ограничен:
при переполнении журнал начинается заново, старые запуски не копятся.

Модули только просят логгер через :func:`get_logger`; обработчики живут
на корневом логгере и настраиваются один раз в точке входа.
"""

from __future__ import annotations

import logging
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_PATH = os.path.join(ROOT, "operation_ozverin.log")
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_HANDLER_MARK = "_ozverin_journal_handler"


class _TruncatingFileHandler(logging.FileHandler):
    """Файловый журнал с жёстким пределом размера.

    ``RotatingFileHandler`` при ``maxBytes > 0`` принудительно открывает
    файл на дозапись и хранит копии. Нам нужно обратное: новый запуск
    начинает файл заново, а переполнение не оставляет старых копий.
    Поэтому после записи, если предел достигнут, поток открывается
    заново в режиме ``"w"``.
    """

    def __init__(self, filename, max_bytes=DEFAULT_MAX_BYTES, **kwargs):
        self.max_bytes = max_bytes
        super().__init__(filename, mode="w", **kwargs)

    def emit(self, record):
        super().emit(record)
        try:
            if self.stream is None:
                return
            if self.stream.tell() < self.max_bytes:
                return
            self.stream.close()
            self.stream = self._open()
        except Exception:
            self.handleError(record)


def get_logger(name):
    """Логгер модуля; вывод настраивает :func:`configure_logging`."""

    return logging.getLogger(name)


def _drop_own_handlers(root):
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
            handler.close()


def configure_logging(
    enabled=False,
    path=None,
    level=logging.DEBUG,
    max_bytes=DEFAULT_MAX_BYTES,
):
    """Настроить журнал и вернуть путь файла (или ``None``).

    Без ``enabled`` файл не создаётся: остаётся только консоль уровня
    INFO. С ``enabled`` файл открывается в режиме ``"w"``, поэтому новый
    запуск не дописывает прошлый. При переполнении журнал начинается
    заново, старые копии не накапливаются.
    """

    root = logging.getLogger()
    _drop_own_handlers(root)
    formatter = logging.Formatter(LOG_FORMAT)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    setattr(console, _HANDLER_MARK, True)
    root.addHandler(console)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    if not enabled:
        return None
    target = os.path.abspath(path or LOG_PATH)
    try:
        size = int(max_bytes)
    except (TypeError, ValueError):
        size = DEFAULT_MAX_BYTES
    if size <= 0:
        size = DEFAULT_MAX_BYTES
    try:
        file_handler = _TruncatingFileHandler(
            target,
            max_bytes=size,
            encoding="utf-8",
        )
    except OSError:
        return None
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    setattr(file_handler, _HANDLER_MARK, True)
    root.addHandler(file_handler)
    return target
