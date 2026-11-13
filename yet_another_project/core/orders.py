"""
core/orders.py

Таблица приказов: геометрия 6 проекций, флаги поведения и расширенные
поля поддержки длительности, стоимости, эффектов, условий и BDI.

Загружает список приказов из JSON-файла configs/content/orders.json
и представляет его в виде типизированных массивов NumPy для быстрого
доступа боевой системой, движком и BDI. Хранит отображение
идентификаторов приказов на индексы и индексы запасных приказов.

Каждый приказ описывается словарём с базовыми полями (id, label,
firepower, vulnerability, move_speed, can_fight, can_barrage,
retreat, recovers) и расширенными полями (duration, morale_effect,
objective_modifier, priority, resource_cost, on_start, on_complete,
condition_required, bdi_relevance, fallback_order). При отсутствии
поля используется значение по умолчанию.

События загрузки и разбора таблицы записываются в журнал
operation_ozverin.log и дублируются в консоль средствами
core.log_journal.
"""

import json
from pathlib import Path

import numpy as np

from .log_journal import get_logger

logger = get_logger("core.orders")

PROJECTIONS = ("front", "left", "right", "rear", "bottom", "top")


class OrderTable:
    """
    Таблица приказов.

    Загружает список приказов из JSON и представляет его в виде
    типизированных массивов для быстрого доступа боевой системой,
    движком и BDI. Хранит отображение идентификаторов приказов на
    индексы и индексы запасных приказов.

    Attributes:
        orders (list[dict]): Исходные словари приказов из JSON.
        fire (np.ndarray): Огневая мощь по 6 проекциям [n, 6].
        vuln (np.ndarray): Уязвимость по 6 проекциям [n, 6].
        move_speed (np.ndarray): Скорость перемещения [n].
        can_fight (np.ndarray): Флаг возможности ведения боя [n].
        can_barrage (np.ndarray): Флаг возможности заградительного огня [n].
        recovers (np.ndarray): Флаг восстановления юнита [n].
        retreat (list[str]): Политика отступления для каждого приказа.
        durations (np.ndarray): Длительность приказа в тиках [n].
        morale_effects (np.ndarray): Эффект на мораль [n].
        objective_modifiers (np.ndarray): Модификатор целевой функции [n].
        priorities (np.ndarray): Приоритет приказа [n].
        resource_costs (list[dict]): Стоимость ресурсов для каждого приказа.
        on_start_effects (list): Эффекты при начале приказа.
        on_complete_effects (list): Эффекты при завершении приказа.
        conditions (list): Условия доступности приказа.
        bdi_relevances (list): Релевантность приказа для BDI.
        id_to_index (dict[str, int]): Отображение ID приказа на индекс.
        fallback_orders (np.ndarray): Индексы запасных приказов [n].
    """

    def __init__(self, path="configs/content/orders.json"):
        """
        Инициализирует таблицу приказов из JSON-файла.

        Читает базовые и расширенные поля каждого приказа и заполняет
        массивы значениями по умолчанию при отсутствии поля.

        Args:
            path (str): Путь к JSON-файлу приказов.

        Raises:
            FileNotFoundError: Если файл приказов не найден.
        """
        path = Path(path)
        if not path.exists():
            logger.error("Файл приказов не найден: %s", path)
            raise FileNotFoundError(
                f"Файл приказов не найден: {path}. "
                "Создайте configs/content/orders.json."
            )
        with open(path, encoding="utf-8") as f:
            self.orders = json.load(f)
        n = len(self.orders)
        logger.info("Таблица приказов загружена: %d приказов из %s", n, path)
        self.fire = np.ones((n, 6), dtype=np.float64)
        self.vuln = np.ones((n, 6), dtype=np.float64)
        self.move_speed = np.zeros(n, dtype=np.float64)
        self.can_fight = np.zeros(n, dtype=bool)
        self.can_barrage = np.zeros(n, dtype=bool)
        self.recovers = np.zeros(n, dtype=bool)
        self.retreat = [o.get("retreat", "never") for o in self.orders]
        self.durations = np.zeros(n, dtype=np.int64)
        self.morale_effects = np.zeros(n, dtype=np.float64)
        self.objective_modifiers = np.zeros(n, dtype=np.float64)
        self.priorities = np.zeros(n, dtype=np.int64)
        self.resource_costs = [
            dict(o.get("resource_cost", {}) or {}) for o in self.orders
        ]
        self.on_start_effects = [o.get("on_start") for o in self.orders]
        self.on_complete_effects = [o.get("on_complete") for o in self.orders]
        self.conditions = [o.get("condition_required") for o in self.orders]
        self.bdi_relevances = [o.get("bdi_relevance") for o in self.orders]
        fallback_ids = [o.get("fallback_order") for o in self.orders]
        for i, o in enumerate(self.orders):
            self.fire[i] = o.get("firepower", [1.0] * 6)
            self.vuln[i] = o.get("vulnerability", [1.0] * 6)
            self.move_speed[i] = float(o.get("move_speed", 0.0))
            self.can_fight[i] = bool(o.get("can_fight", False))
            self.can_barrage[i] = bool(o.get("can_barrage", False))
            self.recovers[i] = bool(o.get("recovers", False))
            self.durations[i] = int(o.get("duration", 0))
            self.morale_effects[i] = float(o.get("morale_effect", 0.0))
            self.objective_modifiers[i] = float(
                o.get("objective_modifier", 0.0)
            )
            self.priorities[i] = int(o.get("priority", 0))
        self.id_to_index = {o["id"]: i for i, o in enumerate(self.orders)}
        self.fallback_orders = np.array(
            [
                self.id_to_index.get(fid, -1) if fid else -1
                for fid in fallback_ids
            ],
            dtype=np.int64,
        )
        logger.debug(
            "Таблица приказов: идентификаторы %s",
            sorted(self.id_to_index.keys()),
        )

    def labels(self):
        """
        Возвращает список человекочитаемых названий всех приказов.

        Returns:
            list[str]: Названия приказов в порядке загрузки.
        """
        return [o["label"] for o in self.orders]

    def index_of(self, order_id):
        """
        Возвращает индекс приказа по идентификатору или None.

        Args:
            order_id (str): Идентификатор приказа.

        Returns:
            int | None: Индекс приказа или None, если он не найден.
        """
        return self.id_to_index.get(order_id)

    def get(self, index):
        """
        Возвращает исходный словарь приказа по индексу или пустой словарь.

        Args:
            index (int): Индекс приказа.

        Returns:
            dict: Словарь приказа или пустой словарь при выходе за диапазон.
        """
        if 0 <= index < len(self.orders):
            return self.orders[index]
        return {}