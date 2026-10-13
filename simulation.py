import math
import random
import statistics
import matplotlib.pyplot as plt


# ============================================================================
#  МОДЕЛЬ КОНКУРЕНЦИИ АВТОМАТОВ (универсальная: физическая, информационная,
#  экономическая конкуренция и мирное сосуществование — единый закон)
#
#  Сущности — конечные автоматы на IPO-архитектуре (+BDI). Каждый автомат:
#    СИЛА (force)      — накопленный операционный ресурс; целевая функция.
#    ЭНЕРГИЯ (pool)    — расходуемый запас («солдаты» метафоры); пополняется
#                        потоком floor(sqrt(сила)) и отдыхом; тратится на РАБОТУ.
#    РАБОТА (work)     — целенаправленная передача энергии адресату. Исход
#                        передачи вероятностен; матожидание управляется
#                        стратегией (мощность, тип, момент), а не архитектурой.
#
#  МЕТАФОРА Клаузевица переведена на ОБЩИЙ ЯЗЫК конкуренции — без фронтов,
#  прорывов и рубежей. Единственный скаляр состояния системы адресата:
#  ИСТОЩЕНИЕ (depletion) x >= 0 — накопленный износ от любого давления
#  (рыночного, информационного, физического). Отдача от настойчивости —
#  S-образная кривая:
#        S(x) = (x/X*)^2 / (1 + (x/X*)^2) ∈ [0, 1)
#  Доходы/убытки успешной передачи объёма w с тематическим множителем m:
#        адресант:  + w * m * S(x/X*)     (открытие отдачи давлением)
#        адресат:   - w * (1 + S(x/X*))   (износ усиливается изношенностью)
#  Три следствия, требуемые заказчиком:
#   1. ДАВЛЕНИЕ ЗАТРАТНО НА ПЕРВЫХ ПОРАХ: при свежем адресате (x≈0) отдача
#      адресанта ≈ 0, а цена COST_FRACTION·w уплачивается всегда => ранние
#      попытки убыточны давящему.
#   2. УПОРСТВО МОЖЕТ ОКУПИТЬСЯ: x растёт от КАЖДОГО удара (даже неудачного:
#      +0.5w), S монотонно открывается => при большом x и удачном типе (m=3)
#      матожидание E[dF_a]/w = p·m·S − cost_frac становится положительным.
#   3. НО НЕ ГАРАНТИРОВАННО: окупаемость требует совпадения трёх факторов —
#      накопленного износа, угаданного типа против контр-защиты и везения
#      броска p_success. При m=1 труд убыточен даже при x→∞ (0.6−0.2 > 0 лишь
#      при p≥..., см. эксперимент): просчитанные кампании проигрывают — модель
#      воспроизводит крах тщательно подготовленных операций как СВОЙСТВО,
#      а не рандом. Никакая стратегия не выигрывает по архитектуре.
#
#  Симметричные ограничители (иначе среда вырождается):
#    - предельная стоимость труда: работа списывается из пула безвозвратно;
#    - логистика покоя с потолком L, растущим ТОЛЬКО от труда (безделие
#      стагнирует и голодает upkeep'ом);
#    - кап MAX_WORK и ограничение work <= pool (нет экспоненты отдачи);
#    - медленное заживление x (×0.995/ход): давление без продолжения угасает.
#
#  Равновесие Нэша — смешанное: вылазки в фазе открытой отдачи чередуются с
#  покоем, пока противник свеж и его контр-тип неизвестен.
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

# --- S-КРИВАЯ ДАВЛЕНИЯ (общий закон «упорство окупается, но не гарантированно») ---
X_SCALE = 15.0        # масштаб истощения адресата X*, при котором отдача перегибается
DEPL_MISS = 0.5       # износ от НЕУДАЧНОЙ передачи: x += DEPL_MISS * w
DEPL_HIT = 1.0        # износ от УСПЕШНОЙ передачи: x += DEPL_HIT * w (сам удар изнашивает)
HEAL_RATE = 0.995     # заживление износа за ход (давление без продолжения угасает)
MARGIN = 0.3          # предельная норма давления: доля вложенного, изымаемая у
                      # адресата БЕЗВОЗВРАТНО (сжигается), а не переносимая.
                      # Без неё встречные передачи — нулевой перенос туда-обратно:
                      # обе стороны лишь платят цену и среда вымирает к F=1.

# --- Логистика покоя ------------------------------------------------------------
L_BASE = 60           # базовый потолок силы при полном покое (вершина логистики r/4 > upkeep)
L_STEP = 10           # за каждый накопленный успех (units) потолок +10
MAX_REST_DELTA = 8    # предельная прибыль покоя (вершина логистики)
STARVING_E = 2        # пул <= STARVING_E: рефлекс принудительного отдыха
UPKEEP = 1            # пассивное поддержание структуры (сила тратится на себя)
MAX_WORK = 200        # кап заявленной работы за ход
BELIEF_NOISE = 2      # шум наблюдения пула противника

# --- Решение о поражении: устойчивое доминирование, НЕ один удачный ход ---------
CAPTURE_RATIO = 1.5   # пул победителя >= ratio*пул проигравшего...
CAPTURE_STREAK = 20   # ...устойчиво, CAPTURE_STREAK подряд шагов
CAPTURE_FRAC = 0.10   # база доли силы, перетекающей победителю


def sigmoid(u):
    return 1.0 / (1.0 + math.exp(-u))


def pressure_yield(depletion):
    """Общий закон отдачи от давления (без фронтов, прорывов и рубежей):
    давление на свежую систему почти бесплодно, настойчивость открывает всё
    большую долю отдачи — но никогда полную. Возвращает S ∈ [0, 1):
        S(x) = (x/X*)^2 / (1 + (x/X*)^2)
    Квадратичный рост у нуля (первые потери несёт давящий), насыщение к 1
    (изношенная система теряет больше, чем свежая). Одинаково описывает
    физическое, информационное и экономическое давление."""
    u = max(depletion, 0.0) / X_SCALE
    return (u * u) / (1.0 + u * u)


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
        self.state = {"energy": 3, "defense": self.defense, "last_act": "REST"}
        self.beliefs = {"opp_energy": 3, "opp_defense": None,
                        "opp_last_act": "REST", "opp_last_work": 0,
                        "opp_force": 10, "opp_depletion": 0}

    @property
    def rest_ceiling(self):
        """Предел покоя L(t) = L_BASE + L_STEP*units. РАСТЁТ ТОЛЬКО ОТ ТРУДА:
        units += реально полученная сила при успешной передаче. Безделие =>
        статичный потолок => отставание от работающих. Побудитель к балансу."""
        return L_BASE + L_STEP * self.rest_units

    def rest_gain(self):
        """Логистическая прибыль покоя: dF/dt = r·E·(1 − E/L). Ускорение внизу,
        убывание у потолка, отрицательна выше него. Сетка L_BASE выбрана так,
        что вершина логистики (r/4 при E=L/2) ПРЕВЫШАЕТ upkeep — иначе даже
        равновесный покой убыточен и вся среда вымирает к F=1 (тест на
        жизнеспособность пассивной стратегии)."""
        e = self.force - UPKEEP
        l = self.rest_ceiling
        return MAX_REST_DELTA * (e / l) * (1.0 - e / l)

    def do_rest(self, chosen=True):
        """Применение покоя. Потолок покоя превзойти отдыхом нельзя — только трудом.
        chosen=True  — ОСОЗНАННЫЙ ОТДЫХ (выбор стратегии или рефлекс голода):
                       полная логистическая прибыль + бонусное пополнение пула;
        chosen=False — РЕЖИМ ПОКОЯ (агент бездействовал, потому что утилита/Q
                       отвергли все работы, а голод ещё не наступил): вдвое
                       слабее. Различие принципиально: иначе пассивное ожидание
                       доминирует над и трудом, и настоящим отдыхом, и дуэли
                       замирают в обоюдном ничейном сне (показано диагностикой)."""
        gain = self.rest_gain() if chosen else 0.5 * self.rest_gain()
        self.force = min(self.force + gain, self.rest_ceiling)
        if chosen:
            self.energy_pool = min(self.energy_pool + max(2, self.regen), 2 * self.regen)
        self.last_act, self.last_work = "REST", 0

    @property
    def regen(self):
        """Поток восстановления структуры: dE/dt = floor(sqrt(F))."""
        return max(1, math.floor(math.sqrt(self.force)))

    def tick_energy(self):
        """Пополнение пула происходит ВСЕГДА (и в покое, и в работе): энергия
        восстанавливается потоком ~sqrt(F); отдых дополнительно растит силу.
        Иначе работающий агент гибнет от двойной денудации (пул+сила) и среда
        вымирает к F=1 за десятки шагов (показано диагностикой)."""
        self.energy_pool = min(self.energy_pool + self.regen, 2 * self.regen)

    def sense(self, opp, rng):
        """Input: частичная наблюдаемость — пул (шум), прошлый ход врага, грубая
        оценка силы и НАКОПЛЕННОГО ИСТОЩЕНИЯ противника (наблюдается косвенно:
        сколько его передач провалилось против нашей защиты)."""
        self.beliefs["opp_energy"] = max(1, opp.energy_pool + rng.randint(-BELIEF_NOISE, BELIEF_NOISE))
        self.beliefs["opp_force"] = max(1, int(round(opp.force, -1)))
        self.beliefs["opp_depletion"] = max(0, opp.depletion)
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
        w = min(int(work), self.energy_pool, MAX_WORK, max(1, self.force // 2))
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
            self.do_rest(chosen=True)   # рефлекс голода — полноценный отдых
            return True
        return False

    # --- накопленное давление (истощение) ---
    @property
    def depletion(self):
        """Мера «изношенности» системы адресата: сумма принятых ударов с
        медленным самовосстановлением (структура заживает). Наблюдается
        противником косвенно (через провалы его собственных передач)."""
        return getattr(self, "_depl", 0.0)

    def add_depletion(self, amount):
        self._depl = getattr(self, "_depl", 0.0) + amount

    def heal_depletion(self):
        self._depl = getattr(self, "_depl", 0.0) * HEAL_RATE  # медленное заживление

    def process_hit(self, tr):
        self.force = max(1, self.force - tr)
        self.add_depletion(tr)
        self.energy_pool = max(0, self.energy_pool - tr // 2)
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}

    def gain(self, tr):
        self.force += tr
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}


class UtilityAI(Agent):
    """Заскриптованный агент: утилита по ожидаемой выгоде с учётом S-кривой
    давления. Не обучается — следует аналитической модели того же закона, что
    и среда. Авантюры (работа по свежему противнику) отвергает сама утилита."""
    def __init__(self):
        super().__init__()

    def expected_gain(self, act, work):
        if act == "REST" or work <= 0:
            return self.rest_gain()
        ev = 0.0
        s = pressure_yield(self.beliefs["opp_depletion"])
        for hypo in TYPES:
            m = MULT.get((act, hypo), 1.0)
            p = P_BASE / (1.0 + math.exp(-K_TYPE)) if MULT.get((hypo, act)) else P_BASE
            ev += work * m * s * p / 3.0
        cost = COST_FRACTION * work
        return ev - cost

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
    ВКЛЮЧАЯ оценку истощения противника: Q различает «давить бесполезно» и
    «давление открыло отдачу». Обучение накапливается через партии (общая Q)."""
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
        dep = self.discretize(int(self.beliefs["opp_depletion"]))
        return (self.discretize(self.energy_pool),
                self.discretize(self.beliefs["opp_energy"]),
                self.beliefs["opp_last_act"],
                threat, dep)

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
      2. Успех вероятностен: p_success (мощность, тип против защиты адресата).
      3. При успехе: адресант получает w·m·S(x/X*) — отдача, ОТКРЫВАЕМАЯ
         накопленным износом адресата (давление на свежую систему почти
         бесплодно; настойчивость окупается, но никогда полностью).
         Адресат теряет ВСЁ вложенное плюс процент от открытия: w·(1+S),
         из которых переносится адресанту только w·m·S, а остальное
         сгорает безвозвратно (MARGIN-семантика: часть разрушается при
         передаче, как товар уничтожается ценовой войной). Без безвозвратной
         компоненты передача — нулевой перенос туда-обратно, и встречные
         удары лишь взаимно истощают среду (вымирание к F=1, показано
         диагностикой).
      4. Износ x растёт от ЛЮБОГО удара — и успешного (+DEPL_HIT·w), и
         неудачного (+DEPL_MISS·w): система трескается даже от промахов.
         Двойного учёта нет: потери по формуле СЛЕДСТВИЕ удара, а не ещё
         один источник износа.
    Никаких фронтов/прорывов/рубежей: x — скаляр износа одной природы для
    любой формы конкуренции. Окупаемость НЕ гарантирована архитектурой:
    она требует износа x, угаданного типа (m=3) и везения броска."""
    if not work:
        return
    att.force = max(1, att.force - int(COST_FRACTION * work))
    s = pressure_yield(dfn.depletion)
    if rng.random() < p_success(att.last_act, work, dfn.defense, dfn.last_work):
        m = MULT.get((att.last_act, dfn.defense), 1.0)
        gained = int(work * m * s)
        lost = int(work * (1.0 + s))
        if gained:
            att.gain(gained)
            att.rest_units += gained      # труд порождает рост потолка покоя
        dfn.force = max(1, dfn.force - lost)
        dfn.energy_pool = max(0, dfn.energy_pool - lost // 2)
        dfn.add_depletion(DEPL_HIT * work)   # сам удар изнашивает систему
        dfn.state = {"energy": dfn.energy_pool, "defense": dfn.defense,
                     "last_act": dfn.last_act}
    else:
        # промах: цена уплачена, но давление накоплено — завтра S будет выше
        dfn.add_depletion(DEPL_MISS * work)


def check_capture(rl, ai):
    """Поражение требует УСТОЙЧИВОГО доминирования (серия CAPTURE_STREAK), а не
    одного удачного хода. Тяжесть поражения растёт с глубиной износа
    проигравшего: 'стоять до конца' при большом x означает крах, сопоставимый
    с разгромом (доля перетекающей силы от CAPTURE_FRAC до ~3*CAPTURE_FRAC).
    Формулировка нейтральна: 'устойчивое доминирование' описывает и рынок
    (вытеснение), и инфо-среду (подавление канала), и физическое давление."""
    global _dom_rl, _dom_ai
    _dom_rl = _dom_rl + 1 if (rl.energy_pool >= CAPTURE_RATIO * ai.energy_pool and rl.force > ai.force) else 0
    _dom_ai = _dom_ai + 1 if (ai.energy_pool >= CAPTURE_RATIO * rl.energy_pool and ai.force > rl.force) else 0
    if _dom_rl >= CAPTURE_STREAK:
        _dom_rl = _dom_ai = 0
        s = pressure_yield(ai.depletion)
        cap = int(ai.force * min(CAPTURE_FRAC * (1.0 + 2.0 * s), 0.5))
        ai.force = max(1, ai.force - cap)
        ai.rest_units = max(0.0, ai.rest_units - cap / L_STEP)
        rl.gain(cap)
        return "RL"
    if _dom_ai >= CAPTURE_STREAK:
        _dom_ai = _dom_rl = 0
        s = pressure_yield(rl.depletion)
        cap = int(rl.force * min(CAPTURE_FRAC * (1.0 + 2.0 * s), 0.5))
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
        rl.heal_depletion()
        ai.heal_depletion()

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
    plt.title("Динамика силы агентов (S-кривая отдачи от давления)", fontsize=14)
    plt.xlabel("Шаг симуляции", fontsize=12)
    plt.ylabel("Сила (Force, log)", fontsize=12)
    plt.yscale("log")
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
