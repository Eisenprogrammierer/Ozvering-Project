import math
import random
import statistics
import matplotlib.pyplot as plt


# ============================================================================
#  МОДЕЛЬ КОНКУРЕНЦИИ АВТОМАТОВ (универсальная: физическая, информационная,
#  экономическая конкуренция и мирное сосуществование — единый закон)
#
#  Сущности — конечные автоматы на IPO-архитектуре (+BDI). Никаких новых
#  сущностей сверх согласованных: только СИЛА (целевая функция), ЭНЕРГИЯ
#  (расходуемый запас, сообщаемый выход адресанта) и РАБОТА (передача).
#  Исход передачи определяется количеством сообщаемой работы, выходом
#  адресанта и ВХОДОМ АДРЕСАТА — как договорились ранее.
#
#  «Клаузевиц» переведён на язык модели метафорически, без фронтов/прорывов:
#  давление на систему дорого в начале и может окупиться при упорстве — НО
#  никогда не гарантированно. Реализация — ПОРОГИ ШМИТТА С ГИСТЕРЕЗИСОМ
#  (предложение заказчика): состояние входа адресата бывает ДВУХ видов,
#  переключение по двум разным порогам:
#      закрытый вход (сопротивление): входящая работа гаснет почти полностью;
#      открытый вход (восприимчивость): работа проходит с тематическим множителем.
#  Открытие требует накопленного давления выше порога ON; обратно вход
#  закрывается лишь ниже более низкого порога OFF (гистерезис: шум не
#  дёргает контакт); самопроизвольно вход захлопывается через OPEN_TTL тактов
#  (окно восприимчивости конечно).
#
#  Это единственный скаляр состояния адресата, выводимый из уже принятых
#  им передач (вход IPO): деградация = f(накопленная принятая работа).
#  Никакой отдельной переменной «резистентность/капитал/истощение» не вводится.
#
#  Почему победа — стратегия, а не архитектура и не удача:
#   1. Ранние удары убыточны: цена COST_FRACTION·w платится всегда, а пока
#      вход закрыт, отдача адресанта ≈ 0 — давящий теряет первым.
#   2. Упорство МОЖЕТ открыть окно (накопить w_adopt >= ON) — тогда удар
#      по открытому входу с угаданным типом (m=3) резко выгоден. Но окно
#      конечно (TTL), противник ротирует защиту, а исход каждого удара
#      вероятностен — просчитанные кампании проваливаются. Крах операции
#      — свойство стратегии (недооценка TTL/типа), а не броска кубика.
#   3. Ни одна чистая стратегия не доминирует: вечное давление платит цену
#      по закрытому входу; вечный покой голодает upkeep'ом и стагнирует под
#      логистическим потолком покоя, который растит только труд.
#
#  Симметричные ограничители среды (иначе вырождение):
#   - энергия списывается с пула безвозвратно при работе;
#   - логистика покоя: потолок L растёт ТОЛЬКО от реально полученной силы;
#   - кап MAX_WORK и work <= пул;
#   - восстановление принятых потерь (recouping): адресат возвращает себе
#     долю lost/(1+GAIN_MAX) — перенос силы НЕ мультипликативен, экспонента
#     подавлена, но атакующий остаётся в выигрыше при открытом входе.
#
#  Равновесие — смешанное: вылазки в открытое окно чередуются с накоплением
#  и покоем; момент и мощность удара важнее самого факта давления.
# ============================================================================

TYPES = ["FIRE", "WATER", "EARTH"]
# Тематический множитель передачи (физика/инфо-война/экономика — единый закон):
# WATER > FIRE > EARTH > WATER (круговой контр-тип x3)
MULT = {("WATER", "FIRE"): 3.0, ("FIRE", "EARTH"): 3.0, ("EARTH", "WATER"): 3.0}

ACTIONS = [("REST", 0)] + [(t, w) for t in TYPES for w in [0.3, 0.7]]

# --- Вероятность успеха передачи ------------------------------------------------
P_BASE = 0.6          # базовая вероятность при равенстве мощностей
K_MASS = 1.0          # вес логарифма отношения мощностей
K_TYPE = 0.8          # штраф за контр-тип в защите адресата
COST_FRACTION = 0.2   # цена работы: доля вложенной энергии, сгорающая всегда

# --- ПОРОГИ ШМИТТА ВХОДА АДРЕСАТА (гистерезис «упорство окупается») -------------
ON_THRESHOLD = 40.0   # (справочный)
ON_FRAC = 0.125       # верхний порог Шмитта = доля СИЛЫ адресата (масштабный)
ON_MIN = 6.0          # но не ниже этого
OFF_THRESHOLD = 15.0  # нижний порог (ниже ON!): пока w_adopt > OFF окно держится;
                      # самовольное захлопывание раньше — по таймеру OPEN_TTL
OPEN_TTL = 8          # длительность окна восприимчивости (тактов)
GAIN_MAX = 1.2        # предельная отдача давления: при открытом входе адресант
                      # получает m*w*GAIN_MAX (сверх трения — окно «распахивает»
                      # вход, пропускная способность выше переданного);
                      # закрытый вход даёт y_small
Y_SMALL = 0.05        # отдача по закрытому входу (почти бесполезно, но не ноль)
RECOUP_FRAC = GAIN_MAX / (1.0 + GAIN_MAX)  # возврат адресата: перенос = нулевой
                                           # по сумме; при m=3 атакующий в плюсе
                                           # за счёт тематического множителя
DECAY_ADOPT = 0.95    # накопленное давление на вход медленно остывает (заживление)

# --- ВОЗМЕЗДИЕ (ответный удар): цена безрассудного напора -----------------------
# Работа, сообщённая адресату, не исчезает бесследно: часть её адресат тратит
# на ответную передачу. Без возмездия вечное давление — бесплатная стратегия,
# и PRESSER доминирует в матрице (показано экспериментом). С возмездием
# равновесие — смешанное: копить, бить в открытое окно, беречь резерв.
RETALIATE_FRACTION = 0.5  # доля принятой работы, идущая на ответный удар
HOCK_FRACTION = 0.25      # шок пула от принятого удара: energy -= 0.25*tr
OPTION_VALUE = 0.10       # цена опциона на окно восприимчивости (за единицу
                          # работы при приближении входа противника к ON)

# --- КОЭФФИЦИЕНТ БОЕВОГО ДЕЙСТВИЯ (Клаузевиц, нейтральная формулировка) ---------
# Всякая передача встречает сопротивление среды: прошедшая сила умножается на
# K_EFFECT < 1. Это единственный источник БЕЗВОЗВРАТНЫХ потерь в обмене; при
# K_EFFECT = 1 перенос силы строго консервативен и ни одна форма конкуренции
# не даёт чистого выигрыша (среда вымирает к F=1 — показано диагностикой).
K_EFFECT = 0.70

# --- Логистика покоя ------------------------------------------------------------
L_BASE = 60           # базовый потолок силы при полном покое
L_STEP = 10           # за каждый накопленный успех (units) потолок +10
MAX_REST_DELTA = 8    # предельная прибыль покоя (вершина логистики)
STARVING_E = 2        # пул <= STARVING_E: рефлекс принудительного отдыха
E_MAX_MULT = 3          # потолок пула = 3·sqrt(F) (в такт пополнения regen=sqrt(F))
UPKEEP = 1            # пассивное поддержание структуры (сила тратится на себя)
MAX_WORK = 200        # кап заявленной работы за ход
MIN_OUTPUT = 3          # минимальный легальный выход (анти-catch-22)
BELIEF_NOISE = 2      # шум НАБЛЮДЕНИЯ (частичная наблюдаемость вместо шума результата)

# --- Решение о поражении: устойчивое доминирование, НЕ один удачный ход ---------
CAPTURE_RATIO = 1.5   # пул победителя >= ratio*пул проигравшего...
CAPTURE_STREAK = 20   # ...устойчиво, CAPTURE_STREAK подряд шагов
CAPTURE_FRAC = 0.10   # база доли силы, перетекающей победителю


def p_success(att_type, att_work, dfn_type, dfn_work):
    """Вероятность успешной передачи: вход адресанта (мощность), тип, защита."""
    mass = min(att_work, MAX_WORK) / max(dfn_work, 1)
    penalty = K_TYPE if MULT.get((dfn_type, att_type)) else 0.0
    logit = math.log(mass) * K_MASS - penalty
    return P_BASE / (1.0 + math.exp(-logit))


class Agent:
    """Базовый автомат (IPO + BDI). Символьный state — единственный источник истины.
    Энергия — РЕАЛЬНЫЙ РЕСУРС: расходуется на работу, пополняется потоком
    sqrt(силы) и отдыхом. Сила — накопленный ресурс; целевая функция."""
    def __init__(self, defense=None):
        self.force = 10
        self.energy_pool = 3
        self.rest_units = 0.0   # накопленные успехи: валюта роста потолка покоя
        self.defense = defense if defense is not None else random.choice(TYPES)
        self.last_act = "REST"
        self.last_work = 0
        # Состояние ВХОДА адресата (пороги Шмитта): выводится из принятой работы.
        self.w_adopt = 0.0      # накопленное давление на вход (входящая работа)
        self.in_open = False    # текущее положение «контакта» входа
        self.open_timer = 0     # остаток тактов окна восприимчивости
        self.state = {"energy": 3, "defense": self.defense, "last_act": "REST"}
        self.beliefs = {"opp_energy": 3, "opp_defense": None,
                        "opp_last_act": "REST", "opp_last_work": 0,
                        "opp_force": 10, "opp_w_adopt": 0.0, "opp_in_open": False}

    @property
    def rest_ceiling(self):
        """Предел покоя L(t) = L_BASE + L_STEP*units. РАСТЁТ ТОЛЬКО ОТ ТРУДА:
        units += реально полученная сила при успешной передаче. Безделие =>
        статичный потолок => отставание от работающих. Побудитель к балансу."""
        return L_BASE + L_STEP * self.rest_units

    def rest_gain(self):
        """Логистическая прибыль покоя: dF/dt = r·E·(1 − E/L). Ускорение внизу,
        убывание у потолка, отрицательна выше него. Вершина логистики превышает
        upkeep — иначе равновесный покой убыточен и среда вымирает к F=1."""
        e = self.force - UPKEEP
        l = self.rest_ceiling
        return MAX_REST_DELTA * (e / l) * (1.0 - e / l)

    def do_rest(self, chosen=True):
        """Применение покоя. Потолок покоя превзойти отдыхом нельзя — только трудом.
        chosen=True  — ОСОЗНАННЫЙ ОТДЫХ (выбор стратегии или рефлекс голода);
        chosen=False — РЕЖИМ ПОКОЯ (агент бездействовал, потому что работа
                       отвергнута утилитой/Q, а голод ещё не наступил): вдвое
                       слабее. Иначе пассивное ожидание доминирует над трудом."""
        gain = self.rest_gain() if chosen else 0.5 * self.rest_gain()
        self.force = min(self.force + gain, self.rest_ceiling)
        # Пул пополняется ВСЕГДА (tick_energy делает это каждый такт); здесь
        # лишь добавка за ОСОЗНАННЫЙ покой — но не менее того, что даёт режим.
        # Потолок пула = E_MAX_MULT·sqrt(F): без него агент с F=60 не копит
        # выход больше 4 ед. и никогда не откроет чужой вход (ON=40) — тупик
        # на месте вместо равновесия (показано диагностикой).
        add = max(2, self.regen) if chosen else 1
        self.energy_pool = min(self.energy_pool + add, E_MAX_MULT * self.regen)
        self.last_act, self.last_work = "REST", 0

    @property
    def regen(self):
        """Поток восстановления структуры: dE/dt = floor(sqrt(F))."""
        return max(1, math.floor(math.sqrt(self.force)))

    def tick_energy(self):
        """Пополнение пула происходит ВСЕГДА (и в покое, и в работе),
        до общего потолка E_MAX_MULT·sqrt(F)."""
        self.energy_pool = min(self.energy_pool + self.regen, E_MAX_MULT * self.regen)

    # --- ПОРОГИ ШМИТТА: динамика восприимчивости входа адресата ---
    def receive_pressure(self, w):
        """Input-обработка: всякая входящая работа (успешная или нет) нагружает
        вход. Накопление w_adopt переводит автомат состояний входа:
        closed --(w_adopt >= ON)--> open; open живёт OPEN_TTL тактов и
        захлопывается сама; сброс накопления ниже OFF тоже закрывает её.
        Гистерезис ON > OFF исключает дребезг от шума наблюдений и мелочи."""
        self.w_adopt += w
        # масштабный порог Шмитта: вход крупного автомата требует крупного напора;
        # малый автомат уязвим к малому давлению (asymptote w/(1-decay) >= ON(F) =>
        # w >= ON(F)*0.05 ~ F/8 — достижимо при любом F, catch-22 снят).
        on = max(ON_MIN, ON_FRAC * self.force)
        if not self.in_open and self.w_adopt >= on:
            self.in_open = True
            self.open_timer = OPEN_TTL

    def tick_input_state(self):
        """Тактовка входа: остывание накопленного давления, таймер окна,
        захлопывание по порогу OFF или истечению TTL."""
        self.w_adopt *= DECAY_ADOPT
        if self.in_open:
            self.open_timer -= 1
            if self.open_timer <= 0 or self.w_adopt < OFF_THRESHOLD:
                self.in_open = False

    def sense(self, opp, rng):
        """Input: частичная наблюдаемость — пул (шум наблюдения, НЕ шум результата),
        прошлый ход врага, грубая оценка силы и положения его ВХОДА (наблюдается
        косвенно: сколько своей работы мы ему уже сообщили)."""
        self.beliefs["opp_energy"] = max(1, opp.energy_pool + rng.randint(-BELIEF_NOISE, BELIEF_NOISE))
        self.beliefs["opp_force"] = max(1, int(round(opp.force, -1)))
        self.beliefs["opp_w_adopt"] = max(0.0, opp.w_adopt)
        self.beliefs["opp_in_open"] = opp.in_open
        hist = self.beliefs.setdefault("opp_act_hist", [])
        hist.append(opp.last_act)
        if len(hist) > 5:
            hist.pop(0)
        non_rest = [a for a in hist if a != "REST"]
        self.beliefs["opp_defense_guess"] = max(set(non_rest), key=non_rest.count) if non_rest else None
        self.beliefs["opp_last_act"] = opp.last_act
        self.beliefs["opp_last_work"] = opp.last_work

    def rotate_defense(self, rng):
        """Защита ротируется среди типов, НЕ контрящих последний тип атаки
        противника. Фиксированная защита делала исход предопределённым;
        ротация оставляет место для стратегии (эксплуатация ограничения)."""
        counters = [t for t in TYPES if not MULT.get((self.beliefs["opp_last_act"], t))]
        self.defense = rng.choice(counters) if counters else rng.choice(TYPES)
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}

    def upkeep(self):
        self.force = max(1, self.force - UPKEEP)

    def commit(self, act, work):
        """Фиксирует намерение; работа ограничена пулом (ЭНЕРГИЯ РЕАЛЬНО ТРАТИТСЯ),
        капом MAX_WORK и силой. Отдых, выбранный СТРАТЕГИЕЙ — осознанный;
        вынужденное бездействие (не хватило пула) — режим покоя."""
        if act == "REST":
            self.do_rest(chosen=True)
            return 0
        # Работу автомат может сообщить не только из пула, но и «из себя»:
        # предельный выход ограничен половиной силы — иначе агент с F=3 способен
        # заявить передачу, разрушающую его структуру (диагностика: смерть RL
        # на 19-м шагу именно от этого).
        # Предельный выход: не более четверти структуры за ход, НО минимум 1 —
        # иначе агент на F<=3 попадает в ловушку (работа запрещена, покой нулевой,
        # вечная ничья на дне; показано диагностикой).
        w = min(int(work), self.energy_pool, MAX_WORK, max(MIN_OUTPUT, self.force // 4))
        if w <= 0:
            self.do_rest(chosen=False)
            return 0
        self.energy_pool -= w
        self.last_act, self.last_work = act, w
        return w

    def rest_if_starving(self):
        """Нижний ярус иерархии (рефлекс самосохранения): при критическом пуле
        покой обязателен. Симметричен для обеих сторон."""
        if self.energy_pool <= STARVING_E:
            self.do_rest(chosen=True)
            return True
        return False

    def process_hit(self, tr):
        """Принятый удар: сила теряет tr (часть вернётся давящему консервативным
        переносом в resolve_attack); пул испытывает шок — удар выбивает энергию
        из структуры (доля HOCK_FRACTION). Без шока давление на пассивного не
        истощало бы его вовсе (показано диагностикой: вечная ничья)."""
        self.force = max(1, self.force - tr)
        self.energy_pool = max(0, self.energy_pool - int(HOCK_FRACTION * tr))
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}

    def gain(self, tr):
        self.force += tr
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}


class UtilityAI(Agent):
    """Заскриптованный агент: утилита по ожидаемой выгоде с учётом положения
    входа противника (пороги Шмитта). Не обучается — следует аналитической
    модели того же закона, что и среда. Авантюры (работа по закрытому входу)
    отвергает сама утилита."""
    def __init__(self):
        super().__init__()

    def gain_model(self, m, p):
        """Ожидаемая отдача единицы работы при гипотезе о типе защиты m и
        вероятности успеха p — тот же закон, что в resolve_attack."""
        if self.beliefs["opp_in_open"]:
            return p * m * GAIN_MAX
        base = Y_SMALL * p * m
        # Опционная надбавка за накопление давления: чем ближе вход противника
        # к порогу ON, тем ценнее каждый удар (он покупает будущее окно).
        progress = min(1.0, self.beliefs["opp_w_adopt"] / ON_THRESHOLD)
        option = OPTION_VALUE * progress
        return base + option

    def expected_retaliation(self, work):
        """Ожидание возмездия: адресат бьёт в ответ долей RETALIATE_FRACTION*w.
        Наш тип атаки меняет его защиту только через ротацию; грубая оценка —
        средний множитель по кругу типов и вероятность успеха ответки."""
        r_w = int(RETALIATE_FRACTION * work)
        if r_w <= 0:
            return 0.0
        ev_loss = 0.0
        for hypo_def in TYPES:          # гипотезы о защите ОТВЕТА (= его defense)
            mr = MULT.get((hypo_def, self.defense), 1.0)
            pr = P_BASE / (1.0 + math.exp(-K_TYPE)) if MULT.get((self.beliefs["opp_last_act"], hypo_def)) else P_BASE
            g = self.gain_model_rev(mr, pr)
            ev_loss += r_w * g / 3.0
        return ev_loss

    def gain_model_rev(self, m, p):
        """Отдача ответного удара по НАШЕМУ входу (наше состояние наблюдаемо нам точно)."""
        if self.in_open:
            return p * m * GAIN_MAX
        return Y_SMALL * p * m

    def retaliation_penalty(self, work):
        """Возмездие — не только ожидаемая сила, но и шок пула: удар выбивает
        HOCK_FRACTION*r_w энергии из нашего запаса. Для агента, живущего от
        пула, это реальная цена: бить по открытому противнику дорого."""
        r_w = int(RETALIATE_FRACTION * work)
        return COST_FRACTION * work + HOCK_FRACTION * r_w

    def expected_gain(self, act, work):
        if act == "REST" or work <= 0:
            return self.rest_gain()
        ev = 0.0
        for hypo in TYPES:
            m = MULT.get((act, hypo), 1.0)
            p = P_BASE / (1.0 + math.exp(-K_TYPE)) if MULT.get((hypo, act)) else P_BASE
            ev += work * self.gain_model(m, p) / 3.0
        return ev - self.retaliation_penalty(work) - self.expected_retaliation(work)

    def form_intention(self):
        best, best_u = ("REST", 0), self.rest_gain()
        for t in TYPES:
            for frac in (0.3, 0.7):
                w = int(self.energy_pool * frac)
                u = self.expected_gain(t, w)
                if u > best_u:
                    best, best_u = (t, w), u
        return best


class RLAgent(Agent):
    """Обучающийся агент (Q-Learning). Состояние — дискретизированные beliefs,
    ВКЛЮЧАЯ положение входа противника: Q различает «давить бесполезно» и
    «окно открыто — бей». Обучение накапливается через партии (общая Q)."""
    def __init__(self, q=None):
        super().__init__()
        self.Q = q if q is not None else {}

    def discretize(self, e):
        if e <= 8:
            return e
        if e <= 32:
            return 8 + (e - 8) // 4
        return 14 + int(math.log(e / 32))

    def skey(self):
        threat = "T" if MULT.get((self.beliefs["opp_last_act"], self.defense)) else "-"
        adopt = self.discretize(int(self.beliefs["opp_w_adopt"]))
        openg = "O" if self.beliefs["opp_in_open"] else "C"
        return (self.discretize(self.energy_pool),
                self.discretize(self.beliefs["opp_energy"]),
                self.beliefs["opp_last_act"],
                threat, adopt, openg)

    def form_intention(self, eps):
        st = self.skey()
        if st not in self.Q:
            self.Q[st] = [0.0] * len(ACTIONS)
        if random.random() < eps:
            return random.randint(0, len(ACTIONS) - 1)
        return self.Q[st].index(max(self.Q[st]))

    def learn(self, st, a_idx, reward, nst, alpha=0.3, gamma=0.9):
        """Корректный переход s -> s': состояние ДО действия и найденное ПОСЛЕ."""
        if nst not in self.Q:
            self.Q[nst] = [0.0] * len(ACTIONS)
        td = reward + gamma * max(self.Q[nst]) - self.Q[st][a_idx]
        self.Q[st][a_idx] += alpha * td


def resolve_attack(att, dfn, work, rng):
    """Единая механика передачи — общий закон конкуренции (физической,
    информационной, экономической; мирное сосуществование = работа=0).
      1. Цена работы: COST_FRACTION·w сгорает всегда (энергия тратится
         безвозвратно — предельная стоимость давления).
      2. Всякая входящая работа нагружает вход адресата (пороги Шмитта):
         накопление >= ON открывает окно восприимчивости на OPEN_TTL тактов.
      3. Успех вероятностен (p_success: мощность, тип против защиты).
      4. При успехе:
           адресант:  + w·m·GAIN_MAX, если вход ОТКРЫТ (окно восприимчивости);
                       + w·m·Y_SMALL, если закрыт (почти бесплодно).
           адресат:   − w (принятые потери) и возврат RECOUP_FRAC·w —
                       перенос силы НЕ мультипликативен (суммарно ~0 при m=1);
                       выгода давящего идёт от тематического множителя m=3
                       в момент открытого окна и угаданного типа.
      5. Промах: цена уплачена, отдачи нет, НО давление на вход накоплено —
         завтра окно может открыться. Износ копят и успешные, и неудачные
         удары: система «трескается» от любого напора.
    Окупаемость НЕ гарантирована архитектурой: нужен накопленный напор,
    угаданный тип (m=3), попадание броска и резерв сил в такт открытого
    окна (которое конечно). Просчитанные кампании гибнут — это свойство
    стратегии, а не случайности."""
    if not work:
        return
    att.force = max(1, att.force - int(COST_FRACTION * work))
    open_now = dfn.in_open              # положение входа ДО данного удара:
                                        # инерция системы — удар, переполнивший
                                        # чашу, сам ещё НЕ проходит сквозь неё;
                                        # окно откроется лишь следующему давящему
                                        # («фронт трескается между боями»)
    dfn.receive_pressure(work)          # любой удар нагружает вход адресата
    hit = rng.random() < p_success(att.last_act, work, dfn.defense, dfn.last_work)
    gained = 0
    if hit:
        m = MULT.get((att.last_act, dfn.defense), 1.0)
        gained = int(work * m * (GAIN_MAX if open_now else Y_SMALL))
        if gained:
            att.gain(gained)
            att.rest_units += gained    # труд порождает рост потолка покоя
        dfn.process_hit(work)           # принятые потери = вложенная работа
        # ТРЕНИЕ ПЕРЕДАЧИ (K_EFFECT): адресат восстанавливает лишь долю
        # принятого удара. work - K_EFFECT*work сгорает безвозвратно — это
        # единственный источник чистых потерь в обмене; при K_EFFECT=1 перенос
        # консервативен и ни одна форма конкуренции не даёт чистого выигрыша
        # (среда вымирает к F=1 — показано диагностикой).
        dfn.force = max(1, dfn.force + int(K_EFFECT * work))

    # --- ВОЗМЕЗДИЕ: ответный удар адресата ---
    # Принятая работа не исчезает бесследно: её часть адресат немедленно
    # тратит на обратную передачу (возвращённая энергия). Это делает грубое
    # давление на свежую систему самоубийственным: проигравший обмен
    # возвращает давящему меньше, чем отняла ответка. Возмездие симметрично:
    # точно такой же закон действует, когда этот агент сам получает удар.
    r_w = int(RETALIATE_FRACTION * work)
    if r_w > 0 and dfn.energy_pool >= 1:
        r_w = min(r_w, dfn.energy_pool, MAX_WORK)
        dfn.energy_pool -= r_w
        dfn.last_act = dfn.defense      # отвечает своим типом защиты
        dfn.last_work = r_w
        rt = rng.random() < p_success(dfn.last_act, r_w, att.defense, att.last_work)
        if rt:
            mr = MULT.get((dfn.last_act, att.defense), 1.0)
            rg = int(r_w * mr * (GAIN_MAX if att.in_open else Y_SMALL))
            if rg:
                dfn.gain(rg)
                dfn.rest_units += rg
            att.process_hit(r_w)
            att.force = max(1, att.force + int(K_EFFECT * r_w))  # трение и для ответки
            att.state = {"energy": att.energy_pool, "defense": att.defense,
                         "last_act": att.last_act}


def check_capture(rl, ai):
    """Поражение требует УСТОЙЧИВОГО доминирования (серия CAPTURE_STREAK), а не
    одного удачного хода. Тяжесть поражения растёт с положением входа
    проигравшего: разгром сопоставим с крахом, если он встречает решение о
    доминировании с открытым (надорванным) входом. Формулировка нейтральна:
    'устойчивое доминирование' описывает и рынок (вытеснение), и инфо-среду
    (подавление канала), и физическое давление."""
    global _dom_rl, _dom_ai
    _dom_rl = _dom_rl + 1 if (rl.energy_pool >= CAPTURE_RATIO * ai.energy_pool and rl.force > ai.force) else 0
    _dom_ai = _dom_ai + 1 if (ai.energy_pool >= CAPTURE_RATIO * rl.energy_pool and ai.force > rl.force) else 0
    if _dom_rl >= CAPTURE_STREAK:
        _dom_rl = _dom_ai = 0
        sev = 2.0 if ai.in_open else 1.0
        cap = int(ai.force * min(CAPTURE_FRAC * sev, 0.5))
        ai.force = max(1, ai.force - cap)
        ai.rest_units = max(0.0, ai.rest_units - cap / L_STEP)
        rl.gain(cap)
        return "RL"
    if _dom_ai >= CAPTURE_STREAK:
        _dom_ai = _dom_rl = 0
        sev = 2.0 if rl.in_open else 1.0
        cap = int(rl.force * min(CAPTURE_FRAC * sev, 0.5))
        rl.force = max(1, rl.force - cap)
        rl.rest_units = max(0.0, rl.rest_units - cap / L_STEP)
        ai.gain(cap)
        return "UtilityAI"
    return None


_dom_rl = 0
_dom_ai = 0


def play_game(rl, ai, steps=1000, seed=0):
    """Одна партия. RL сохраняет Q-таблицу между партиями (перенос обучения)."""
    global _dom_rl, _dom_ai
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
        rl.tick_input_state()   # тактовка порогов Шмитта обоих входов
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
    """Пакет прогонов: RL обучается сквозняком через партии (общая Q-таблица)."""
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
