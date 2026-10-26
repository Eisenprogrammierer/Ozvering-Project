"""Графический редактор конечных автоматов (контент-инструмент).

Пакет самостоятелен: ``model.py`` не импортирует pygame, ``canvas.py`` и
``scenes/`` отвечают за представление. Запуск — ``python3 -m automata`` или
``python3 main.py --automata``.
"""

__all__ = ["model", "storage"]
