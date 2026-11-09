"""Составные автоматы: композиция 4-2-1 (WORLD_CORE_MODEL §2.7, §7.1 №7–8).

`Automaton` — атомарная единица. Организация, фракция, сложный предмет —
это автомат из автоматов. Модуль задаёт ровно те правила, которых не
хватало открытым вопросам §7.1:

* **что агрегирует родитель** — две разные вещи, которые нельзя путать:
  ёмкость (`F/E` складываются, потому что это ресурсы) и качество
  (целостность/здоровье — взвешенное среднее нормированных долей);
* **как дочерние автоматы получают работу** — `distribute()` делит
  `Work.amount` между листьями, не создавая работу из воздуха; отчёт
  аддитивен: `loss + entropy + stored == amount`;
* **что значит «часть автомата»** — вложенность произвольная, но
  ациклическая и с ограничением глубины; дубликаты id и циклы отвергаются;
* **персистентность** — `composite_state()`/`load_composite_state()`
  сохраняют состояние оболочки и детей, не пытаясь сериализовать
  обработчики (они остаются runtime-функциями, как и в `Automaton`).

Кампанийная проекция иерархии органов (`campaign/fractal.py`) остаётся
своей моделью; `campaign.fractal.organ_composite()` строит из неё
`CompositeAutomaton` как диагностическое представление, а не заменяет
`OrganRuntime`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import (
    HEALTH_MAX,
    Automaton,
    conversion_report,
)
from .types import Work

MAX_COMPOSITE_DEPTH = 8
DISTRIBUTION_STRATEGIES = (
    "proportional",
    "even",
    "weakest",
    "strongest",
    "round_robin",
)
DEFAULT_DISTRIBUTION_STRATEGY = "proportional"


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp01(value):
    return max(0.0, min(1.0, _as_float(value)))


def automaton_state(unit):
    """Состояние атомарного автомата для снимка составного дерева."""
    return {
        "id": unit.id,
        "force": float(unit.force),
        "max_force": float(unit.max_force),
        "energy": float(unit.energy),
        "max_energy": float(unit.max_energy),
        "health": float(unit.health),
        "max_health": float(unit.max_health),
        "sickness": float(unit.sickness),
        "wound": float(unit.wound),
        "state": dict(unit.state),
    }


def load_automaton_state(unit, payload):
    """Восстановить изменяемые поля автомата из снимка.

    Обработчики, навыки и отношения не трогаются: это runtime-конфигурация,
    а не состояние. Значения клампятся в допустимые диапазоны.
    """
    if not isinstance(payload, dict):
        return unit
    unit.force = max(
        0.0,
        min(
            float(unit.max_force),
            _as_float(payload.get("force"), unit.force),
        ),
    )
    unit.max_force = max(
        1e-9,
        _as_float(payload.get("max_force"), unit.max_force),
    )
    unit.force = min(unit.force, unit.max_force)
    unit.energy = max(
        0.0,
        min(
            float(unit.max_energy),
            _as_float(payload.get("energy"), unit.energy),
        ),
    )
    unit.max_energy = max(
        1e-9, _as_float(payload.get("max_energy"), unit.max_energy)
    )
    unit.energy = min(unit.energy, unit.max_energy)
    unit.max_health = max(
        1e-9, _as_float(payload.get("max_health"), unit.max_health)
    )
    unit.health = max(
        0.0,
        min(unit.max_health, _as_float(payload.get("health"), unit.health)),
    )
    unit.sickness = _clamp01(
        _as_float(payload.get("sickness"), unit.sickness)
    )
    unit.wound = _clamp01(_as_float(payload.get("wound"), unit.wound))
    if isinstance(payload.get("state"), dict):
        unit.state = dict(payload["state"])
    return unit


@dataclass
class CompositeAutomaton(Automaton):
    """Автомат, который содержит дочерние автоматы.

    Оболочка (`force/energy/health`) — это «штаб» составного автомата.
    Агрегаты по всему дереву доступны через `total_force`,
    `aggregate_force_ratio` и `aggregate_state()`. Работа, пришедшая в
    `receive()`, по умолчанию уходит листьям через `distribute()`.
    """

    children: dict = field(default_factory=dict)
    max_depth: int = MAX_COMPOSITE_DEPTH

    def __post_init__(self):
        self.children = dict(self.children or {})
        self._composite_parent = None

    def iter_tree(self):
        """Обойти узел и всех потомков в детерминированном порядке."""
        yield self
        for child in self.children.values():
            if isinstance(child, CompositeAutomaton):
                yield from child.iter_tree()
            else:
                yield child

    def leaves(self):
        """Листья дерева: единицы, которые реально принимают работу."""
        if not self.children:
            yield self
            return
        for child in self.children.values():
            if isinstance(child, CompositeAutomaton):
                yield from child.leaves()
            else:
                yield child

    def part(self, node_id):
        """Найти узел дерева по id (оболочка или потомок)."""
        node_id = str(node_id)
        for node in self.iter_tree():
            if node.id == node_id:
                return node
        return None

    def height(self):
        """Высота поддерева: 0 у листа, 1 у родителя листа."""
        if not self.children:
            return 0
        return 1 + max(
            child.height() if isinstance(child, CompositeAutomaton) else 0
            for child in self.children.values()
        )

    def path_depth(self):
        """Сколько родителей над этим узлом (у корня 0)."""
        depth = 0
        node = getattr(self, "_composite_parent", None)
        seen = set()
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            depth += 1
            node = getattr(node, "_composite_parent", None)
        return depth

    def add_child(self, child, *, replace=False):
        """Добавить дочерний автомат.

        Отвергает дубликаты id во всём дереве, самого себя и циклы, а также
        превышение `max_depth`. Если ребёнок уже привязан к другому
        родителю, он сначала открепляется от него.
        """
        if not isinstance(child, Automaton):
            raise TypeError("child must be an Automaton")
        if not str(child.id):
            raise ValueError("child id must be non-empty")
        if child is self:
            raise ValueError("automaton cannot contain itself")
        existing = self.children.get(child.id)
        if existing is not None and existing is not child:
            if not replace:
                raise ValueError("duplicate child id: %s" % child.id)
            self.remove_child(child.id)
        if any(node.id == child.id for node in self.iter_tree()):
            raise ValueError("duplicate child id: %s" % child.id)
        child_height = (
            child.height() if isinstance(child, CompositeAutomaton) else 0
        )
        if isinstance(child, CompositeAutomaton) and self in child.iter_tree():
            raise ValueError("composite cycle: %s" % child.id)
        root = self
        while getattr(root, "_composite_parent", None) is not None:
            root = root._composite_parent
        limit = getattr(root, "max_depth", self.max_depth)
        if self.path_depth() + 1 + child_height > limit:
            raise ValueError("composite depth exceeds %d" % limit)
        old_parent = getattr(child, "_composite_parent", None)
        if old_parent is not None and old_parent is not self:
            old_parent.remove_child(child.id)
        self.children[child.id] = child
        child._composite_parent = self
        return child

    def remove_child(self, node_id):
        """Открепить ребёнка по id; вернуть его или `None`."""
        node_id = str(node_id)
        child = self.children.pop(node_id, None)
        if child is not None:
            child._composite_parent = None
        return child

    def clear_children(self):
        for child in self.children.values():
            child._composite_parent = None
        self.children.clear()

    def _parts(self):
        """Все узлы дерева, включая оболочки вложенных составных."""
        yield self
        for child in self.children.values():
            if isinstance(child, CompositeAutomaton):
                yield from child._parts()
            else:
                yield child

    @property
    def total_force(self):
        """Суммарная ёмкость `F`: силы частей складываются."""
        return sum(max(0.0, node.force) for node in self._parts())

    @property
    def total_max_force(self):
        return sum(max(0.0, node.max_force) for node in self._parts())

    @property
    def total_energy(self):
        """Суммарная ёмкость `E`: энергия частей складывается."""
        return sum(max(0.0, node.energy) for node in self._parts())

    @property
    def total_max_energy(self):
        return sum(max(0.0, node.max_energy) for node in self._parts())

    @property
    def aggregate_force_ratio(self):
        maximum = self.total_max_force
        if maximum <= 0.0:
            return 0.0
        return _clamp01(self.total_force / maximum)

    @property
    def aggregate_energy_ratio(self):
        maximum = self.total_max_energy
        if maximum <= 0.0:
            return 0.0
        return _clamp01(self.total_energy / maximum)

    @property
    def aggregate_health_ratio(self):
        """Здоровье — качество, а не ёмкость: взвешенное среднее.

        Вес — структурная масса `max_force`, поэтому большой, но раненый
        орган влияет сильнее маленького. Суммировать `health` нельзя: у
        каждого автомата свой потолок `max_health`.
        """
        parts = list(self._parts())
        weights = sum(max(0.0, node.max_force) for node in parts)
        if weights <= 0.0:
            return 0.0
        return _clamp01(
            sum(
                _clamp01(node.health_ratio) * max(0.0, node.max_force)
                for node in parts
            )
            / weights
        )

    @property
    def worst_sickness(self):
        return max((node.sickness for node in self._parts()), default=0.0)

    @property
    def worst_wound(self):
        return max((node.wound for node in self._parts()), default=0.0)

    @property
    def is_dead(self):
        """Составной автомат мёртв, когда не осталось ни одной живой части."""
        return not any(node.health > 0.0 for node in self._parts())

    @property
    def is_sick(self):
        return self.worst_sickness > 0.0

    @property
    def is_wounded(self):
        return self.worst_wound > 0.0

    def force_throughput(self):
        """Пропускная способность всего дерева, а не только оболочки."""
        return self.total_force

    def skill(self, form):
        """Навык дерева — среднее по листьям, взвешенное их массой.

        Оболочки составных автоматов не работают сами: они маршрутизуют.
        Поэтому навык берётся у листьев, а пустой составной автомат
        наследует обычную семантику `Automaton.skill`.
        """
        if not self.children:
            return super().skill(form)
        leaves = list(self.leaves())
        weights = sum(max(0.0, node.max_force) for node in leaves)
        if weights <= 0.0:
            return 0.0
        return sum(
            node.skill(form) * max(0.0, node.max_force)
            for node in leaves
        ) / weights

    def work_effectiveness(self):
        if not self.children:
            return super().work_effectiveness()
        leaves = list(self.leaves())
        weights = sum(max(0.0, node.max_force) for node in leaves)
        if weights <= 0.0:
            return 0.0
        return sum(
            node.work_effectiveness() * max(0.0, node.max_force)
            for node in leaves
        ) / weights

    def attack_effectiveness(self):
        if not self.children:
            return super().attack_effectiveness()
        leaves = list(self.leaves())
        weights = sum(max(0.0, node.max_force) for node in leaves)
        if weights <= 0.0:
            return 0.0
        return sum(
            node.attack_effectiveness() * max(0.0, node.max_force)
            for node in leaves
        ) / weights

    def can_receive(self, form):
        return form in self.inputs or any(
            child.can_receive(form) for child in self.children.values()
        )

    def resistance(self, form):
        if not self.can_receive(form):
            return 1.0
        return min(
            1.0,
            0.65 * self.aggregate_force_ratio
            + 0.35 * self.aggregate_energy_ratio,
        )

    def aggregate_state(self):
        """Публичный срез агрегатов для UI, политик и диагностики."""
        return {
            "id": self.id,
            "force": self.total_force,
            "max_force": self.total_max_force,
            "force_ratio": self.aggregate_force_ratio,
            "energy": self.total_energy,
            "max_energy": self.total_max_energy,
            "energy_ratio": self.aggregate_energy_ratio,
            "health": self.aggregate_health_ratio * HEALTH_MAX,
            "max_health": HEALTH_MAX,
            "health_ratio": self.aggregate_health_ratio,
            "sickness": self.worst_sickness,
            "wound": self.worst_wound,
            "alive": not self.is_dead,
            "parts": sum(1 for _ in self._parts()),
            "leaves": sum(1 for _ in self.leaves()),
            "height": self.height(),
        }

    def distribution_strategy(self):
        value = self.state.get(
            "distribution_strategy", DEFAULT_DISTRIBUTION_STRATEGY
        )
        if value not in DISTRIBUTION_STRATEGIES:
            return DEFAULT_DISTRIBUTION_STRATEGY
        return value

    def set_distribution_strategy(self, strategy):
        if strategy not in DISTRIBUTION_STRATEGIES:
            raise ValueError(
                "unknown distribution strategy: %s" % strategy
            )
        self.state["distribution_strategy"] = strategy
        return strategy

    def _distribution_targets(self, form, recursive=True, include_self=False):
        if recursive:
            pool = [node for node in self.leaves() if node is not self]
            if include_self:
                pool.insert(0, self)
        else:
            pool = list(self.children.values())
            if include_self or not pool:
                pool.insert(0, self)
        targets = [node for node in pool if node.can_receive(form)]
        unique = []
        seen = set()
        for node in targets:
            if id(node) in seen:
                continue
            seen.add(id(node))
            unique.append(node)
        return unique

    def _shares(self, targets, amount, strategy):
        amount = max(0.0, float(amount))
        if not targets or amount <= 0.0:
            return []
        if strategy in ("weakest", "strongest", "round_robin"):
            if strategy == "weakest":
                target = min(
                    targets, key=lambda node: (node.force_ratio, node.id)
                )
            elif strategy == "strongest":
                target = max(
                    targets, key=lambda node: (node.force_ratio, node.id)
                )
            else:
                cursor = int(
                    self.state.get("distribution_cursor", 0) or 0
                ) % len(targets)
                target = targets[cursor]
                self.state["distribution_cursor"] = (cursor + 1) % len(
                    targets
                )
            return [(target, amount)]
        if strategy == "even":
            weights = [1.0] * len(targets)
        else:
            weights = [max(1e-9, node.max_force) for node in targets]
        total = sum(weights)
        if total <= 0.0:
            weights = [1.0] * len(targets)
            total = float(len(targets))
        shares = []
        remaining = amount
        for index, (node, weight) in enumerate(zip(targets, weights)):
            if index == len(targets) - 1:
                share = remaining
            else:
                share = amount * weight / total
                remaining -= share
            shares.append((node, max(0.0, share)))
        return shares

    def distribute(
        self,
        work,
        *,
        strategy=None,
        source=None,
        world=None,
        include_self=False,
        recursive=True,
    ):
        """Разделить работу между частями и собрать аддитивный отчёт.

        `Work.amount` не дублируется: сумма долей равна исходному объёму.
        `recursive=True` направляет работу листьям, а вложенные составные
        автоматы исполняют роль маршрутизаторов. `recursive=False` отдаёт
        долю прямым детям (полезно для пошагового распределения).
        """
        amount = max(0.0, _as_float(getattr(work, "amount", 0.0)))
        strategy = strategy or self.distribution_strategy()
        targets = self._distribution_targets(
            work.form, recursive=recursive, include_self=include_self
        )
        if not targets:
            report = conversion_report(amount, work.form, 0.0, 0.0)
            report.update(
                {
                    "accepted": False,
                    "success": False,
                    "energy": 0.0,
                    "force": 0.0,
                    "pressure": 0.0,
                    "strategy": strategy,
                    "shares": {},
                }
            )
            return report
        shares = self._shares(targets, amount, strategy)
        reports = {}
        stored_total = 0.0
        loss_total = 0.0
        entropy_total = 0.0
        accepted_any = False
        pressure_total = 0.0
        energy_total = 0.0
        force_total = 0.0
        for node, share in shares:
            child_work = Work(
                amount=share,
                form=work.form,
                payload=getattr(work, "payload", ()),
                duration=getattr(work, "duration", 1.0),
            )
            if node is self:
                shell_handler = self.handlers.get(work.form)
                if shell_handler is not None:
                    child_report = shell_handler(
                        self, child_work, source, world
                    )
                else:
                    child_report = self.default_receive(child_work)
            else:
                child_report = node.receive(
                    child_work, source=source, world=world
                )
            reports[node.id] = dict(child_report)
            stored_total += _as_float(child_report.get("stored"), 0.0)
            loss_total += _as_float(child_report.get("loss"), 0.0)
            entropy_total += _as_float(child_report.get("entropy"), 0.0)
            accepted_any = accepted_any or bool(
                child_report.get("accepted")
            )
            pressure_total += _as_float(
                child_report.get("pressure"), 0.0
            )
            energy_total += _as_float(child_report.get("energy"), 0.0)
            force_total += _as_float(child_report.get("force"), 0.0)
        arrived = stored_total + entropy_total
        return {
            "amount": amount,
            "arrived": arrived,
            "stored": stored_total,
            "loss": loss_total,
            "entropy": entropy_total,
            "efficiency": (arrived / amount) if amount > 0.0 else 0.0,
            "accepted": accepted_any,
            "success": accepted_any,
            "energy": energy_total,
            "force": force_total,
            "pressure": pressure_total,
            "strategy": strategy,
            "shares": {
                node.id: {
                    "amount": share,
                    "report": reports[node.id],
                }
                for node, share in shares
            },
        }

    def receive(self, work, source=None, world=None):
        """Принять работу: явный обработчик → дети → оболочка.

        Если на оболочке задан обработчик канала, он имеет приоритет.
        Иначе работа распределяется по листьям. Если ни один ребёнок не
        принимает форму, оболочка обрабатывает её сама (штаб берёт на себя
        то, что некому делегировать) либо отвергает как потерю.
        """
        handler = self.handlers.get(work.form)
        if handler is not None:
            return handler(self, work, source, world)
        if not self.children:
            return self.default_receive(work)
        targets = self._distribution_targets(
            work.form, recursive=True, include_self=False
        )
        if targets:
            return self.distribute(work, source=source, world=world)
        return self.default_receive(work)

    def apply_force_damage(self, damage, target_id=None):
        """Урон по составному автомату.

        С `target_id` урон уходит конкретной части. Без цели он
        распределяется между живыми листьями пропорционально их текущей
        `F`: атака на организацию бьёт по её частям, а не по абстрактному
        агрегату. Возвращает суммарные `(absorbed, overflow, health_damage)`.
        """
        damage = max(0.0, float(damage))
        if target_id is not None:
            node = self.part(target_id)
            if node is not None and node is not self:
                return node.apply_force_damage(damage)
        if not self.children:
            return super().apply_force_damage(damage)
        leaves = [node for node in self.leaves() if node.health > 0.0]
        if not leaves:
            return super().apply_force_damage(damage)
        weights = [max(0.0, node.force) for node in leaves]
        total = sum(weights)
        if total <= 0.0:
            weights = [max(0.0, node.max_force) for node in leaves]
            total = sum(weights)
        if total <= 0.0:
            weights = [1.0] * len(leaves)
            total = float(len(leaves))
        absorbed = overflow = health_damage = 0.0
        remaining = damage
        for index, node in enumerate(leaves):
            if index == len(leaves) - 1:
                share = remaining
            else:
                share = damage * weights[index] / total
                remaining -= share
            if share <= 0.0:
                continue
            part_absorbed, part_overflow, part_health = (
                node.apply_force_damage(share)
            )
            absorbed += part_absorbed
            overflow += part_overflow
            health_damage += part_health
        return absorbed, overflow, health_damage

    def composite_state(self):
        return {
            "id": self.id,
            "force": float(self.force),
            "max_force": float(self.max_force),
            "energy": float(self.energy),
            "max_energy": float(self.max_energy),
            "health": float(self.health),
            "max_health": float(self.max_health),
            "sickness": float(self.sickness),
            "wound": float(self.wound),
            "state": dict(self.state),
            "children": [
                child.composite_state()
                if isinstance(child, CompositeAutomaton)
                else automaton_state(child)
                for child in self.children.values()
            ],
        }

    def load_composite_state(self, payload):
        """Восстановить оболочку и известных детей; вернуть список id."""
        restored = []
        if not isinstance(payload, dict):
            return restored
        load_automaton_state(self, payload)
        for child_payload in payload.get("children") or ():
            if not isinstance(child_payload, dict):
                continue
            child_id = str(child_payload.get("id") or "")
            node = self.children.get(child_id)
            if node is None:
                continue
            if isinstance(node, CompositeAutomaton):
                restored.extend(node.load_composite_state(child_payload))
            else:
                load_automaton_state(node, child_payload)
            restored.append(child_id)
        return restored

    def clone_for_tick(self):
        """Копия дерева для одновременного разрешения такта."""
        clone = super().clone_for_tick()
        clone.children = {
            child_id: child.clone_for_tick()
            for child_id, child in self.children.items()
        }
        for child in clone.children.values():
            child._composite_parent = clone
        clone._composite_parent = None
        return clone
