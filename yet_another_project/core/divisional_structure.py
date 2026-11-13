"""
core/divisional_structure.py

Виртуальная иерархическая структура подразделения.

Дивизия остаётся одной сущностью в WorldState, но внутри неё
живёт массив виртуальных рот, батальонов и полков.
При атаке на конкретный сектор пересчитываются только роты
этого сектора, затем агрегируются обратно в дивизию.
Это даёт тактическую глубину без ущерба производительности.

Модуль предоставляет датаклассы Company, Battalion, Regiment
и DivisionalStructure для представления виртуальной иерархии,
а также перечисление Sector для обозначения секторов расположения
рот относительно центра дивизии.

DivisionalStructure поддерживает инициализацию из пресета с
равномерным распределением личного состава по ротам, применение
потерь к ротам указанного сектора с учётом усталости и морали,
агрегацию состояния рот обратно в параметры дивизии для обновления
WorldState и формирование отчёта по секторам для UI.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import random


class Sector(Enum):
    """
    Сектор расположения роты относительно центра дивизии.

    Определяет пять секторов: фронт, левый фланг, правый фланг,
    тыл и центр. Используется для таргетирования потерь и
    формирования отчётов по секторам.

    Attributes:
        FRONT: Фронтальный сектор.
        LEFT: Левый фланг.
        RIGHT: Правый фланг.
        REAR: Тыловой сектор.
        CENTER: Центральный сектор (резерв).
    """

    FRONT = "front"
    LEFT = "left"
    RIGHT = "right"
    REAR = "rear"
    CENTER = "center"


@dataclass
class Company:
    """
    Виртуальная рота внутри дивизии.

    Не является отдельной сущностью в WorldState, но участвует
    в тактических расчётах. Хранит личный состав, мораль,
    технику, усталость, потери и флаг вовлечённости в бой.

    Attributes:
        id: Уникальный идентификатор роты.
        manpower: Текущая численность личного состава.
        max_manpower: Штатная численность личного состава.
        morale: Уровень морали [0.0, 1.0].
        equipment: Словарь техники {тип: количество}.
        sector: Сектор расположения роты.
        fatigue: Уровень усталости [0.0, 1.0].
        casualties: Накопленные потери личного состава.
        is_engaged: Флаг участия в боестолкновении.
    """

    id: str
    manpower: float
    max_manpower: float
    morale: float
    equipment: Dict[str, float] = field(default_factory=dict)
    sector: Sector = Sector.FRONT
    fatigue: float = 0.0
    casualties: float = 0.0
    is_engaged: bool = False

    @property
    def strength_ratio(self) -> float:
        """
        Возвращает отношение текущего личного состава к штатному.

        Returns:
            float: Отношение manpower / max_manpower.
                Минимум 0.0 при max_manpower <= 0.
        """
        return self.manpower / max(1.0, self.max_manpower)

    @property
    def is_effective(self) -> bool:
        """
        Проверяет боеспособность роты.

        Рота считается боеспособной, если её strength_ratio
        превышает 0.3 (30% штатного состава).

        Returns:
            bool: True, если рота боеспособна.
        """
        return self.strength_ratio > 0.3


@dataclass
class Battalion:
    """
    Виртуальный батальон, содержащий роты.

    Является промежуточным уровнем иерархии между полком и ротой.
    Хранит список подчинённых рот и собственный сектор.

    Attributes:
        id: Уникальный идентификатор батальона.
        companies: Список рот батальона.
        sector: Сектор расположения батальона.
    """

    id: str
    companies: List[Company] = field(default_factory=list)
    sector: Sector = Sector.FRONT


@dataclass
class Regiment:
    """
    Виртуальный полк, содержащий батальоны.

    Является верхним уровнем иерархии внутри дивизии.
    Хранит список подчинённых батальонов и собственный сектор.

    Attributes:
        id: Уникальный идентификатор полка.
        battalions: Список батальонов полка.
        sector: Сектор расположения полка.
    """

    id: str
    battalions: List[Battalion] = field(default_factory=list)
    sector: Sector = Sector.FRONT


@dataclass
class DivisionalStructure:
    """
    Виртуальная структура дивизии.

    Хранит иерархию полков, батальонов и рот. При атаке на
    сектор пересчитывает только роты этого сектора, затем
    агрегирует результаты обратно в дивизию. Поддерживает
    инициализацию из пресета, применение секторных потерь,
    агрегацию состояния и формирование секторных отчётов.

    Attributes:
        division_entity_id: ID сущности дивизии в WorldState.
        regiments: Список полков дивизии.
        sector_distribution: Распределение сил по секторам.
    """

    division_entity_id: str
    regiments: List[Regiment] = field(default_factory=list)
    sector_distribution: Dict[Sector, float] = field(
        default_factory=lambda: {
            Sector.FRONT: 0.4,
            Sector.LEFT: 0.2,
            Sector.RIGHT: 0.2,
            Sector.REAR: 0.1,
            Sector.CENTER: 0.1,
        }
    )

    def initialize_from_preset(
        self,
        total_manpower: float,
        num_regiments: int = 3,
        num_battalions_per_regiment: int = 3,
        num_companies_per_battalion: int = 3,
        equipment_config: Optional[Dict[str, float]] = None,
    ):
        """
        Инициализирует структуру дивизии из пресета.

        Создаёт иерархию полков, батальонов и рот. Личный состав
        распределяется равномерно по всем ротам. Каждая рота
        получает копию equipment_config. Сектора назначаются
        автоматически через _assign_sector.

        Args:
            total_manpower: Общая численность личного состава дивизии.
            num_regiments: Количество полков (по умолчанию 3).
            num_battalions_per_regiment: Количество батальонов в полку
                (по умолчанию 3).
            num_companies_per_battalion: Количество рот в батальоне
                (по умолчанию 3).
            equipment_config: Начальная конфигурация техники для каждой
                роты. Если None, роты создаются без техники.
        """
        self.regiments = []
        equipment_config = equipment_config or {}
        total_companies = (
            num_regiments
            * num_battalions_per_regiment
            * num_companies_per_battalion
        )
        company_manpower = (
            total_manpower / total_companies if total_companies > 0 else 0.0
        )
        for r_idx in range(num_regiments):
            regiment = Regiment(
                id=f"полк_{r_idx + 1}",
                sector=self._assign_sector(r_idx, num_regiments),
            )
            for b_idx in range(num_battalions_per_regiment):
                battalion = Battalion(
                    id=f"батальон_{r_idx + 1}_{b_idx + 1}",
                    sector=self._assign_sector(
                        b_idx, num_battalions_per_regiment
                    ),
                )
                for c_idx in range(num_companies_per_battalion):
                    company = Company(
                        id=(
                            f"рота_{r_idx + 1}_{b_idx + 1}_{c_idx + 1}"
                        ),
                        manpower=company_manpower,
                        max_manpower=company_manpower,
                        morale=0.7,
                        equipment=dict(equipment_config),
                        sector=battalion.sector,
                    )
                    battalion.companies.append(company)
                regiment.battalions.append(battalion)
            self.regiments.append(regiment)

    def _assign_sector(self, index: int, total: int) -> Sector:
        """
        Назначает сектор по индексу элемента в группе.

        При одном элементе возвращает CENTER. Первый элемент
        получает FRONT, последний — REAR. Элементы в первой
        половине получают LEFT, во второй — RIGHT.

        Args:
            index: Индекс элемента в группе (от 0).
            total: Общее количество элементов в группе.

        Returns:
            Sector: Назначенный сектор.
        """
        if total == 1:
            return Sector.CENTER
        if index == 0:
            return Sector.FRONT
        if index == total - 1:
            return Sector.REAR
        if index < total // 2:
            return Sector.LEFT
        return Sector.RIGHT

    def get_companies_in_sector(self, sector: Sector) -> List[Company]:
        """
        Возвращает все роты указанного сектора.

        Обходит всю иерархию полков и батальонов, собирая роты,
        чей сектор совпадает с запрошенным.

        Args:
            sector: Запрашиваемый сектор.

        Returns:
            list[Company]: Список рот в указанном секторе.
        """
        companies = []
        for regiment in self.regiments:
            for battalion in regiment.battalions:
                for company in battalion.companies:
                    if company.sector == sector:
                        companies.append(company)
        return companies

    def apply_sector_losses(
        self,
        sector: Sector,
        total_loss: float,
        morale_penalty: float = 0.0,
        equipment_loss_ratio: float = 0.0,
        rng: Optional[random.Random] = None,
    ) -> Dict[str, float]:
        """
        Применяет потери к ротам указанного сектора.

        Распределяет total_loss пропорционально численности каждой
        роты в секторе. Учитывает модификаторы усталости и морали:
        уставшие и деморализованные роты теряют больше. Потери
        ограничены 90% текущей численности роты. Снижает мораль
        и технику согласно переданным коэффициентам.

        Args:
            sector: Сектор, подвергающийся атаке.
            total_loss: Общие потери личного состава для распределения.
            morale_penalty: Штраф к морали каждой роты в секторе.
            equipment_loss_ratio: Доля потерь техники (0.0–1.0).
            rng: Генератор случайных чисел (зарезервирован).

        Returns:
            dict: Результаты применения потерь:
                - manpower_loss: Фактические потери личного состава.
                - morale_loss: Суммарное снижение морали.
                - equipment_loss: Потери техники по типам.
                - sector_companies_affected: Число затронутых рот.
        """
        if rng is None:
            rng = random.Random()
        sector_companies = self.get_companies_in_sector(sector)
        if not sector_companies:
            return {
                "manpower_loss": 0.0,
                "morale_loss": 0.0,
                "equipment_loss": {},
                "sector_companies_affected": 0,
            }
        total_sector_manpower = sum(c.manpower for c in sector_companies)
        if total_sector_manpower <= 0:
            return {
                "manpower_loss": 0.0,
                "morale_loss": 0.0,
                "equipment_loss": {},
                "sector_companies_affected": len(sector_companies),
            }
        actual_manpower_loss = 0.0
        actual_morale_loss = 0.0
        equipment_losses: Dict[str, float] = {}
        for company in sector_companies:
            company_ratio = company.manpower / total_sector_manpower
            company_loss = total_loss * company_ratio
            fatigue_mult = 1.0 + company.fatigue * 0.5
            morale_mult = 1.0 + (1.0 - company.morale) * 0.3
            actual_loss = company_loss * fatigue_mult * morale_mult
            actual_loss = min(actual_loss, company.manpower * 0.9)
            company.manpower -= actual_loss
            company.casualties += actual_loss
            company.morale = max(0.0, company.morale - morale_penalty)
            for equip_type, equip_amount in company.equipment.items():
                equip_loss = (
                    equip_amount * equipment_loss_ratio * company_ratio
                )
                company.equipment[equip_type] = max(
                    0.0, equip_amount - equip_loss
                )
                equipment_losses[equip_type] = (
                    equipment_losses.get(equip_type, 0.0) + equip_loss
                )
            actual_manpower_loss += actual_loss
            actual_morale_loss += morale_penalty * company_ratio
        return {
            "manpower_loss": actual_manpower_loss,
            "morale_loss": actual_morale_loss,
            "equipment_loss": equipment_losses,
            "sector_companies_affected": len(sector_companies),
        }

    def aggregate_to_division(self) -> Dict[str, float]:
        """
        Агрегирует состояние рот в параметры дивизии.

        Вызывается после тактических расчётов для обновления
        WorldState. Суммирует личный состав, потери и технику
        всех рот. Мораль вычисляется как средневзвешенная по
        численности. Подсчитывает число боеспособных рот.

        Returns:
            dict: Агрегированные параметры дивизии:
                - U_manpower: Общая численность личного состава.
                - U_casualties: Доля потерь от штатной численности.
                - morale: Средневзвешенная мораль.
                - equipment: Суммарная техника по типам.
                - effective_companies: Число боеспособных рот.
                - total_companies: Общее число рот.
        """
        total_manpower = 0.0
        total_max_manpower = 0.0
        total_casualties = 0.0
        total_morale_weighted = 0.0
        total_equipment: Dict[str, float] = {}
        effective_companies = 0
        total_companies = 0
        for regiment in self.regiments:
            for battalion in regiment.battalions:
                for company in battalion.companies:
                    total_manpower += company.manpower
                    total_max_manpower += company.max_manpower
                    total_casualties += company.casualties
                    total_morale_weighted += (
                        company.morale * company.manpower
                    )
                    if company.is_effective:
                        effective_companies += 1
                    total_companies += 1
                    for equip_type, equip_amount in company.equipment.items():
                        total_equipment[equip_type] = (
                            total_equipment.get(equip_type, 0.0)
                            + equip_amount
                        )
        avg_morale = (
            total_morale_weighted / max(1e-6, total_manpower)
        )
        return {
            "U_manpower": total_manpower,
            "U_casualties": (
                total_casualties / max(1.0, total_max_manpower)
            ),
            "morale": avg_morale,
            "equipment": total_equipment,
            "effective_companies": effective_companies,
            "total_companies": total_companies,
        }

    def get_sector_report(self) -> Dict[Sector, Dict[str, float]]:
        """
        Возвращает отчёт по секторам для UI.

        Для каждого сектора, содержащего хотя бы одну роту,
        вычисляет суммарную численность, соотношение сил,
        среднюю мораль и число боеспособных рот.

        Returns:
            dict[Sector, dict]: Отчёт по секторам. Каждый сектор
                содержит:
                - manpower: Суммарная численность.
                - strength_ratio: Отношение к штатной численности.
                - morale: Средняя мораль.
                - effective_companies: Число боеспособных рот.
                - total_companies: Общее число рот в секторе.
        """
        report = {}
        for sector in Sector:
            sector_companies = self.get_companies_in_sector(sector)
            if not sector_companies:
                continue
            total_manpower = sum(c.manpower for c in sector_companies)
            total_max = sum(c.max_manpower for c in sector_companies)
            avg_morale = (
                sum(c.morale for c in sector_companies)
                / len(sector_companies)
            )
            effective = sum(
                1 for c in sector_companies if c.is_effective
            )
            report[sector] = {
                "manpower": total_manpower,
                "strength_ratio": total_manpower / max(1.0, total_max),
                "morale": avg_morale,
                "effective_companies": effective,
                "total_companies": len(sector_companies),
            }
        return report