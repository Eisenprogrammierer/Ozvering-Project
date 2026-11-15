from dataclasses import dataclass, field


@dataclass(frozen=True)
class Work:
    amount: float
    form: str = "force"
    payload: tuple = ()
    duration: float = 1.0


@dataclass
class WorkReport:
    """Отчёт получателя о работе: единый контракт ``receive``.

    Заменяет плоский dict, который возвращал ``default_receive`` и
    обработчики арены. Поля:

    * ``accepted`` — принял ли получатель работу (форма совместима);
    * ``success`` — успешен ли исход (если исход вообще есть);
    * ``amount`` — объём работы (для сверки);
    * ``efficiency`` — КПД канала/контекста (0..1);
    * ``stored`` — сколько фактически попало в ``E`` получателя;
    * ``loss`` — сколько потеряно на входе (не дошло до цели);
    * ``entropy`` — сколько ушло в энтропию/отходы;
    * ``effect`` — что получатель сделал с работой (например,
      ``{"legitimacy": -0.035, "fear": 0.01}``); это не словарь
      «эффектов работы», а результат обработчика;
    * ``projections`` — что из этого следует записать в состояние
      (обычно ``{"self": {...}, "target": {...}}`` для ``effects.py``);
    * ``payload`` — что было доставлено (эхо, если получатель его прочитал);
    * ``trace`` — свободная трассировка (в фазе 3 — ``WorkTrace``);
    * ``extra`` — дополнительные поля обработчика (например,
      ``{"was_open": True}``).

    Для обратной совместимости с dict-контрактом ``WorkReport``
    поддерживает ``report["accepted"]``, ``report.get("accepted")``,
    ``"accepted" in report``, ``report.keys()``/``items()``/``values()``.
    ``extra`` при этом раскрывается в плоском доступе: старый код,
    читавший ``result["custom"]``, продолжает работать.

    ``stored + loss + entropy == amount`` с точностью до округления —
    инвариант, который проверяют тесты.
    """

    accepted: bool = False
    success: bool = False
    amount: float = 0.0
    efficiency: float = 0.0
    stored: float = 0.0
    loss: float = 0.0
    entropy: float = 0.0
    effect: dict = field(default_factory=dict)
    projections: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    trace: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def as_dict(self):
        data = {
            "accepted": bool(self.accepted),
            "success": bool(self.success),
            "amount": round(float(self.amount), 6),
            "efficiency": round(float(self.efficiency), 6),
            "stored": round(float(self.stored), 6),
            "loss": round(float(self.loss), 6),
            "entropy": round(float(self.entropy), 6),
            "effect": dict(self.effect or {}),
            "projections": dict(self.projections or {}),
            "payload": dict(self.payload or {}),
            "trace": dict(self.trace or {}),
        }
        for key, value in (self.extra or {}).items():
            data.setdefault(str(key), value)
        return data

    def _flat(self):
        return self.as_dict()

    def __getitem__(self, key):
        data = self._flat()
        if key in data:
            return data[key]
        raise KeyError(key)

    def get(self, key, default=None):
        return self._flat().get(key, default)

    def __contains__(self, key):
        return key in self._flat()

    def __iter__(self):
        return iter(self._flat())

    def __len__(self):
        return len(self._flat())

    def keys(self):
        return self._flat().keys()

    def values(self):
        return self._flat().values()

    def items(self):
        return self._flat().items()


@dataclass(frozen=True)
class Action:
    kind: str = "REST"
    form: str = "force"
    fraction: float = 0.0
    target: str = "opponent"
    duration: float = 1.0


@dataclass(frozen=True)
class Observation:
    self_force: float
    self_energy: float
    self_max_force: float
    self_max_energy: float
    opponent_force: float
    opponent_energy: float
    opponent_max_force: float
    opponent_max_energy: float
    opponent_pressure: float
    opponent_open: bool
    time: float
    forms: tuple = ("force",)
    opponent_defense: str = ""
    self_health: float = 100.0
    self_max_health: float = 100.0
    self_sickness: float = 0.0
    opponent_health: float = 100.0
    opponent_max_health: float = 100.0
    opponent_sickness: float = 0.0
    self_wound: float = 0.0
    opponent_wound: float = 0.0
    env_pressure: float = 0.0
    env_season: float = 1.0
    env_window: float = 0.0
    opponent_confidence: float = 1.0
    opponent_weak_point: float = 0.0
    self_busy: float = 0.0
    opponent_busy: float = 0.0
    opponent_pending_form: str = ""
    opponent_pending_fraction: float = 0.0


@dataclass(frozen=True)
class Transition:
    observation: Observation
    action: Action
    reward: float
    next_observation: Observation
    done: bool
    next_actions: tuple = ()
    info: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CampaignAction:
    """Действие кампанейного среза (проблема №6 готовности к обучению).

    Кампания живёт на дневном такте `WorldEngine`, а не на секундном тике
    арены, поэтому использует отдельный тип действия поверх того же
    контракта Work/Action/Observation/Transition:

    - ``kind`` — идентификатор действия из конфига мира (``inspect``,
      ``reform``, …) либо служебный ``END_DAY`` (ход мира и дневной срез);
    - ``target`` — id узла-цели (пусто для self-действий и ``END_DAY``);
    - ``form``/``fraction`` — зарезервированы под будущую проекцию
      кампанейных ресурсов на каналы ядра; в текущем MVP не используются.
    """

    kind: str = "END_DAY"
    target: str = ""
    form: str = ""
    fraction: float = 0.0


@dataclass(frozen=True)
class CampaignObservation:
    """Наблюдение игрока-автомата в кампании (плоское, нормированное).

    Все величины приведены к [0, 1] там, где это возможно, чтобы тот же
    пайплайн признаков, что и на арене, мог работать без правок. Поля
    соответствуют открытым вопросам §7 (28–31): распад организации и
    потеря должности наблюдаются через ``power``/``cohesion``/``standing``
    и флаги ``collapsed``/``dismissed``; финалы бесконечного сценария
    помечены как ``truncated``-состояния среды, а не объективной победы.
    """

    day: int = 1
    total_days: int = 1
    actions_left: int = 0
    actions_per_day: int = 1
    health: float = 100.0
    max_health: float = 100.0
    sickness: float = 0.0
    wound: float = 0.0
    alive: bool = True
    influence: float = 0.0
    favor: float = 0.0
    evidence: float = 0.0
    standing: float = 0.0
    authority: float = 0.0
    power: float = 0.0
    wealth: float = 0.0
    legitimacy: float = 0.0
    cohesion: float = 0.0
    reach: float = 0.0
    capacity: float = 0.0
    attached: bool = False
    finished: bool = False
    outcome: str = ""
    collapsed: bool = False
    dismissed: bool = False
    time: float = 0.0
    extra: dict = field(default_factory=dict)
    energy: float = -1.0
    max_energy: float = 0.0
    force: float = -1.0
    max_force: float = 0.0
