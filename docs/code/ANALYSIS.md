# Поэтапный анализ кода репозитория (Ozvering-Project)

> Документ генерируется по мере анализа. Каждый раздел = модуль/пакет:
> сигнатуры публичных функций/классов и краткая логика работы.
> Дата анализа: 2026-10-31.

## Оглавление и карта репозитория

```
/workspace
├── main.py            — точка входа, маршрутизация по флагам CLI
├── simulation.py      — каноническая модель дуэли агентов (4-2-1 ядро)
├── warfare.py         — война: потребности, личности, отряды, симуляция боя
├── game_engine.py     — pygame-приложение «Арены» (визуализация дуэли)
├── information.py     — энтропийная модель убеждений (Shannon/noise floor)
├── observability.py   — канал наблюдения с разрешением и задержкой
├── lod.py             — Level-of-Detail интеграция времени в дуэли
├── core41/            — новое ядро: Automaton, Arena, Duel, Clock, Env
├── campaign/          — кампания: роли, персонажи, планировщик, мир
├── agents/            — политики RL, обучение, чекпойнты
├── automata/          — pygame-редактор графов конечных автоматов
├── organizations/     — генератор организаций-суперсистем + runtime
├── naming/            — генератор русских имён/названий (морфология)
├── systems/           — системные автоматы: среда, драматург, события
├── interaction/       — модель диалогового взаимодействия
├── ui/                — pygame UI «Престола» (сцены)
├── view/              — pygame UI нового цикла (screens/support/ui)
├── experiments/       — численные эксперименты/калибровка модели
├── tests/             — pytest-тесты
├── configs/           — JSON-конфиги (автоматы, кампании и т.д.)
└── docs/              — документация (SOURCE_OF_TRUTH.md — приоритет)
```

Приоритет доменов (по README/docs/SOURCE_OF_TRUTH): `simulation.py` и
`warfare.py` — канон модели; `core41/` — новая онтология 4-2-1;
инструменты (`automata`, `organizations`, `naming`, `systems`) развиваются
в ветке без изменения канона.

---

## 1. Корневые модули

### 1.1 `main.py` (54 строки) — точка входа

**Сигнатуры:**
- `main(argv=None) -> int|None`

**Логика:**
- Парсит флаги-маршрутизаторы: `--automata|--editor` → `automata.app.main`;
  `--view|--campaign` → `view.app.main`; `--arena|--engine` → `game_engine.main`;
  `--interaction` → добавляет `--scene interaction` и идёт в `ui.app.main`.
- Флаги изымаются из `sys.argv` перед диспатчем. Без флагов — старое UI
  (`ui/app.py`). Обёртка `__main__`: печатает traceback и `sys.exit(1)` при
  фатальных ошибках.

### 1.2 `information.py` (89 строк) — энтропия убеждений

**Константы:** `N_BUCKETS = 4`, `H_MAX = ln(4)`.

**Сигнатуры:**
- `shannon_entropy(probs) -> float`
- `bucket_index(context_base: int, in_open: bool) -> int` — 3 если открыт,
  иначе контекст 0/1/2.
- `class BeliefEntropy(ema=0.25, sigma=0.15, df=3.0, deadband=0.15)`
  - `new_lineage(reset_counts=True) -> int` — сброс распределения (новая «линия» наблюдений).
  - `observe(context_base, in_open) -> (probs, H_local)` — EMA-обновление счётчиков бакетов, локальная энтропия, отслеживание минимума `H_min` и накопленного роста `H_cum`; `noise_floor = min(1, H_cum/H_MAX)`.
  - `next_factor(rng) -> float` — множитель шума `exp(sigma*noise_floor*t)` со Student-t (df), mёртвая зона `deadband`, кламп [0.5, 2.0].
  - `perturb(beliefs, rng) -> float` — применяет фактор к `opp_energy/opp_force/opp_w_adopt` в словаре убеждений.

**Логика:** рост энтропии наблюдений относительно исторического минимума →
«пол шума» → стохастическое искажение убеждений агента (шум тем сильнее, чем
менее предсказуем противник).

### 1.3 `observability.py` (56 строк) — канал наблюдения

**Сигнатуры:**
- `@dataclass(frozen=True) Observation(work: float = 0.0, count: int = 0)`
- `class LossyChannel(resolution=1.0, delay=0)`
  - `push(work)` — накопление работы (игнорирует ≤0).
  - `drain() -> Observation` — выдаёт квантованное `floor(acc/res)*res` + число событий; при `delay>0` ставит в очередь и выдаёт с задержкой (иначе пустой Observation).
  - `clear()`
- `class PublicEnvironment(env)` — фасад: свойство `in_open` → `env.public_window()`.

**Логика:** окружение «видит» суммарную работу участников лишь с конечным
разрешением и лагом — реализация ограниченной наблюдаемости.

### 1.4 `lod.py` (141 строка) — Level of Detail для дуэли

**Константы:** `LOD1, LOD2, LOD3 = 1, 2, 3`. Зависимость: `import simulation as S`.

**Сигнатуры:**
- `integrate_time(agent, dt, resting=True) -> bool` — аналитический шаг на `dt` тиков: списание `UPKEEP*dt`, реген энергии, затухание `w_adopt *= decay^dt`, закрытие окна; при отдыхе — логистическое приближение роста `force` к потолку `rest_ceiling` (`MAX_REST_DELTA/L` экспонента). Возвращает False, если событие «открыл→закрыл» или `force` упало до 1 (нужен точный шаг).
- `class LodController(work_threshold=None, horizon=None, error_tol=None)`
  - `near_boundary(agent)` / `stationary(agent)` — критерии близости к порогу Шмитта/голоду vs стационарности.
  - `work_interval(*agents) -> int` — сколько тиков можно «съесть» одним шагом: `threshold // rate`, кламп [1, horizon].
  - `level(*agents) -> LOD1|2|3`
- `mean_field_step(agent, dt, controller=None) -> bool` — LOD3: только для стационарных.
- `run_duel_lod(a, b, policy_a, policy_b, rng, env, ticks, controller=None) -> (ha, hb, levels)` — цикл дуэли: LOD1 — точный `S.run_tick`; LOD2 — крупный шаг + контрольный точный тик с rollback снапшота при нарушении условий; LOD3 — mean-field с rollback.

**Логика:** ускорение симуляции за счёт аналитической интеграции «скучных» периодов с гарантиями точности у границ событий.

### 1.5 `simulation.py` (892 строки) — КАНОН модели дуэли

**Данные:**
- `PARAMETERS: dict` (~40 констант: `P_BASE, K_MASS, K_TYPE, ON_FRAC, OFF_FRAC, OPEN_TTL, GAIN_MAX, Y_SMALL, DECAY_ADOPT, RETALIATE_FRACTION, HOCK_FRACTION, OPTION_VALUE, K_EFFECT, L_BASE, L_STEP, MAX_REST_DELTA, UPKEEP, CAPTURE_*, ENV_*, ENTROPY_*, OBS_*, LOD_*`); разворачивается в globals через `globals().update(PARAMETERS)`.
- `TYPES = ["FIRE","WATER","EARTH"]` (в PARAMETERS); `MULT` — круговое 3× превосходство (WATER>FIRE>EARTH>WATER).
- `PROFILES = {"ZEALOT":0.7, "ORTHODOX":0.85, "CANON":1.0}` — параметр `p` (эффективность/догматичность), валидируется при импорте (0 < p ≤ 1).
- `ACTIONS = [("REST",0)] + [(t, w) for t in TYPES for w in (0.3, 0.7)]` — 7 действий.

**Сигнатуры и логика:**
- `p_success(att_type, att_work, dfn_type, dfn_work) -> float`
  логистическая вероятность успеха: `P_BASE / (1+exp(-(K_MASS*ln(mass) - penalty)))`, mass = работа атакующего/защищающегося, штраф `K_TYPE` если тип защитника контрит атакующего.
- `class Agent(profile="CANON")` — базовая боевая единица:
  - поля `state{force, energy_pool, rest_units, last_act, last_work, w_adopt, in_open, open_timer}` и `beliefs{opp_*...}`; свойства-прокси к state.
  - `set_profile(profile, allow_out_of_range=False)` — строка из PROFILES или число p.
  - `reset_state()`, `new_entropy_lineage()`.
  - `context_base(energy_pool, w_adopt, in_open, force) -> 0|1|2` (statik) — классификация состояния: crisis(2)/normal(1)/low(0).
  - `receptive_type(...) -> str` — «восприимчивый тип» защиты = `TYPES[(base+hidden)%3]`, hidden — индекс последнего действия (скрытая ротируемая защита).
  - `rest_ceiling = L_BASE + L_STEP*rest_units`; `rest_gain()` — логистическая кривая отдыха `MAX_REST_DELTA*(e/L)(1-e/L)`; `do_rest(chosen)`.
  - `regen = max(1, floor(sqrt(force)))`; `tick_energy()` — пополнение пула до `E_MAX_MULT*regen`.
  - `schmitt_on() = max(ON_MIN, ON_FRAC*force)`; `effective_decay() = DECAY_ADOPT*p`; `receive_pressure(w)` — порог Шмитта ВКЛ (in_open + OPEN_TTL); `tick_input_state()` — затухание и ВЫКЛ (`OFF_FRAC/p * schmitt_on`).
  - `sense(opp, rng)` — формирование убеждений: энергия с шумом ±BELIEF_NOISE, force округлена до 10, оценка `opp_decay_guess` по истории w_adopt, `opp_defense_guess` — мода непустых действий за 5 тактов; опционально энтропийный шум (`info.perturb`).
  - `commit(act, work) -> w` — лимит `min(work, energy, MAX_WORK, max(MIN_OUTPUT, force//4))`, REST при нуле; `committed_work`, `defense_after`, `rest_if_starving()` (pool≤STARVING_E), `process_hit(tr)` (force−tr, энергия −HOCK_FRACTION*tr), `gain(tr)`, `upkeep()`.
- `class UtilityAI(Agent, profile_aware=False)` — ИИ ожидаемой полезности:
  - `gain_model(m, p)` — ценность успеха: в открытом окне `p*m*GAIN_MAX`, иначе `Y_SMALL*p*m + option-value` (опцион «давить дальше», зависит от прогресса к порогу, надёжности наблюдений и оценки decay противника).
  - `expected_gain(act, work)` — среднее по 3 гипотезам защиты минус штраф ответного удара (`retaliation_penalty` + `expected_retaliation`).
  - `form_intention() -> (act, work)` — перебор ACTIONS (доли 0.3/0.7 энергии), максимум полезности, иначе REST.
- `class RLAgent(Agent)` — табличный Q-learning:
  - ε-greedy: `epsilon()` (1.0→0.05 за 3000 шагов); `discretize(e)` — нелинейная сетка (линейно до 8, /4 до 32, лог выше); `skey()` — состояние из (своя энергия, энергия врага, последнее действие врага, угроза MULT, adopt, открыт ли, ctx_base); `form_intention(eps, rng) -> idx`; `learn(st, a_idx, reward, nst, alpha=0.3, gamma=0.9)` — стандартный TD-обнов.
- `class Environment(Agent, start_force=10, members=None, lossy=False)` — надсистема (толпа/среда):
  - `receive_pressure` дополнительно растит `rest_units` (+0.01*w, cap ENV_REST_CAP); `ingest(work)` — прямой или через LossyChannel; `public_window()` — публичное (с лагом) состояние окна; `snapshot()`/`public_snapshot()` (bands давления/силы); `member_output()` — сумма работ участников; `tick()` — сбор выхода членов → давление себе, энергия, input-state, доход `ENV_INCOME` до потолка, upkeep, обновление `_public_window_prev`.
- `resolve_attack(att, dfn, work, rng, env=None)` — стоимость атаки (`COST_FRACTION*work`), перенос `_apply_transfer` (шанс `p_success`; gain = `work*MULT*GAIN_MAX|Y_SMALL`, бонус среды `1+ENV_BONUS` в её окне; урон защитнику + частичный возврат `K_EFFECT*work`), затем автоматический ответный удар `RETALIATE_FRACTION*work`.
- `dominates(att, dfn)` — энергетическое (×CAPTURE_RATIO) и силовое преимущество.
- `check_capture(rl, ai, dom_rl, dom_ai, ...) -> (winner|None, d1, d2)` — серия доминирования ≥ CAPTURE_STREAK ⇒ трофей `CAPTURE_FRAC*force` (×2 если жертва в окне), сброс lineage энтропии.
- `run_tick(a, b, intent_a, intent_b, rng, env=None) -> (work_a, work_b)` — порядок такта: sense → rotate_defense → upkeep/tick_energy/tick_input_state(+env.tick) → замыслы → commit → resolve_attack в обе стороны.
- `play_game(rl, ai, steps=1000, seed=0, profiles=None, with_env=True, env_members=None, entropy=False, lossy=False) -> (winner, rl_hist, ai_hist, end_step)` — полный матч RL vs UtilityAI, награда = дельта силы.
- `run_batch(n_games=10, ...) -> (rl, last, results)` — серия партий (RL сохраняется между играми — обучение), печать итогов.
- `main()` — демо + matplotlib график динамики силы.

### 1.6 `warfare.py` (1872 строки) — война, потребности, отряды

Зависимость: `import simulation as S` (отряд = Environment, персонаж = UtilityAI).

**Данные:**
- `NEEDS` — 16 потребностей (hunger…friendship), `NEEDS_RU` — русские метки.
- `_NEED_RATES` — скорости роста (0.001–0.0052/такт при 1800 с).
- `HEALTH_DEATH_THRESHOLD=1.0`, `HEALTH_NEED_WEIGHTS` — вклад дефицита других нужд в деградацию здоровья; множитель клампится [0.35, 3.0].
- `TRAITS` (12 черт) + `TRAITS_RU`; `_ARCHETYPES` — модификаторы черт (veteran, conscript, commissar, chaplain, medic, scout, machinegunner).

**Сигнатуры и логика:**
- `@dataclass Personality(values, archetype, seed)`; `from_seed(seed, archetype)` — база черт + шум ±0.12 + модификатор архетипа, кламп [0,1]; `__getitem__/get/as_dict`.
- `@dataclass Intention(kind, need, urgency, reason)`; `@dataclass OrderSignal(aggression, discipline, morale, fear, fanaticism, retreat_allowed, needs, label)`.
- `class Order(name, signal=None, duration=5, targets=(), side=None, defer=False)` — приказ-модулятор: `activate/touch(target)` (вызывает `target.receive_order`), `tick()` (TTL), `modulation()` (сигнал или пустой), `snapshot()`.
- `class Character(S.UtilityAI)` — солдат с психикой:
  - `__init__(name, side, seed, archetype, profile, role)` — needs (нач. значения), morale (зависит от courage), mind, panic/fanatic таймеры+кулдауны, orders.
  - `is_dead` — health ≥ 1.0; `health_degradation_multiplier()` — произведение `(1+w*(2v−1))` по весам.
  - `weighted_urgency()` — urgency = need × личностный вес (страх↓у смелых, статус↑у амбициозных и т.д.).
  - `deliberate() -> Intention` — правила: паника→retreat, фанатизм→banzai, физиология>0.42→rest, страх>0.40→hold, status/spirituality/aggression→assault, иначе fire; хранит последние 3 намерения.
  - `receive_order(order)`, `modulation()` — аддитивная свёртка активных приказов + вычистка неактивных.
  - `tick_needs(in_combat, under_fire, supported, rested, rng, seconds=1800, rate_multipliers, morale_baseline_bonus)` — главный психотик: rates × личность; боевые добавки к fatigue/fear/anxiety/health (масштаб by under_fire); health умножается на деградационный множитель; поддержка снижает социальные нужды; отдых снимает физиологию; бой качает skill/status; смерть-проверка; стресс-взвешенная мораль (дрейф к baseline дисциплины, штрафы за stress/под огнём, бонусы приказов/поддержки); далее `_update_mind` + `deliberate`.
  - `_update_mind(rng)` — scores panic/fanatic (линейные комбинации нужд, черт, приказа + шум); триггеры >0.42/>0.48 с timer=3 и cooldown 20/16; состояния mind: panicked/fanatical/shaken/steady.
  - `satisfy(effects, morale_bonus)` — снижение нужд + мораль; `needs_summary`, `snapshot`.
- `class Detachment(S.Environment)` — отряд (среда из персонажей):
  - `__init__(name, side, characters, position, profile, role, doctrine)` — start_force=min(34, 6+2N); психология (morale/cohesion/aggression/discipline/fanaticism), retreating/panicked/fanatical/broken, losses, combat_loss_scale.
  - `refresh_psychology()` — усреднение по живым персонажам + сигналы приказов + доктрина (assault/defensive); panic любого → panic отряда (если отход разрешён).
  - `receive_order` — спускается всем персонажам; `process_hit(tr)` — потери масштабируются `combat_loss_scale`; `modulation/retreat_allowed`.
  - `after_combat(under_fire, rng)` — `tick_needs` каждому (support = cohesion×morale-фактор), `_update_retreat`.
  - `_update_retreat(rng)` — отход при panic_frac≥0.30 | паника лидера при низкой дисциплине | morale<20; фанатизм блокирует отход.
  - `prepare_turn()`, `choose_intent(target, rng) -> (act, work)` — ретрит→REST, фанатик→banzai (70% энергии, тип `_fanatic_type`), низкая мораль→hold, иначе максимизация `_attack_score` (ожидание как UtilityAI + опционная ценность − стоимость/шок) с поправками aggression/morale; сравнение с `_rest_score`.
  - `move_away(opponents, bounds=(0,24,0,24))` — манхэттенский шаг от ближайшего врага; `snapshot`.
- `class BarrierDetachment(Detachment)` — заградотряд: `retreat_allowed=False`; `enforce(allies, rng, turn)` — снимает retreating/panic у союзников с morale<38, навязывает Order(«заградотряд», duration 3), при уже начавшем отходе — штраф (force−1, morale−2, punished++).
- `class Stan(S.Environment)` — станция возрождения: `tick/clock`, `can_spawn()` (reserve или factory, лимит max_spawns), `drain_spawns()` — каждые spawn_interval выпускает отряд на rally-точку.
- `class Reinforcement(S.Environment)` — подкрепление: `ready` после delay, `drain_arrivals()` — разовый ввод отрядов.
- `class WarfareSimulation(seed=0, turns=120)` — оркестратор:
  - реестры detachments/stans/reinforcements/organizations/orders/scheduled_orders/events; `engage_range`, `focus_targets`.
  - `add_*`, `issue_order(order)`, `schedule_order(turn, order)`, `log_event(kind,text,...)`.
  - `tick()` — последовательность: `_tick_orders` (TTL + запуск назначенных) → `_tick_sources` (станы/подкрепления) → `prepare_turn` → `_enforce_barriers` → `_retreat_moves` (4 такта и morale>30 ⇒ выход из отхода) → `_fight` → `_after_fight` (broken при force≤1 или morale≤1) → `_tick_organizations` (duck-typed `organization.tick(rng,turn)→{"events":[...]}`) → `_check_victory` (истребление или по сумме force на max_turns).
  - `_pair_engagements()` — жадное парное сопоставление атакующих с ближайшими живыми врагами (учитывая engage_range, focus_targets, роль barrier не выбирается целью при наличии линейных).
  - `_fight()` — на пару: `S.run_tick` с политиками `choose_intent`, under_fire = относительная потеря силы, `after_combat`, логиEngagement/panic/banzai (`_report_mind`).
  - `run(turns=None)`, `counts()`, `summary()` (снапшоты сторон/организаций/событий).
- `_character_roster(side, prefix, archetypes, seed)`; `build_demo_scenario(seed=7, turns=140)` — демо: составы red/blue, барьер, приказы (расписание), станы, подкрепления; `main(seed=7, turns=140, verbose=True)` — прогон и печать summary.

### 1.7 `game_engine.py` (2436 строк) — pygame-приложение «Арена»

**Структура:** логирование, bootstrap pygame, вёрстка, движок матча, шрифты, приложение.

**Сигнатуры и логика:**
- `class _Logger` (singleton `LOG`) — уровни error/warn/info/debug/exc, throttling по key, `set_sim_time(t)`, потоковый вывод.
- `_dump_stack(where)`, `_probe_font()`, `_try_fix_freetype()` — диагностика и починка шрифтов Freetype в SDL.
- `compute_window_size()`, `init_pygame_minimal()`, `quit_pygame()` — безопасная инициализация display/font отдельно.
- Константы UI: PANEL_W, FPS, цвета (COL_*), `DEFENSE_COLORS/ACTION_LABELS/DEFENSE_LABELS`, `action_label/defense_label`, `agent_radius(force)`, `env_bg_color(env_force)`.
- `class Layout(w, h, n_actions)` — чистая геометрия: пересчёт зон (панель, агенты, история, кнопки, action-bar) под любой размер окна.
- `parse_health_factors(text) -> dict` — разбор «aging=1.2, stress=0.8».
- `_ai_policy(checkpoint, seed)` — фабрика политики UtilityAI (или из чекпойнта).
- `class MatchEngine(seed, steps, with_env, q_table, profile_rl, profile_ai, checkpoint, health_factors, sickness)` — обёртка над `core41.ArenaMatch` (rl_policy=QTablePolicy, ai_policy=_ai_policy); read-only properties (step/winner/finished/events/hist/dom/rest_ticks/last_action); `step_tick(forced_rl_action=None)` — один такт + запись событий; `sanitize_text`, `BitmapText`, `_SafePyFont`, `FontSet` — fallback-рендер текста (битмап при битом TTF).
- `class GameApp(...)` — игровой цикл:
  - speed/paused/ticks_per_sec через SimulationClock; `_maybe_auto_pause`; `_press(name)` — экшены; `handle_events(events=None)` — клавиша/мышь (выбор действия по тайлам `_action_at_mouse`);
  - `new_match(seed)`, `start_match(seed, resume_tick)`, `progress()`, `restore_conditions(rl, ai)`;
  - `on_resize(w,h)`, `update(dt)`, `draw(surface)` — слои: `_draw_zone_separators`, `draw_panel` (карточки состояний/убеждений), `draw_agents` (круги силы, окно Шмитта), `draw_transfers` (переливы силы), `draw_env_info`, `draw_history` (графики force), `draw_caption`, `draw_action_bar`, `draw_buttons`, `draw_status`, `draw_help`;
  - `run()` — main loop 60 FPS; `main()` — CLI-парсинг и запуск.

**Логика:** визуальный бой RL-vs-AI поверх core41: пользователь может ставить на паузу, вручную навязывать действие RL (`forced_rl_action`), смотреть панель убеждений и графики.
