"""Контракт журнала: файл только по флагу, перезапись и лимит."""

from __future__ import annotations

import main

from view.support import log_journal


def _reset():
    log_journal.configure_logging(enabled=False)


def test_logging_is_off_by_default(tmp_path):
    target = tmp_path / "journal.log"
    try:
        assert log_journal.configure_logging(
            enabled=False, path=str(target)
        ) is None
        assert not target.exists()
    finally:
        _reset()


def test_logging_overwrites_file_on_each_run(tmp_path):
    target = tmp_path / "journal.log"
    try:
        log_journal.configure_logging(enabled=True, path=str(target))
        logger = log_journal.get_logger("test.journal")
        logger.warning("первый запуск")
        assert "первый запуск" in target.read_text(encoding="utf-8")

        log_journal.configure_logging(enabled=True, path=str(target))
        logger.warning("второй запуск")
        text = target.read_text(encoding="utf-8")
        assert "второй запуск" in text
        assert "первый запуск" not in text
    finally:
        _reset()


def test_logging_limits_file_size(tmp_path):
    target = tmp_path / "journal.log"
    try:
        log_journal.configure_logging(
            enabled=True, path=str(target), max_bytes=512
        )
        logger = log_journal.get_logger("test.journal.limit")
        for index in range(500):
            logger.warning("%03d %s", index, "x" * 80)
        assert target.exists()
        assert target.stat().st_size <= 512 + 256
        assert (tmp_path / "journal.log.1").exists() is False
    finally:
        _reset()


def test_logging_flags_are_stripped():
    argv, enabled, path = main._strip_logging_flags(
        [
            "--log",
            "--scene",
            "menu",
            "--log-file",
            "custom.log",
            "--fullscreen",
        ]
    )
    assert enabled is True
    assert path == "custom.log"
    assert argv == ["--scene", "menu", "--fullscreen"]


def test_log_file_flag_enables_logging():
    argv, enabled, path = main._strip_logging_flags(
        ["--log-file=logs/game.log", "--view"]
    )
    assert enabled is True
    assert path == "logs/game.log"
    assert argv == ["--view"]


def test_usage_documents_logging_flags():
    assert "--log" in main.USAGE
    assert "--log-file" in main.USAGE
