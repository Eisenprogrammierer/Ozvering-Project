"""Информационный слой: энтропия смысла, износ канала и шум убеждений.

Слой реализует требование «энтропия Шеннона как демпфер самоусиливающихся
петель» строго на компоненте ВХОДА (``beliefs``), не трогая физические метрики
``force`` и ``energy_pool``. Это сохраняет канон «ровно две метрики»: энтропия —
производная величина от наблюдений, а не третья метрика состояния.

Ключевые свойства (см. ``docs/DESIGN_ADVANCED.md``):

* **H локальна** — энтропия распределения убеждений о наблюдаемом состоянии
  противника (4 канонических корзины: ``(context_base, in_open)``).
* **H_cum не имеет обратного хода** — накопленная потеря смысла измеряется
  относительно САМОГО ЧЁТКОГО состояния текущей линии (``H_min``) и только
  растёт (ratchet). Новая линия (``new_lineage``) начинает локальный отсчёт
  заново, но глобальный ``H_cum`` не откатывается: похожий сигнал — это новый
  сигнал, а не возврат прежнего.
* **Шум мультипликативен и тяжёлохвост** — применяется только к числовым
  убеждениям (``opp_energy``/``opp_w_adopt``/``opp_force``), не к энергии.
  Фактор — ``exp(sigma * t_nu)`` с стьюдентовским ``t_nu`` (тяжёлые хвосты),
  с мёртвой зоной и защёлкиванием (гистерезис).
* **Сила демпфера** пропорциональна ``noise_floor = H_cum / ln(4)``: свежий
  канал чист, изношенный — шумный.

Модуль не импортирует ``simulation`` (чтобы не было цикла); константы
передаются из ``PARAMETERS`` явными аргументами.
"""

import math

# Канонические корзины наблюдаемого состояния противника:
#   0: (context_base=0, вход закрыт) — истощён
#   1: (context_base=1, вход закрыт) — наполнен
#   2: (context_base=2, вход закрыт) — на пороге
#   3: (context_base=2, вход открыт) — окно открыто
N_BUCKETS = 4
H_MAX = math.log(N_BUCKETS)


def shannon_entropy(probs):
    """Энтропия Шеннона в натуральных логарифмах для распределения ``probs``."""
    return -sum(p * math.log(p) for p in probs if p > 0.0)


def bucket_index(context_base, in_open):
    """Каноническая корзина убеждений по наблюдаемым признакам."""
    if in_open:
        return 3
    if context_base == 0:
        return 0
    if context_base == 1:
        return 1
    return 2


class BeliefEntropy:
    """Распределение убеждений о состоянии противника + необратимый износ.

    Поля:
        counts      — сглаженная гистограмма (EMA) по 4 корзинам;
        H_local     — текущая энтропия распределения;
        H_min       — минимум энтропии в текущей линии («пик смысла»);
        H_cum       — накопленная потеря смысла (ratchet, не убывает);
        noise_floor — нормированный износ ``H_cum / ln(4)`` в [0, 1];
        lineage     — идентификатор линии сигнала.
    """

    def __init__(self, ema=0.25, sigma=0.15, df=3.0, deadband=0.15):
        self.ema = min(1.0, max(0.0, float(ema)))
        self.sigma = max(0.0, float(sigma))
        self.df = max(1.0, float(df))          # df > 2 — конечная дисперсия
        self.deadband = max(0.0, float(deadband))
        self.counts = [1.0 / N_BUCKETS] * N_BUCKETS
        self.H_local = H_MAX
        self.H_min = H_MAX
        self.H_cum = 0.0
        self.noise_floor = 0.0
        self.lineage = 0
        self._factor = 1.0                     # защёлкнутый множитель (гистерезис)

    # --- линия сигнала ---------------------------------------------------
    def new_lineage(self, reset_counts=True):
        """Новая линия сигнала: локальный отсчёт заново, глобальный износ — нет.

        Именно здесь реализовано «похожий сигнал — это новый сигнал»: локально
        канал снова может быть чистым (``H_min = H_MAX``), но ``H_cum``
        сохраняется, поэтому прежний смысл не возвращается.
        """
        self.lineage += 1
        if reset_counts:
            self.counts = [1.0 / N_BUCKETS] * N_BUCKETS
            self.H_local = H_MAX
            self.H_min = H_MAX
            self._factor = 1.0
        return self.lineage

    # --- наблюдение ------------------------------------------------------
    def observe(self, context_base, in_open):
        """Обновить распределение убеждений и вернуть ``(probs, H_local)``.

        Энтропия считается по сглаженной гистограмме (EMA), поэтому она
        реагирует на поток наблюдений, а не на одно событие.
        """
        idx = bucket_index(context_base, in_open)
        self.counts = [c * (1.0 - self.ema) for c in self.counts]
        self.counts[idx] += self.ema
        total = sum(self.counts)
        probs = [c / total for c in self.counts]
        self.H_local = shannon_entropy(probs)
        if self.H_local < self.H_min:
            self.H_min = self.H_local
        # Ratchet: потеря смысла относительно самого чёткого состояния линии.
        loss = self.H_local - self.H_min
        if loss > self.H_cum:
            self.H_cum = loss
        self.noise_floor = min(1.0, self.H_cum / H_MAX)
        return probs, self.H_local

    # --- шум убеждений ---------------------------------------------------
    def _student_t(self, rng):
        """Стандартная стьюдентовская величина с ``df`` степенями свободы."""
        z = rng.gauss(0.0, 1.0)
        chi2 = rng.gammavariate(self.df / 2.0, 2.0)
        return z / math.sqrt(chi2 / self.df)

    def next_factor(self, rng):
        """Мультипликативный фактор шума с тяжёлыми хвостами и гистерезисом.

        * сила шума ``sigma_eff = sigma * noise_floor`` (свежий канал чист);
        * фактор ``exp(sigma_eff * t_nu)``, ограниченный ``[0.5, 2.0]``;
        * мёртвая зона ``deadband``: малое изменение не трогает состояние
          (защёлкивание), поэтому шум не «дребезжит» каждый такт.
        """
        sigma_eff = self.sigma * self.noise_floor
        if sigma_eff <= 0.0:
            return 1.0
        raw = math.exp(max(-2.0, min(2.0, sigma_eff * self._student_t(rng))))
        if abs(math.log(raw)) < self.deadband:
            return self._factor
        self._factor = max(0.5, min(2.0, raw))
        return self._factor

    def perturb(self, beliefs, rng):
        """Применить шум ТОЛЬКО к числовым убеждениям; вернуть фактор.

        Физические метрики (``force``/``energy_pool``) и ``state`` не читаются и
        не изменяются: демпфер работает на размывании информации, не энергии.
        """
        factor = self.next_factor(rng)
        if factor == 1.0:
            beliefs["belief_noise_factor"] = 1.0
            return 1.0
        beliefs["opp_energy"] = max(1, int(round(beliefs["opp_energy"] * factor)))
        beliefs["opp_force"] = max(1, int(round(beliefs["opp_force"] * factor)))
        beliefs["opp_w_adopt"] = max(0.0, beliefs["opp_w_adopt"] * factor)
        beliefs["belief_noise_factor"] = factor
        return factor
