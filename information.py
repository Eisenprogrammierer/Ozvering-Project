import math

N_BUCKETS = 4
H_MAX = math.log(N_BUCKETS)


def shannon_entropy(probs):
    return -sum(p * math.log(p) for p in probs if p > 0.0)


def bucket_index(context_base, in_open):
    if in_open:
        return 3
    if context_base == 0:
        return 0
    if context_base == 1:
        return 1
    return 2


class BeliefEntropy:

    def __init__(self, ema=0.25, sigma=0.15, df=3.0, deadband=0.15):
        self.ema = min(1.0, max(0.0, float(ema)))
        self.sigma = max(0.0, float(sigma))
        self.df = max(1.0, float(df))
        self.deadband = max(0.0, float(deadband))
        self.counts = [1.0 / N_BUCKETS] * N_BUCKETS
        self.H_local = H_MAX
        self.H_min = H_MAX
        self.H_cum = 0.0
        self.noise_floor = 0.0
        self.lineage = 0
        self._factor = 1.0

    def new_lineage(self, reset_counts=True):
        self.lineage += 1
        if reset_counts:
            self.counts = [1.0 / N_BUCKETS] * N_BUCKETS
            self.H_local = H_MAX
            self.H_min = H_MAX
            self._factor = 1.0
        return self.lineage

    def observe(self, context_base, in_open):
        idx = bucket_index(context_base, in_open)
        self.counts = [c * (1.0 - self.ema) for c in self.counts]
        self.counts[idx] += self.ema
        total = sum(self.counts)
        probs = [c / total for c in self.counts]
        self.H_local = shannon_entropy(probs)
        if self.H_local < self.H_min:
            self.H_min = self.H_local

        loss = self.H_local - self.H_min
        if loss > self.H_cum:
            self.H_cum = loss
        self.noise_floor = min(1.0, self.H_cum / H_MAX)
        return probs, self.H_local

    def _student_t(self, rng):
        z = rng.gauss(0.0, 1.0)
        chi2 = rng.gammavariate(self.df / 2.0, 2.0)
        return z / math.sqrt(chi2 / self.df)

    def next_factor(self, rng):
        sigma_eff = self.sigma * self.noise_floor
        if sigma_eff <= 0.0:
            return 1.0
        raw = math.exp(max(-2.0, min(2.0, sigma_eff * self._student_t(rng))))
        if abs(math.log(raw)) < self.deadband:
            return self._factor
        self._factor = max(0.5, min(2.0, raw))
        return self._factor

    def perturb(self, beliefs, rng):
        factor = self.next_factor(rng)
        if factor == 1.0:
            beliefs["belief_noise_factor"] = 1.0
            return 1.0
        beliefs["opp_energy"] = max(
            1, int(round(beliefs["opp_energy"] * factor))
        )
        beliefs["opp_force"] = max(
            1, int(round(beliefs["opp_force"] * factor))
        )
        beliefs["opp_w_adopt"] = max(0.0, beliefs["opp_w_adopt"] * factor)
        beliefs["belief_noise_factor"] = factor
        return factor
