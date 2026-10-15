"""Ozvering-Project: модель конкуренции IPO-автоматов.

Полная документация механики, формулы и параметры — в docs/MODEL.md.
Кратко: сущности обладают двумя метриками (сила force — целевая функция,
энергия energy_pool — расходуемый запас, пополняемый потоком floor(sqrt(F)));
взаимодействие — передача работы; восприимчивость входа адресата описывается
порогами Шмитта с гистерезисом ON(F)/OFF(F); прибыль покоя логистическая с
потолком, растущим только от труда; поражение — по устойчивому доминированию.
Среда — всеобъемлющий IPO-автомат (суперсистема того же кодекса, см. раздел 13
docs/MODEL.md): её вход нагружается всякой передачей, открытое окно даёт
надбавку к отдаче адресанта, автономный доход ENV_INCOME поддерживает динамику.
Иерархия автоматов (раздел 14 MODEL.md): суперсистемы строятся композицией
Environment из нижестоящих автоматов (members) без новых переменных состояния;
выходы членов суммируются на вход суперсистемы, а её окно конъюнктуры
модулирует их отдачу — эмерджентность и самоподобие как свойства архитектуры.
Терминология нейтральна: один закон покрывает физическую, информационную и
экономическую конкуренцию и мирное сосуществование (работа = 0).
"""

import math
import random
import statistics


PARAMETERS = {
    "TYPES": ["FIRE", "WATER", "EARTH"],
    "P_BASE": 0.6,
    "K_MASS": 1.0,
    "K_TYPE": 0.8,
    "COST_FRACTION": 0.2,
    "ON_FRAC": 0.25,
    "ON_MIN": 6.0,
    "OFF_FRAC": 0.4,
    "MIN_OUTPUT": 2,
    "OPEN_TTL": 8,
    "GAIN_MAX": 1.2,
    "Y_SMALL": 0.05,
    "DECAY_ADOPT": 0.95,
    "RETALIATE_FRACTION": 0.5,
    "HOCK_FRACTION": 0.25,
    "OPTION_VALUE": 0.10,
    "K_EFFECT": 0.70,
    "L_BASE": 60,
    "L_STEP": 10,
    "MAX_REST_DELTA": 8,
    "STARVING_E": 2,
    "E_MAX_MULT": 3,
    "UPKEEP": 1,
    "MAX_WORK": 200,
    "BELIEF_NOISE": 2,
    "CAPTURE_RATIO": 1.5,
    "CAPTURE_STREAK": 20,
    "CAPTURE_FRAC": 0.10,
    "ENV_BONUS": 0.25,
    "ENV_INCOME": 2,
    "ENV_REST_CAP": 10.0,
}
"""Канонические значения калибровки модели; смысл каждого параметра — в docs/MODEL.md, раздел 8.

ENV_REST_CAP — предохранитель от долгого дрейфа среды: потолок покоя суперсистемы
растёт от чужого труда (Environment.receive_pressure), и без капа `rest_units`
уползал бы неограниченно, уводя порог Шмитта ON(F) вверх. Кап держит потолок
конечным (см. docs/MODEL.md, разделы 8 и 13)."""

globals().update(PARAMETERS)

MULT = {("WATER", "FIRE"): 3.0, ("FIRE", "EARTH"): 3.0, ("EARTH", "WATER"): 3.0}
"""Круговой контр-множитель типов: WATER > FIRE > EARTH > WATER (x3). Цикл симметричен,
ни один тип не доминирует архитектурно; тип входа — контекстная фаза (Agent.defense,
см. docs/MODEL.md §2), отдельной ротации нет."""

PROFILES = {
    # p — профильный параметр «догматичности» входа: множитель при DECAY_ADOPT.
    # p < 1: давление остывает быстрее (DECAY*p), нижний порог OFF(F) выше
    #        (OFF_FRAC/p) — окно открывается реже и живёт меньше; вход «догматичен»,
    #        устойчив к чужому напору, но сам требует большего собственного напора
    #        для вскрытия чужого окна через тот же закон.
    # p = 1: каноническая механика (прежние значения калибровки без изменений).
    "ZEALOT": 0.7,   # догматик: медленная ротация защиты, быстрое «заживление» входа
    "ORTHODOX": 0.85,
    "CANON": 1.0,    # базовый профиль == прежняя модель
    "PRAGMATIST": 1.15,
    "OPPORTUNIST": 1.3,  # оппортунист: быстрая ротация, вязкое давление (окна чаще/дольше)
}
"""Профильные классы автоматов: ОДИН параметр p, умножающий существующие константы
входа (DECAY_ADOPT и OFF_FRAC) — новых переменных состояния или метрик не вводится.
Смысл и обоснование достаточности IPO-архитектуры — docs/MODEL.md, раздел 2а."""

ACTIONS = [("REST", 0)] + [(t, w) for t in TYPES for w in [0.3, 0.7]]
"""Пространство действий автомата: покой либо передача типом с долей пула 0.3/0.7."""


def p_success(att_type, att_work, dfn_type, dfn_work):
    """Вероятность успешной передачи по логистике отношения мощностей
    (min(w_att, MAX_WORK)/max(w_def,1)) со штрафом K_TYPE, если защита
    адресата контрит тип атаки. Вход адресанта, тип энергии и количество
    работы — единственные определители вероятности (согласованная модель)."""
    mass = min(att_work, MAX_WORK) / max(dfn_work, 1)
    penalty = K_TYPE if MULT.get((dfn_type, att_type)) else 0.0
    logit = math.log(mass) * K_MASS - penalty
    return P_BASE / (1.0 + math.exp(-logit))


class Agent:
    """Базовый автомат на IPO-архитектуре (+BDI у персонажей).

    Компоненты IPO представлены единообразно, как части одного автомата:

      * ВХОД — ``beliefs`` (BDI-слой): оценки противника, собираемые ``sense()``;
        восприимчивость собственного входа адресата (пороги Шмитта) — поля
        ``w_adopt``, ``in_open``, ``open_timer``;
      * СОСТОЯНИЕ — ``state``: единственное хранилище внутреннего состояния
        автомата. В нём лежат обе метрики (``force`` — сила, целевая функция;
        ``energy_pool`` — энергия, расходуемый запас) и управляющие переменные
        (``defense``, ``last_act``, ``last_work``, ``w_adopt``, ``in_open``,
        ``open_timer``, ``rest_units``). Не объемлющая характеристика, а один
        из компонентов наравне с входом/выходом/обработчиками;
      * ОБРАБОТКА/ВЫХОД — методы-обработчики (``commit``, ``do_rest``,
        ``rotate_defense``, ``gain``, ``process_hit``, ``sense`` и т.д.).

    Обработчики читают и записывают ``state`` напрямую — Мили-подобная
    зависимость, но шире: состояние определяет не только выход, но и
    переходы и вид обработки. Именованные атрибуты (``force``, ``in_open``,
    ``last_act``, …) — представления полей ``state`` через ``@property``,
    поэтому внешний код и обработчики обращаются к ним как к обычным полям,
    а единым хранилищем остаётся ``state``. Метрики при этом не теряют
    статуса метрик: ``energy_pool`` пополняется потоком
    ``regen = floor(sqrt(F))`` с потолком ``E_MAX_MULT * regen``.
    """

    def __init__(self, defense=None, profile="CANON"):
        """profile — имя из PROFILES или вещественный p (см. docs/MODEL.md, раздел 2а).

        Профиль НЕ вводит новых переменных состояния: это единственный скаляр ``p``,
        модифицирующий ОБРАБОТКУ существующих IPO-компонентов — вход (пороги Шмитта:
        decay и нижний порог) и выход (тяжесть поражения при доминировании).
        Метрики force/energy_pool, их динамика и состав beliefs остаются прежними;
        профиль не наблюдается противником напрямую (частичная наблюдаемость).

        Аргумент ``defense`` сохранён ради обратной совместимости и игнорируется:
        тип входа больше не хранится, а выводится из контекста (см. property
        ``defense``): конверсия типов энергии не нужна.
        """
        self.profile = profile if isinstance(profile, str) else round(float(profile), 4)
        self.p = PROFILES[profile] if isinstance(profile, str) else float(profile)
        self.reset_state()

    def reset_state(self):
        """Сброс физического состояния к началу партии (метрики и наблюдения).

        Физическое состояние (сила, пул, вход Шмитта, ``beliefs``) — состояние
        ПАРТИИ, а не ресурс, переносимый между партиями. Сброс гарантирует
        равные стартовые условия каждой партии: иначе проигравший начинал бы
        следующую партию ослабленным (сила у дна), а победитель — усиленным,
        и исход зависел бы от ПОРЯДКА партий, а не от стратегии. Обучение
        (Q-таблица ``RLAgent``) сюда не входит и переносится отдельно.
        """
        # Единое хранилище внутреннего состояния автомата (IPO-компонент
        # «состояние»): обе метрики и управляющие переменные. Обработчики
        # читают/пишут поля напрямую через представления-свойства ниже.
        self.state = {
            "force": 10,
            "energy_pool": 3,
            "rest_units": 0.0,
            # Поля "defense" в составе состояния НЕТ: рецептивный тип входа —
            # не хранимая/ротируемая метка, а функция контекста (см. property
            # ``defense``). Тип энергии определяется контекстом её сообщения
            # между автоматами, поэтому конвертировать типы не требуется.
            "last_act": "REST",
            "last_work": 0,
            "w_adopt": 0.0,
            "in_open": False,
            "open_timer": 0,
        }
        self.beliefs = {"opp_energy": 3, "opp_defense": None,
                        "opp_last_act": "REST", "opp_last_work": 0,
                        "opp_force": 10, "opp_w_adopt": 0.0, "opp_in_open": False,
                        "opp_type_guess": None, "opp_ctx_base": None}

    # --- Представления полей ``state`` (единое хранилище внутреннего состояния).
    # Позволяют обработчикам и внешнему коду работать с полями как с обычными
    # атрибутами, тогда как источником истины остаётся ``state``.
    @property
    def force(self):
        """Сила — метрика (целевая функция автомата)."""
        return self.state["force"]

    @force.setter
    def force(self, value):
        self.state["force"] = value

    @property
    def energy_pool(self):
        """Энергия — метрика (расходуемый запас)."""
        return self.state["energy_pool"]

    @energy_pool.setter
    def energy_pool(self, value):
        self.state["energy_pool"] = value

    @property
    def rest_units(self):
        """Труд, накопленный отдыхом (расширяет потолок покоя)."""
        return self.state["rest_units"]

    @rest_units.setter
    def rest_units(self, value):
        self.state["rest_units"] = value

    @property
    def defense(self):
        """Рецептивный тип входа — КОНТЕКСТ обмена, а не хранимая метка.

        Тип энергии не является «валютой» автомата, которую нужно конвертировать:
        это фаза самого автомата в его цикле, выводимая из контекста —
        напора на входе (``w_adopt``), состояния окна (``in_open``),
        наполненности пула и **выходной фазы** данного такта (текущее действие
        ``last_act``). Так «тип» определяется выходом и входом адресата,
        обработчиками (``p_success``/``_apply_transfer``) и состояниями — как
        того требует архитектура. Выходная фаза адресата одновременна нашему
        ходу и потому противнику не наблюдается: это и есть остаточная
        неопределённость типа (``context_base`` видна, ``hidden`` — нет).
        Ротация защиты как независимой метки упразднена (``rotate_defense``
        оставлен no-op ради совместимости API).
        """
        hidden = TYPES.index(self.last_act) if self.last_act in TYPES else 0
        return self.receptive_type(self.energy_pool, self.w_adopt,
                                   self.in_open, self.force, hidden)

    @staticmethod
    def context_base(energy_pool, w_adopt, in_open, force):
        """Наблюдаемая часть контекста входа: 0/1/2 (истощён/наполнен/на порогe).

        Из неё выводится рецептивный тип вместе со скрытой выходной фазой
        (``hidden``). Именно эта часть известна противнику (по его наблюдениям).
        """
        full = energy_pool / max(1.0, E_MAX_MULT * max(1, math.floor(math.sqrt(max(1, force)))))
        press = w_adopt / max(1.0, max(ON_MIN, ON_FRAC * force))
        if in_open or press >= 1.0:
            return 2
        if full >= 0.5:
            return 1
        return 0

    @staticmethod
    def receptive_type(energy_pool, w_adopt, in_open, force, hidden=0):
        """Единый закон вывода рецептивного типа из контекста (см. ``defense``).

        ``context_base`` (наблюдаемо) + ``hidden`` (выходная фаза адресата,
        не наблюдаема противником при одновременных ходах) по модулю 3.
        """
        base = Agent.context_base(energy_pool, w_adopt, in_open, force)
        return TYPES[(base + int(hidden)) % 3]


    @property
    def last_act(self):
        """Последнее совершённое действие (для расчёта p_success)."""
        return self.state["last_act"]

    @last_act.setter
    def last_act(self, value):
        self.state["last_act"] = value

    @property
    def last_work(self):
        """Работа последнего действия (для расчёта p_success)."""
        return self.state["last_work"]

    @last_work.setter
    def last_work(self, value):
        self.state["last_work"] = value

    @property
    def w_adopt(self):
        """Накопленное давление на входе (пороги Шмитта)."""
        return self.state["w_adopt"]

    @w_adopt.setter
    def w_adopt(self, value):
        self.state["w_adopt"] = value

    @property
    def in_open(self):
        """Признак открытого окна восприимчивости входа."""
        return self.state["in_open"]

    @in_open.setter
    def in_open(self, value):
        self.state["in_open"] = value

    @property
    def open_timer(self):
        """Остаток времени жизни открытого окна (такты)."""
        return self.state["open_timer"]

    @open_timer.setter
    def open_timer(self, value):
        self.state["open_timer"] = value

    @property
    def rest_ceiling(self):
        """Потолок покоя L(t) = L_BASE + L_STEP * rest_units.

        Работает побудителем баланса: ``rest_units`` растут только от труда
        (реально полученная сила при успешных передачах), поэтому бездельник
        стагнирует на статичном потолке и отстаёт от работающих."""
        return L_BASE + L_STEP * self.rest_units

    def rest_gain(self):
        """Логистическая прибыль покоя: dF/dt = r * E * (1 - E/L).

        Ускорение внизу, убывание у потолка, ноль выше него. Вершина логистики
        превышает UPKEEP — иначе равновесный покой убыточен и среда вымирает
        к F=1 (показано диагностикой)."""
        e = self.force - UPKEEP
        l = self.rest_ceiling
        return MAX_REST_DELTA * (e / l) * (1.0 - e / l)

    def do_rest(self, chosen=True):
        """Применение покоя; потолок покоя превзойти отдыхом нельзя — только трудом.

        Args:
            chosen: True — осознанный отдых (выбор стратегии или рефлекс голода),
                полная прибыль; False — режим покоя (работа отвергнута расчётом,
                голод ещё не наступил), вдвое слабее. Иначе пассивное ожидание
                доминирует над трудом."""
        gain = self.rest_gain() if chosen else 0.5 * self.rest_gain()
        self.force = min(self.force + gain, self.rest_ceiling)
        add = max(2, self.regen) if chosen else 1
        self.energy_pool = min(self.energy_pool + add, E_MAX_MULT * self.regen)
        self.last_act, self.last_work = "REST", 0

    @property
    def regen(self):
        """Поток восстановления структуры: dE/dt = floor(sqrt(F)).

        Сохраняет формулу README «энергия = корень из силы» как темп пополнения
        расходуемого пула энергии."""
        return max(1, math.floor(math.sqrt(self.force)))

    def tick_energy(self):
        """Тактовое пополнение пула (в покое и в работе) потоком ``regen``.

        Пул никогда не превышает потолок ``E_MAX_MULT * regen``: запас энергии
        пропорционален темпу её восстановления, поэтому крупная структура
        копит больший резерв для давления, а мелкая остаётся быстрой, но
        неспособной к длительному напору."""
        self.energy_pool = min(self.energy_pool + self.regen, E_MAX_MULT * self.regen)

    def schmitt_on(self):
        """Верхний порог Шмитта входа: ON(F) = max(ON_MIN, ON_FRAC * force).

        Масштабный (выведен из силы адресата — одной из двух метрик модели):
        крупный автомат требует крупного напора, малый уязвим к малому.
        Исторический абсолютный порог ON=40 создавал catch-22 дна (см. H-A)."""
        return max(ON_MIN, ON_FRAC * self.force)

    def effective_decay(self):
        """Профильная скорость остывания давления: DECAY_ADOPT * p.

        Вынесено в метод, чтобы обработчики (вход — tick_input_state и модель
        планирования UtilityAI) использовали одну и ту же формулу; новых
        переменных не появляется — это функция от уже существующих p и DECAY_ADOPT."""
        return DECAY_ADOPT * self.p

    def receive_pressure(self, w):
        """Input-обработка входящей работы: накопление давления на вход.

        Всякая входящая работа (успешная или нет) увеличивает ``w_adopt``.
        При ``w_adopt >= ON(F)`` вход переходит в состояние открытого окна
        восприимчивости длительностью OPEN_TTL тактов. Гистерезис ON > OFF
        исключает дребезг контакта от шума и мелочи."""
        self.w_adopt += w
        if not self.in_open and self.w_adopt >= self.schmitt_on():
            self.in_open = True
            self.open_timer = OPEN_TTL

    def tick_input_state(self):
        """Тактовка состояния входа адресата (пороги Шмитта с гистерезисом).

        Профильный множитель ``p`` входит в обработку ДВУХ существующих величин
        (см. docs/MODEL.md, раздел 2а): скорость остывания давления и положение
        нижнего порога гистерезиса. Верхний порог ON(F) остаётся инвариантом
        автомата — «конституция» по сути, но не по значению: новые переменные
        не введены, изменена только обработка.

        Три перехода за один такт:
          1. ``w_adopt *= DECAY_ADOPT * p`` — «заживление»: накопленное давление
             остывает, если напор не поддерживается; при p<1 (догматик) — быстрее;
          2. при открытом окне уменьшается ``open_timer`` (окно конечно);
          3. окно захлопывается по истечении ``OPEN_TTL`` **или** когда
             давление упало ниже ``OFF(F) = (OFF_FRAC / p) * ON(F)`` — у догматика
             нижний порог выше relative ON, окно захлопывается раньше.

        Нижний порог строго выше нуля и меньше верхнего (гистерезис ON > OFF),
        поэтому шум наблюдения и мелкая работа не «дёргают» контакт: вход
        открывается только устойчивым напором и так же устойчиво закрывается."""
        self.w_adopt *= self.effective_decay()
        if self.in_open:
            self.open_timer -= 1
            off_now = (OFF_FRAC / self.p) * self.schmitt_on()
            if self.open_timer <= 0 or self.w_adopt < off_now:
                self.in_open = False

    def sense(self, opp, rng):
        """Input-фаза: построение beliefs о противнике (частичная наблюдаемость).

        Реализует согласованное допущение модели «шум наблюдения вместо шума
        результата»: сам исход передачи не рандомизирован сверх ``p_success``,
        но агенты видят мир неполно и неточно:

          * ``opp_energy`` — пул противника с аддитивным шумом +/- BELIEF_NOISE;
          * ``opp_force`` — сила, округлённая до десятков (грубая оценка);
          * ``opp_w_adopt`` / ``opp_in_open`` — косвенный сигнал о состоянии
            входа противника (накопленное давление и положение окна);
          * ``opp_defense_guess`` — тип защиты НЕ наблюдается вовсе; оценка
            строится скользющим большинством последних 5 действий противника;
          * ``opp_last_act`` / ``opp_last_work`` — его прошлый ход;
          * ``opp_decay_guess`` — КОСВЕННАЯ оценка профильной скорости остывания
            чужого входа. Профиль не наблюдается напрямую (частичная
            наблюдаемость); он выводится из уже наблюдаемой траектории
            ``w_adopt``: если давление не пополнялось, w_adopt за такт умножилось
            на DECAY_ADOPT·p — отсюда p = decay_obs / DECAY_ADOPT. Скользящее
            среднее по последним 8 наблюдениям. Новых истинных переменных нет:
            это производная величина от уже существующих наблюдений.

        Args:
            opp: наблюдаемый противник.
            rng: генератор случайных чисел партии (шум наблюдения детерминирован seed'ом)."""
        prev_w = self.beliefs.get("opp_w_adopt_prev")
        self.beliefs["opp_energy"] = max(1, opp.energy_pool + rng.randint(-BELIEF_NOISE, BELIEF_NOISE))
        self.beliefs["opp_force"] = max(1, int(round(opp.force, -1)))
        self.beliefs["opp_w_adopt"] = max(0.0, opp.w_adopt)
        self.beliefs["opp_in_open"] = opp.in_open
        if prev_w is not None and prev_w > 1e-6 and opp.w_adopt <= prev_w:
            # В текущем такте вход ещё не пополнялся (resolve_attack идёт после
            # sense), поэтому изменение w_adopt от прошлого наблюдения — чистое
            # «заживление»: наблюдаем эффективный decay входа противника.
            obs_decay = min(0.999, max(0.5, opp.w_adopt / prev_w))
            dq = self.beliefs.setdefault("opp_decay_hist", [])
            dq.append(obs_decay)
            if len(dq) > 8:
                dq.pop(0)
            self.beliefs["opp_decay_guess"] = sum(dq) / len(dq)
        self.beliefs["opp_w_adopt_prev"] = opp.w_adopt
        hist = self.beliefs.setdefault("opp_act_hist", [])
        hist.append(opp.last_act)
        if len(hist) > 5:
            hist.pop(0)
        non_rest = [a for a in hist if a != "REST"]
        # Оценка защиты противника — мода последних наблюдённых действий, но
        # перебор строго по TYPES, а НЕ по set(): порядок обхода set зависит от
        # рандомизации хэшей строк между процессами (PYTHONHASHSEED), из-за чего
        # при равных частотах результат «плавал» и партии/тесты были невоспроизводимы
        # (детерминизм по seed нарушался). При ничьей выигрывает первый тип в TYPES.
        self.beliefs["opp_defense_guess"] = (
            max(TYPES, key=non_rest.count) if non_rest else None
        )
        # Оценка рецептивного типа противника из НАБЛЮДАЕМЫХ величин — тем же
        # законом, что и свойство ``defense``. Наблюдаема лишь базовая часть
        # контекста (``context_base``); скрытая выходная фаза текущего такта
        # противнику неизвестна, поэтому обработчики маргинализуют по трём
        # возможным типам (см. ``UtilityAI``), а здесь хранится база и базовая
        # оценка при hidden=0. Новых истинных переменных состояния не вводится.
        base = self.context_base(
            self.beliefs["opp_energy"], self.beliefs["opp_w_adopt"],
            self.beliefs["opp_in_open"], self.beliefs["opp_force"])
        self.beliefs["opp_ctx_base"] = base
        self.beliefs["opp_type_guess"] = TYPES[base]
        self.beliefs["opp_last_act"] = opp.last_act
        self.beliefs["opp_last_work"] = opp.last_work

    def rotate_defense(self, rng):
        """Ротация защиты упразднена: тип входа выводится из контекста.

        Раньше защита была хранимой меткой, которую приходилось ротировать,
        чтобы исход не был предопределён архитектурным контр-типом. Теперь
        «тип» — не валюта автомата, а фаза его состояния (property ``defense``),
        поэтому отдельной ротации не требуется (по ТРИЗ: лучшая функция — та,
        которой нет; здесь функция растворена в сущности контекста). Метод
        оставлен no-op ради совместимости API с внешним кодом (game_engine,
        эксперименты).
        """
        return None

    def upkeep(self):
        """Пассивное поддержание структуры: сила тратится на себя каждый такт."""
        self.force = max(1, self.force - UPKEEP)

    def commit(self, act, work):
        """Processing-фаза: фиксация намерения и списание энергии из пула.

        Энергия — настоящий расходуемый ресурс: заявленная работа вычитается
        из ``energy_pool`` безвозвратно (частично возвращается через трение
        обмена в ``resolve_attack``). Легальный выход ограничен сверху тремя
        барьерами одновременно:
          * ``energy_pool`` — нельзя сообщить больше, чем имеешь в запасе;
          * ``MAX_WORK`` — кап за такт (стабилизирует экспоненту);
          * ``max(MIN_OUTPUT, force // 4)`` — предельная доля структуры:
            автомат не может заявить передачу, разрушающую его саму;
            ``MIN_OUTPUT`` страхует зону дна от catch-22 (слабый должен иметь
            хотя бы минимальный легальный напор).

        Пустая или нулевая работа переводит автомат в режим покоя
        (неосознанный отдых — вдвое слабее осознанного).

        Returns:
            int: фактический выход работы (0, если выбран покой или работа
            оказалась невозможной)."""
        if act == "REST":
            self.do_rest(chosen=True)
            return 0
        w = min(int(work), self.energy_pool, MAX_WORK, max(MIN_OUTPUT, self.force // 4))
        if w <= 0:
            self.do_rest(chosen=False)
            return 0
        self.energy_pool -= w
        self.last_act, self.last_work = act, w
        return w

    def rest_if_starving(self):
        """Рефлекс самосохранения (нижний ярус иерархии автомата).

        При критическом пуле (<= STARVING_E) покой обязателен и не подлежит
        ни утилитарному расчёту, ни Q-разведке; симметричен для обеих сторон."""
        if self.energy_pool <= STARVING_E:
            self.do_rest(chosen=True)
            return True
        return False

    def process_hit(self, tr):
        """Output-обработка принятой передачи: потеря силы и шок пула.

        Принятый удар (мощность ``tr``) действует двояко:
          * сила уменьшается на ``tr`` — прямое следствие входа адресата;
          * из пула выбивается ``HOCK_FRACTION * tr`` энергии — структурный
            шок: без него давление на пассивного не истощало бы его вовсе
            (диагностика: вечная ничья PRESSER vs PASSIVE).

        Часть ``tr`` возвращается адресату позже трением ``K_EFFECT`` в
        ``resolve_attack`` — безвозвратны лишь ``(1 - K_EFFECT) * tr``."""
        self.force = max(1, self.force - tr)
        self.energy_pool = max(0, self.energy_pool - int(HOCK_FRACTION * tr))

    def gain(self, tr):
        """Приращение силы (Output-эффект успешной передачи)."""
        self.force += tr


class UtilityAI(Agent):
    """Заскриптованный BDI-агент: намерение по ожидаемой выгоде U(action).

    Не обучается — следует аналитической модели того же закона, что и среда
    (включая положение входа противника по порогам Шмитта). Авантюры — работу
    по закрытому входу — отвергает сама утилита: U(action) = delta + gamma*reward(t).

    Профильная осведомлённость (параметр ``profile_aware``, по умолчанию False —
    прежние значения калибровки и поведение без изменений): при True модель
    накопления чужого входа использует косвенную оценку остывания давления
    ``opp_decay_guess`` вместо глобального DECAY_ADOPT. Демонстрация того, что
    «характер» автомата различим существующими IPO-каналами
    (наблюдение → beliefs → расчёт) без введения новых переменных мира."""

    def __init__(self, profile="CANON", profile_aware=False):
        super().__init__(profile=profile)
        self.profile_aware = profile_aware

    def gain_model(self, m, p):
        """Ожидаемая отдача единицы работы при гипотезе о защите (множитель m)
        и вероятности успеха p — тот же закон, что в ``resolve_attack``.

        Различает два положения чужого входа:
          * открыт: ``y = p * m * GAIN_MAX`` — окно «распахивает» вход;
          * закрыт: ``y = p * m * Y_SMALL`` плюс **опционная надбавка**
            ``OPTION_VALUE * progress``, где ``progress`` — доля порога ON(F),
            уже накопленная давлением на вход. Смысл: каждый удар по закрытому
            входу приближает его к открытию и потому ценен не только сейчас,
            но и как покупка будущего окна восприимчивости. Это позволяет
            UtilityAI осмысленно выбирать кампанию накопления, а не только
            мгновенную выгоду."""
        if self.beliefs["opp_in_open"]:
            return p * m * GAIN_MAX
        base = Y_SMALL * p * m
        on_opp = max(ON_MIN, ON_FRAC * self.beliefs["opp_force"])
        progress = min(1.0, self.beliefs["opp_w_adopt"] / on_opp)
        # Профильно-осведомлённая модель опциона: давление на чужой вход остывает
        # со скоростью DECAY_ADOPT*p_opp; при p<1 (догматик) накопленное быстрее
        # утекает, и опцион «покупки окна» дешевле; при p>1 — дороже и вероятнее.
        # Оценка p_opp берётся из beliefs (opp_decay_guess); без profile_aware или
        # без достаточных наблюдений — канонический DECAY_ADOPT (прежнее поведение).
        eff_decay = DECAY_ADOPT
        if self.profile_aware:
            dg = self.beliefs.get("opp_decay_guess")
            if dg is not None:
                eff_decay = dg
        k = 3  # горизонт планирования опциона (в тактах), вынесен локально
        retained = sum(eff_decay ** i for i in range(1, k + 1)) / k
        option = OPTION_VALUE * progress * (retained / (sum(DECAY_ADOPT ** i for i in range(1, k + 1)) / k))
        return base + option

    def expected_retaliation(self, work):
        """Оценка возмездия: адресат бьёт в ответ долей RETALIATE_FRACTION*w.

        Рецептивный тип ответчика складывается из наблюдаемой базы контекста и
        СКРЫТОЙ выходной фазы данного такта (см. §2); противнику скрытая фаза
        неизвестна, поэтому её маргинал равномерен и оценка — среднее по трём
        возможным типам. Вероятность успеха и множитель считаются фактическим
        законом ``p_success``/``MULT`` (тем же, что в ``resolve_attack``), поэтому
        прежнее отклонение (штраф по ``opp_last_act``) устранено."""
        r_w = int(RETALIATE_FRACTION * work)
        if r_w <= 0:
            return 0.0
        ev = 0.0
        for t in TYPES:
            mr = MULT.get((t, self.defense), 1.0)
            pr = p_success(t, r_w, self.defense, self.last_work)
            ev += r_w * self.gain_model_rev(mr, pr) / 3.0
        return ev

    def gain_model_rev(self, m, p):
        """Отдача ответного удара по НАШЕМУ входу (наше состояние нам точно известно)."""
        if self.in_open:
            return p * m * GAIN_MAX
        return Y_SMALL * p * m

    def retaliation_penalty(self, work):
        """Цена возмездия для нас: цена работы COST_FRACTION*w плюс шок пула
        HOCK_FRACTION*r_w от ответного удара. Бить по открытому противнику дорого."""
        r_w = int(RETALIATE_FRACTION * work)
        return COST_FRACTION * work + HOCK_FRACTION * r_w

    def expected_gain(self, act, work):
        """U(action): ожидаемая отдача минус цена работы и минус ожидание
        возмездия. Покой оценивается логистикой rest_gain.

        Рецептивный тип адресата = наблюдаемая база контекста + СКРЫТАЯ выходная
        фаза данного такта (§2). Скрытая фаза противнику неизвестна, поэтому её
        маргинал равномерен и отдача оценивается средним по трём возможным типам;
        вероятность успеха — фактическим законом ``p_success`` (мощность и
        контр-тип), тем же, что в ``resolve_attack``."""
        if act == "REST" or work <= 0:
            return self.rest_gain()
        ev = 0.0
        for hypo in TYPES:
            m = MULT.get((act, hypo), 1.0)
            p = p_success(act, work, hypo, self.beliefs["opp_last_work"])
            ev += work * self.gain_model(m, p) / 3.0
        return ev - self.retaliation_penalty(work) - self.expected_retaliation(work)

    def form_intention(self):
        """Перебор действий (покой/3 типа x 2 доли пула), выбор максимума U."""
        best, best_u = ("REST", 0), self.rest_gain()
        for t in TYPES:
            for frac in (0.3, 0.7):
                w = int(self.energy_pool * frac)
                u = self.expected_gain(t, w)
                if u > best_u:
                    best, best_u = (t, w), u
        return best


class RLAgent(Agent):
    """Обучающийся агент: табличный Q-Learning с переносом обучения между партиями.

    Состояние — дискретизированные beliefs, включая положение входа противника
    (O/C) и степень его наполнения давлением: Q различает «давить бесполезно»
    и «окно открыто — бей». Между партиями переносится ТОЛЬКО Q-таблица; физическое
    состояние сбрасывается ``reset_state`` в начале каждой партии (иначе порядок
    партий влиял бы на исход). Разведка anneal'ится по ОБЩЕМУ опыту (``epsilon``),
    а не по номеру такта внутри партии."""

    # Горизонт annealing разведки — в тактах ОБЩЕГО опыта агента за все партии
    # (не по такту партии: короткие партии иначе целиком проходят «в разведке»).
    EPS_START = 1.0
    EPS_MIN = 0.05
    EPS_DECAY_STEPS = 3000

    def __init__(self, q=None, profile="CANON"):
        super().__init__(profile=profile)
        self.Q = q if q is not None else {}
        self.steps_trained = 0

    def epsilon(self):
        """Текущая вероятность разведки по ОБЩЕМУ числу тактов обучения.

        Прежде eps anneal'ился по номеру такта ВНУТРИ партии и сбрасывался
        каждую партию. При коротких партиях (~20–60 тактов до захвата) агент
        почти всю игру действовал случайно и НИКОГДА не эксплуатировал
        выученное — отсюда его слабость. Здесь горизонт — суммарный опыт за все
        партии, поэтому выученная политика успевает выразиться в игре."""
        e = max(self.EPS_MIN, self.EPS_START - self.steps_trained / self.EPS_DECAY_STEPS)
        self.steps_trained += 1
        return e

    def discretize(self, e):
        """Многошкалильная дискретизация: точная до 8, шаг 4 до 32, далее log-баки."""
        if e <= 8:
            return e
        if e <= 32:
            return 8 + (e - 8) // 4
        return 14 + int(math.log(e / 32))

    def skey(self):
        """Ключ символического состояния RL-агента (дискретизированные beliefs).

        Семь компонент — всё наблюдаемое, никаких скрытых истинных переменных:
          1. собственный пул (``energy_pool``, дискретизация ``discretize``);
          2. пул противника (оценка с шумом наблюдения);
          3. последний тип атаки противника;
          4. признак угрозы ``T/-``: контрит ли его последняя атака нашу защиту;
          5. уровень давления на его вход (накопленный ``w_adopt``) — степень
             близости чужого окна восприимчивости;
          6. положение его входа ``O/C`` (Open/Closed);
          7. наблюдаемая база рецептивного контекста противника ``opp_ctx_base``
             (0/1/2): истощён / наполнен / на пороге.

        Компонента 7 несёт наблюдаемую часть рецептивного типа (§2); его СКРЫТАЯ
        выходная фаза (текущее действие противника) агенту недоступна — это и есть
        остаточная неопределённость типа. Компоненты 5–6 дают Q-функции различать
        «давить бесполезно» и «окно открыто — бей», не вводя новых состояний среды."""
        threat = "T" if MULT.get((self.beliefs["opp_last_act"], self.defense)) else "-"
        adopt = self.discretize(int(self.beliefs["opp_w_adopt"]))
        openg = "O" if self.beliefs["opp_in_open"] else "C"
        return (self.discretize(self.energy_pool),
                self.discretize(self.beliefs["opp_energy"]),
                self.beliefs["opp_last_act"],
                threat, adopt, openg,
                self.beliefs.get("opp_ctx_base"))

    def form_intention(self, eps, rng):
        """Выбор действия epsilon-greedy по Q-таблице текущего состояния.

        Args:
            eps: вероятность разведки (epsilon-greedy).
            rng: генератор случайных чисел партии — разведка берёт случайность
                из него, а НЕ из глобального ``random``, поэтому прогоны
                воспроизводимы по seed (см. play_game)."""
        st = self.skey()
        if st not in self.Q:
            self.Q[st] = [0.0] * len(ACTIONS)
        if rng.random() < eps:
            return rng.randint(0, len(ACTIONS) - 1)
        return self.Q[st].index(max(self.Q[st]))

    def learn(self, st, a_idx, reward, nst, alpha=0.3, gamma=0.9):
        """TD-обновление по корректному переходу s -> s'.

        Args:
            st: состояние ДО применения действия (снимается до commit).
            a_idx: индекс выбранного действия.
            reward: изменение силы за такт (delta + gamma*reward(t) в TD-цели).
            nst: состояние ПОСЛЕ разрешения боя.
        """
        if nst not in self.Q:
            self.Q[nst] = [0.0] * len(ACTIONS)
        td = reward + gamma * max(self.Q[nst]) - self.Q[st][a_idx]
        self.Q[st][a_idx] += alpha * td


class Environment(Agent):
    """Среда как всеобъемлющий IPO-автомат (суперсистема над автоматами).

    Утверждённое архитектурное решение (раздел 13 MODEL.md; бывший эксперимент —
    «гипотеза B», гипотеза A удалена из кода): среда — не пустое пространство
    между автоматами, а автомат того же кодекса. Среда наследует ``Agent``,
    поэтому весь кодекс Шмитта и логистика покоя реализованы обработчиками
    базового автомата один-в-один: повторения кода нет и новых переменных
    состояния не вводится (набор полей среды — точное подмножество полей Agent).

      INPUT   : входящие работы всех автоматов такта (каждая передача нагружает
                вход среды через resolve_attack -> receive_pressure) плюс
                автономный доход ENV_INCOME; в многоуровневой иерархии
                (``members``, см. ниже и раздел 14 MODEL.md) вход дополнительно
                нагружается суммарной работой членов нижнего яруса;
      PROCESS : накопление w_adopt и гистерезис ON(F)/OFF(F) — восприимчивость
                среды = «конъюнктура»; ротация типа «погоды» (defense); upkeep,
                пополнение пула, покой — всё обработчиками Agent при профиле
                CANON (p=1), т.е. без профильных искажений суперсистемы;
      OUTPUT  : состояние входа транслируется в правила для автоматов одним
                скаляром: при открытом входе среды отдача адресанта увеличивается
                на ENV_BONUS («окно возможностей»), при закрытом — прежний канон.

    Тактовый протокол tick() повторяет протокол автомата, т.е. среда подчинена
    той же IPO-архитектуре — иерархия автоматов (открытый вопрос 4 MODEL.md
    закрыт разделом 14: композиция Environment из Environment/Agent) получает
    ярусы без расширения онтологии.

    Иерархия (параметр ``members``): суперсистема может объять нижестоящие
    автоматы — список ``Agent`` (или других ``Environment``; композиция
    рекурсивна: Environment может быть членом Environment). Тогда каждый такт:
      * выходы членов (всякая их передача в ``resolve_attack``) уже нагружают
        вход суперсистемы через ``receive_pressure`` — суммирование работ есть
        эмерджентный вход верхнего яруса;
      * в ``tick()`` перед собственной тактовкой входа среда агрегирует суммарную
        работу автономных членов (``member_output``), а открытое окно среды
        транслируется всякому адресанту надбавкой ENV_BONUS к отдаче —
        самоподобие: закон модуляции окна одинаков на всех ярусах.
    ``members=None`` (по умолчанию) — прежнее поведение плоской среды; список
    пуст — то же. Новых переменных состояния не вводится: members — структура
    из уже существующих объектов-автоматов, их поля — те же поля Agent.

    Отличие от автомата-персонажа одно и состоит из уже существующих состояний:
    у среды нет оппонента, поэтому beliefs фиксированы («противник REST с
    нулевой работой»), а её собственный выход наружу — не передача силы, а
    окно конъюнктуры (ENV_BONUS) и автономный доход (ENV_INCOME).

    Альтернативная онтология («среда как отдельное пространство», гипотеза A)
    удалена из кода по итогам сравнения (раздел 13 MODEL.md): она не имела ни
    метрик, ни состояний и была вырожденным случаем настоящей среды (env=None).
    """

    def __init__(self, start_force=10, members=None):
        # Профиль CANON (p=1): среда применяет кодекс без профильных искажений.
        super().__init__(defense=TYPES[0], profile="CANON")
        self.force = float(start_force)          # сила среды (капитал конъюнктуры)
        # Иерархия: нижестоящие автоматы, объятые этой суперсистемой (см.
        # docs/MODEL.md, раздел 14). None/пусто — плоская среда (прежнее
        # поведение). Новых переменных нет: members — контейнер существующих
        # автоматов, его содержимое описывается тем же кодексом Agent.
        self.members = list(members) if members else []
        # Среде некого наблюдать: beliefs нейтральны, тогда унаследованная
        # rotate_defense выбирает «погоду» равномерно из TYPES — прежнее поведение.
        self.beliefs.update({"opp_last_act": "REST", "opp_last_work": 0,
                             "opp_energy": 0, "opp_force": 1,
                             "opp_w_adopt": 0.0, "opp_in_open": False})

    def receive_pressure(self, w):
        """Input-обработка Agent + рост потолка покоя от труда автоматов.

        Наследует накопление давления и открытие окна по Шмитту у Agent;
        добавляет единственное средовое следствие нагрузки: rest_units среды
        растёт от входящей работы (w * 0.01), расширяя потолок покоя
        суперсистемы. Новых переменных нет — rest_units есть поле Agent.

        Рост ограничен ENV_REST_CAP (предохранитель): иначе на длинных партиях
        потолок покоя среды уползал бы неограниченно, а с ним и порог Шмитта
        ON(F), из-за чего окно конъюнктуры в итоге перестало бы открываться."""
        super().receive_pressure(w)
        self.rest_units = min(self.rest_units + w * 0.01, ENV_REST_CAP)  # труд расширяет потолок (с капом)

    def rotate_defense(self, rng):
        """Ротация «погоды» среды — тот же обработчик, что у Agent.

        Фиксированная защита среды делала бы контр-цикл предопределённым;
        ротация оставляет место для стратегии (наблюдательный агент
        эксплуатирует распределение). При нейтральных beliefs унаследованный
        выбор равномерен по TYPES — прежнее поведение среды, код не дублируется.

        Иерархия: если среда объят другой суперсистемой (её members непусты),
        погода членов ротируется в их собственном такте — здесь только своё.
        Исключение: автономные члены-среды (super().__init__ не вызывался — см.
        __init__) собственного такта вне партии не имеют, поэтому их «погода»
        ротируется здесь, на ярус выше; кодекс тот же (унаследованный выбор)."""
        super().rotate_defense(rng)
        for m in self.members:
            if isinstance(m, Environment):
                Agent.rotate_defense(m, rng)   # без профильных искажений CANON-среды

    def snapshot(self):
        """Снимок IPO-состояния суперсистемы для наблюдения за иерархией.

        Только ЧТЕНИЕ существующих полей — новых переменных состояния не вводится.
        Рекурсивен: включает снимки объятых членов-сред, поэтому многоуровневая
        композиция наблюдаема целиком (нужно экспериментам раздела 14 MODEL.md).
        last_work/last_act среды отражают её входной труд за такт (агрегат)."""
        return {
            "force": self.force,
            "energy_pool": self.energy_pool,
            "w_adopt": round(self.w_adopt, 2),
            "in_open": self.in_open,
            "defense": self.defense,
            "last_act": self.last_act,
            "last_work": self.last_work,
            "members": [m.snapshot() for m in self.members
                        if isinstance(m, Environment)],
        }

    def member_output(self):
        """Эмерджентный выход нижнего яруса: суммарная работа членов за такт.

        Выходы автоматов (``last_work`` при nonzero ``last_act``) складываются —
        это и есть вход суперсистемы от объятых ею структур. Новых переменных
        нет: сумма берётся из уже существующих полей членов; свойство
        самоподобия — та же величина, что нагружает вход среды в партии
        (resolve_attack -> receive_pressure), здесь агрегируется явно.

        Агрегация РЕКУРСИВНА: если член — сам среда-суперсистема, в сумму
        входит её собственный ``member_output`` (а не её ``last_work``: среда
        наружу даёт окно конъюнктуры, а не передачу силы, и в покое её
        ``last_act`` = REST). Иначе труд членов второго и более ярусов не
        доходил бы до верхнего входа — глубина ≥2 была бы разорвана. Тот же
        кодекс на всех ярусах (docs/MODEL.md, раздел 14; автотест —
        experiments/exp_hierarchy_depth.py)."""
        total = 0.0
        for m in self.members:
            if isinstance(m, Environment):
                total += m.member_output()          # рекурсия вниз по ярусам
            elif m.last_act != "REST":
                total += m.last_work
        return total

    def tick(self):
        """Один такт среды: тот же протокол Process, что у автомата.

        Ротация типа вынесена в шаг 2 такта партии (env.rotate_defense(rng) —
        там же, где у автоматов); здесь — энергия, состояния входа, автономный
        доход и покой/upkeep. Все фазы — унаследованные обработчики Agent.

        Иерархия (members): перед собственной тактовкой входа среда принимает
        эмерджентный вход яруса — суммарную работу членов (member_output).
        В партии play_game члены-персонажи уже бьют по входу среды напрямую
        (resolve_attack -> receive_pressure); здесь же агрегируются выходы
        автономных подсистем, живущих вне дуэли: суперсистема «видит» труд
        своих членов как единое давление, и окно конъюнктуры верхнего яруса
        открывается устойчивым суммарным напором, а не отдельными передачами —
        эмерджентность порога Шмитта над суммацией работ. Обработчик тот же
        (receive_pressure), новых переменных нет.

        Автономный доход ENV_INCOME — единственный элемент, отсутствовавший в
        прежней модели «среды-пространства»: среда-автомат воспроизводит
        закрытый разделом 13 открытый вопрос 3 MODEL.md (внешняя среда с
        автономным доходом) без новых переменных — доход есть работа самой
        среды, порождаемая её состоянием покоя. Замечание: потолок покоя среды
        растёт только от чужого труда (receive_pressure), сам доход rest_units
        не увеличивает — принцип §5 («потолок недоступен бездельнику»)
        сохранён и для суперсистемы. Автономный доход ограничен этим же
        потолком покоя (``min(force + ENV_INCOME, rest_ceiling)``): без
        ограничения сила среды растёт безгранично (ENV_INCOME > upkeep), а с ней
        и порог Шмитта ON(F), из-за чего окно конъюнктуры закрывается навсегда —
        среда переставала быть источником окон.

        Покой применяется как НЕвыбранный (do_rest(chosen=False), половина
        прибыли и малое пополнение пула): осознанный отдых Agent ограничивает
        силу потолка ПОЛОЖИТЕЛЬНЫМ приростом, из-за чего среда не могла бы
        опуститься ниже L и окно конъюнктуры переставало бы захлопываться
        (дегенерация гистерезиса). Прежняя средовая форма do_rest была
        эквивалентна именно этому вызову.

        Иерархия (рекурсия ярусов): если среди members есть нижестоящие
        суперсистемы (Environment), они тактуются ЗДЕСЬ — тот же протокол
        на ярус ниже (их собственные члены агрегируются их же tick). Так
        многоуровневая композиция живёт без расширения онтологии: порядок
        обхода — снизу вверх (сначала труд членов, затем вход яруса), что
        соответствует причинности партии (передачи персонажей бьют по входу
        среды уже в resolve_attack)."""
        for m in self.members:                   # рекурсивный такт нижних ярусов
            if isinstance(m, Environment):       # автономные подсреды «дышат» сами
                m.tick()                         # агенты-члены вне дуэли такта не имеют
        if self.members:                         # вход суперсистемы: суммарный труд членов
            w_members = self.member_output()
            if w_members:
                self.receive_pressure(w_members) # тот же кодекс Шмитта — самоподобие
        self.tick_energy()                       # пополнение пула потоком regen (Agent)
        self.tick_input_state()                  # гистерезис Шмитта входа (Agent)
        # Автономный доход НЕ обходит потолок покоя: иначе сила среды растёт
        # безгранично (ENV_INCOME > upkeep), а вместе с ней и порог Шмитта
        # ON(F)=max(ON_MIN, ON_FRAC*F) — окно конъюнктуры закрывается навсегда
        # (замер: force 10→1030 при потолке ~76, ON→258). Доход ограничен тем же
        # логистическим потолком, что и покой любого автомата, поэтому среда
        # остаётся рабочей «конъюнктурой», а не бесконечным накопителем.
        self.force = min(self.force + ENV_INCOME, self.rest_ceiling)
        if self.force < self.rest_ceiling:       # логистический покой (Agent)
            self.do_rest(chosen=False)
        self.upkeep()                            # содержание структуры (Agent)


def _apply_transfer(att, dfn, work, att_type, rng, env=None):
    """Ядро единого закона передачи: шаги 2–5 протокола ``resolve_attack``.

    Выделено, чтобы ОБА направления — основной удар и ответный — проходили один
    и тот же закон, но ответный не порождал собственного контр-возмездия (иначе
    бесконечная рекурсия). Отличие от прежней версии принципиально: тип энергии
    адресанта передаётся ЯВНЫМ аргументом ``att_type`` и НЕ читается из
    ``att.last_act``, поэтому ответный удар не искажает намерение адресанта
    (раньше возмездие перезаписывало ``last_act``/``last_work`` адресата, и
    вторая атака такта уходила чужим типом — защитой вместо выбранного действия).

    Args:
        att, dfn: адресант и адресат передачи.
        work: мощность передачи (единиц работы).
        att_type: тип энергии адресанта (его выбранное действие или защита
            при возмездии) — определяет контр-множитель ``MULT``.
        rng: генератор случайных чисел партии.
        env: необязательная среда-автомат; её вход нагружается всякой передачей,
            открытое окно даёт надбавку ENV_BONUS к отдаче адресанта.
    """
    open_now = dfn.in_open
    dfn.receive_pressure(work)
    if env is not None:
        env.receive_pressure(work)
    if rng.random() < p_success(att_type, work, dfn.defense, dfn.last_work):
        m = MULT.get((att_type, dfn.defense), 1.0)
        gain_frac = GAIN_MAX if open_now else Y_SMALL
        if env is not None and env.in_open:
            gain_frac *= (1.0 + ENV_BONUS)
        gained = int(work * m * gain_frac)
        if gained:
            att.gain(gained)
            att.rest_units += gained
        dfn.process_hit(work)
        dfn.force = max(1, dfn.force + int(K_EFFECT * work))


def resolve_attack(att, dfn, work, rng, env=None):
    """Единый закон передачи — общий для конкуренции любой природы
    (физической, информационной, экономической; мирное сосуществование = работа 0).

    Порядок разрешения такта давящего att против адресата dfn:
      1. Цена работы: COST_FRACTION*w сгорает всегда — предельная стоимость давления.
      2. Накопление давления: всякая входящая работа нагружает вход адресата
         (пороги Шмитта); окно открывается со следующего удара — инерция системы
         (удар, переполнивший чашу, сам сквозь неё ещё не проходит).
      3. Успех вероятностен (p_success: мощность, тип против защиты).
      4. При успехе: адресант получает w*m*(GAIN_MAX если вход был открыт, иначе
         Y_SMALL); адресат теряет w и восстанавливает K_EFFECT*w — разница
         сгорает безвозвратно (единственный источник чистых потерь обмена).
         Труд адресанта порождает rest_units (рост потолка покоя).
      5. Промах: цена уплачена, отдачи нет, но износ входа накоплен — завтра
         окно может открыться. Система «трескается» от любого напора.
      6. Возмездие: адресат отвечает долей RETALIATE_FRACTION*w ПО ТОМУ ЖЕ закону
         (шаги 1–5 ниже через ``_apply_transfer``: цена работы, накопление
         давления на входе обидчика, шок его пула, трение, окно среды), но без
         собственного контр-возмездия. Тип ответа — тип защиты адресата.
         ``last_act``/``last_work`` адресата не перезаписываются, поэтому
         запланированное им действие такта не искажается ответным ударом.

    Окупаемость давления НЕ гарантирована архитектурой: нужен накопленный напор,
    угаданный тип (m=3), попадание броска и резерв сил в такт конечного окна.
    Просчитанные кампании гибнут — это свойство стратегии, а не случайности.

    Опциональный env (среда-автомат, см. Environment): работа одновременно нагружает
    вход среды; если вход среды открыт, адресант получает надбавку ENV_BONUS к
    отдаче — среда-автомат транслирует накопленное давление в выход для автоматов.

    Иерархия (раздел 14 MODEL.md): env может быть суперсистемой с members —
    тогда всякая передача нижестоящего автомата удваивает канал входа яруса:
    прямой удар по входу среды (здесь) и суммирование работ членов (Environment.
    tick -> member_output -> receive_pressure). Модуляция отдачи окном среды
    действует на любого адресанта, объятного этой средой, — закон одинаков для
    всех направлений иерархии (самоподобие)."""
    if not work:
        return
    att.force = max(1, att.force - int(COST_FRACTION * work))
    _apply_transfer(att, dfn, work, att.last_act, rng, env)

    # Возмездие (шаг 6 протокола): доля принятой работы возвращается адресатом
    # по ТОМУ ЖЕ закону — с ценой работы, накоплением давления на входе обидчика,
    # шоком его пула, трением и модуляцией окном среды, — но без собственного
    # контр-возмездия (иначе рекурсия). Тип ответа — тип защиты адресата.
    # ``last_act``/``last_work`` при этом НЕ перезаписываются: они принадлежат
    # запланированному действию адресата в этом такте и не должны искажаться.
    r_w = int(RETALIATE_FRACTION * work)
    if r_w > 0 and dfn.energy_pool >= 1:
        r_w = min(r_w, dfn.energy_pool, MAX_WORK)
        dfn.energy_pool -= r_w
        dfn.force = max(1, dfn.force - int(COST_FRACTION * r_w))
        _apply_transfer(dfn, att, r_w, dfn.defense, rng, env)


def check_capture(rl, ai, dom_rl=0, dom_ai=0):
    """Решение о поражении по устойчивому доминированию, а не по одному удачному ходу.

    Доминирование фиксируется серией из CAPTURE_STREAK тактов, в течение которых
    одна сторона сохраняет пул >= CAPTURE_RATIO * пула соперника и большую силу.
    Тогда перетекает CAPTURE_FRAC силы проигравшего; тяжесть удваивается, если
    проигравший встречает решение с открытым (надорванным) входом — стоять до
    конца на надорванном входе сопоставимо с разгромом, отступление покоем дешевле.
    Формулировка нейтральна: описывает вытеснение с рынка, подавление канала
    в инфо-среде и физическое давление одинаково.

    Серии доминирования — состояние ПАРТИИ, а не автомата: передаются и
    возвращаются явно (``dom_rl``/``dom_ai``), поэтому функция реентерабельна и
    не держит модульных глобалов (несколько партий могут сосуществовать).

    Args:
        rl, ai: стороны.
        dom_rl, dom_ai: текущие серии доминирования сторон (такты).

    Returns:
        (winner, dom_rl, dom_ai): winner — "RL" | "UtilityAI" | None
        (None означает «партия продолжается»); серии сбрасываются при решении.
    """
    dom_rl = dom_rl + 1 if (rl.energy_pool >= CAPTURE_RATIO * ai.energy_pool and rl.force > ai.force) else 0
    dom_ai = dom_ai + 1 if (ai.energy_pool >= CAPTURE_RATIO * rl.energy_pool and ai.force > rl.force) else 0
    if dom_rl >= CAPTURE_STREAK:
        sev = 2.0 if ai.in_open else 1.0
        cap = int(ai.force * min(CAPTURE_FRAC * sev, 0.5))
        # Профильная обработка выхода: догматик (p<1) встречает разгром стойче —
        # тяжесть потери масштабируется его скаляром профиля; оппортунист (p>1)
        # платит больше за «продажность» позиции. Никаких новых переменных.
        cap = int(cap * max(0.5, min(1.0, ai.p)))
        ai.force = max(1, ai.force - cap)
        ai.rest_units = max(0.0, ai.rest_units - cap / L_STEP)
        rl.gain(cap)
        return "RL", 0, 0
    if dom_ai >= CAPTURE_STREAK:
        sev = 2.0 if rl.in_open else 1.0
        cap = int(rl.force * min(CAPTURE_FRAC * sev, 0.5))
        cap = int(cap * max(0.5, min(1.0, rl.p)))
        rl.force = max(1, rl.force - cap)
        rl.rest_units = max(0.0, rl.rest_units - cap / L_STEP)
        ai.gain(cap)
        return "UtilityAI", 0, 0
    return None, dom_rl, dom_ai


def play_game(rl, ai, steps=1000, seed=0, profiles=None, with_env=True,
              env_members=None):
    """Одна партия; между партиями переносится только Q-таблица RL.

    Физическое состояние сторон сбрасывается в начале партии (``reset_state``):
    каждая партия стартует с равных условий (сила 10, пул 3, вход закрыт), а
    обучение (Q) переносится. Без сброса порядок партий влиял бы на исход.

    Args:
        profiles: None — профили сторон берутся из уже заданных при создании
            агентов (по умолчанию "CANON" == прежняя каноническая механика);
            пара (p_rl, p_ai) — применить профили сторонам перед партией
            (имя из PROFILES или вещественный p). Профиль присваивается
            существующему скаляру ``Agent.p`` — новых переменных не появляется.
        with_env: участвовать ли среде-автомату (Environment) в партии.
            Среда как всеобъемлющий IPO-автомат — утверждённое архитектурное
            решение (раздел 13 MODEL.md), поэтому по умолчанию True: вход
            среды нагружается всякой передачей, а открытое окно даёт адресанту
            надбавку ENV_BONUS к отдаче и среда несёт автономный доход
            ENV_INCOME. False оставлен лишь для сравнения с прежним каноном
            («среда-пространство» удалена из кода вместе с гипотезой A).
        env_members: список нижестоящих автоматов, объятых средой партии
            (суперсистема, раздел 14 MODEL.md). Принято передавать саму среду
            ([rl, ai] либо [rl, ai, подсреда]) — тогда персонажи одновременно
            члены дуэли и объятые структуры, а их суммарный труд образует
            эмерджентный вход яруса (Environment.tick -> member_output).
            Ветки members, не участвующие в дуэли (автономные подсреды),
            тактуются рекурсивно внутри env.tick(). Новых переменных нет:
            members — контейнер существующих автоматов того же кодекса.

    Протокол такта (фиксированный порядок, стороны зеркальны):
      1. Взаимное наблюдение (sense) — частичная наблюдаемость.
      2. Ротация защит обеих сторон (профильно-модулируемая: см. rotate_defense).
      3. Поддержание структуры (upkeep), пополнение пулов (tick_energy),
         тактовка состояний входов (tick_input_state, пороги Шмитта с
         профильным decay/OFF). При with_env тем же шагом тактуется
         и среда (Environment.tick — тот же протокол для суперсистемы);
         если заданы env_members, её вход дополнительно нагружается
         суммарным трудом объятых автоматов (эмерджентность яруса), а
         автономные подсреды тактуются в ней рекурсивно.
      4. Намерения: RL epsilon-greedy (eps annealing по ОБЩЕМУ опыту агента,
         см. ``RLAgent.epsilon``); Utility — argmax U(action); рефлекс голода
         имеет приоритет над обоими.
      5. Разрешение передач по единому закону (resolve_attack) в обе стороны;
         при with_env передачи одновременно нагружают вход среды.
      6. TD-обучение RL на корректном переходе s -> s' с наградой delta F.
      7. Проверка устойчивого доминирования (check_capture; тяжесть поражения
         масштабируется профилем проигравшего).

    Returns:
        (winner | None, rl_hist, ai_hist, end_step)
    """
    if profiles is not None:
        p_rl, p_ai = profiles
        for agent, prof in ((rl, p_rl), (ai, p_ai)):
            agent.profile = prof if isinstance(prof, str) else round(float(prof), 4)
            agent.p = PROFILES[prof] if isinstance(prof, str) else float(prof)
    # Партия начинается с равных стартовых условий: физическое состояние
    # (метрики, вход, наблюдения) сбрасывается, переносится только обучение
    # (Q-таблица RL). Иначе проигравший стартовал бы ослабленным, а победитель —
    # усиленным, и исход зависел бы от порядка партий (см. Agent.reset_state).
    rl.reset_state()
    ai.reset_state()
    env = Environment(members=env_members) if with_env else None
    dom_rl = dom_ai = 0                     # серии доминирования — локальны для партии
    rng = random.Random(seed)
    rl_hist, ai_hist = [], []
    for step in range(steps):
        rl.sense(ai, rng)
        ai.sense(rl, rng)

        rl.rotate_defense(rng)
        ai.rotate_defense(rng)
        if env is not None:
            env.rotate_defense(rng)      # «погода» среды ротируется тем же обработчиком

        rl.upkeep()
        ai.upkeep()
        rl.tick_energy()
        ai.tick_energy()
        rl.tick_input_state()
        ai.tick_input_state()
        if env is not None:
            env.tick()

        a_idx = rl.form_intention(rl.epsilon(), rng)
        act_name, frac = ACTIONS[a_idx]
        st_before = rl.skey()
        f_before = rl.force

        if rl.rest_if_starving():
            w_rl = 0
        else:
            w_rl = rl.commit(act_name, rl.energy_pool * frac)

        ai_act, ai_work = ai.form_intention()
        if ai.rest_if_starving():
            w_ai = 0
        else:
            w_ai = ai.commit(ai_act, ai_work)

        resolve_attack(rl, ai, w_rl, rng, env)
        resolve_attack(ai, rl, w_ai, rng, env)

        rl_hist.append(rl.force)
        ai_hist.append(ai.force)
        rl.learn(st_before, a_idx, rl.force - f_before, rl.skey())

        winner, dom_rl, dom_ai = check_capture(rl, ai, dom_rl, dom_ai)
        if winner:
            return winner, rl_hist, ai_hist, step
    return None, rl_hist, ai_hist, steps


def run_batch(n_games=10, steps=1000, quiet=False, with_env=True,
              env_members_fn=None):
    """Пакет партий со сквозным обучением RL (общая Q-таблица через все партии).

    Args:
        with_env: участвовать ли среде-автомату в партиях (см. play_game;
            по умолчанию True — утверждённая онтология раздела 13 MODEL.md).
        env_members_fn: None — плоская среда (канон); вызываемый объект
            fn(rl, ai) -> list — состав members среды каждой партии
            (суперсистема, раздел 14 MODEL.md), напр. lambda rl, ai: [rl, ai].
            Вызывается после создания оппонента, до старта тактов.

    Returns:
        (rl_agent, last_game_tuple, results_dict) — results_dict считает победы
        по ключам "RL" / "UtilityAI" / None (None — «без решения» за steps тактов).
    """
    rl = RLAgent()
    results = {"RL": 0, "UtilityAI": 0, None: 0}
    finals = {"RL": [], "UtilityAI": [], None: []}
    last = None
    for g in range(n_games):
        ai = UtilityAI()
        members = env_members_fn(rl, ai) if env_members_fn else None
        winner, rl_hist, ai_hist, end_step = play_game(
            rl, ai, steps, seed=g, with_env=with_env, env_members=members)
        results[winner] += 1
        finals[winner].append(rl.force)
        last = (winner, rl_hist, ai_hist, end_step)
        if not quiet:
            print(f"Game {g+1}: winner={winner or 'no-capture'} at step {end_step} | "
                  f"final RL force={rl.force:.0f}, final UtilityAI force={ai_hist[-1]:.0f}")
    if not quiet:
        print("\nИтоги пакетного прогона:")
        print(f"  RL победил: {results['RL']}/{n_games}, "
              f"UtilityAI: {results['UtilityAI']}/{n_games}, "
              f"без решения: {results[None]}/{n_games}")
        for k in finals:
            if finals[k]:
                print(f"  Финальная сила RL при '{k}': медиана={statistics.median(finals[k]):.0f}")
    return rl, last, results


def main():
    """Точка входа: пакет из 10 партий со сквозным обучением RL, сводка и график.

    График — динамика силы обеих сторон за последнюю партию (лог-шкала),
    наглядно показывающая фазы накопления, окон восприимчивости и доминирования.

    ``matplotlib`` импортируется лениво: ядро модели (и все эксперименты/тесты,
    которым график не нужен) не зависят от графической библиотеки."""
    rl, (winner, rl_hist, ai_hist, end_step), results = run_batch(n_games=10)

    print(f"\nПоследняя партия: winner={winner or 'no-capture'}, шагов={end_step}")
    print(f"Q-состояний изучено: {len(rl.Q)}")

    import matplotlib.pyplot as plt
    plt.figure(figsize=(10, 6))
    plt.plot(rl_hist, label="RL Agent", color='blue', linewidth=2)
    plt.plot(ai_hist, label="Utility AI", color='red', linewidth=2)
    plt.title("Динамика силы агентов (пороги Шмитта на входе адресата)", fontsize=14)
    plt.xlabel("Шаг симуляции", fontsize=12)
    plt.ylabel("Сила (Force, log)", fontsize=12)
    plt.yscale("log")
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
