from dataclasses import dataclass, field


@dataclass(frozen=True)
class Work:
    amount: float
    form: str = "force"
    payload: tuple = ()
    duration: float = 1.0


@dataclass(frozen=True)
class Action:
    kind: str = "REST"
    form: str = "force"
    fraction: float = 0.0
    target: str = "opponent"


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
    # Ядро 4-2-1: E/F — те же шкалы, что у арены. Отрицательный сентинел
    # означает «поле не заполнено»; признаки тогда падают обратно на
    # actions_left/standing для старых конструкторов.
    energy: float = -1.0
    max_energy: float = 0.0
    force: float = -1.0
    max_force: float = 0.0
    # Состояние персонажа (health/sickness — то же ядро, что и на арене).
    health: float = 100.0
    max_health: float = 100.0
    sickness: float = 0.0
    alive: bool = True
    # Ресурсы позиции (легаси-шкалы как проекции ядра: F-канал позиции).
    influence: float = 0.0
    favor: float = 0.0
    evidence: float = 0.0
    standing: float = 0.0
    authority: float = 0.0
    # Статистика собственной организации (узел должности).
    power: float = 0.0
    wealth: float = 0.0
    legitimacy: float = 0.0
    cohesion: float = 0.0
    reach: float = 0.0
    capacity: float = 0.0
    # Признаки завершения сюжета.
    attached: bool = False
    finished: bool = False
    outcome: str = ""
    collapsed: bool = False
    dismissed: bool = False
    time: float = 0.0
    extra: dict = field(default_factory=dict)
