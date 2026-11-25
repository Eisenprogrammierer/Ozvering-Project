"""Проверка диалоговых JSON: ссылки, категории, роли, покрытие.

Публичная точка входа сохранена: реализация разрезана на
``lint_base.py`` (грамматика и планы) и ``lint_ext.py`` (верхние слои).
"""

from __future__ import annotations

from .lint_ext import lint_catalog, lint_directory, main

__all__ = ["lint_catalog", "lint_directory", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
