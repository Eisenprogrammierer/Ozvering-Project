import math
import random
import statistics
import matplotlib.pyplot as plt


TYPES = ["FIRE", "WATER", "EARTH"]
# Тройной множитель по кругу: WATER > FIRE > EARTH > WATER
MULT = {("WATER", "FIRE"): 3.0, ("FIRE", "EARTH"): 3.0, ("EARTH", "WATER"): 3.0}

# Действия: отдых либо атака типом с долей работы 0.3/0.7
ACTIONS = [("REST", 0)] + [(t, w) for t in TYPES for w in [0.3, 0.7]]

# --- Параметры передачи энергии (мощность и вероятность) ---
P_BASE = 0.6          # базовая вероятность успеха при равенстве мощностей
K_MASS = 1.0          # вес логарифма отношения масс (мощности)
K_TYPE = 0.8          # штраф за контр-тип в защите адресата
COST_FRACTION = 0.2   # цена атаки: доля заявленной работы, сгорающая всегда
# --- ЛОГИСТИКА ОТДЫХА (починка «непобедимого пассива») ---
# Прежний отдых давал чистый +REST_GAIN в силу КАЖДЫЙ ход без ограничений,
# из-за чего стратегия «вечно отдыхать» была строго доминирующей. Теперь
# прибыль отдыха — логистическая кривая: пока структура слаба, отдых даёт
# всё больше (ускорение), но у силы есть естественный предел покоя L(t):
# «безделие чревато отставанием от конкурентов» — потолок растёт только от
# АКТИВНОСТИ (успешных передач). Кто не работает, тот стагнирует: дельта
# отдыха стремится к нулю на потолке и отрицательна выше него.
# КАЛИБРОВКА: в средней зоне чистый отдых (gain - upkeep) должен быть ПОЛОЖИТЕЛЕН,
# иначе среда смертельна для всех и партии вырождаются во взаимное истощение к F=1.
# При r=8, L=30: net(отдых) > 0 для F в ~[7..27], пик +1.0 у F=15; на краях — отрицателен.
L_BASE = 30           # базовый потолок силы при полном покое
L_STEP = 10           # за каждый накопленный успех (units) потолок +10
MAX_REST_DELTA = 8    # предельная прибыль отдыха (dF/dt при E=0, x=L/2)
STARVING_E = 2        # энергия <= STARVING_E: рефлекс принудительного отдыха
RECOVERY_FLOOR = 1    # гарантированный минимум восстановления силой в полном покое
                      # (нейтрализует upkeep на «последнем рубеже»; потолок L(t) не обходится:
                      # выше потолка отдых по-прежнему не даёт роста)
UPKEEP = 1            # пассивное поддержание структуры (сила тратится на себя)
MAX_WORK = 200        # кап заявленной работы за ход (стабилизирует экспоненту)
BELIEF_NOISE = 2      # шум наблюдения энергии противника (+/- BELIEF_NOISE)
CAPTURE_RATIO = 1.5   # порешение: энергия победителя >= ratio*проигравшего...
CAPTURE_STREAK = 20   # ...УСТОЙЧИВО, на протяжении CAPTURE_STREAK подряд шагов
CAPTURE_FRAC = 0.10   # доля силы проигравшего, перетекающая победителю
# --- КЛАУЗЕВИЦ: оборона сильна до прорыва (см. breach_factor) ---
BREACH_K = 8          # пологость перехода «до/после прорыва» (чем больше, тем резче)

_dom_rl = 0           # текущая серия доминирования RL-агента
_dom_ai = 0           # текущая серия доминирования UtilityAI


def p_success(att_type, att_work, dfn_type, dfn_work):
    """Вероятность успешной передачи: зависит от входа адресанта (работа),
    типа энергии и защиты адресата. Детерминизм убран: исход хода —
    случайная величина, но её матожидание управляется стратегией."""
    mass = min(att_work, MAX_WORK) / max(dfn_work, 1)
    penalty = K_TYPE if MULT.get((dfn_type, att_type)) else 0.0
    logit = math.log(mass) * K_MASS - penalty
    return P_BASE / (1.0 + math.exp(-logit))


# ===================== ПРЕДЕЛ ТРУДА (ОСТАНОВИТЕЛЬ ЭКСПОНЕНТЫ) =====================
# Клаузевиц: «наступление истощается» — атака не может масштабироваться линейно по
# накопленной силе. Без этого положительная обратная связь (приём -> рост regen ->
# больший пул -> больший удар) даёт взрыв F до 10^4 в экспоненциальной фазе прорыва.
# Формально: эффективная работа w_eff = w / (1 + w/F_att) <= F_att/2 — убывающая
# отдача относительно операционного ресурса наступающего. При малых w (w << F)
# w_eff ~ w (ничего не меняется в зоне тактики); при w >> F — насыщение ~F/2.
def effective_work(work, f_att):
    """Насыщающаяся отдача труда: предельный труд ограничен долей силы наступателя."""
    if work <= 0:
        return 0
    return int(work * f_att / (f_att + work))   # <= w и <= F/2


# ===================== КЛАУЗЕВИЦ: ОБОРОНА СИЛЬНА ДО ПРОРЫВА =====================
# Аналогия (оперативный ресурс -> СИЛА, солдаты -> ЭНЕРГИЯ, наступление -> РАБОТА):
# обороняющийся держит рубеж, пока его структура (сила F_d) выше наступающего
# (F_a). Пока рубеж держится — потери несут наступающие: цена работы повышена
# (COST_DEFENDER_HELD > COST_FRACTION), а успех передач редок (p делится на DEF_SHOCK).
# Как только силы сравнялись/наступающий превзошёл — рубеж ПРОБИТ, и дальше потери
# несут уже обороняющиеся, причём «куда как больше»: урон передачей усиливается
# множителем прорыва B(t), растущим лавинообразно по мере удаления победителя.
# Отступление (сознательное или вынужденное поражением) = добровольная потеря
# части силы ради сохранения пула энергии; на новом рубеже защита получает
# временный шок-бонус (DEF_SHOCK восстанавливается) — «отступать на более
# выгодный рубеж и нести больше потерь на первых этапах отступления».
# СТОЯТЬ ДО КОНЦА = отказ отступить => при глубоком прорыве поражение
# сопоставимо с разгромом (CAPTURE_FRAC растёт с глубиной прорыва).
# Формализация перехода «до/после» — сигмоида по логарифму отношения сил:
#   B(r) = 1 + (B_MAX-1)*sigmoid(K*(ln r - ln R_BREACH)),  r = F_a/F_d >= 1
# B=1 до прорыва, B->B_MAX глубоко за прорывом; резкость задаёт BREACH_K.
DEF_SHOCK = 2.5       # оборона до прорыва: вероятность успеха атакующего /DEF_SHOCK
COST_DEFENDER_HELD = 0.45  # цена работы, пока рубеж держится (против COST_FRACTION=0.2)
R_BREACH = 1.0        # порог отношения сил, после которого рубеж считается пробитым
B_MAX = 3.0           # предел множителя прорыва (лавина после прорыва)


def breach_factor(f_att, f_def):
    """Множитель тяжести потерь ОБОРОНЯЮЩЕГОСЯ после прорыва. До прорыва (r<=1)
    РАВЕН ЕДИНИЦЕ (иначе «лавина» включается раньше рубежа и оборона не защищена —
    встречная драка убивала обоих, см. эксперимент Э7); после прорыва — сигмоидальный
    рост к B_MAX. Симметрично: чей рубеж пробит, тот и теряет помноженное."""
    r = max(f_att, 1) / max(f_def, 1)
    if r < R_BREACH:
        return 1.0
    x = BREACH_K * (math.log(r) - math.log(R_BREACH))
    return 1.0 + (B_MAX - 1.0) / (1.0 + math.exp(-x))


def defender_holds(f_att, f_def):
    """Рубеж держится, пока обороняющийся не слабее наступающего (r < 1)."""
    return f_att < f_def


class Agent:
    """Базовый автомат (IPO + BDI). Символьный state — единственный источник истины.
    Энергия — РЕАЛЬНЫЙ РЕСУРС: расходуется на работу и пополняется отдыхом/успешной
    передачей. Формула энергии = floor(sqrt(сила)) сохранена как ПОТОК (восстановление),
    а не как мгновенное значение: за шаг агент восстанавливает ~sqrt(force) единиц."""
    def __init__(self, defense=None):
        self.force = 10
        self.energy_pool = 3
        self.rest_units = 0.0   # накопленные «успехи»: единственная валюта роста потолка покоя
        # защита ротируется каждый ход (см. rotate_defense) — фиксированный тип
        # делал исход предопределённым (контр-тип гарантировал победу)
        self.defense = defense if defense is not None else random.choice(TYPES)
        self.last_act = "REST"
        self.last_work = 0
        self.state = {"energy": 3, "defense": self.defense, "last_act": "REST"}
        self.beliefs = {"opp_energy": 3, "opp_defense": None,
                        "opp_last_act": "REST", "opp_last_work": 0,
                        "opp_force": 10}

    @property
    def rest_ceiling(self):
        """Естественный предел силы при покое L(t) = L_BASE + L_STEP*units.
        Потолок РАСТЁТ ТОЛЬКО ОТ АКТИВНОСТИ: units += реально переданная сила при
        успешной передаче. Безделие => статичный потолок => отставание от тех,
        кто работает (их потолок растёт). Это и есть побудитель к балансу."""
        return L_BASE + L_STEP * self.rest_units

    def rest_gain(self):
        """Логистическая прибыль отдыха: dF/dt = r*E*(1 - E/L), E = force - upkeep.
        Пока структура далеко ниже потолка — отдых даёт всё БОЛЬШЕ (ускорение);
        у потолка — убывает; выше потолка — отрицателен (излишества безделья)."""
        e = self.force - UPKEEP
        l = self.rest_ceiling
        return MAX_REST_DELTA * (e / l) * (1.0 - e / l)

    def do_rest(self):
        """Единая точка применения отдыха (осознанный выбор И рефлекс голода):
        сила растёт на логистическую дельту, но НЕ более чем до потолка покоя
        (потолок можно превзойти только трудом — передачей энергии).
        ГАРАНТИРОВАННЫЙ МИНИМУМ RECOVERY_FLOOR: разбитая в щепки структура («остатки
        армии») в полном покое восстанавливается хотя бы на уровень распада upkeep —
        иначе падение к F<=4 необратимо и партия вырождается в зависание двух трупов.
        Предел покоя L(t) по-прежнему запрещает расти без труда: потолок не обходится."""
        self.force = min(max(self.force + self.rest_gain(),
                             self.force + RECOVERY_FLOOR), self.rest_ceiling)
        # пул восстанавливается отдыхом быстрее пассивного потока: «солдат»
        # пополняется в покое; без этого агенты с F<=4 умирали от истощения
        self.energy_pool = min(self.energy_pool + max(2, self.regen), 2 * self.regen)
        # ОТДЫХ ПОД РУБЕЖОМ: пока противник сильнее (рубеж держим вынужденно),
        # часть сил уходит на удержание линии фронта: floor = RECOVERY_FLOOR - UPKEEP.
        # Это цена фазы обороны («первоначальные потери обороняющегося») и одновременно
        # стимул не прятаться в вечный покой при численном преимуществе врага.
        opp_f = self.beliefs.get("opp_force")
        if opp_f is not None and opp_f > self.force:
            self.force = max(1, self.force - UPKEEP)
        self.last_act, self.last_work = "REST", 0

    @property
    def regen(self):
        """Поток восстановления структуры: dE/dt = floor(sqrt(F)) (энергия как мера силы)."""
        return max(1, math.floor(math.sqrt(self.force)))

    def tick_energy(self):
        """Обновление пула энергии: пассивная регенерация (поток sqrt(силы)), кап = 2*regen."""
        self.energy_pool = min(self.energy_pool + self.regen, 2 * self.regen)

    def sense(self, opp, rng):
        """Input: частичная наблюдаемость — видим пул энергии (шум) и прошлый ход врага.
        Тип защиты адресата НЕ наблюдаем напрямую: оценка формируется через
        скользящее большинство последних действий противника (символьные beliefs)."""
        self.beliefs["opp_energy"] = max(1, opp.energy_pool + rng.randint(-BELIEF_NOISE, BELIEF_NOISE))
        # сила противника наблюдаема лишь грубо (округление до порядка): частичная наблюдаемость
        self.beliefs["opp_force"] = max(1, int(round(opp.force, -1)))
        hist = self.beliefs.setdefault("opp_act_hist", [])
        hist.append(opp.last_act)
        if len(hist) > 5:
            hist.pop(0)
        non_rest = [a for a in hist if a != "REST"]
        if non_rest:
            self.beliefs["opp_defense_guess"] = max(set(non_rest), key=non_rest.count)
        else:
            self.beliefs["opp_defense_guess"] = None
        self.beliefs["opp_last_act"] = opp.last_act
        self.beliefs["opp_last_work"] = opp.last_work

    def rotate_defense(self, rng):
        """Защита ротируется каждый ход среди типов, НЕ контрящих последний тип атаки
        противника (наблюдаемый). Это не 'читерство' и не случайность ради случайности:
        фиксированная защита делала исход предопределённым (контр-тип гарантировал
        победу); ротация оставляет место для стратегии — агент может эксплуатировать
        ограничение ротации, угадывая оставшиеся два типа."""
        counters = [t for t in TYPES if not MULT.get((self.beliefs["opp_last_act"], t))]
        self.defense = rng.choice(counters) if counters else rng.choice(TYPES)
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}

    def upkeep(self):
        """Поддержание структуры: сила расходуется на саму себя каждый ход."""
        self.force = max(1, self.force - UPKEEP)

    def commit(self, act, work):
        """Фиксирует намерение; работа ограничена ДОСТУПНЫМ ПУЛОМ энергии (тратится!),
        капом и силой. Отдых — логистический прирост структуры (см. do_rest)."""
        if act == "REST":
            self.do_rest()
            return 0
        w = min(int(work), self.energy_pool, MAX_WORK)
        if w <= 0:                      # энергии нет — тело не слушается: принудительный отдых
            self.do_rest()
            return 0
        self.energy_pool -= w           # ЭНЕРГИЯ РЕАЛЬНО ТРАТИТСЯ НА РАБОТУ
        self.last_act, self.last_work = act, w
        return w

    RETREAT_FRAC = 0.25     # теряемая доля силы при отступлении
    RETREAT_TRIGGER = 1.6   # рубеж проигран, если F_opp > trigger*F_self (противник явно сильнее)

    def try_retreat(self):
        """Отступление по Клаузевицу: сознательная потеря доли силы ради сохранения
        пула энергии («солдат») и занятия более выгодного рубежа. Компенсации:
        энергия НЕ утрачивается при организованном уходе, а отдых восстанавливает
        структуру только до нового (пониженного) потолка покоя — отступивший платит
        тем, что его «бездеятельный предел» падает вместе с broken units."""
        opp_f = self.beliefs.get("opp_force", self.force)
        if self.force <= 5 or self.force * self.RETREAT_TRIGGER >= opp_f:
            return False                      # отступать рано или не из чего
        lost = int(self.force * self.RETREAT_FRAC)
        self.force = max(1, self.force - lost)
        self.rest_units = max(0.0, self.rest_units - lost / L_STEP)
        self.last_act, self.last_work = "RETREAT", 0
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": "RETREAT"}
        return True

    def rest_if_starving(self):
        """Инстинкт самосохранения автомата: при критическом пуле энергии отдых обязателен.
        Это нижний ярус иерархии (рефлекс), не подлежащий ни утилитарному расчёту,
        ни Q-разведке — иначе агенты взаимно вымирают в nash-равновесии 'все атакуют'.
        Рефлекс симметричен: обе стороны получают тот же шанс восстановления."""
        if self.energy_pool <= STARVING_E:
            self.do_rest()
            return True
        return False

    def process_hit(self, tr):
        """Обработка входящей передачи: потеря силы И части пула энергии (структура повреждена)."""
        self.force = max(1, self.force - tr)
        self.energy_pool = max(0, self.energy_pool - tr // 2)
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}

    def gain(self, tr):
        self.force += tr
        self.state = {"energy": self.energy_pool, "defense": self.defense,
                      "last_act": self.last_act}


class UtilityAI(Agent):
    """Заскриптованный агент: утилита по ожидаемой выгоде с УЧЁТОМ ФАЗ БОЯ
    (Клаузевиц). До прорыва чужого рубежа атака убыточна (цена x2.25, успех /DEF_SHOCK)
    — утилита это отражает и сама отвергает авантюры; после прорыва B(r)>1 делает
    работу выгодной. Отступление — отдельное намерение (ниже порога триггера)."""
    def __init__(self):
        super().__init__()

    def expected_gain(self, act, work):
        ev = 0.0
        for hypo in TYPES:
            m = MULT.get((act, hypo), 1.0)
            p = P_BASE / (1.0 + math.exp(-K_TYPE)) if MULT.get((hypo, act)) else P_BASE
            ev += work * m * p / 3.0
        # фаза: наступаем на того, кто сильнее нас? => рубеж держится, потери наши
        held = defender_holds(self.force, self.beliefs["opp_force"])
        if held:
            ev /= DEF_SHOCK                      # успех редок до прорыва
            cost_frac = COST_DEFENDER_HELD
        else:
            B = breach_factor(self.force, self.beliefs["opp_force"])
            ev *= min(B, B_MAX)                  # после прорыва потери врага помножены
            cost_frac = COST_FRACTION
        loss_m = 1.0 * 0.5 + 3.0 * 0.5
        cost = cost_frac * work + 0.5 * self.beliefs["opp_last_work"] * loss_m
        return ev - cost

    def form_intention(self):
        best, best_u = ("REST", 0), self.rest_gain()   # отдых = логистическая дельта силы
        for t in TYPES:
            for frac in (0.3, 0.7):
                w = int(self.energy_pool * frac)
                u = self.expected_gain(t, w)
                if u > best_u:
                    best, best_u = (t, w), u
        return best


class RLAgent(Agent):
    """Обучающийся агент (Q-Learning). Состояние — дискретизированные beliefs
    плюс ФАЗА БОЯ (держит/пробит) — чтобы Q-значения различали «до прорыва» и
    «после прорыва»: там разные оптимальные действия. RETREAT — отдельное действие."""
    def __init__(self, q=None):
        super().__init__()
        self.Q = q if q is not None else {}

    def discretize(self, e):
        if e <= 8:
            return e
        if e <= 32:
            return 8 + (e - 8) // 4
        return 14 + int(math.log(e / 32))

    def phase(self):
        """r = F_self/F_opp в лог-шкале, квантованно: -2..+2 (до/после прорыва)."""
        r = math.log(max(self.force, 1) / max(self.beliefs["opp_force"], 1))
        return max(-2, min(2, int(round(r * 2))))

    def skey(self):
        threat = "T" if MULT.get((self.beliefs["opp_last_act"], self.defense)) else "-"
        return (self.discretize(self.energy_pool),
                self.discretize(self.beliefs["opp_energy"]),
                self.beliefs["opp_last_act"],
                threat, self.phase())

    def form_intention(self, eps):
        st = self.skey()
        na = len(ACTIONS) + 1          # последнее действие — RETREAT
        if st not in self.Q:
            self.Q[st] = [0.0] * na
        if random.random() < eps:
            return random.randint(0, na - 1)
        return self.Q[st].index(max(self.Q[st]))

    def learn(self, st, a_idx, reward, nst, alpha=0.3, gamma=0.9):
        """Корректный переход s -> s': вызывается с состоянием ДО применения
        действия и НАЙДЕННЫМ состоянием ПОСЛЕ (U = delta + gamma*reward(t))."""
        if nst not in self.Q:
            self.Q[nst] = [0.0] * (len(ACTIONS) + 1)
        td = reward + gamma * max(self.Q[nst]) - self.Q[st][a_idx]
        self.Q[st][a_idx] += alpha * td


def resolve_attack(att, dfn, work, rng):
    """Атака: часть работы сгорает как цена, остальное — заявленная мощность.
    Успех вероятностный; при успехе передаётся work*m (сила адресата не тратится).
    Реальный труд порождает рост: units адресанта += реально переданная сила
    (успешные передачи поднимают его потолок покоя — см. rest_ceiling)."""
    att.force = max(1, att.force - int(COST_FRACTION * work))
    if work and rng.random() < p_success(att.last_act, work, dfn.defense, dfn.last_work):
        tr = int(work * MULT.get((att.last_act, dfn.defense), 1.0))
        att.gain(tr)
        att.rest_units += tr
        dfn.process_hit(tr)


# --- ЭКОНОМИЧЕСКИЙ БАЛАНС (калибровка) ---
# В прежней среде отдых давал чистый +REST_GAIN в силу без ограничений, а атака —
# ~0 чистой выгоды (отнятое у цели work*m агент тут же получал обратно). Поэтому
# пассивная стратегия «вечно отдыхать» была строго доминирующей. ЛОГИСТИКА ОТДЫХА
# (см. rest_gain/rest_ceiling) ограничила прибыль покоя потолком L(t), растущим
# только от успешных передач. Для дальнейшей калибровки вводим ФУНДАМЕНТАЛЬНЫЙ
# закон модели: сила — мера способности сообщать энергию; при успешной передаче
# адресат теряет ровно столько способности, сколько потерял адресант энергии,
# то есть delta(сила адресата) = -work (без множителя), а множитель типа x3 остаётся
# на стороне ПРИЁМА (delta(сила адресанта) = +work*m). Тогда атака становится
# чистым выигрышем только при удачном типе/мощности, а промах — чистым убытком:
# баланс сил перестаёт быть производным от порядка ходов.
POWER_LAW = True    # Клаузевиц включён: потери после прорыва необратимы (перенос с множителем B)


def resolve_attack_calibrated(att, dfn, work, rng):
    """Единая механика передачи с КЛАУЗЕВИЦЕМ (POWER_LAW — переключаемый калибровочный
    закон переноса силы; фазы боя — всегда включены):

    ФАЗА 1. Рубеж держится (F_att < F_def): потери несут наступающие.
      - цена работы повышена: COST_DEFENDER_HELD вместо COST_FRACTION;
      - успех передач редок: p_eff = p_success / DEF_SHOCK.
    ФАЗА 2. Рубеж пробит (r = F_att/F_def >= R_BREACH): потери несут обороняющиеся,
    «куда как больше»: урон передачей умножается на B(r) = breach_factor (->B_MAX).
    При POWER_LAW способность адресата уходит безвозвратно (-work*B), при приём
    адресант получает work*m (множитель типа остаётся на стороне приёма)."""
    if not work:
        return
    held = defender_holds(att.force, dfn.force)
    cost_frac = COST_DEFENDER_HELD if held else COST_FRACTION
    att.force = max(1, att.force - int(cost_frac * work))
    p = p_success(att.last_act, work, dfn.defense, dfn.last_work)
    if held:
        p /= DEF_SHOCK                       # оборона сильна до прорыва
    if rng.random() >= p:
        return
    m = MULT.get((att.last_act, dfn.defense), 1.0)
    tr = int(work * m)
    att.gain(tr)                             # приём усиливает адресанта по множителю типа
    att.rest_units += tr                     # труд порождает рост потолка покоя
    if POWER_LAW:
        B = breach_factor(att.force, dfn.force)   # лавина после прорыва
        dfn.force = max(1, dfn.force - work * B)  # способность уходит помноженной
        dfn.energy_pool = max(0, dfn.energy_pool - int(work * B) // 2)
    else:
        dfn.process_hit(tr)                  # прежняя механика: перенос work*m


def check_capture(rl, ai):
    """Решение о поражении НЕ детерминировано одним удачным ходом: требуется
    устойчивое доминирование — серия из CAPTURE_STREAK шагов. Но ТЯЖЕСТЬ поражения
    по Клаузевицу зависит от глубины прорыва: 'стоять до конца' при B(r)>>1 означает
    поражение, сопоставимое с разгромом — доля перетекающей силы растёт от
    CAPTURE_FRAC до ~B_MAX*CAPTURE_FRAC."""
    global _dom_rl, _dom_ai
    _dom_rl = _dom_rl + 1 if (rl.energy_pool >= CAPTURE_RATIO * ai.energy_pool and rl.force > ai.force) else 0
    _dom_ai = _dom_ai + 1 if (ai.energy_pool >= CAPTURE_RATIO * rl.energy_pool and ai.force > rl.force) else 0
    if _dom_rl >= CAPTURE_STREAK:
        _dom_rl = _dom_ai = 0
        B = breach_factor(rl.force, ai.force)
        cap = int(ai.force * min(CAPTURE_FRAC * B, 0.9))   # разгром: до 90% силы
        ai.force = max(1, ai.force - cap)
        ai.rest_units = max(0.0, ai.rest_units - cap / L_STEP)
        rl.gain(cap)
        return "RL"
    if _dom_ai >= CAPTURE_STREAK:
        _dom_ai = _dom_rl = 0
        B = breach_factor(ai.force, rl.force)
        cap = int(rl.force * min(CAPTURE_FRAC * B, 0.9))
        rl.force = max(1, rl.force - cap)
        rl.rest_units = max(0.0, rl.rest_units - cap / L_STEP)
        ai.gain(cap)
        return "UtilityAI"
    return None


_dom_rl = 0
_dom_ai = 0


def play_game(rl, ai, steps=1000, seed=0, retreat=True):
    """Одна партия. RL сохраняет Q-таблицу между партиями (перенос обучения).
    retreat=False — эксперимент «стоять до конца»: отступления запрещены обеим сторонам."""
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
        rl.tick_energy()      # пассивная регенерация пула: поток ~ sqrt(силы)
        ai.tick_energy()

        eps = max(0.05, 1.0 - step / 300)
        a_idx = rl.form_intention(eps)
        st_before = rl.skey()
        f_before = rl.force

        # --- нижний ярус: рефлекс самосохранения подавляет намерение при истощении ---
        rl_restressed = rl.rest_if_starving()
        if not rl_restressed:
            if a_idx >= len(ACTIONS):                 # RETREAT как намерение RL
                if retreat and rl.try_retreat():
                    w_rl = 0
                else:
                    w_rl = rl.commit("REST", 0)       # отказ/невозможность -> отдых
            else:
                act_name, frac = ACTIONS[a_idx]
                w_rl = rl.commit(act_name, rl.energy_pool * frac)
        else:
            w_rl = 0

        # --- UtilityAI: отступление как утилитарное решение (Клаузевиц) ---
        if retreat and ai.try_retreat():
            w_ai = 0
        else:
            ai_act, ai_work = ai.form_intention()
            if ai.rest_if_starving():
                w_ai = 0
            else:
                w_ai = ai.commit(ai_act, ai_work)

        resolve_attack_calibrated(rl, ai, w_rl, rng)
        resolve_attack_calibrated(ai, rl, w_ai, rng)

        rl_hist.append(rl.force)
        ai_hist.append(ai.force)
        rl.learn(st_before, a_idx, rl.force - f_before, rl.skey())

        winner = check_capture(rl, ai)
        if winner:
            return winner, rl_hist, ai_hist, step
    return None, rl_hist, ai_hist, steps


def run_batch(n_games=10, steps=1000):
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
        print(f"Game {g+1}: winner={winner or 'no-capture'} at step {end_step} | "
              f"final RL force={rl.force}, final UtilityAI force={ai_hist[-1]}")
    print("\nИтоги пакетного прогона:")
    print(f"  RL победил: {results['RL']}/{n_games}, "
          f"UtilityAI: {results['UtilityAI']}/{n_games}, "
          f"без решения: {results[None]}/{n_games}")
    for k in finals:
        if finals[k]:
            print(f"  Финальная сила RL при '{k}': медиана={statistics.median(finals[k]):.0f}")
    return rl, last


def main():
    rl, (winner, rl_hist, ai_hist, end_step) = run_batch(n_games=10)

    print(f"\nПоследняя партия: winner={winner or 'no-capture'}, шагов={end_step}")
    print(f"Q-состояний изучено: {len(rl.Q)}")

    plt.figure(figsize=(10, 6))
    plt.plot(rl_hist, label="RL Agent (Water)", color='blue', linewidth=2)
    plt.plot(ai_hist, label="Utility AI (Fire)", color='red', linewidth=2)
    plt.title("Динамика силы агентов (логистика отдыха)", fontsize=14)
    plt.xlabel("Шаг симуляции", fontsize=12)
    plt.ylabel("Сила (Force, log)", fontsize=12)
    plt.yscale("log")
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()