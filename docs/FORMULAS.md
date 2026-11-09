# Формулы проекта: просто и по шагам

**Статус:** справочник текущих формул. Он объясняет, **что именно считает
код**, а не только целевую модель. Если формула расходится с кодом, прав код
и тесты; документ нужно поправить.

**Дата сверки:** 2026-11-09.

**Связанные документы:** [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) —
навигатор и канон; [`ALGORITHMS.md`](ALGORITHMS.md) — точный порядок такта,
признаки и обучение; [`MODEL.md`](MODEL.md) — легаси `simulation.py`;
[`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) — кампанийный поток.

**Как читать.** Каждая формула снабжена:

- обозначениями и единицами;
- словесным смыслом («что это на самом деле значит»);
- числовым примером;
- ссылкой на функцию в коде.

Числа по умолчанию — из кода и `configs/`. Контент может их переопределять;
тогда действует значение из конфига, а не таблица этого документа.

---

## 0. Обозначения и единицы

| Символ | Смысл | Единица |
|---|---|---|
| `E` | универсальная энергия; в кампании ещё и дневной бюджет действий | пункты, `0..max_energy` |
| `F` | сила/пропускная способность/сопротивление; в кампании `standing` | пункты или доля `0..1` |
| `W` | работа: `{amount, form, payload, duration}` | `amount` в единицах `E` |
| `H` | здоровье | пункты, `0..100` |
| `sickness` | тяжесть болезни | доля `0..1` |
| `wound` | тяжесть устойчивой раны | доля `0..1` |
| `p` | вероятность | доля `0..1` |
| `t` | такт арены | секунда (базовый тик) |
| `day` | день кампании | сутки мира |

`form` — канал работы (`force`, `info`), а **не** отдельный вид энергии.
Один и тот же `E` в разных каналах даёт разные эффекты и потери.

Два разных времени не путать:

- **арена** — такт `1` секунды, скорости `пауза/1x/2x/4x/8x/16x`;
- **кампания автоматов** — `turn_seconds = 240` в
  `configs/campaigns/base/automata_defaults.json` (это темп кампании
  автоматов, а не аренный тик);
- **день `world_actor`** — `SECONDS_PER_DAY = 120` в `campaign/clock.py`
  (отдельный дневной мир, не кампания автоматов).

---

## 1. Энергия, работа и потери

### 1.1. Конверсия работы

**Код:** `core41/model.py`, `conversion_efficiency()` и
`conversion_report()`.

Работа приходит в автомат не целиком. Часть теряется по дороге, часть
рассеивается внутри обработчика, остаток становится полезным запасом.

```text
arrived = amount · efficiency
stored  = arrived · storage_share
loss    = amount − arrived
entropy = arrived − stored
waste   = loss + entropy
```

Проверка баланса:

```text
loss + entropy + stored = amount
```

**Что это значит.** Ни одна конверсия не создаёт работу из воздуха. Если
отправили `100`, а КПД канала `0.55`, то до обработчика дошло `55`; из них
`35%` (`19.25`) осталось запасом, а `35.75` рассеялось внутри. Внешние
потери — `45`, внутренняя энтропия — `35.75`, запас — `19.25`; сумма снова
`100`.

КПД по умолчанию (`core41/model.py`):

| Канал | `efficiency` |
|---|---|
| `force` | `0.55` |
| `info` | `0.75` |
| неизвестный | `0.55` |

**Код:** `campaign/economy.py`, `conversion_quote()` — та же формула плюс
поле `waste`, и `price_for_effect()`, `conversion_chain()`.

### 1.2. Цена эффекта и цепочка

```text
price_for_effect(effect) = effect / efficiency
```

Если нужен эффект `10` по каналу `info`, заплатить нужно
`10 / 0.75 = 13.33` единицы `E`. Плохой канал не делает работу дешевле.

Цепочка `A → B → C` не складывает КПД, а умножает его: каждый следующий шаг
получает только `arrived` предыдущего. Поэтому три конверсии по `0.75` дают
не `0.75`, а `0.75³ ≈ 0.42`.

### 1.3. Объём работы на арене

**Код:** `core41/arena.py`, `work_amount()`, `_work_cost_factor()`,
`work_duration()`.

```text
cost_factor  = 0.60, если form == "info", иначе 1.00
energy_budget = E / cost_factor
nominal       = fraction · max_energy
force_budget  = F · duration · FORCE_WORK_RATIO
amount        = min(energy_budget, nominal, force_budget)
cost          = amount · cost_factor
```

`FORCE_WORK_RATIO = 1.0`. `fraction` — доля действия (`0.3` или `0.7` для
удара). `duration` — длительность работы.

**Что это значит.**

- `E` оплачивает работу;
- `F` ограничивает, сколько работы вообще можно провести за такт
  (пропускная способность);
- `fraction` задаёт масштаб намерения;
- разведка `info` дешевле (`0.60`), но не наносит прямого урона.

**Длительность:**

```text
duration = 2, если form == "force" и fraction >= 0.7
duration = 1, иначе
```

Сильный удар `0.7` — двухтактная подготовка: первый такт уходит на заряд,
второй — на удар. Подготовка видна противнику.

**Пример.** `E = 100`, `max_energy = 100`, `F = 100`, `fraction = 0.7`,
`force`. Тогда `energy_budget = 100`, `nominal = 70`,
`force_budget = 100 · 2 · 1 = 200`; `amount = 70`, `cost = 70`.

### 1.4. Отдых и лечение

**Код:** `core41/arena.py`, `_rest_effect()` и `_prepare_action()`.

```text
REST:  E += 14.0  (до max_energy)
       F += 0.6   (до max_force)
       pressure *= 0.5
```

`REST` не тратит `E`; он восстанавливает `E`, `F` и немного здоровья через
`tick_health(resting=True)`.

`TREAT`:

```text
spent = min(E, TREAT_ENERGY_FRACTION · max_energy)
TREAT_ENERGY_FRACTION = 0.10
sickness -= SICKNESS_TREAT_RATE · care / max(0.25, illness)
wound    -= WOUND_TREAT_RATE    · care
```

`TREAT` предлагается только когда есть что лечить (`sickness > 0` или
`wound > 0`).

---

## 2. Вероятность успеха

### 2.1. Логистика ядра

**Код:** `core41/model.py`, `success_probability()`.

```text
p = sigmoid(
      intercept
    + skill      · S · work_effectiveness · attack_effectiveness
    + authority  · A
    − resistance · R
    + open       · [is_open]
    + env        · env_bonus
    + intel      · weak_point
    − amount     · min(1, W / max_F)
)
```

`S` — навык атакующего по каналу работы, `A` — полномочия, `R` —
сопротивление защитника, `W` — объём работы, `weak_point ∈ [0,1]` — свежая
уязвимость, найденная разведкой.

```text
sigmoid(x) = 1 / (1 + e^(−x))
```

Коэффициенты по умолчанию (`DEFAULT_SUCCESS_COEFFICIENTS`):

| Ключ | Значение | Смысл |
|---|---|---|
| `intercept` | `−0.4` | базовый порог |
| `skill` | `2.2` | навык, работоспособность, здоровье |
| `authority` | `1.3` | полномочия/должность |
| `resistance` | `1.8` | сопротивление цели (вычитается) |
| `open` | `0.9` | цель открыта |
| `env` | `1.0` | бонус среды |
| `intel` | `0.8` | свежая слабая точка |
| `amount` | `0.5` | штраф за крупную работу (вычитается) |

Формула `skill`:

```text
skill_term = S · work_effectiveness · attack_effectiveness
```

где

```text
work_effectiveness = max(
    SICKNESS_WORK_FLOOR · WOUND_WORK_FLOOR,
    max(SICKNESS_WORK_FLOOR, 1 − 0.60 · sickness)
    · max(WOUND_WORK_FLOOR,   1 − 0.70 · wound)
)

attack_effectiveness = 0.50 + 0.50 · (H / max_H)
```

`SICKNESS_WORK_FLOOR = 0.40`, `WOUND_WORK_FLOOR = 0.30`. Здоровье никогда не
опускает множитель нападения ниже `0.50`: живой боец слабее, но не беспомощен.

**Пример.** `S = 0.6`, `A = 0.2`, `R = 0.5`, работа `force` на `30` при
`max_F = 100`, все множители равны `1`, `is_open = 0`, `env = intel = 0`:

```text
logit = −0.4 + 2.2·0.6 + 1.3·0.2 − 1.8·0.5 − 0.5·0.30
      = −0.4 + 1.32 + 0.26 − 0.90 − 0.15 = 0.13
p = sigmoid(0.13) ≈ 0.532
```

**Переопределение контента.** Действие может передать
`success.coefficients`/`success_coefficients`
(`campaign/success.py`, `resolve_success_coefficients()`). Неизвестные ключи
игнорируются, значения клампятся в `[−10, 10]`, отсутствующие берутся по
умолчанию. Поэтому старый контент сохраняет прежнюю калибровку.

### 2.2. Смешивание с авторским шансом в кампании

**Код:** `campaign/actor.py`, `campaign_success_chance()`.

Кампанийное действие имеет авторский `base` (обычно `0.6`) и проходит через
ту же ядровую логистику:

```text
core    = success_probability(...)
chance  = clamp(base + CAMPAIGN_CORE_CHANCE_WEIGHT · (core − 0.5), 0.05, 0.95)
CAMPAIGN_CORE_CHANCE_WEIGHT = 0.30
```

**Что это значит.** Ядро не заменяет авторский замысел, а сдвигает его не
более чем на `±0.15` (потому что `0.30 · (core − 0.5)` при `core ∈ [0,1]`
даёт `[−0.15, +0.15]`). При этом `F`, навык, болезнь и сопротивление цели
всё равно входят в бросок.

**Пример.** `base = 0.6`, `core = 0.9`:
`chance = 0.6 + 0.30·0.4 = 0.72`. При `core = 0.1`:
`chance = 0.6 − 0.30·0.4 = 0.48`.

### 2.3. Отношения как сдвиг шанса

**Код:** `campaign/relations.py`, `relation_effect()`.

```text
shift = Σ (weight_axis · clamp(axis, −1, 1))
shift = clamp(shift, −0.20, 0.20)
```

Берутся оси **цели к действующему**, то есть `R_target→actor`. Веса:

| Ось | `force` | `info` |
|---|---|---|
| `affinity` | `0.02` | `0.06` |
| `trust` | `−0.02` | `0.14` |
| `fear` | `0.10` | `−0.04` |
| `respect` | `0.08` | `0.04` |

**Что это значит.** Сила проходит к тому, кто боится или уважает; информация
проходит к тому, кто доверяет и расположен. Предел `0.20` не даёт отношениям
заменить `F/E`, навык и сопротивление: это сдвиг, а не второй бюджет.

### 2.4. Битый бросок и маржа

Исход бинарный: `roll < chance` — успех. Но результат несёт `chance`, `roll`
и `margin = chance − roll` для калибровки. `margin` не меняет исход; он нужен
аналитике.

---

## 3. Урон, здоровье, болезнь, рана

### 3.1. Урон и переполнение в здоровье

**Код:** `core41/model.py`, `apply_force_damage()`.

```text
absorbed = min(F, damage)
F'       = max(0, F − absorbed)
overflow = max(0, damage − absorbed)

health_damage = overflow
              · HEALTH_DAMAGE_RATIO
              · health_damage_multiplier
              · (1 + WOUND_DAMAGE_BONUS · wound)
```

```text
health_damage_multiplier = aging · illness · (1 + SICKNESS_DAMAGE_BONUS · sickness)
HEALTH_DAMAGE_RATIO = 0.25
SICKNESS_DAMAGE_BONUS = 0.50
WOUND_DAMAGE_BONUS = 0.25
```

**Что это значит.** Сначала урон съедает `F`. Только остаток после `F = 0`
идёт в здоровье, и то лишь на четверть (плюс поправки на возраст, болезнь и
рану). Поэтому обнулённая сила — это ещё не смерть: персонаж может
отдохнуть и восстановиться.

**Пример.** `F = 20`, урон `40`, множители `1`, раны нет.
`absorbed = 20`, `overflow = 20`, `health_damage = 20 · 0.25 = 5`.
Здоровье падает на `5`, `F` становится `0`.

### 3.2. Тик здоровья

**Код:** `core41/model.py`, `tick_health(resting=...)`.

```text
если E <= 0:        H −= HEALTH_STARVE_DECAY · health_decay_multiplier
иначе если REST:     H += HEALTH_REST_REGEN · health_regen_multiplier
                          · max(0.25, 1 − WOUND_REGEN_PENALTY · wound)

health_decay_multiplier = aging · illness · stress
health_regen_multiplier = care / max(0.25, illness)
```

Константы: `HEALTH_STARVE_DECAY = 0.20`, `HEALTH_REST_REGEN = 0.78`,
`WOUND_REGEN_PENALTY = 0.50`. Все множители клампятся в `[0, 10]`.

**Порядок важен.** Сначала расход/восстановление от `E`, затем прямой урон
от раны и болезни, затем их прогресс/лечение. Итог клампится в
`[0, max_health]`.

### 3.3. Болезнь

**Код:** `core41/model.py`, поля `sickness`, `infect()`, `treat()` и
`tick_health()`.

```text
без отдыха:  sickness += SICKNESS_PROGRESS · health_decay_multiplier
с отдыхом:   sickness −= SICKNESS_REST_RECOVERY · care / max(0.25, illness)
урон:        H −= SICKNESS_HEALTH_DECAY · sickness · aging
```

Константы: `SICKNESS_PROGRESS = 0.004`, `SICKNESS_REST_RECOVERY = 0.01`,
`SICKNESS_HEALTH_DECAY = 1.5`.

`treat(amount)` снимает болезнь:

```text
sickness −= amount · care / max(0.25, illness)
```

`illness` и `sickness` не удваивают урон: `illness` задаёт чувствительность
процесса и общий урон, а `sickness` — текущую тяжесть.

### 3.4. Рана

**Код:** `core41/model.py`, поля `wound`, `injure()`, `treat_wound()` и
`tick_health()`.

```text
без отдыха:  wound += WOUND_PROGRESS · health_decay_multiplier
с отдыхом:   wound −= WOUND_REST_RECOVERY · care / max(0.25, illness)
урон:        H −= WOUND_HEALTH_DECAY · wound · aging
удар:        wound = max(wound, WOUND_HIT_SEVERITY · health_damage / max_health)
```

Константы: `WOUND_PROGRESS = 0.002`, `WOUND_REST_RECOVERY = 0.012`,
`WOUND_HEALTH_DECAY = 0.60`, `WOUND_HIT_SEVERITY = 0.30`.

Рана отличается от болезни: она даёт прямой суточный/тиковый урон и штраф к
восстановлению, но не «разгоняется» сама так быстро, как болезнь.

### 3.5. Передача болезни

**Код:** `core41/model.py`, `transmit_sickness()`; кампания —
`campaign/world.py`, `_spread_contagion()`.

Арена (после успешного `force`-контакта):

```text
шанс передачи    = CONTAGION_CHANCE · sickness_source
тяжесть передачи = CONTAGION_SEVERITY · sickness_source
```

`CONTAGION_CHANCE = 0.35`, `CONTAGION_SEVERITY = 0.50`. `info`, мёртвый
получатель и уже максимальная болезнь передачи не дают.

Кампания (контакт в одном узле):

```text
шанс    = CAMPAIGN_CONTAGION_CHANCE · sickness_source
добавка = CAMPAIGN_CONTAGION_SEVERITY · sickness_source
```

`CAMPAIGN_CONTAGION_CHANCE = 0.30`, `CAMPAIGN_CONTAGION_SEVERITY = 0.35`.

### 3.6. Работа и здоровье

```text
work_effectiveness = max(
    SICKNESS_WORK_FLOOR · WOUND_WORK_FLOOR,
    max(SICKNESS_WORK_FLOOR, 1 − 0.60·sickness)
    · max(WOUND_WORK_FLOOR,   1 − 0.70·wound)
)
```

Болезнь и рана снижают успех работы, но **не** меняют сохранённый навык и
расход `E`. То есть они бьют по результату, а не по цене.

---

## 4. Давление и захват

### 4.1. Давление

**Код:** `core41/model.py` (свойства `pressure`, `is_open`,
`decay_pressure`) и `core41/arena.py` (`resolve_work`).

```text
за работу force: pressure += amount · PRESSURE_PER_WORK
за работу info:  pressure += amount · INFO_PRESSURE_PER_WORK
pressure = min(PRESSURE_MAX, pressure)
за такт:         pressure *= PRESSURE_DECAY
открытость:      is_open = pressure >= OPEN_PRESSURE
```

`PRESSURE_PER_WORK = 0.30`, `INFO_PRESSURE_PER_WORK = 0.50`,
`PRESSURE_MAX = 30.0`, `PRESSURE_DECAY = 0.82`, `OPEN_PRESSURE = 8.0`.
Разведка `info` давит сильнее, но не наносит прямого урона.

### 4.2. Захват

**Код:** `core41/arena.py`, `_resolve_capture()` / `check_capture()`.

Доминирование растёт, пока одна сторона одновременно:

```text
E_side >= CAPTURE_RATIO · E_opponent   (CAPTURE_RATIO = 1.5)
F_side >  F_opponent
```

Иначе счётчик доминирования сбрасывается в `0`. При
`dom >= CAPTURE_STREAK` (`36` тактов) происходит захват:

```text
severity = 2.0, если цель открыта (in_open), иначе 1.0
cap = int(F_target · min(CAPTURE_FRAC · severity, 0.5))
F_target -= cap, но не ниже 1.0
F_winner += cap · 0.20
```

`CAPTURE_FRAC = 0.10`. Захват — не смерть: он снимает силу и переводит
победу в исход партии. Лимит шагов — усечение, а не победа.

---

## 5. Награда арены

**Код:** `core41/arena.py`, `reward_delta()` и `terminal_reward()`.

Профили награды: `legacy`, `advantage`, `advantage_cost`. По умолчанию —
`advantage_cost`.

`advantage`:

```text
reward = loss_opponent(F) + loss_opponent(H)
       − loss_self(F)     − loss_self(H)
       + 1.0 · max(0, sickness_before_self − sickness_self)
       + 0.5 · max(0, sickness_opponent − sickness_before_opponent)
       + wound_term
```

где

```text
loss(x_before, x_now, x_max) = max(0, x_before − x_now) / max(1, x_max)
wound_term = 0.8 · (wound_before_self − wound_self)
           + 0.4 · (wound_opponent − wound_before_opponent)
```

`advantage_cost` дополнительно вычитает цену потраченной энергии:

```text
− 0.10 · max(0, E_before_self − E_self) / max(1, E_max)
```

**Что это значит.** Восстановление `E/F/H` не оплачивается как «награда»:
учитываются только потери. Иначе политика училась бы бесконечно отдыхать.
`advantage_cost` добавляет реальную цену каждого потраченного `E`.

Терминальный бонус:

```text
победа = +1.0, поражение = −1.0, ничья/усечение = 0.0
```

`legacy` сохраняет старую формулу (включая положительные приросты и штраф
`REWARD_ENERGY_COST = 0.6`) для воспроизведения старых прогонов.

---

## 6. Кампания: день и организация

### 6.1. Дневной доход должности

**Код:** `campaign/world.py`, `_apply_daily_income()`.

```text
influence += CAMPAIGN_INFLUENCE_INCOME + CAMPAIGN_INFLUENCE_PER_AUTHORITY · authority
favor     += CAMPAIGN_FAVOR_INCOME     + CAMPAIGN_FAVOR_PER_STANDING      · standing
```

`CAMPAIGN_INFLUENCE_INCOME = 0.04`, `CAMPAIGN_INFLUENCE_PER_AUTHORITY = 0.21`,
`CAMPAIGN_FAVOR_INCOME = 0.03`, `CAMPAIGN_FAVOR_PER_STANDING = 0.20`.
Доход идёт только пока герой жив и занимает должность.

Влияние и связи — политическая проекция, а не второй бюджет действий:
бюджет остаётся `E`.

### 6.2. Дрейф организации

**Код:** `campaign/world.py`, `_apply_organizational_drift()`.

Считается за день, если включён `organizational_drift`:

```text
d_cohesion = 0
d_power    = 0

если legitimacy <= 0.02:          # кризис
    d_cohesion -= 0.020; d_power -= 0.010
иначе если legitimacy <= 0.08:    # напряжение
    d_cohesion -= 0.010; d_power -= 0.005

если wealth <= 0.10:              # бедность
    d_cohesion -= 0.010

если legitimacy >= 0.45
   и wealth > 0.10
   и power > collapse_min_power
   и cohesion > collapse_min_cohesion:
    d_cohesion += 0.005; d_power += 0.005

cohesion += d_cohesion · scale
power    += d_power    · scale
```

`scale` — `organizational_drift_scale` (калибровочный множитель, по
умолчанию `1`). Дрейф не отменяет пороги распада: он лишь приближает или
отодвигает их, превращая распад в процесс.

### 6.3. Восстановление легитимности

**Код:** `campaign/world.py`, `_apply_legitimacy_recovery()`.

```text
если герой прикреплён и жив
   и power > collapse_min_power
   и cohesion > collapse_min_cohesion:
    legitimacy += LEGITIMACY_RECOVERY   # 0.02
```

Ниже порога распада организация не «самолечится».

### 6.4. Распад и смена роли

**Код:** `campaign/world.py`, `_check_dismissal()`.

Распад:

```text
power <= 0.05  ИЛИ  cohesion <= 0.05  в течение COLLAPSE_GRACE_DAYS = 2 дней подряд
→ lose (организация распалась)

power <= 0 И cohesion <= 0 → lose сразу
```

Смена роли (не поражение):

```text
standing <= 0.05  ИЛИ  legitimacy <= 0.08
и с последней смены прошло >= ROLE_CHANGE_COOLDOWN_DAYS = 5 дней
→ другая роль в той же структуре или вне службы
```

Потеря должности без замены завершает эпизод нейтральным исходом, а не
оставляет игрока с единственным `END_DAY`.

### 6.5. Шанс действия

**Код:** `campaign/world.py`, `_action_chance()`; `campaign/actor.py`,
`campaign_success_chance()`; `campaign/success.py`.

```text
base   = success.chance (по умолчанию 0.6)
base  += relation_effect(R_target→actor, form)
core   = success_probability(attacker, defender, work, is_open)
chance = clamp(base + 0.30·(core − 0.5), 0.05, 0.95)
```

`amount = 0` для кампанийного броска: объём работы здесь не моделируется
так, как на арене. Отношения не заменяют `F/E` и сопротивление, а сдвигают
авторский шанс до ядрового смешивания.

### 6.6. Навыки от практики

**Код:** `campaign/world.py`, `execute()`.

```text
успех:  skill += CAMPAIGN_SKILL_GAIN          # 0.03
провал: skill += CAMPAIGN_SKILL_FAILURE_GAIN  # 0.01
skill = min(CAMPAIGN_SKILL_CAP, skill)        # 0.90
```

Прирост идёт в навык домена цели (или домена действия). `aptitudes` и
доступные предметы пересчитываются, поэтому профиль может дорасти до
требований вышестоящей должности.

---

## 7. Кампания: экономика одной энергии

**Код:** `campaign/economy.py`.

### 7.1. Цена и эффект с масштабом

```text
scaled_cost(base) = base · (1
    + w_level      · level
    + w_force      · force
    + w_resistance · resistance
    + w_domain     · max(0, domain_factor − 1))
```

Все веса по умолчанию `0`, поэтому без контента цена не растёт сама.

```text
scaled_effect(base_effect) = base_effect
    · clamp(delivered / amount)
    · (1 − min(max_suppression, w_resistance · resistance))
```

`max_suppression = 0.90`: сопротивление подавляет эффект, но не обнуляет
любое действие.

### 7.2. Поддержание и ремонт

```text
maintenance = base + per_level·level + per_force·force + per_wound·wound
```

По умолчанию все веса `0`: поддержание — явный сток, который включает
контент, а не скрытый налог.

```text
repair_energy = wound · 20.0 + health_missing · 0.50
```

Ремонт — отдельный расход `E` и времени, а не бесплатное восстановление.

### 7.3. Бедность и клапаны

```text
energy_ratio = E / max_energy
strained    = energy_ratio <= POVERTY_ENERGY_RATIO   # 0.25
exhausted   = actions_left <= 0
needs_relief = strained или exhausted
```

Клапаны не делают действие бесплатным: каждый переносит цену во время,
отношения или долг.

**Отдых** (тратит оставшиеся действия):

```text
health_gain = min(max_H − H, 6.0 · actions · (1 − 0.5·wound))
force_gain  = 0.04 · actions
wound_gain  = min(wound, 0.02 · actions)
```

**Помощь** (нужно `trust >= 0.20`):

```text
capacity   = money_to_energy(wealth · 0.50)
obligation = clamp(amount / max_energy · 0.75, 0.01, 1.0)
```

**Кредит**:

```text
capacity   = money_to_energy(wealth · 0.75)
obligation = clamp(amount / max_energy · (1 + 0.10), 0.01, 1.0)
```

Срок кредита — `CREDIT_DAYS = 7`.

### 7.4. Обмен денег и энергии

```text
money → energy:  result = wealth · max_energy · MARKET_BUY_EFFICIENCY   # 0.60
energy → money:  result = energy / max_energy · MARKET_SELL_EFFICIENCY  # 0.75
```

Прямого обмена `influence`/`favor`/`evidence` с `E` нет: это права,
обязательства и сигналы. Они меняют цену, успех или отношения, но не
превращаются в энергию сами по себе.

### 7.5. Работа природы

**Код:** `campaign/economy.py`, `nature_yield()`.

```text
potential  = max_work · season · (1 + 0.50·fertility)
labor_work = labor · max_work · 0.50
damage     = damage · max_work
work       = max(0, potential + labor_work − damage)
```

Дальше `work` проходит обычную конверсию `force` с КПД
`NATURE_EFFICIENCY = 0.65`. В казну возвращается доля
`NATURE_WEALTH_SHARE = 1.0` от `arrived / max_work`; это курсом «работа →
деньги», а не второй вид энергии.

---

## 8. Кампания: коалиции и автономия

### 8.1. Сила пары

**Код:** `campaign/coalitions.py`, `pair_score()`.

```text
left  = average(axes R_a→b)
right = average(axes R_b→a)
pair  = clamp(0.5·(left + right) + 0.06·min(obligations, 3), 0, 1)
```

`obligation_bonus = 0.06`, порог формирования `form_threshold = 0.35`,
порог распада `decay_threshold = 0.15`. Связка формируется после
`form_days = 2` дней выше порога и распускается после `decay_days = 3`
дней ниже порога или выбытия участника.

### 8.2. Автономные контакты

**Код:** `campaign/world.py`, `_autonomy_intent()`.

```text
affinity <= −0.2                          → reconcile   (приоритет 1)
affinity >= 0 и trust >= 0.35             → rapprochement
иначе                                     → probe
```

Исход бросается общей `campaign_success_chance` с
`AUTONOMY_BASE_CHANCE = 0.6`, форма `info`, защитник — структура. Успех даёт
`+0.02/+0.01` к осям, провал — зеркало вдвое слабее. Контакт отменяется,
если к моменту исполнения `affinity > 0.8`.

### 8.3. Оценка действия ИИ

**Код:** `campaign/world.py`, `_ai_base()` и `_ai_score()`.

```text
base = Σ interests[key] · action.ai_weight[key]
       (если весов нет: base = 0.2)
base -= 0.10 · Σ cost.node[key]
       и ещё −0.3 за каждый cost.node[key], при stats[key] < 0.2

score = base
      + 0.15 · relations[target]
      + 0.05, если polity(target) == polity(node)
      + 0.20 · deterministic_roll(...)
      + strategy_bonus
      + coalition_bonus
```

`deterministic_roll` — не случайность в момент игры, а воспроизводимое
число от `seed` и токена (`_roll`). Поэтому одинаковый `seed` даёт
одинаковый ход ИИ.

---

## 9. Кампания: награда среды

**Код:** `campaign/env.py`, `campaign_reward()` и
`terminal_campaign_reward()`.

```text
reward = 0.5 · (standing_after − standing_before)
       + 0.5 · 0.5 · ((power+cohesion)_after − (power+cohesion)_before)
       + 1.0 · (health_after − health_before) / 100
       − 1.0 · (sickness_after − sickness_before) / 1
       − 0.8 · (wound_after − wound_before) / 1
       + 0.10, если действие успешно
       + outcome_delta
```

Терминальный бонус: `win = +1.0`, `lose = −1.0`, `neutral = 0.0`.
Усечение горизонта (`truncated`) — ничья (`winner = None`), а не поражение.

---

## 10. Время

### 10.1. Арена

**Код:** `core41/clock.py`.

```text
BASE_TICK_SECONDS = 1.0
SPEEDS = (пауза, 1x, 2x, 4x, 8x, 16x)
advance(dt) возвращает число целых тактов
MAX_CATCHUP_TICKS = 64  (лишние отбрасываются в dropped_ticks)
```

`1x` — это физическая секунда на такт. Ускорение меняет число тактов за
реальную секунду, но не длительность самого такта. Поэтому «замедлить» игру
— значит уменьшить динамику, а не растянуть физическое время.

### 10.2. Кампания автоматов

**Код:** `configs/campaigns/base/automata_defaults.json`.

```text
turn_seconds = 240
actions_per_turn = 3
action_interval_seconds = 80
ai_interval_seconds = 80
organization_interval_seconds = 240
speeds = [1, 2, 4, 8, 16, 32]
```

Один ход — `240` секунд, внутри — три действия по `80` секунд. Полное
восстановление лимита действий за `2` минуты недопустимо: бюджет `E`
восстанавливается по правилам мира, а не ускорением.

### 10.3. День `world_actor`

**Код:** `campaign/clock.py`.

```text
SECONDS_PER_DAY = 120.0
MAX_CATCHUP_DAYS = 7
```

Это отдельный дневной мир; не путать с `turn_seconds = 240` кампании
автоматов.

---

## 11. Легаси `simulation.py`

**Код:** `simulation.py`, `p_success()`.

Старый канон дуэлей использует другую формулу:

```text
mass    = min(att_work, MAX_WORK) / max(dfn_work, 1)
penalty = K_TYPE, если контр-тип совпал, иначе 0
logit   = K_MASS · ln(mass) − penalty
p       = P_BASE / (1 + e^(−logit))
```

Это **не** активный игровой поток: `simulation.py` остаётся
воспроизводимым baseline и легаси-каноном. Активные сцены (`game_engine.py`,
`ui/battlefield.py`) используют `core41`.

---

## 12. Сводная таблица констант

### Ядро (`core41/model.py`)

| Константа | Значение |
|---|---|
| `HEALTH_MAX` | `100` |
| `HEALTH_CRITICAL` | `25` |
| `HEALTH_REST_REGEN` | `0.78` |
| `HEALTH_STARVE_DECAY` | `0.20` |
| `HEALTH_DAMAGE_RATIO` | `0.25` |
| `HEALTH_ATTACK_FLOOR` | `0.50` |
| `SICKNESS_MAX` | `1.0` |
| `SICKNESS_CRITICAL` | `0.75` |
| `SICKNESS_HEALTH_DECAY` | `1.5` |
| `SICKNESS_DAMAGE_BONUS` | `0.50` |
| `SICKNESS_PROGRESS` | `0.004` |
| `SICKNESS_REST_RECOVERY` | `0.01` |
| `SICKNESS_TREAT_RATE` | `0.08` |
| `TREAT_ENERGY_FRACTION` | `0.10` |
| `CONTAGION_CHANCE` | `0.35` |
| `CONTAGION_SEVERITY` | `0.50` |
| `SICKNESS_WORK_PENALTY` | `0.60` |
| `SICKNESS_WORK_FLOOR` | `0.40` |
| `WOUND_WORK_PENALTY` | `0.70` |
| `WOUND_WORK_FLOOR` | `0.30` |
| `WOUND_PROGRESS` | `0.002` |
| `WOUND_MAX` | `1.0` |
| `WOUND_HEALTH_DECAY` | `0.60` |
| `WOUND_REST_RECOVERY` | `0.012` |
| `WOUND_TREAT_RATE` | `0.10` |
| `WOUND_REGEN_PENALTY` | `0.50` |
| `WOUND_DAMAGE_BONUS` | `0.25` |
| `ENERGY_STORAGE_SHARE` | `0.35` |

### Арена и давление (`core41/arena.py`, `core41/model.py`)

`PRESSURE_DECAY` и `OPEN_PRESSURE` заданы в `core41/model.py` и
используются ареной; остальные строки — из `core41/arena.py`.

| Константа | Значение |
|---|---|
| `FORCE_WORK_RATIO` | `1.0` |
| `INFO_COST_FACTOR` | `0.60` |
| `CHARGE_DAMAGE_BONUS` | `0.20` |
| `INFO_PRESSURE_PER_WORK` | `0.50` |
| `PRESSURE_MAX` | `30.0` |
| `CAPTURE_RATIO` | `1.5` |
| `CAPTURE_STREAK` | `36` |
| `CAPTURE_FRAC` | `0.10` |
| `OPEN_PRESSURE` | `8.0` |
| `PRESSURE_DECAY` | `0.82` |
| `PRESSURE_PER_WORK` | `0.30` |
| `REST_REGEN` | `14.0` |
| `REST_FORCE` | `0.60` |

### Кампания (`campaign/world.py`, `campaign/economy.py`)

| Константа | Значение |
|---|---|
| `CAMPAIGN_HEALTH_REGEN` | `1.0` |
| `CAMPAIGN_SICKNESS_PROGRESS` | `0.01` |
| `CAMPAIGN_SICKNESS_HEALTH_DECAY` | `6.0` |
| `CAMPAIGN_WOUND_HEALTH_DECAY` | `4.0` |
| `CAMPAIGN_CONTAGION_CHANCE` | `0.30` |
| `CAMPAIGN_CONTAGION_SEVERITY` | `0.35` |
| `CAMPAIGN_SKILL_GAIN` | `0.03` |
| `CAMPAIGN_SKILL_FAILURE_GAIN` | `0.01` |
| `CAMPAIGN_SKILL_CAP` | `0.90` |
| `COLLAPSE_POWER` / `COLLAPSE_COHESION` | `0.05` |
| `COLLAPSE_GRACE_DAYS` | `2` |
| `COLLAPSE_LEGITIMACY` | `0.02` |
| `DISMISSAL_STANDING` | `0.05` |
| `DISMISSAL_LEGITIMACY` | `0.08` |
| `ROLE_CHANGE_COOLDOWN_DAYS` | `5` |
| `LEGITIMACY_RECOVERY` | `0.02` |
| `MARKET_BUY_EFFICIENCY` | `0.60` |
| `MARKET_SELL_EFFICIENCY` | `0.75` |
| `CREDIT_INTEREST` | `0.10` |
| `CREDIT_DAYS` | `7` |
| `POVERTY_ENERGY_RATIO` | `0.25` |

### Чекпойнты и признаки

| Параметр | Значение |
|---|---|
| `CHECKPOINT_VERSION` | `3` |
| `DUEL_CHECKPOINT_VERSION` | `5` |
| аренные признаки `bdi`/`qtable`/`mlp` | `22` |
| признаки `duel-mlp` | `30` |
| `SCHEMA_VERSION` снимка мира | `1` |

---

## 13. Где менять формулу

| Что нужно | Где менять |
|---|---|
| КПД каналов | `core41/model.py`, `FORM_CONVERSION_EFFICIENCY` |
| Коэффициенты успеха | `DEFAULT_SUCCESS_COEFFICIENTS` или `success.coefficients` действия |
| Здоровье/болезнь/раны | `core41/model.py` (`HEALTH_*`, `SICKNESS_*`, `WOUND_*`) |
| Урон и захват арены | `core41/arena.py` |
| Награду арены | `core41/arena.py`, `REWARD_*` |
| Дрейф, распад, доход | `campaign/world.py` (`DECAY_*`, `COLLAPSE_*`, `CAMPAIGN_*_INCOME`) |
| Экономику | `campaign/economy.py` |
| Коалиции | `campaign/coalitions.py`, блок `coalitions` мира |
| Отношения | `campaign/relations.py` |
| Награду кампании | `campaign/env.py`, `CAMPAIGN_REWARD_*` |
| Темп кампании автоматов | `configs/campaigns/base/automata_defaults.json` |
| День `world_actor` | `campaign/clock.py`, `SECONDS_PER_DAY` |

**Правило.** Если формула задаёт поведение ядра, её константы живут в коде
ядра; если это данные мира (темп, цены, пороги контента) — в `configs/`.
Нельзя дублировать одно и то же число в коде и конфиге без явного
переопределения.
