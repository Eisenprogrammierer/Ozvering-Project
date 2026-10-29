# Обучаемые агенты и RL-срез

**Статус:** текущая реализация. Это первый слой, а не полная миграция мира.
**Дата:** 2026-10-29
**Связанные документы:** [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md),
[`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md),
[`MODEL.md`](MODEL.md).

---

## 1. Что уже работает

В коде появились два независимых, но совместимых слоя.

### 1.1. `core41/` — дуэльный срез целевой модели

`core41` реализует минимальный вертикальный срез 4-2-1:

- `Work` — работа `{amount, form, payload, duration}`; `form` — канал, а не
  тип энергии;
- `Automaton` — `I/O/H/S/F/E/W` с одной универсальной энергией;
- `DuelWorld` — два автомата, обработчики, давление, окно входа,
  логистическая вероятность успеха;
- `DuelEnv` — Gym-подобный интерфейс `reset/step` для раннего `force`-среза;
- `ArenaEnv` — Gym-подобная среда активной арены: `ArenaMatch`, шесть
  `CORE_ACTIONS`, `info`/`force`, захват и та же награда, что в игре;
  обучение идёт внешним циклом (`auto_learn=False`), чтобы политика не
  обновлялась дважды;
- `ArenaEnvironment` — актор среды: при `with_env=True` по расписанию
  добавляет истощение/передышку, средовой источник болезни
  (`ENV_ILLNESS_INTERVAL`/`ENV_SICKNESS`) и острые раны
  (`ENV_WOUND_INTERVAL`/`ENV_WOUND_DAMAGE`), учитывает сезонность
  (`SEASONS`) и асимметрию (основная сторона получает полный эффект,
  вторая — `ENV_SECONDARY_SHARE`); наблюдаемое расписание отдаётся в
  `Observation.env_pressure/env_season` (включая `illness`/`wound`). При
  `with_env=False` среды нет, а признаки нейтральны, поэтому прежняя
  калибровка арены сохраняется;
- `arena.py` — runtime активной арены: `ArenaAgent`, `ArenaMatch`,
  `run_duel_tick`, `check_capture`, формы `force`/`info` и UI-совместимый
  фасад (`force`, `energy_pool`, `health`, `defense`, `w_adopt`, `Q`,
  истории);
- здоровье — отдельное состояние `S`, не энергия: `health ∈ [0, max_health]`,
  смерть при `health <= 0`; урон переполнения после `F=0` идёт в здоровье;
- болезнь — отдельное изменяющееся состояние `sickness ∈ [0, 1]`, не энергия
  и не статический множитель: она влияет на урон, отдых и лечение;
- `Action`, `Observation`, `Transition` — общий контракт агентского слоя;
- `REST` предлагается только когда есть что восстанавливать (`E`, `F`,
  здоровье неполны или есть болезнь). Полностью отдохнувшему агенту no-op
  не предлагается: иначе две стороны могут бесконечно выбирать `REST`, и
  self-play сходится к 100% таймаутов;
- лимит шагов арены — **усечение** (`truncated`), а не победа по остатку
  `(force, health)`. На усечении `winner=None`, а `Transition.done=False`:
  политика не получает выдуманный терминальный `±1.0`.

`core41` не является полным миром: в нём нет кампании, организаций и
кампанийного планировщика. Конверсии между формами работы ещё не реализованы.
Здоровье/смерть и секундный клок реализованы как первый рабочий срез, а не как
финальная физиология и не как полный real-time мир.

### 1.2. Здоровье, смерть и множители

Принятая первая модель (константы — `core41/model.py`):

| Параметр | Значение | Смысл |
|---|---|---|
| `HEALTH_MAX` | 100 | старт и потолок здоровья |
| `HEALTH_CRITICAL` | 25 | критический порог (авто-пауза, HUD) |
| `HEALTH_REST_REGEN` | 0.78/тик | отдых при `E > 0` восстанавливает здоровье |
| `HEALTH_STARVE_DECAY` | 1.0/тик | при `E = 0` здоровье падает |
| `HEALTH_DAMAGE_RATIO` | 0.62 | доля переполнения урона, идущая в здоровье |

Урон сначала поглощается `F`; остаток после `F=0` уменьшает здоровье. Смерть —
`health <= 0`, а не `F=0`: обнулённая сила означает потерю способности влиять,
но персонаж ещё может отдохнуть. `REST` восстанавливает `F`, `E` и немного
здоровья; работа при нулевой энергии ускоряет истощение.

Множители состояния (`health_factors`): `aging`, `illness`, `stress`, `care`.
Их можно задать у `Automaton` или через `ArenaAgent.set_health_factor(...)`:

- истощение: `aging · illness · stress`;
- урон: `aging · illness`;
- восстановление: `care / max(0.25, illness)`.

Значения клампятся в `[0, 10]`. Это позволяет моделировать возраст, болезнь,
уход и стресс без введения отдельных типов энергии.

Болезнь как процесс (`sickness ∈ [0, 1]`, `core41/model.py`):

| Параметр | Значение | Смысл |
|---|---|---|
| `SICKNESS_MAX` | 1.0 | потолок тяжести болезни |
| `SICKNESS_CRITICAL` | 0.75 | порог тяжёлой болезни для UI/авто-паузы |
| `SICKNESS_HEALTH_DECAY` | 1.5/тик | урон здоровью при `sickness = 1` |
| `SICKNESS_DAMAGE_BONUS` | 0.5 | добавка к переполнению урона |
| `SICKNESS_PROGRESS` | 0.004/тик | пассивное прогрессирование |
| `SICKNESS_REST_RECOVERY` | 0.01/тик | восстановление отдыхом |
| `SICKNESS_TREAT_RATE` | 0.08 | снятие болезни действием `TREAT` |
| `CONTAGION_CHANCE` | 0.35 | шанс передачи при `sickness = 1` |
| `CONTAGION_SEVERITY` | 0.50 | доля болезни источника при передаче |
| `SICKNESS_WORK_PENALTY` | 0.60 | снижение работоспособности при `sickness = 1` |
| `SICKNESS_WORK_FLOOR` | 0.40 | нижняя граница множителя работы |

- `infect(severity)` задаёт болезнь, `treat(amount)` снимает её;
- без отдыха болезнь растёт на `SICKNESS_PROGRESS · aging · illness · stress`
  за такт и наносит `SICKNESS_HEALTH_DECAY · sickness · aging` урона
  здоровью (без повторного `illness`);
- отдых снижает болезнь на `SICKNESS_REST_RECOVERY · care / max(0.25, illness)`
  и лечит здоровье;
- переполнение урона после `F=0` умножается на
  `1 + SICKNESS_DAMAGE_BONUS · sickness`;
- успех работы умножается на `work_effectiveness = max(0.40,
  1 - 0.60 · sickness)` в логите `success_probability`; сохранённый навык и
  расход `E` не меняются, `illness` действует только через `sickness`;
- `sickness = 0` по умолчанию не меняет прежнюю калибровку здоровья;
- лечение — шестое действие `TREAT` (`CORE_ACTIONS` из шести): тратит
  `TREAT_ENERGY_FRACTION = 0.10` от `max_energy`, снимает
  `SICKNESS_TREAT_RATE`, при отсутствии болезни бесполезно;
- `TREAT` предлагается политике и в `DuelWorld.legal_actions` только при
  `sickness > 0`, поэтому здоровая дуэль сохраняет прежнюю калибровку;
- `Observation` содержит `self_sickness`/`opponent_sickness`; BDI-политика
  видит их и признак `is_treat`, QTable включает болезнь в ключ состояния;
- источник болезни — явное `--sickness`/`infect()`; после успешного
  `force`-контакта возможна асимметричная передача:
  шанс `CONTAGION_CHANCE · sickness`, тяжесть
  `CONTAGION_SEVERITY · sickness`; `info`, мёртвый получатель и максимум
  болезни передачи не дают;
- средовой резервуар болезни и острые раны реализованы в
  `ArenaEnvironment` (первый срез §2.3.5); кампанийная передача болезни —
  контакт в одном узле (`CAMPAIGN_CONTAGION_CHANCE`/
  `CAMPAIGN_CONTAGION_SEVERITY`); устойчивые раны с отдельным состоянием
  пока не реализованы;
- `health`/`sickness` — состояние персонажа: `condition_state()`/
  `load_condition()` переносят его между партиями, `reset_state()` остаётся
  жёстким сбросом. `GameApp.progress()` сохраняет текущие `health_*`/
  `sickness_*`, `GameScene` восстанавливает их после перемотки тика; старые
  сейвы используют начальное `sickness`;
- кампанийный `WorldEngine` получил дневной срез §2.3.4: у героя и персонажей
  есть `health/sickness/alive`, `end_day()` прогрессирует болезнь, смерть
  героя завершает кампанию, смерть персонажа запрещает действия с ним,
  `power`/`cohesion` узла не выше `0.05` два дня подряд — распад организации
  (полный ноль — сразу), а низкая репутация/легитимность — смена роли, не
  поражение. Условия сохраняются в `to_dict()`/`load_snapshot()`;
  `WorldScreen` показывает `H` и болезнь, панель поля боя — бар болезни.

Начальная болезнь задаётся через `--sickness 0..1`
(или раздельно `--sickness-rl`/`--sickness-ai`), `MatchEngine(sickness=...)`,
`ArenaMatch(sickness_rl=..., sickness_ai=...)` или
`BattlefieldModel(sickness=...)`.

Калибровка дуэльного среза закреплена экспериментом
`experiments/exp_health_calibration.py` (N=100, 2000 тактов, QTable
против BDI). Текущие `0.70` урона и `0.75` отдыха после смены награды и
`CAPTURE_STREAK = 22` дают 49% смертей, 23% захватов и 28% таймаутов при
медиане 646 тактов; голод — 20.5% урона. Старые `1.0`/`0.5` давали 72%
смертей и 2% таймаутов. С болезнью: `--sickness 0.25` — 57/17/26%,
`0.50` — 41/28/31%, `0.75` — 50/23/27% (смерть/захват/таймаут); медиана
666–817 тактов, голодный урон 20.5–25.5%. Все полосы остаются в допуске.
Целевые полосы, таблица «было/стало» и команды повторной проверки — в
[`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md), §2.3.2–2.3.3.

### 1.3. Реальное время

`core41/clock.py` содержит `SimulationClock` — первый срез реального времени:

- базовый тик — `1.0` секунды (`BASE_TICK_SECONDS`);
- скорости — пауза, `1x`, `2x`, `4x`, `8x`, `16x` (`SPEEDS`);
- `advance(dt)` копит дробные тики и возвращает число целых тактов;
- пауза сохраняет выбранную скорость и возвращается к ней при `resume()`;
- авто-пауза (`auto_pause=True`) срабатывает на завершении партии и при
  здоровье `H <= 25` (`HEALTH_CRITICAL` в `core41/model.py`);
- догон ограничен `MAX_CATCHUP_TICKS = 64`, лишние тики отбрасываются и
  считаются в `dropped_ticks` — окно не «зависает» после сворачивания;
- при потере фокуса `GameApp.run` пропускает отрисовку, но продолжает
  `update`, то есть симуляция идёт в фоне.

Активная арена (`GameApp`) использует этот клок: `--speed 1|2|4|8|16`,
`--no-auto-pause`. Полноценный real-time-планировщик кампании (непрерывные
внутридневные действия и политика автономных персонажей вне кадра) не
реализован; первый срез — очередь намерений (`campaign/planner.py`) и
фон/оффлайн-догон (`campaign/clock.py`).

### 1.4. `agents/` — политики и адаптивный агент

- `BDIPolicy` — BDI-политика с убеждениями/желаниями/намерениями и линейной
  TD-оценкой; обновляется online;
- `QTablePolicy` — табличный baseline;
- `RandomPolicy` — baseline для сравнения;
- `PolicyAgent` — совместимый мост к `simulation.Agent` для легаси-тестов и
  экспериментов; активные сцены его больше не создают;
- `agents.train` — CLI обучения на `DuelEnv`.

`PolicyAgent` сохраняет API `simulation.Agent` (`force`, `energy_pool`,
`sense`, `form_intention`, `rest_if_starving` и т.д.), поэтому старые тесты и
эксперименты можно запускать без переписывания. Активная арена использует
`ArenaAgent` и одну универсальную энергию.

---

## 2. Что изменилось в игре

Обе активные сцены работают на `core41`:

- `game_engine.MatchEngine` создаёт `ArenaMatch`; RL-сторона — `QTablePolicy`
  (Q-learning), BDI-сторона — `BDIPolicy`. `PolicyAgent`, `RLAgent` и
  типизированная энергия в игровой поток не входят;
- `ui/battlefield.Commander` создаёт `ArenaAgent`; человек управляет своей
  стороной, противник использует `BDIPolicy`;
- дуэль на тактическом поле идёт через `core41.run_duel_tick`, захват — через
  `core41.check_capture`;
- `UtilityAI` больше не создаётся в игровом потоке; он остаётся в
  `simulation.py` как baseline для `tests/test_canon.py` и исторических
  экспериментов.

`simulation.check_capture` сохраняет необязательные метки победителя
(`winner_rl`, `winner_ai`) для легаси-тестов. Активные сцены используют
`core41.check_capture`, а `simulation.py` не импортируется из `game_engine.py`
и `ui/battlefield.py`.

Обучение в игре:

- `ArenaMatch` обновляет обе политики после каждого такта (`auto_learn=True`);
- `ArenaEnv` по умолчанию создаёт матч с `auto_learn=False`: действия
  выбирает и `Transition` обрабатывает внешний цикл обучения;
- `BattlefieldModel` обновляет BDI-политику противника после дуэли;
- награда — изменение силы, энергии, здоровья и болезни плюс терминальный
  бонус за победу/поражение:
  `F` и `H` нормированы на максимумы, стоимость `E` — `0.6·ΔE/E_max`,
  снятие своей болезни — `+1.0·Δsickness`, заражение противника —
  `+0.5·Δsickness`, победа `+1.0`, поражение `-1.0` (`reward_delta`,
  `terminal_reward` в `core41/arena.py`).

Это online-обучение на коротких партиях. Оно не заменяет офлайн-тренировку и
не гарантирует сильную политику.

---

## 3. Как обучить политику

Из корня репозитория:

```bash
venv/bin/python -m agents.train --episodes 500 --seed 0
```

По умолчанию обучение идёт в `ArenaEnv` — той же среде, что активная арена
(`force`/`info`, `TREAT`, захват). Горизонт арены по умолчанию — 2000 шагов:
на 160 шагах захват (22 тика доминирования) почти не успевает случиться, и
self-play выглядит как 100% ничьих. Ранний `force`-срез доступен явно:

```bash
venv/bin/python -m agents.train --episodes 500 --seed 0 --env duel
```

Дневной кампанейный срез (проблема готовности №6) выбирается флагом
`--env campaign`: там один агент без оппонента и без self-play, действие —
`CampaignAction` (`END_DAY`, `TREAT_SELF` и ordinary-ходы `WorldEngine` по
всем доступным адресатам), награда — `campaign_reward()` из дельт
положения/организации/здоровья/болезни с терминальным бонусом исхода ±1.0;
горизонт 30 дней — усечение обучения, а не поражение. Мир по умолчанию
работает в бесконечной рамке (`infinite=True`), а нарративный финал задаётся
`end_storyline()`.

```bash
venv/bin/python -m agents.train --episodes 100 --seed 0 --env campaign \
    --policy bdi
```

Кампанейные наблюдения проходят через `campaign_features()` (21 признак:
18 прежних, код действия и два нейтральных env-слота), поэтому `bdi`/`mlp`
различают `inspect` и `build_network`; для таблиц есть отдельный вид
`qtable-campaign` — его ключ строится из дневных разрядов и не смешивается
с аренной Q-таблицей.
Персонаж кампании — `CampaignActor` на том же ядре: `E` — дневной бюджет
действий (`CAMPAIGN_ENERGY_MAX / actions_per_day` на действие), `F` —
`standing` (0..1), `H`/`sickness` — общие с ареной. `actions_left` остаётся
проекцией `E`, поэтому старый UI/сейвы совместимы, а наблюдение отдаёт
`energy/max_energy/force/max_force`.
`CampaignEnv(target_mode="all")` открывает действия по всем узлам (по
умолчанию), `target_mode="first"` сохраняет прежний узкий режим. Потеря
должности без замены завершает эпизод нейтральным исходом, а не оставляет
состояние с единственным `END_DAY`. Персистентность среды:
`CampaignEnv.state_dict()/load_state_dict()` сохраняют снимок мира, сид,
горизонт и `target_mode`.

Навыки профиля растут от практики: `WorldEngine.execute()` после действия
добавляет прирост в навыки домена цели (или домена действия), успех —
`CAMPAIGN_SKILL_GAIN`, провал — `CAMPAIGN_SKILL_FAILURE_GAIN`, с
насыщением к `CAMPAIGN_SKILL_CAP`. `aptitudes` и доступные предметы
пересчитываются, поэтому стартовый профиль может дорасти до требований
`seek_promotion` и вышестоящих должностей. Карьерные действия в
`CampaignEnv` по-прежнему исключены из `legal_actions()`: повышение — это
решение игрока/UI, а не автоматический шаг политики.

Очередь намерений (`campaign/planner.py`, первый срез real-time-
планировщика §7 №31): `WorldEngine.schedule_intent(due_day, kind, ...)`
откладывает событие на будущий день, `IntentQueue` исполняет его в начале
`end_day()` до хода ИИ, а очередь входит в снимок мира. Виды первого среза:
`message` (только журнал) и `contact` (персонаж сам выходит на связь и
применяет `payload["effects"]`). Персонаж с `autonomous: true` и
`autonomy_period` сам назначает контакты; по умолчанию автономия выключена,
поэтому баланс существующих миров не меняется. `CampaignEnv` отдаёт число
планов в `info["intents"]`, а `WorldScreen` показывает `планов N` в шапке.
Очередь ограничена `MAX_INTENTS = 64` и отбрасывает самые далёкие события.

Обучение по умолчанию идёт в self-play: обе стороны получают собственный
`Transition` и обновляют свои политики. Отключить обучение противника можно
флагом `--no-self-play`; тогда он остаётся фиксированным спарринг-партнёром.

После обучения CLI по умолчанию играет held-out матрицу силы: политика
против `bdi`, `qtable`, `random` и `mlp` на отдельных seed'ах, без
исследования и без обновления весов. Параметры:

```bash
venv/bin/python -m agents.train --episodes 2000 --seed 0 \
    --eval-episodes 50 --eval-seed 100000 \
    --eval-opponents bdi,qtable,random,mlp \
    --out saves/bdi.json --eval-out saves/eval.json
```

`--eval-episodes 0` выключает оценку. Матрица также доступна из Python:
`agents.train.evaluate(policy, opponent, ...)` и
`agents.train.evaluate_matrix(policies, opponents, ...)`. Оценка никогда не
вызывает `observe()` и не меняет веса.

Перед held-out матрицей `qtable`/`mlp` без чекпойнта **прогреваются** на
отдельном потоке seed'ов (`--eval-baseline-episodes`, по умолчанию 50):
иначе их строка измеряла бы случайную инициализацию, а не baseline. Прогрев
идёт против стабильного `bdi`, не касаясь основной политики и eval seed'ов;
в строке появляются `trained_episodes` и `policy_source` (`warmup`/
`builtin`). Готовый чекпойнт можно передать явно и отключить прогрев:

```bash
venv/bin/python -m agents.train --episodes 2000 --seed 0 \
    --eval-episodes 50 --eval-opponents bdi,qtable,random,mlp \
    --eval-checkpoint qtable=saves/qtable.json \
    --out saves/bdi.json --eval-out saves/eval.json
```

`--eval-baseline-episodes 0` оставляет baseline нетренированным (строка
честно помечается `policy_source: builtin`, `trained_episodes: 0`).

С сохранением весов:

```bash
venv/bin/python -m agents.train --episodes 2000 --seed 0 --out saves/bdi.json
```

CLI печатает JSON со статистикой (`wins`, `losses`, `draws`, `win_rate`,
`policy_updates`, `opponent_updates`, `resumed_from`, `eval`). `BDIPolicy`
умеет `save/load`; все политики — `state_dict/load_state_dict`.
`agents.load_policy(path)` читает `kind` из файла и возвращает `BDIPolicy`,
`QTablePolicy` или `MLPPolicy`.

Продолжить обучение с чекпойнта можно флагами `--resume`/`--resume-opponent`
(проблема готовности №5). `--resume` относится к обучению и остаётся явным:
случайный чекпойнт из `checkpoints/` не должен незаметно менять эксперимент.

```bash
venv/bin/python -m agents.train --episodes 2000 --seed 0 \
    --resume saves/bdi.json --resume-opponent saves/qtable.json \
    --out saves/bdi.json
```

Доменная рандомизация (проблема готовности №7): `--domain-randomize` берёт
перед каждым обучающим эпизодом новый домен — профили арены, стартовую
болезнь сторон, множители health-факторов (`arena`) или джиттер навыков и
болезнь героя (`campaign`). Диапазоны задаются флагами; жеребьёвка
детерминирована `--seed` (отдельный rng с солью 7919), поэтому запуск
воспроизводим. Для `--env duel` флаг честно игнорируется (легаси-срез без
доменных параметров, в статистике `domain_randomize: false`):

```bash
venv/bin/python -m agents.train --episodes 2000 --seed 0 \
    --domain-randomize \
    --profiles CANON,ZEALOT,ORTHODOX \
    --sickness-min 0.0 --sickness-max 0.6 \
    --health-factors aging,illness,stress,care \
    --health-min 0.75 --health-max 1.25 \
    --skill-jitter 0.25          # только для --env campaign
```

Held-out оценка по умолчанию идёт на фиксированном каноническом домене —
иначе матрица силы несравнима между запусками. Явный
`--eval-domain-randomize` усредняет оценку по распределению доменов
(строки матрицы получают `domain_randomized: true`; для `--env duel` флага
нет, потому что домены там не применяются). Для `--env campaign` held-out
оценка — одна строка «политика против мира» (`opponent: "world"`): оппонента
в кампании нет, и матрица из одинаковых строк была бы шумом. Неизвестные
имена профилей и health-факторов отвергаются с `ValueError`.

В общем учёте кампании усечение горизонта (`truncated`) — ничья
(`winner: None`), а не поражение; терминальный `lose` остаётся поражением
только при гибели героя/распаде организации по правилам `WorldEngine`.

Загрузить чекпойнт в активную сцену можно явно:

```bash
python3 main.py --checkpoint saves/bdi.json
python3 main.py --arena --checkpoint saves/bdi.json
python3 main.py --scene battlefield --checkpoint saves/bdi.json
python3 main.py --health-factors aging=1.5,illness=2,care=0.8
python3 main.py --sickness 0.5    # начальная болезнь 0..1
python3 main.py --speed 4          # 1x/2x/4x/8x/16x
python3 main.py --no-auto-pause    # отключить авто-паузу
```

Production-автопоиск (P2, `agents/checkpoints.py`): если `--checkpoint` не
задан, игра сама берёт чекпойнт из каталога `checkpoints/` (или
`OZVERING_CHECKPOINT_DIR`, или `--checkpoints-dir`). Порядок — `best.json`,
`latest.json`, затем самый свежий `*.json` по `mtime`. Файл должен быть
JSON-объектом известного вида (`bdi`/`qtable`/`mlp`) и не новее
`CHECKPOINT_VERSION`; битые и чужие файлы пропускаются, поэтому испорченный
`best.json` не ломает запуск. Явный `--checkpoint` всегда важнее автопоиска,
`--no-auto-checkpoint` возвращает прежнее поведение «всегда новая BDI», а
`--list-checkpoints` печатает найденное без открытия окна:

```bash
python3 main.py --list-checkpoints
python3 main.py --arena --list-checkpoints --checkpoints-dir saves/
python3 main.py --no-auto-checkpoint            # игнорировать checkpoints/
```

Тот же автопоиск работает для автопилота кампании (`main.py --campaign`):
`App(checkpoint=...)` передаёт путь в `WorldScreen`, а битый файл
логируется и заменяется свежей BDI, не роняя игру.

```python
from agents import load_policy
from core41 import ArenaAgent

policy = load_policy("saves/bdi.json", seed=0)
agent = ArenaAgent("player", policy=policy, seed=0)
```

Старый `PolicyAgent` по-прежнему умеет `load_policy("saves/bdi.json")` для
легаси-моста. Оценка качества загруженной политики есть в
`agents.train.evaluate`; `--save-best` выбирает лучший held-out чекпойнт во
время обучения, а `agents/checkpoints.py` находит его при запуске игры.

---

## 4. Контракт наблюдения и действия

```text
Observation: F/E/H свои и противника, давление, окно входа, время, формы
Action:      REST | TREAT | WORK(form, fraction), form = force | info
Transition:  observation, action, reward, next_observation, done, next_actions
```

`ArenaAgent` — это автомат плюс политика. Он не хранит типизированную
энергию: `energy_pool` — проекция единственного `E`, а `form` выбирает канал
работы. `Policy`-объект должен уметь:

- `act(observation, actions, explore=True) -> Action`;
- `observe(transition) -> None`;
- `state_dict()/load_state_dict()` для сохранения.

Этого достаточно для подключения будущей нейросетевой политики без изменения
игрового цикла.

### Ёмкость политик и версии чекпойнтов (проблемы готовности №4–№5)

Активный набор политик в `agents/policies.py`:

| kind      | ёмкость                          | обучение                        | роль                    |
|-----------|----------------------------------|---------------------------------|-------------------------|
| `bdi`     | линейные веса 21×6               | online градиент по признакам    | baseline AI             |
| `qtable`  | таблица, ключ 12 полей           | tabular Q(λ)-подобный TD        | baseline RL             |
| `mlp`     | tanh-hidden=16                   | online TD(0) + target-сеть      | function approximation  |
| `random`  | нет весов                        | нет                             | спарринг/нижняя граница |

`MLPPolicy` использует те же 21 признак, что `BDIPolicy`, совместима с
`ArenaEnv`/`DuelEnv` и не требует PyTorch; `bdi`/`qtable` остаются
baseline. Двадцатый и двадцать первый признаки — наблюдаемое расписание
среды (`env_pressure`/`env_season`); в кампании они нейтральны. Девятнадцатый
признак — стабильный код действия (`action_feature_code()`): без него в
кампании `inspect` и `build_network` давали одинаковый вектор, потому что у
обоих `fraction=0`.

Формат чекпойнта версионирован: `CHECKPOINT_VERSION = 2` пишется в поле
`version` каждого `state_dict()`; файлы без поля трактуются как v0
(`checkpoint_version()`). Миграции при загрузке:

- v0 `QTablePolicy` — легаси-ключи 8/10 → 12 полей (отсутствующие
  sickness-поля заполняются нулём, коллизии усредняются). Ключи v1→v2 не
  менялись: код действия уже входит в ключ отдельным полем.
- v0/v1 `BDIPolicy` — короткий вектор веса дополняется нулями до 21.
- v1/v2 `MLPPolicy` — строки `weights1` 18/19→21 дополняются нулями, поэтому
  выученные веса сохраняются; старый чекпойнт без target-сети копирует
  online-веса в target, а не оставляет случайную инициализацию.

`load_policy` отказывается читать файлы с версией выше поддерживаемой.
Старые шкалы и ранние сейвы при этом не ломаются: миграция происходит только
в памяти загруженной политики.

---

## 5. Ограничения и следующий шаг

- `simulation.py` всё ещё использует контекстные фазы `WATER/FIRE/EARTH`;
  это легаси-канон и baseline, но не активный игровой поток.
- `core41.arena` — дуэль/арена, а не мир. Кампания теперь использует
  `CampaignActor` с теми же `E/F/H`: `E` — дневной бюджет действий, `F` —
  `standing`, `H`/`sickness` — общие с ареной. Организационные шкалы
  (`power/cohesion/...`) остаются легаси-проекциями мира и не смешиваются с
  ареной; `CampaignEnv` (проблема №6) подключает их к обучению отдельной
  средой.
- Здоровье/смерть откалиброваны для дуэльного среза; болезнь, контактная
  передача и лечение реализованы в `core41` как процесс и шестое действие
  `TREAT`. `health`/`sickness` сохраняются в сейве и переносятся через
  `condition_state()`. В кампании есть дневной срез болезни, смерти,
  grace-распада организации, смена роли и бесконечный горизонт. Средовой
  резервуар болезни и острые раны закрыты первым срезом; открыты устойчивые
  раны, UI-болезни и непрерывные внутридневные действия кампании.
- `illness`-множитель и `sickness` сосуществуют осознанно: `illness` задаёт
  чувствительность процесса и общий урон, но не удваивает урон от текущей
  `sickness`. `SICKNESS_*`, `TREAT_ENERGY_FRACTION` и `CONTAGION_*` входят в
  `CALIBRATABLE`; болезнь сторон задаётся `--sickness-rl`/`--sickness-ai`.
- Реальное время есть в арене (`SimulationClock`); в кампании появился
  ограниченный фоновый/оффлайн-догон (`campaign/clock.py`) и первый срез
  планировщика — очередь намерений (`campaign/planner.py`), но непрерывных
  внутридневных тиков и production-планировщика по-прежнему нет.
- Актор среды `ArenaEnvironment` есть в новом runtime: при `with_env=True`
  он по расписанию добавляет истощение/передышку (`ENV_EVENT_INTERVAL`/
  `ENV_RELIEF_INTERVAL`), учитывает сезонность и асимметрию, а
  `ArenaMatch`, `MatchEngine` и `BattlefieldModel` выставляют `env`
  реальным объектом. `ArenaEnv` по умолчанию `with_env=True`
  (train/serve alignment), `--no-with-env` — контрольное плечо. Это рабочий
  срез, а не полная экономика среды: средовой резервуар болезни и острые
  раны есть, а собственные цели среды, устойчивые раны и
  `force/defense/in_open` открыты.
- Коэффициенты логистики и единицы `F/E/W` остаются открытыми.
- Нет PyTorch-зависимости; `MLPPolicy` — собственный tanh-MLP (online TD(0)
  с target-сетью и периодической синхронизацией) без внешних библиотек,
  `bdi`/`qtable` остаются линейной/табличной baseline.
- Production-чекпойнт находится автоматически (`agents/checkpoints.py`):
  `--checkpoint` важнее поиска, `checkpoints/best.json` → `latest.json` →
  свежий `*.json`, `--no-auto-checkpoint` отключает, `--list-checkpoints`
  печатает кандидатов. Для выбора лучшего чекпойнта во время обучения есть
  `--save-best`/`--best-every`/`--best-eval-episodes`; матрица силы
  считается через `agents.train.evaluate_matrix`.
- `UtilityAI` не удалён: он нужен как воспроизводимый baseline.

Следующий инженерный шаг — довести планировщик кампании до непрерывного
времени (внутридневные тики, приоритеты/отмена намерений), затем добавить
устойчивые раны и собственные цели среды. Калибровку здоровья
после миграции нужно повторить на новых политиках (`mlp`) и на длинных
прогонах. Проблемы готовности к
обучению №1–№7 закрыты по порядку: ArenaEnv, награда, self-play/eval,
ёмкость политик, версионирование чекпойнтов, CampaignEnv (включая `E/F/H`
персонажа), доменная рандомизация. Открытые вопросы §7 №28–31 закрыты первым
срезом (grace-распад, смена роли, бесконечный горизонт без `win`,
ограниченный фон/оффлайн-догон); глубокие вопросы перечислены в docs/TODO.md
и `WORLD_CORE_MODEL.md` §7.5.
