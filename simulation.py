"""Ozvering-Project: модель конкуренции IPO-автоматов.

Полная документация механики, формулы и параметры — в docs/MODEL.md.
Кратко: сущности обладают двумя метриками (сила force — целевая функция,
энергия energy_pool — расходуемый запас, пополняемый потоком floor(sqrt(F)));
взаимодействие — передача работы; восприимчивость входа адресата описывается
порогами Шмитта с гистерезисом ON(F)/OFF(F); прибыль покоя логистическая с
потолком, растущим только от труда; поражение — по устойчивому доминированию.
Терминология нейтральна: один закон покрывает физическую, информационную и
экономическую конкуренцию и мирное сосуществование (работа = 0).
"""

import math
import random
import statistics
import matplotlib.pyplot as plt


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
    "PROFILE_RNG": [0.7, 1.0],
}
"""Канонические значения калибровки модели; смысл каждого параметра — в docs/MODEL.md, раздел 8.

PROFILE_RNG — интервал случайного профиля по умолчанию (см. PROFILES ниже):
партия с seed=None или прогоны без явного профиля получают профиль равномерно
из этого интервала. Значение 1.0 соответствует прежней канонической механике."""

globals().update(PARAMETERS)

MULT = {("WATER", "FIRE"): 3.0, ("FIRE", "EARTH"): 3.0, ("EARTH", "WATER"): 3.0}
"""Круговой контр-множитель типов: WATER > FIRE > EARTH > WATER (x3). Цикл симметричен,
ни один тип не доминирует архитектурно; защита ротируется (Agent.rotate_defense)."""

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


def _profile_from_seed(seed):
    """Детерминированный выбор профиля по seed партии (для воспроизводимости прогонов).

    Используется только когда профиль явно не передан: profile=None означает
    «случайный профиль из PROFILE_RNG». При seed=None возвращается середина
    интервала PROFILE_RNG (нейтральное ожидание); при seed>=0 — детерминированное
    значение из того же интервала. В run_batch партии получают seed=g, поэтому
    профили сторон чередуются детерминированно, а не случайно между запусками."""
    lo, hi = PROFILE_RNG[0], PROFILE_RNG[1]
    if seed is None:
        return 0.5 * (lo + hi)
    rnd = random.Random(hash(("profile", seed)) & 0xFFFFFFFF)
    return rnd.uniform(lo, hi)


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

    Символьный ``state`` — единственный источник истины автомата. Метрики:
    ``force`` (сила, целевая функция, вещественная) и ``energy_pool``
    (энергия — расходуемый запас; пополняется потоком ``regen = floor(sqrt(F))``,
    ограниченным потолком ``E_MAX_MULT * regen``). Вход адресата несёт
    скалярное состояние восприимчивости (пороги Шмитта): ``w_adopt``,
    ``in_open``, ``open_timer`` — всё выводится из принятых передач,
    новых сущностей не вводится.
    """

    def __init__(self, defense=None, profile="CANON"):
        """profile — имя из PROFILES или вещественный p (см. docs/MODEL.md, раздел 2а).

        Профиль НЕ вводит новых переменных состояния: это единственный скаляр ``p``,
        модифицирующий ОБРАБОТКУ существующих IPO-компонентов — вход (пороги Шмитта:
        decay и нижний порог) и выход (тяжесть поражения при доминировании).
        Метрики force/energy_pool, их динамика и состав beliefs остаются прежними;
        профиль не наблюдается противником напрямую (частичная наблюдаемость).
        """
        self.profile = profile if isinstance(profile, str) else round(float(profile), 4)
        self.p = PROFILES[profile] if isinstance(profile, str) else float(profile)
        self.force = 10
        self.energy_pool = 3
        self.rest_units = 0.0
        self.defense = defense if defense is not None else random.choice(TYPES)
        self.last_act = "REST"
        self.last_work = 0
        self.w_adopt = 0.0
        self.in_open = False
        self.open_timer = 0
        self.state = {"energy": 3, "defense": self.defense, "last_act": "REST"}
        self.beliefs = {"opp_energy": 3, "opp_defense": None,
                        "opp_last_act": "REST", "opp_last_work": 0,
                        "opp_force": 10, "opp_w_adopt": 0.0, "opp_in_open": False}

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
        self.beliefs["opp_defense_guess"] = max(set(non_rest), key=non_rest.count) if non_rest else None
        self.beliefs["opp_last_act"] = opp.last_act
        self.beliefs["opp_last_work"] = opp.last_work

    def rotate_defense(self, rng):
        """Ротация защиты в начале такта (свойство среды + профильная обработка).

        Из множества типов исключаются те, которые контрят последний тип атаки
        противника (наблюдаемое ограничение), и защита выбирается равномерно из
        оставшихся. Фиксированная защита делала исход предопределённым
        (архитектурный контр-тип); ротация снимает гарантию, но оставляет место
        для стратегии: наблюдательный агент эксплуатирует ограничение ротации,
        предугадывая узкий набор возможных защит.

        Профильная дифференциация на выходе автомата: вероятность сменить защиту
        равна ``min(1.0, p)`` — «догматик» (p<1) держит позицию дольше,
        оппортунист (p>=1) ротируется каждый такт. Новых переменных не вводится:
        используется уже существующий скаляр профиля p и штатный rng партии;
        состояние ``defense`` было в модели всегда."""
        counters = [t for t in TYPES if not MULT.get((self.beliefs["opp_last_act"], t))]
        pool = counters if counters else TYPES
        if self.p >= 1.0 or rng.random() < self.p:
            self.defense = rng.choice(pool)
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}

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
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}

    def gain(self, tr):
        """Приращение силы (Output-эффект успешной передачи) с обновлением state."""
        self.force += tr
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}


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

        Защита ответа неизвестна — среднее по трём гипотезам; вероятность
        успеха ответки штрафуются контр-типом к нашей последней атаке."""
        r_w = int(RETALIATE_FRACTION * work)
        if r_w <= 0:
            return 0.0
        ev_loss = 0.0
        for hypo_def in TYPES:
            mr = MULT.get((hypo_def, self.defense), 1.0)
            pr = P_BASE / (1.0 + math.exp(-K_TYPE)) if MULT.get((self.beliefs["opp_last_act"], hypo_def)) else P_BASE
            g = self.gain_model_rev(mr, pr)
            ev_loss += r_w * g / 3.0
        return ev_loss

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
        """U(action): средняя ожидаемая отдача по гипотезам о защите минус цена
        работы и минус ожидание возмездия. Покой оценивается логистикой rest_gain."""
        if act == "REST" or work <= 0:
            return self.rest_gain()
        ev = 0.0
        for hypo in TYPES:
            m = MULT.get((act, hypo), 1.0)
            p = P_BASE / (1.0 + math.exp(-K_TYPE)) if MULT.get((hypo, act)) else P_BASE
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
    и «окно открыто — бей». Q-таблица общая между партиями (run_batch)."""

    def __init__(self, q=None, profile="CANON"):
        super().__init__(profile=profile)
        self.Q = q if q is not None else {}

    def discretize(self, e):
        """Многошкалильная дискретизация: точная до 8, шаг 4 до 32, далее log-баки."""
        if e <= 8:
            return e
        if e <= 32:
            return 8 + (e - 8) // 4
        return 14 + int(math.log(e / 32))

    def skey(self):
        """Ключ символического состояния RL-агента (дискретизированные beliefs).

        Шесть компонент — всё наблюдаемое, никаких скрытых истинных переменных:
          1. собственный пул (``energy_pool``, дискретизация ``discretize``);
          2. пул противника (оценка с шумом наблюдения);
          3. последний тип атаки противника;
          4. признак угрозы ``T/-``: контрит ли его последняя атака нашу защиту;
          5. уровень давления на его вход (накопленный ``w_adopt``) — степень
             близости чужого окна восприимчивости;
          6. положение его входа ``O/C`` (Open/Closed).

        Компоненты 5 и 6 дают Q-функции различать «давить бесполезно» и
        «окно открыто — бей», не вводя новых состояний среды."""
        threat = "T" if MULT.get((self.beliefs["opp_last_act"], self.defense)) else "-"
        adopt = self.discretize(int(self.beliefs["opp_w_adopt"]))
        openg = "O" if self.beliefs["opp_in_open"] else "C"
        return (self.discretize(self.energy_pool),
                self.discretize(self.beliefs["opp_energy"]),
                self.beliefs["opp_last_act"],
                threat, adopt, openg)

    def form_intention(self, eps):
        """Выбор действия epsilon-greedy по Q-таблице текущего состояния."""
        st = self.skey()
        if st not in self.Q:
            self.Q[st] = [0.0] * len(ACTIONS)
        if random.random() < eps:
            return random.randint(0, len(ACTIONS) - 1)
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


def resolve_attack(att, dfn, work, rng):
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
      6. Возмездие: адресат отвечает долей RETALIATE_FRACTION*w по тому же закону
         (своим типом защиты, с учётом положения НАШЕГО входа и шока пула).

    Окупаемость давления НЕ гарантирована архитектурой: нужен накопленный напор,
    угаданный тип (m=3), попадание броска и резерв сил в такт конечного окна.
    Просчитанные кампании гибнут — это свойство стратегии, а не случайности."""
    if not work:
        return
    att.force = max(1, att.force - int(COST_FRACTION * work))
    open_now = dfn.in_open
    dfn.receive_pressure(work)
    hit = rng.random() < p_success(att.last_act, work, dfn.defense, dfn.last_work)
    gained = 0
    if hit:
        m = MULT.get((att.last_act, dfn.defense), 1.0)
        gained = int(work * m * (GAIN_MAX if open_now else Y_SMALL))
        if gained:
            att.gain(gained)
            att.rest_units += gained
        dfn.process_hit(work)
        dfn.force = max(1, dfn.force + int(K_EFFECT * work))

    r_w = int(RETALIATE_FRACTION * work)
    if r_w > 0 and dfn.energy_pool >= 1:
        r_w = min(r_w, dfn.energy_pool, MAX_WORK)
        dfn.energy_pool -= r_w
        dfn.last_act = dfn.defense
        dfn.last_work = r_w
        rt = rng.random() < p_success(dfn.last_act, r_w, att.defense, att.last_work)
        if rt:
            mr = MULT.get((dfn.last_act, att.defense), 1.0)
            rg = int(r_w * mr * (GAIN_MAX if att.in_open else Y_SMALL))
            if rg:
                dfn.gain(rg)
                dfn.rest_units += rg
            att.process_hit(r_w)
            att.force = max(1, att.force + int(K_EFFECT * r_w))
            att.state = {"energy": att.energy_pool, "defense": att.defense,
                         "last_act": att.last_act}


def check_capture(rl, ai):
    """Решение о поражении по устойчивому доминированию, а не по одному удачному ходу.

    Доминирование фиксируется серией из CAPTURE_STREAK тактов, в течение которых
    одна сторона сохраняет пул >= CAPTURE_RATIO * пула соперника и большую силу.
    Тогда перетекает CAPTURE_FRAC силы проигравшего; тяжесть удваивается, если
    проигравший встречает решение с открытым (надорванным) входом — стоять до
    конца на надорванном входе сопоставимо с разгромом, отступление покоем дешевле.
    Формулировка нейтральна: описывает вытеснение с рынка, подавление канала
    в инфо-среде и физическое давление одинаково.

    Returns:
        "RL" | "UtilityAI" | None — None означает «партия продолжается».
    """
    global _dom_rl, _dom_ai
    _dom_rl = _dom_rl + 1 if (rl.energy_pool >= CAPTURE_RATIO * ai.energy_pool and rl.force > ai.force) else 0
    _dom_ai = _dom_ai + 1 if (ai.energy_pool >= CAPTURE_RATIO * rl.energy_pool and ai.force > rl.force) else 0
    if _dom_rl >= CAPTURE_STREAK:
        _dom_rl = _dom_ai = 0
        sev = 2.0 if ai.in_open else 1.0
        cap = int(ai.force * min(CAPTURE_FRAC * sev, 0.5))
        # Профильная обработка выхода: догматик (p<1) встречает разгром стойче —
        # тяжесть потери масштабируется его скаляром профиля; оппортунист (p>1)
        # платит больше за «продажность» позиции. Никаких новых переменных.
        cap = int(cap * max(0.5, min(1.0, ai.p)))
        ai.force = max(1, ai.force - cap)
        ai.rest_units = max(0.0, ai.rest_units - cap / L_STEP)
        rl.gain(cap)
        return "RL"
    if _dom_ai >= CAPTURE_STREAK:
        _dom_ai = _dom_rl = 0
        sev = 2.0 if rl.in_open else 1.0
        cap = int(rl.force * min(CAPTURE_FRAC * sev, 0.5))
        cap = int(cap * max(0.5, min(1.0, rl.p)))
        rl.force = max(1, rl.force - cap)
        rl.rest_units = max(0.0, rl.rest_units - cap / L_STEP)
        ai.gain(cap)
        return "UtilityAI"
    return None


_dom_rl = 0
_dom_ai = 0


def play_game(rl, ai, steps=1000, seed=0, profiles=None):
    """Одна партия; RL сохраняет Q-таблицу между партиями (перенос обучения).

    Args:
        profiles: None — профили сторон берутся из уже заданных при создании
            агентов (по умолчанию "CANON" == прежняя каноническая механика);
            пара (p_rl, p_ai) — применить профили сторонам перед партией
            (имя из PROFILES или вещественный p). Профиль присваивается
            существующему скаляру ``Agent.p`` — новых переменных не появляется.

    Протокол такта (фиксированный порядок, стороны зеркальны):
      1. Взаимное наблюдение (sense) — частичная наблюдаемость.
      2. Ротация защит обеих сторон (профильно-модулируемая: см. rotate_defense).
      3. Поддержание структуры (upkeep), пополнение пулов (tick_energy),
         тактовка состояний входов (tick_input_state, пороги Шмитта с
         профильным decay/OFF).
      4. Намерения: RL epsilon-greedy (eps annealing до 0.05 за 300 шагов),
         Utility — argmax U(action); рефлекс голода имеет приоритет над обоими.
      5. Разрешение передач по единому закону (resolve_attack) в обе стороны.
      6. TD-обучение RL на корректном переходе s -> s' с наградой delta F.
      7. Проверка устойчивого доминирования (check_capture; тяжесть поражения
         масштабируется профилем проигравшего).

    Returns:
        (winner | None, rl_hist, ai_hist, end_step)
    """
    global _dom_rl, _dom_ai
    if profiles is not None:
        p_rl, p_ai = profiles
        for agent, prof in ((rl, p_rl), (ai, p_ai)):
            agent.profile = prof if isinstance(prof, str) else round(float(prof), 4)
            agent.p = PROFILES[prof] if isinstance(prof, str) else float(prof)
    _dom_rl = _dom_ai = 0
    rng = random.Random(seed)
    rl_hist, ai_hist = [], []
    for step in range(steps):
        rl.sense(ai, rng)
        ai.sense(rl, rng)

        rl.rotate_defense(rng)
        ai.rotate_defense(rng)

        rl.upkeep()
        ai.upkeep()
        rl.tick_energy()
        ai.tick_energy()
        rl.tick_input_state()
        ai.tick_input_state()

        eps = max(0.05, 1.0 - step / 300)
        a_idx = rl.form_intention(eps)
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

        resolve_attack(rl, ai, w_rl, rng)
        resolve_attack(ai, rl, w_ai, rng)

        rl_hist.append(rl.force)
        ai_hist.append(ai.force)
        rl.learn(st_before, a_idx, rl.force - f_before, rl.skey())

        winner = check_capture(rl, ai)
        if winner:
            return winner, rl_hist, ai_hist, step
    return None, rl_hist, ai_hist, steps


def run_batch(n_games=10, steps=1000, quiet=False):
    """Пакет партий со сквозным обучением RL (общая Q-таблица через все партии).

    Returns:
        (rl_agent, last_game_tuple, results_dict) — results_dict считает победы
        по ключам "RL" / "UtilityAI" / None (None — «без решения» за steps тактов).
    """
    rl = RLAgent()
    results = {"RL": 0, "UtilityAI": 0, None: 0}
    finals = {"RL": [], "UtilityAI": [], None: []}
    last = None
    for g in range(n_games):
        winner, rl_hist, ai_hist, end_step = play_game(rl, UtilityAI(), steps, seed=g)
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
    наглядно показывающая фазы накопления, окон восприимчивости и доминирования."""
    rl, (winner, rl_hist, ai_hist, end_step), results = run_batch(n_games=10)

    print(f"\nПоследняя партия: winner={winner or 'no-capture'}, шагов={end_step}")
    print(f"Q-состояний изучено: {len(rl.Q)}")

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
