"""
core/logistics.py

Логистическая система игрового мира.

Управляет снабжением подразделений: базами, складами, маршрутами,
транспортом, конвоями и операциями. Учитывает модификаторы черт
персонажа для снабжения, потерь при casualties и шума докладов
через функции из core.traits.

Класс LogisticsSystem рассчитывает нормы потребления ресурсов
для военных подразделений на основе численности и техники,
пополняет запасы на базах, списывает пассивное ежедневное
потребление, распределяет ресурсы со складов и баз по
подразделениям в радиусе снабжения, обрабатывает движение
конвоев с учётом порчи и износа транспорта, выполняет
логистические операции с убывающей отдачей и временными
эффектами, предоставляет модификаторы боеприпасов, обороны
и атаки для боевой системы.

Состояние логистики (LogisticsState) сериализуется в словарь
для сохранений и восстанавливается из него. Загрузка из блока
сценария читает глобальную конфигурацию из logistics.json и
применяет размещения баз, складов, маршрутов и транспорта.
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config_loader import load_json
from .log_journal import get_logger
from .traits import (
    get_supply_modifier,
    get_supply_loss_on_casualties,
    get_report_noise_modifier,
)

logger = get_logger("core.logistics")

NODE_OPERATIONAL = 0
NODE_DAMAGED = 1
NODE_DESTROYED = 2

VEHICLE_OK = 0
VEHICLE_DAMAGED = 1
VEHICLE_BROKEN = 2

ROUTE_DIRT = 0
ROUTE_HIGHWAY = 1
ROUTE_FIELD = 2


@dataclass
class SupplyBase:
    """
    База снабжения.

    Хранит позицию, фракцию, поддерживаемые классы ресурсов,
    скорость поступления, радиус снабжения, текущие запасы
    и состояние узла.

    Attributes:
        id: Уникальный идентификатор базы.
        x: Координата X на карте.
        y: Координата Y на карте.
        faction: Фракция владельца.
        classes: Список поддерживаемых классов ресурсов.
        intake_rate: Скорость поступления ресурсов за день.
        supply_radius: Радиус снабжения в клетках.
        stockpile: Текущие запасы по классам ресурсов.
        state: Состояние узла (NODE_OPERATIONAL/DAMAGED/DESTROYED).
    """

    id: str
    x: int
    y: int
    faction: str
    classes: List[str]
    intake_rate: Dict[str, float]
    supply_radius: float
    stockpile: Dict[str, float] = field(default_factory=dict)
    state: int = NODE_OPERATIONAL


@dataclass
class ForwardDepot:
    """
    Передовой склад.

    Хранит позицию, фракцию, вместимость, радиус снабжения,
    уровень защиты, состояние и текущие запасы.

    Attributes:
        id: Уникальный идентификатор склада.
        x: Координата X на карте.
        y: Координата Y на карте.
        faction: Фракция владельца.
        capacity: Максимальная вместимость склада.
        supply_radius: Радиус снабжения в клетках.
        protection: Уровень защиты от перехвата.
        state: Состояние узла (NODE_OPERATIONAL/DAMAGED/DESTROYED).
        stockpile: Текущие запасы по классам ресурсов.
    """

    id: str
    x: int
    y: int
    faction: str
    capacity: float
    supply_radius: float
    protection: float
    state: int = NODE_OPERATIONAL
    stockpile: Dict[str, float] = field(default_factory=dict)


@dataclass
class Route:
    """
    Маршрут снабжения между двумя узлами.

    Attributes:
        id: Уникальный идентификатор маршрута.
        from_node: ID узла отправления.
        to_node: ID узла назначения.
        route_type: Тип дороги (ROUTE_DIRT/HIGHWAY/FIELD).
        throughput: Пропускная способность.
        wear: Текущий износ маршрута [0, 1].
        repair_difficulty: Сложность ремонта.
        length: Длина маршрута в условных единицах.
    """

    id: str
    from_node: str
    to_node: str
    route_type: int = ROUTE_DIRT
    throughput: float = 1.0
    wear: float = 0.0
    repair_difficulty: float = 1.0
    length: float = 1.0


@dataclass
class Vehicle:
    """
    Транспортное средство.

    Attributes:
        id: Уникальный идентификатор транспорта.
        type_id: Тип транспорта (ключ из vehicle_defs).
        state: Состояние (VEHICLE_OK/DAMAGED/BROKEN).
        wear: Текущий износ [0, 1].
        repair_ticks_left: Оставшиеся тики до завершения ремонта.
        assigned_convoy: ID назначенного конвоя или None.
    """

    id: int
    type_id: str
    state: int = VEHICLE_OK
    wear: float = 0.0
    repair_ticks_left: int = 0
    assigned_convoy: Optional[str] = None


@dataclass
class UnitSupply:
    """
    Снабжение подразделения.

    Хранит нормы потребления, фактические запасы, счётчики
    дней дефицита и доступность источника воды.

    Attributes:
        unit_idx: Индекс подразделения в WorldState.
        norm: Нормы потребления по классам ресурсов.
        actual: Фактические запасы по классам ресурсов.
        deficit_days: Счётчики дней дефицита по классам.
        water_source_available: Доступность местного источника воды.
    """

    unit_idx: int
    norm: Dict[str, float] = field(default_factory=dict)
    actual: Dict[str, float] = field(default_factory=dict)
    deficit_days: Dict[str, int] = field(default_factory=dict)
    water_source_available: bool = True


@dataclass
class Convoy:
    """
    Конвой снабжения.

    Attributes:
        id: Уникальный идентификатор конвоя.
        vehicle_type: Тип используемого транспорта.
        resource_class: Класс перевозимого ресурса.
        amount: Количество ресурса.
        route_id: ID маршрута следования.
        origin_node: ID узла отправления.
        dest_node: ID узла назначения.
        departure_tick: Тик отправления.
        eta_tick: Тик предполагаемого прибытия.
        lost: Флаг потери конвоя.
        spoiled: Доля испорченного груза [0, 1].
        vehicle_ids: Список ID задействованных транспортных средств.
    """

    id: str
    vehicle_type: str
    resource_class: str
    amount: float
    route_id: str
    origin_node: str
    dest_node: str
    departure_tick: int
    eta_tick: int
    lost: bool = False
    spoiled: float = 0.0
    vehicle_ids: List[int] = field(default_factory=list)


class LogisticsState:
    """
    Контейнер логистических данных мира.

    Хранит определения ресурсов, транспорта, операций, настройки
    неопределённости, конфигурации конвоев и маршрутов, списки
    баз, складов, маршрутов, транспорта, конвоев, снабжение
    подразделений и состояние активных операций.

    Поддерживает сериализацию в словарь и десериализацию из
    словаря для системы сохранений.
    """

    def __init__(self):
        """Инициализирует пустое логистическое состояние."""
        self.resource_defs: Dict[str, dict] = {}
        self.vehicle_defs: Dict[str, dict] = {}
        self.operation_defs: Dict[str, dict] = {}
        self.uncertainty: Dict[str, float] = {}
        self.convoy_config: Dict[str, float] = {}
        self.route_config: Dict[str, float] = {}
        self.distribution_config: Dict[str, float] = {}
        self.bases: List[SupplyBase] = []
        self.depots: List[ForwardDepot] = []
        self.routes: List[Route] = []
        self.vehicles: List[Vehicle] = []
        self.convoys: List[Convoy] = []
        self.unit_supply: Dict[int, UnitSupply] = {}
        self.operation_counters: Dict[int, Dict[str, int]] = {}
        self.daily_operation_counts: Dict[int, Dict[str, int]] = {}
        self.active_operation_effects: Dict[int, Dict[str, float]] = {}
        self.effect_expiry: Dict[int, Dict[str, int]] = {}

    def to_dict(self) -> dict:
        """
        Сериализует логистическое состояние в словарь.

        Преобразует все датаклассы через vars(), ключи unit_supply
        приводятся к строкам для совместимости с JSON.

        Returns:
            dict: Полная сериализованная копия состояния.
        """
        return {
            "resource_defs": self.resource_defs,
            "vehicle_defs": self.vehicle_defs,
            "operation_defs": self.operation_defs,
            "uncertainty": self.uncertainty,
            "convoy_config": self.convoy_config,
            "route_config": self.route_config,
            "distribution_config": self.distribution_config,
            "bases": [vars(b) for b in self.bases],
            "depots": [vars(d) for d in self.depots],
            "routes": [vars(r) for r in self.routes],
            "vehicles": [vars(v) for v in self.vehicles],
            "convoys": [vars(c) for c in self.convoys],
            "unit_supply": {
                str(k): vars(v) for k, v in self.unit_supply.items()
            },
            "operation_counters": self.operation_counters,
            "daily_operation_counts": self.daily_operation_counts,
            "active_operation_effects": self.active_operation_effects,
            "effect_expiry": self.effect_expiry,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LogisticsState":
        """
        Восстанавливает логистическое состояние из словаря.

        Создаёт новый экземпляр LogisticsState и заполняет его
        данными из словаря. Отсутствующие ключи заменяются
        пустыми значениями. Ключи unit_supply преобразуются
        обратно в int.

        Args:
            data: Словарь с сериализованными данными.

        Returns:
            LogisticsState: Восстановленное состояние.
        """
        ls = cls()
        ls.resource_defs = data.get("resource_defs", {}) or {}
        ls.vehicle_defs = data.get("vehicle_defs", {}) or {}
        ls.operation_defs = data.get("operation_defs", {}) or {}
        ls.uncertainty = data.get("uncertainty", {}) or {}
        ls.convoy_config = data.get("convoy_config", {}) or {}
        ls.route_config = data.get("route_config", {}) or {}
        ls.distribution_config = data.get("distribution_config", {}) or {}
        ls.bases = [
            SupplyBase(**b) for b in data.get("bases", []) or []
        ]
        ls.depots = [
            ForwardDepot(**d) for d in data.get("depots", []) or []
        ]
        ls.routes = [
            Route(**r) for r in data.get("routes", []) or []
        ]
        ls.vehicles = [
            Vehicle(**v) for v in data.get("vehicles", []) or []
        ]
        ls.convoys = [
            Convoy(**c) for c in data.get("convoys", []) or []
        ]
        ls.unit_supply = {
            int(k): UnitSupply(**v)
            for k, v in (data.get("unit_supply", {}) or {}).items()
        }
        ls.operation_counters = data.get("operation_counters", {}) or {}
        ls.daily_operation_counts = (
            data.get("daily_operation_counts", {}) or {}
        )
        ls.active_operation_effects = (
            data.get("active_operation_effects", {}) or {}
        )
        ls.effect_expiry = data.get("effect_expiry", {}) or {}
        return ls


def load_logistics_config(
    path: str = "configs/content/logistics.json",
) -> dict:
    """
    Загружает конфигурацию логистики из JSON-файла.

    Читает configs/content/logistics.json через безопасный
    загрузчик. При отсутствии файла или ошибке парсинга
    возвращает пустой словарь.

    Args:
        path: Путь к JSON-файлу конфигурации логистики.

    Returns:
        dict: Конфигурация логистики или пустой словарь.
    """
    return load_json(path, {}) or {}


def load_logistics_state(block: dict, state) -> LogisticsState:
    """
    Загружает логистическое состояние из блока сценария.

    Читает глобальную конфигурацию из logistics.json, затем
    применяет данные из блока сценария: базы, склады, маршруты,
    транспорт и начальное снабжение подразделений. Для каждого
    военного подразделения создаётся UnitSupply с начальными
    запасами из блока и флагом доступности воды.

    Args:
        block: Блок logistics из JSON-сценария.
        state: Состояние игрового мира (WorldState).

    Returns:
        LogisticsState: Заполненное логистическое состояние.
    """
    ls = LogisticsState()
    config = load_logistics_config()
    ls.resource_defs = config.get("resource_classes", {}) or {}
    ls.vehicle_defs = config.get("vehicle_types", {}) or {}
    ls.operation_defs = config.get("operations", {}) or {}
    ls.uncertainty = config.get("uncertainty", {}) or {}
    ls.convoy_config = config.get("convoy_config", {}) or {}
    ls.route_config = config.get("route_config", {}) or {}
    ls.distribution_config = config.get("distribution_config", {}) or {}
    default_water = block.get("default_water_source", True)
    for b_data in block.get("bases", []):
        ls.bases.append(
            SupplyBase(
                id=b_data["id"],
                x=int(b_data["x"]),
                y=int(b_data["y"]),
                faction=b_data.get("faction", "player"),
                classes=b_data.get("classes", []),
                intake_rate=b_data.get("intake_rate", {}),
                supply_radius=float(b_data.get("supply_radius", 50.0)),
                stockpile=dict(b_data.get("stockpile", {})),
            )
        )
    for d_data in block.get("depots", []):
        ls.depots.append(
            ForwardDepot(
                id=d_data["id"],
                x=int(d_data["x"]),
                y=int(d_data["y"]),
                faction=d_data.get("faction", "player"),
                capacity=float(d_data.get("capacity", 1000.0)),
                supply_radius=float(d_data.get("supply_radius", 20.0)),
                protection=float(d_data.get("protection", 0.0)),
                stockpile=dict(d_data.get("stockpile", {})),
            )
        )
    for r_data in block.get("routes", []):
        ls.routes.append(
            Route(
                id=r_data["id"],
                from_node=r_data["from_node"],
                to_node=r_data["to_node"],
                route_type=r_data.get("route_type", ROUTE_DIRT),
                throughput=float(r_data.get("throughput", 1.0)),
                wear=float(r_data.get("wear", 0.0)),
                repair_difficulty=float(
                    r_data.get("repair_difficulty", 1.0)
                ),
                length=float(r_data.get("length", 1.0)),
            )
        )
    vid = 0
    for v_data in block.get("vehicles", []):
        v_type = v_data.get("type", "truck")
        count = int(v_data.get("count", 1))
        for _ in range(count):
            ls.vehicles.append(Vehicle(id=vid, type_id=v_type))
            vid += 1
    initial_supply = block.get("initial_unit_supply", {})
    for idx in range(state.count):
        cfg = state.class_configs[state.class_ids[idx]]
        if cfg.class_name != "military_unit":
            continue
        unit = UnitSupply(
            unit_idx=idx,
            actual=dict(initial_supply),
            water_source_available=default_water,
        )
        ls.unit_supply[idx] = unit
    logger.info(
        "Логистическое состояние загружено: баз=%d, складов=%d, "
        "маршрутов=%d, транспорта=%d, подразделений=%d",
        len(ls.bases),
        len(ls.depots),
        len(ls.routes),
        len(ls.vehicles),
        len(ls.unit_supply),
    )
    return ls


class LogisticsSystem:
    """
    Логистическая система игрового мира.

    Рассчитывает нормы потребления, управляет запасами на базах
    и складах, распределяет ресурсы по подразделениям, обрабатывает
    конвои и логистические операции. Учитывает модификаторы черт
    персонажа для снабжения, потерь при casualties и шума докладов
    через функции из core.traits.

    Attributes:
        state: Состояние игрового мира (WorldState).
        ls: Логистическое состояние (LogisticsState).
        app: Экземпляр приложения для доступа к чертам персонажа.
        last_day: Последний обработанный игровой день.
    """

    def __init__(self, state, ls: LogisticsState, app=None):
        """
        Инициализирует логистическую систему и сразу считает нормы.

        Args:
            state: Состояние игрового мира.
            ls: Логистическое состояние.
            app: Экземпляр приложения для доступа к чертам.
        """
        self.state = state
        self.ls = ls
        self.app = app
        self.last_day = 0
        self._update_norms()
        logger.info("LogisticsSystem инициализирована")

    def tick(self, dt_hours: float, day: int):
        """
        Выполняет один шаг логистики.

        Обрабатывает конвои и ремонт транспорта каждый вызов.
        При смене дня дополнительно применяет поступление ресурсов,
        пассивное потребление, пересчёт норм, распределение по
        подразделениям, обновление счётчиков дефицита и истечение
        эффектов операций.

        Args:
            dt_hours: Длительность шага в часах.
            day: Текущий игровой день.
        """
        self._process_convoys()
        self._process_vehicle_repairs()
        if day != self.last_day:
            self._apply_daily_intake()
            self._apply_daily_passive_consumption()
            self._update_norms()
            self._distribute_to_units()
            self._update_deficit_counters()
            self._expire_operation_effects()
            self.last_day = day
            logger.debug("Логистика: обработан день %d", day)

    def _update_norms(self):
        """
        Пересчитывает нормы потребления для всех подразделений.

        Для каждого военного подразделения вычисляет норму по
        каждому классу ресурсов на основе численности (U_manpower),
        количества техники (U_tanks, U_sp_guns, U_at_guns,
        U_artillery, U_mlrs) и параметров из resource_defs.
        """
        st = self.state
        for idx, supply in self.ls.unit_supply.items():
            if idx >= st.count:
                continue
            cfg = st.class_configs[st.class_ids[idx]]
            if cfg.class_name != "military_unit":
                continue
            manpower = 0.0
            ch_man = cfg.voltage_layout.channel_index.get("U_manpower")
            if ch_man is not None:
                manpower = float(st.read_voltage(idx, "U_manpower"))
            equipment_count = 0.0
            for ch_name in (
                "U_tanks",
                "U_sp_guns",
                "U_at_guns",
                "U_artillery",
                "U_mlrs",
            ):
                ch_idx = cfg.voltage_layout.channel_index.get(ch_name)
                if ch_idx is not None:
                    equipment_count += float(
                        st.read_voltage(idx, ch_name)
                    )
            supply.norm = {}
            for cls, meta in self.ls.resource_defs.items():
                val = 0.0
                if "norm_per_manpower" in meta:
                    val += manpower * float(meta["norm_per_manpower"])
                if "norm_per_equipment" in meta:
                    val += equipment_count * float(
                        meta["norm_per_equipment"]
                    )
                if "norm_per_unit" in meta:
                    val += float(meta["norm_per_unit"])
                supply.norm[cls] = val

    def _apply_daily_intake(self):
        """
        Пополняет запасы на базах снабжения.

        Для каждой действующей базы добавляет ресурсы согласно
        intake_rate. Уничтоженные базы пропускаются.
        """
        for base in self.ls.bases:
            if base.state == NODE_DESTROYED:
                continue
            for cls, rate in base.intake_rate.items():
                current = base.stockpile.get(cls, 0.0)
                base.stockpile[cls] = current + float(rate)

    def _apply_daily_passive_consumption(self):
        """
        Списывает пассивное ежедневное потребление.

        Для каждого военного подразделения списывает ресурсы
        с флагом passive_daily: еда (norm_per_manpower),
        топливо для техники (norm_per_equipment, passive="tech"),
        вода при отсутствии местного источника (norm_per_unit,
        passive="conditional"). Запасы не уходят ниже нуля.
        """
        st = self.state
        for idx, supply in self.ls.unit_supply.items():
            if idx >= st.count:
                continue
            cfg = st.class_configs[st.class_ids[idx]]
            if cfg.class_name != "military_unit":
                continue
            manpower = 0.0
            ch_man = cfg.voltage_layout.channel_index.get("U_manpower")
            if ch_man is not None:
                manpower = float(st.read_voltage(idx, "U_manpower"))
            for cls, meta in self.ls.resource_defs.items():
                passive = meta.get("passive_daily", False)
                if not passive:
                    continue
                consume = 0.0
                if passive is True and "norm_per_manpower" in meta:
                    consume = manpower * float(meta["norm_per_manpower"])
                elif passive == "tech" and "norm_per_equipment" in meta:
                    for ch_name in (
                        "U_tanks",
                        "U_sp_guns",
                        "U_at_guns",
                        "U_artillery",
                        "U_mlrs",
                    ):
                        ch_idx = cfg.voltage_layout.channel_index.get(
                            ch_name
                        )
                        if ch_idx is not None:
                            consume += float(
                                st.read_voltage(idx, ch_name)
                            ) * float(meta["norm_per_equipment"])
                elif (
                    passive == "conditional"
                    and "norm_per_unit" in meta
                ):
                    if cls == "VI" and not supply.water_source_available:
                        consume = float(meta["norm_per_unit"])
                if consume > 0:
                    current = supply.actual.get(cls, 0.0)
                    supply.actual[cls] = max(0.0, current - consume)

    def _distribute_to_units(self):
        """
        Распределяет ресурсы со складов и баз по подразделениям.

        Для каждого подразделения и каждого класса ресурсов
        вычисляет дефицит относительно нормы (с учётом черты
        снабжения), затем последовательно запрашивает ресурсы
        сначала у ближайших складов, затем у баз в радиусе
        снабжения. Расстояние вычисляется по манхэттенской метрике.
        """
        st = self.state
        trait_mult = get_supply_modifier(self.app) if self.app else 1.0
        for idx, supply in self.ls.unit_supply.items():
            if idx >= st.count:
                continue
            ux = float(st.coords[idx, 0])
            uy = float(st.coords[idx, 1])
            for cls in supply.norm.keys():
                needed = supply.norm[cls] * trait_mult
                current = supply.actual.get(cls, 0.0)
                deficit = max(0.0, needed - current)
                if deficit <= 0:
                    continue
                delivered = 0.0
                for depot in self.ls.depots:
                    if depot.state == NODE_DESTROYED:
                        continue
                    dist = abs(depot.x - ux) + abs(depot.y - uy)
                    if dist <= depot.supply_radius:
                        available = depot.stockpile.get(cls, 0.0)
                        take = min(available, deficit - delivered)
                        if take > 0:
                            depot.stockpile[cls] -= take
                            delivered += take
                    if delivered >= deficit:
                        break
                if delivered < deficit:
                    for base in self.ls.bases:
                        if base.state == NODE_DESTROYED:
                            continue
                        dist = abs(base.x - ux) + abs(base.y - uy)
                        if dist <= base.supply_radius:
                            available = base.stockpile.get(cls, 0.0)
                            take = min(available, deficit - delivered)
                            if take > 0:
                                base.stockpile[cls] -= take
                                delivered += take
                        if delivered >= deficit:
                            break
                supply.actual[cls] = current + delivered

    def _update_deficit_counters(self):
        """
        Обновляет счётчики дней дефицита.

        Если фактический запас ниже 90% нормы, счётчик дней
        дефицита увеличивается. При достаточном запасе сбрасывается.
        """
        for supply in self.ls.unit_supply.values():
            for cls, norm_val in supply.norm.items():
                actual_val = supply.actual.get(cls, 0.0)
                if actual_val < norm_val * 0.9:
                    supply.deficit_days[cls] = (
                        supply.deficit_days.get(cls, 0) + 1
                    )
                else:
                    supply.deficit_days[cls] = 0

    def _process_convoys(self):
        """
        Обрабатывает движение конвоев и доставку грузов.

        Проверяет прибытие конвоев по eta_tick. Прибыший конвой
        разгружается на целевой склад (с учётом порчи), транспорт
        освобождается и получает износ. В пути конвой может
        накапливать порчу с вероятностью spoilage_chance.
        """
        st = self.state
        spoilage_chance = self.ls.uncertainty.get("spoilage_chance", 0.0)
        arrived = []
        for convoy in self.ls.convoys:
            if convoy.lost:
                continue
            if st.current_tick >= convoy.eta_tick:
                dest_node = None
                for d in self.ls.depots:
                    if d.id == convoy.dest_node:
                        dest_node = d
                        break
                if dest_node and dest_node.state != NODE_DESTROYED:
                    amount = convoy.amount * (1.0 - convoy.spoiled)
                    current = dest_node.stockpile.get(
                        convoy.resource_class, 0.0
                    )
                    dest_node.stockpile[convoy.resource_class] = (
                        current + amount
                    )
                    logger.info(
                        "Логистика: конвой %s прибыл в %s, "
                        "доставлено %.1f %s",
                        convoy.id,
                        convoy.dest_node,
                        amount,
                        convoy.resource_class,
                    )
                for vid in convoy.vehicle_ids:
                    for v in self.ls.vehicles:
                        if v.id == vid:
                            v.assigned_convoy = None
                            v.wear += 0.1
                            if v.wear > 1.0:
                                v.state = VEHICLE_BROKEN
                arrived.append(convoy)
            else:
                if random.random() < spoilage_chance:
                    convoy.spoiled = min(1.0, convoy.spoiled + 0.1)
        for c in arrived:
            self.ls.convoys.remove(c)

    def _process_vehicle_repairs(self):
        """
        Обрабатывает ремонт транспорта.

        Уменьшает repair_ticks_left для сломанного транспорта.
        При достижении нуля восстанавливает состояние в OK
        и сбрасывает износ.
        """
        for v in self.ls.vehicles:
            if v.state == VEHICLE_BROKEN:
                v.repair_ticks_left -= 1
                if v.repair_ticks_left <= 0:
                    v.state = VEHICLE_OK
                    v.wear = 0.0
                    logger.info(
                        "Логистика: транспорт %d отремонтирован", v.id
                    )

    def dispatch_convoy(
        self,
        origin_node_id: str,
        dest_node_id: str,
        resource_class: str,
        amount: float,
        vehicle_type: str = "truck",
    ) -> bool:
        """
        Формирует и отправляет конвой.

        Проверяет наличие узла отправления, достаточность запасов,
        доступность транспорта и существование маршрута. При успехе
        списывает ресурсы, назначает транспорт, вычисляет ETA
        на основе типа дороги и создаёт объект Convoy.

        Args:
            origin_node_id: ID узла отправления.
            dest_node_id: ID узла назначения.
            resource_class: Класс перевозимого ресурса.
            amount: Количество ресурса.
            vehicle_type: Тип транспорта (по умолчанию "truck").

        Returns:
            bool: True, если конвой успешно отправлен.
        """
        st = self.state
        ls = self.ls
        origin_node = None
        for b in ls.bases:
            if b.id == origin_node_id:
                origin_node = b
                break
        if not origin_node or origin_node.state == NODE_DESTROYED:
            return False
        available = origin_node.stockpile.get(resource_class, 0.0)
        if available < amount:
            return False
        vehicles = []
        for v in ls.vehicles:
            if (
                v.type_id == vehicle_type
                and v.state == VEHICLE_OK
                and v.assigned_convoy is None
            ):
                vehicles.append(v)
                if len(vehicles) >= 2:
                    break
        if not vehicles:
            return False
        route = None
        for r in ls.routes:
            if r.from_node == origin_node_id and r.to_node == dest_node_id:
                route = r
                break
        if not route:
            return False
        origin_node.stockpile[resource_class] -= amount
        speed_map = {
            ROUTE_HIGHWAY: 2.0,
            ROUTE_DIRT: 1.0,
            ROUTE_FIELD: 0.5,
        }
        speed = speed_map.get(route.route_type, 1.0)
        eta_ticks = max(1, int(route.length / speed))
        convoy_id = f"convoy_{st.current_tick}_{len(ls.convoys)}"
        convoy = Convoy(
            id=convoy_id,
            vehicle_type=vehicle_type,
            resource_class=resource_class,
            amount=amount,
            route_id=route.id,
            origin_node=origin_node_id,
            dest_node=dest_node_id,
            departure_tick=st.current_tick,
            eta_tick=st.current_tick + eta_ticks,
            vehicle_ids=[v.id for v in vehicles],
        )
        for v in vehicles:
            v.assigned_convoy = convoy_id
        ls.convoys.append(convoy)
        logger.info(
            "Логистика: конвой %s отправлен %s -> %s (%s: %.1f)",
            convoy_id,
            origin_node_id,
            dest_node_id,
            resource_class,
            amount,
        )
        return True

    def execute_operation(
        self, unit_idx: int, op_id: str, amount: int = 1
    ) -> bool:
        """
        Выполняет логистическую операцию.

        Проверяет существование операции и достаточность ресурсов.
        Списывает стоимость, обновляет счётчики операций, вычисляет
        эффект с убывающей отдачей и устанавливает временный эффект
        с истечением по duration_ticks.

        Args:
            unit_idx: Индекс подразделения.
            op_id: Идентификатор операции.
            amount: Количество применений операции.

        Returns:
            bool: True, если операция успешно выполнена.
        """
        ls = self.ls
        op_def = ls.operation_defs.get(op_id)
        if op_def is None:
            return False
        supply = ls.unit_supply.get(unit_idx)
        if supply is None:
            return False
        cost = op_def.get("cost", {})
        for cls, req in cost.items():
            total_req = float(req) * amount
            if supply.actual.get(cls, 0.0) < total_req:
                return False
        for cls, req in cost.items():
            total_req = float(req) * amount
            supply.actual[cls] -= total_req
        if unit_idx not in ls.operation_counters:
            ls.operation_counters[unit_idx] = {}
        ls.operation_counters[unit_idx][op_id] = (
            ls.operation_counters[unit_idx].get(op_id, 0) + amount
        )
        if unit_idx not in ls.daily_operation_counts:
            ls.daily_operation_counts[unit_idx] = {}
        ls.daily_operation_counts[unit_idx][op_id] = (
            ls.daily_operation_counts[unit_idx].get(op_id, 0) + 1
        )
        effect_type = op_def.get("effect_type")
        duration = op_def.get("duration_ticks", 24)
        diminishing = op_def.get("diminishing", [1.0])
        count = ls.operation_counters[unit_idx][op_id]
        effect_val = 0.0
        if count <= len(diminishing):
            effect_val = diminishing[count - 1] * amount
        else:
            effect_val = diminishing[-1] * amount
        if unit_idx not in ls.active_operation_effects:
            ls.active_operation_effects[unit_idx] = {}
        ls.active_operation_effects[unit_idx][effect_type] = (
            ls.active_operation_effects[unit_idx].get(effect_type, 0.0)
            + effect_val
        )
        if unit_idx not in ls.effect_expiry:
            ls.effect_expiry[unit_idx] = {}
        ls.effect_expiry[unit_idx][effect_type] = (
            self.state.current_tick + duration
        )
        logger.info(
            "Логистика: операция %s выполнена для юнита %d "
            "(эффект %.2f)",
            op_id,
            unit_idx,
            effect_val,
        )
        return True

    def _expire_operation_effects(self):
        """
        Сбрасывает истёкшие эффекты операций.

        Проверяет effect_expiry для всех подразделений. Удаляет
        истёкшие эффекты из active_operation_effects и effect_expiry.
        При полном отсутствии эффектов очищает также счётчики операций.
        """
        st = self.state
        expired_units = []
        for unit_idx, effects in list(self.ls.effect_expiry.items()):
            for effect_type, expiry_tick in list(effects.items()):
                if st.current_tick >= expiry_tick:
                    del effects[effect_type]
                    if unit_idx in self.ls.active_operation_effects:
                        self.ls.active_operation_effects[unit_idx].pop(
                            effect_type, None
                        )
            if not effects:
                expired_units.append(unit_idx)
        for u in expired_units:
            del self.ls.effect_expiry[u]
            self.ls.active_operation_effects.pop(u, None)
            self.ls.operation_counters.pop(u, None)
            self.ls.daily_operation_counts.pop(u, None)

    def get_ammo_modifier(self, idx: int) -> float:
        """
        Возвращает модификатор боеприпасов для боевой мощи.

        Вычисляет отношение фактических запасов боеприпасов (класс II)
        к норме. Результат линейно интерполируется в диапазон [0.5, 1.2].
        При отсутствии снабжения или нулевой норме возвращает 1.0.

        Args:
            idx: Индекс подразделения.

        Returns:
            float: Модификатор боеприпасов [0.5, 1.2].
        """
        supply = self.ls.unit_supply.get(idx)
        if supply is None:
            return 1.0
        norm = supply.norm.get("II", 0.0)
        actual = supply.actual.get("II", 0.0)
        if norm <= 0:
            return 1.0
        ratio = actual / norm
        return max(0.5, min(1.2, 0.5 + 0.7 * ratio))

    def get_defense_modifier(self, idx: int) -> float:
        """
        Возвращает модификатор обороны от активных операций.

        Суммирует эффекты defense и active_defense из
        active_operation_effects подразделения.

        Args:
            idx: Индекс подразделения.

        Returns:
            float: Суммарный модификатор обороны.
        """
        effects = self.ls.active_operation_effects.get(idx, {})
        return effects.get("defense", 0.0) + effects.get(
            "active_defense", 0.0
        )

    def get_offense_modifier(self, idx: int) -> float:
        """
        Возвращает модификатор атаки от активных операций.

        Читает эффект offense из active_operation_effects подразделения.

        Args:
            idx: Индекс подразделения.

        Returns:
            float: Модификатор атаки.
        """
        effects = self.ls.active_operation_effects.get(idx, {})
        return effects.get("offense", 0.0)

    def get_displayed_stockpile(
        self, node, rng=None
    ) -> Dict[str, float]:
        """
        Возвращает запасы узла с учётом погрешности разведки.

        Копирует реальные запасы и применяет случайный шум
        в пределах display_error из uncertainty. Без rng
        возвращает точные значения. Модификатор шума может
        зависеть от черты персонажа через report_noise_mult.

        Args:
            node: Узел снабжения (SupplyBase или ForwardDepot).
            rng: Генератор случайных чисел или None.

        Returns:
            dict: Отображаемые запасы по классам ресурсов.
        """
        displayed = dict(node.stockpile)
        if rng is None:
            return displayed
        error_margin = self.ls.uncertainty.get("display_error", 0.1)
        noise_mult = (
            get_report_noise_modifier(self.app) if self.app else 1.0
        )
        effective_error = error_margin * noise_mult
        for cls in displayed:
            noise = rng.uniform(-effective_error, effective_error)
            displayed[cls] = max(0.0, displayed[cls] * (1.0 + noise))
        return displayed

    def consume_combat(self, idx: int, amount: float):
        """
        Расходует боеприпасы и топливо пропорционально интенсивности боя.

        Списывает класс II (боеприпасы) и класс III (топливо)
        из фактических запасов подразделения. Без пополнения
        запас падает, модификатор боеприпасов снижается и боевая
        мощь деградирует — логистика становится критичной.

        Args:
            idx: Индекс подразделения.
            amount: Интенсивность боя (основа для расчёта расхода).
        """
        supply = self.ls.unit_supply.get(idx)
        if supply is None or amount <= 0:
            return
        ammo = amount * 0.5
        fuel = amount * 0.15
        for cls, delta in (("II", ammo), ("III", fuel)):
            cur = supply.actual.get(cls, 0.0)
            if cur > 0:
                supply.actual[cls] = max(0.0, cur - delta)