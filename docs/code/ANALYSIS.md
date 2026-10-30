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

**Статус покрытия анализа (перепроверено скриптом по git ls-files, 2026-10-31):**
Всего Python-файлов в репозитории: **220**. Из них 177 уже разобраны в справочнике `docs/code/*.md` (заголовки `## \`файл\``). Оставшиеся **43 файла** закрыты новыми разделами этого документа:
- §2 — весь `core41/` (8 файлов); §3 — весь `agents/` (5 файлов);
- §4 — недостающие модули `campaign/`: world.py, env.py, actor.py, planner.py, clock.py, character.py (6 файлов);
- §5.1–5.4 — `view/screens/world_screen.py`, `view/screens/automaton_select.py`, `view/support/world_text.py`, `view/ui/world_art.py` (4 файла);
- §5.5 — `experiments/exp_campaign_calibration.py`, `exp_health_calibration.py` (2 файла);
- §5.6 — 18 тестовых файлов new-среза (краткий обзор назначения каждого).

Итог: **покрытие — 220/220 Python-модулей (100%)**. Не является кодом и не анализируется как модули: `configs/**.json`, `scenarios/**`, `assets/**`, `music/**`, `patches/**` (данные/конфиги/патчи). Глубина разбора неравномерна: ядро (`simulation/warfare/core41/campaign`) расписано детально, тесты и калибровочные эксперименты — обзорно.

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

## 2. Пакет `core41/` — новая онтология 4-2-1 (ядро)

### 2.1 `core41/types.py` (133 строки) — контракты данных

Все типы — `@dataclass(frozen=True)` (иммутабельны, безопасны для RL-переходов):
- `Work(amount, form="force", payload=(), duration=1.0)` — единица работы (канал `form`).
- `Action(kind="REST", form="force", fraction=0.0, target="opponent")` — действие автомата.
- `Observation(self_force, self_energy, self_max_*, opponent_*, opponent_pressure, opponent_open, time, forms, opponent_defense, self_health/max/sickness/wound, opponent_health/sickness/wound, env_pressure, env_season)` — плоское наблюдение политики; все шкалы E/F/H + рана/болезнь + наблюдаемое расписание среды (P1.8).
- `Transition(observation, action, reward, next_observation, done, next_actions, info)` — стандартный кортеж RL.
- `CampaignAction(kind="END_DAY", target, form, fraction)` — действие кампанейного среза (дневной такт WorldEngine поверх того же контракта).
- `CampaignObservation(day, actions_left, health/sickness/wound, influence/favor/evidence/standing/authority, power/wealth/legitimacy/cohesion/reach/capacity, finished/outcome/collapsed/dismissed, energy/force…)` — нормированные [0,1] признаки кампании; сентинел `-1` = «поле не заполнено» (обратная совместимость старых конструкторов).

### 2.2 `core41/model.py` (341 строка) — автомат и здоровье

Константы: давление (`OPEN_PRESSURE=8.0`, `PRESSURE_DECAY=0.82`, `PRESSURE_PER_WORK=0.30`), отдых (`REST_REGEN=14.0`, `REST_FORCE=0.6`), три блока H-механики: `HEALTH_*` (max 100, крит 25, `HEALTH_DAMAGE_RATIO=0.62` — урон по силе капает и в здоровье), `SICKNESS_*` (0..1, прогресс 0.004/такт, штраф работы ×0.6→пол 0.4, заражение `CONTAGION_CHANCE=0.35`), `WOUND_*` (устойчивая рана: капает здоровьем, замедляет реген, лечится отдыхом/TREAT).

- `sigmoid(value)`, `success_probability(attacker, defender, work, is_open) -> float` — вероятность попадания: скилл атакующего против сопротивления защитника, открытость увеличивает шанс.
- `transmit_sickness(source, target, rng, form="force")` — контактная передача болезни при успешной работе (шанс × тяжесть).
- `class Automaton` (dataclass): поля `id, force, energy, max_*, inputs/outputs, skills{form->x}, authority, state{pressure}, handlers, relations, health, health_factors, sickness, wound`.
  - Свойства: `F`, `E`, `is_dead` (H≤0), `is_sick`, `is_wounded`, `work_effectiveness` (множитель от ран/болезни), `health_ratio`, `pressure`, `is_open`.
  - Множители здоровья: `health_factor(name)/set_health_factor` (aging/stress/feed…), `health_decay_multiplier`, `health_regen_multiplier`, `health_damage_multiplier`, `sickness_damage_multiplier`, `health_sickness_multiplier`.
  - Мутации: `infect(severity)`, `treat(amount)`, `injure(severity)`, `treat_wound(amount)`, `apply_force_damage(damage)` (перелив F→H по HEALTH_DAMAGE_RATIO).
  - `tick_health(resting=False)` — главный такт здоровья: голод/истощение, реген при отдыхе, прогресс/откат болезни и раны, смерть.
  - `can_receive(form)`, `skill(form)`, `resistance(form)`, `decay_pressure()`, `receive(work, source=None, world=None)` → диспетч в `handlers[form]` либо `default_receive` (давление + open-окно).

### 2.3 `core41/duel.py` (292 строки) — минимальный дуэльный мир

- `class DuelWorld(seed=0, max_steps=200)` — две стороны («agent»/«opponent») из `Automaton` (`_make(name, skill, authority)`); обработчик `_force_handler(target, work, source, world)` — урон по F, ответное давление, передача болезни.
- `reset(seed=None)`, `_perform(attacker, defender, action)` (ATTACK/CHARGE/REST/FORCE…, fraction→Work), `step(actions: dict[agent_id->Action])` — одновременный шаг + tick_health + decay_pressure + проверка терминала; `observe(agent_id) -> Observation`; `legal_actions(agent_id)`.
- **Логика:** канонический «эталон дуэли» для Gym-обёртки `DuelEnv` и тестов канона — без UI и без среды.

### 2.4 `core41/clock.py` (154 строки) — реальное время

- Константы: `BASE_TICK_SECONDS=1.0`, `SPEEDS=(0,1,2,4,8,16)`, `MAX_CATCHUP_TICKS=64`.
- `normalize_speed(value)`, `speed_label(value)`.
- `class SimulationClock(...)` — свойства `speed/paused/ticks_per_sec/seconds_per_tick/label/selected_speed/selected_label`; методы `set_speed(value, reason)`, `pause(reason)`, `resume()`, `set_paused(v)`, `toggle_pause()`, `faster()/slower()` (шаг по SPEEDS), `advance(dt) -> int` (сколько тиков отдать за dt с ограничением догона), `reset_counters()`. Используется `game_engine` и `view`.

### 2.5 `core41/environment.py` (327 строк) — актор среды арены

Константы расписания: `ENV_EVENT_INTERVAL=17`, `ENV_RELIEF_INTERVAL=31`, `ENV_ILLNESS_INTERVAL=500`, `ENV_WOUND_INTERVAL=700`, величины дренажа/рельефа, `SEASONS=(calm .6, lean 1.0, harsh 1.3, recovery .8)`, `ENV_SEASON_LENGTH=240`, `ENV_SECONDARY_SHARE=0.5` (вторая сторона получает половину асимметричного эффекта).
- `class ArenaEnvironment(seed=...)`: `season`, `public_state()` → `(env_pressure, env_season)` для наблюдения политик, `_targets(kind)` (выбор цели истощения/раны), `tick(left, right)` — по расписанию давит E/H, лечит, заражает болезнью, наносит рану; `state_dict()/load_state_dict()`. Хелперы `_agent/_sickness/_energy/_wound/_health/_set_*` работают и с фасадом `Commander` (через `.agent`).
- **Логика:** среда — третий неявный агент-фон, не воюет; включает флаг `with_env` в матчах и обучении (доменное разнообразие).

### 2.6 `core41/env.py` (313 строки) — Gym-окружения

- `randomize_draw(env, rng, opts)` / `env.apply_domain(**kwargs)` — случайная жеребьёвка параметров домена (профили, health_factors, sickness/wound, with_env) для domain-randomization.
- `class DuelEnv(seed=0, max_steps=200)` — тонкая обёртка `DuelWorld`: `action_space`, `observe(side="rl")`, `legal_actions`, `reset(seed)`, `step(action, opponent_action=None) -> (obs, reward, done, info)`.
- `class ArenaEnv(...)` — обёртка над `ArenaMatch` для обучения: `__init__(seed, steps, profile_rl/ai, health_factors, sickness, wound, with_env, auto_learn…)`; `apply_domain`, `reset`, `step(action, opponent_action)` — один тик матча, reward со стороны rl; `_opponent_action()` — политика-оппонент (по умолчанию REST/heuristic).
- **Логика:** единый RL-контракт (reset/step/observe) поверх обоих миров; используются `agents/train.py`.

### 2.7 `core41/arena.py` (985 строк) — активная арена (полный матч)

Константы: `FORMS=("force","info")`, `FRACTIONS=(0.3,0.7)`, `CORE_ACTIONS` (REST/MOVE/ATTACK/DEFEND… индекс↔Action), захват `CAPTURE_RATIO=1.5, CAPTURE_STREAK=20, CAPTURE_FRAC=0.10`, `L_STEP=10.0`, профили `PROFILE_SKILLS` (CANON/AGGR/DEFN/SNEAK…), награды `REWARD_*` (цена энергии 0.6, своя болезнь −1.0, чужая +0.5, раны, терминал ±1.0).
- `reward_delta(me, before, other, other_before) -> float` — пошаговая награда из изменений E/F/H/sickness/wound обеих сторон; `terminal_reward(winner, side)`; `action_from_index(i) -> Action`; `_default_action(obs)`.
- `class _RestPolicy` — заглушка политики (всегда REST; интерфейс `act/observe/state_dict/load_state_dict`).
- `_perform(attacker, defender, action, world)` — исполнение действия: атака (вероятность успеха → урон F+H, info-канал → давление/дезинформация, open-окно), DEFEND (смена защиты), REST (реген E/F/H через `tick_health`), результат с событиями; `_transfer_event(side, agent, result)` — описание перелива для UI.
- `class ArenaAgent(id, policy=None, profile="CANON", seed, health_factors, sickness, wound)` — автомат + окно Шмитта (`defense`, `in_open`, `w_adopt`, `open_timer`, `schmitt_on`, `Q`) + свойства E/F/H/sickness/wound + `set_profile`, `reset_state`, `condition_state()/load_condition()` (состояние для реплея), `actions()`, `needs_recovery()`, `observe(opponent) -> Observation` (частичная видимость: `opponent_open`, давление), `choose_action(opponent, explore)` (делегат в policy или эвристику), `record_action`, `learn(reward, next_obs, done, opponent)` (обратная связь в policy), обработчики `_force_handler/_info_handler/_receive_work` (получение работы: урон, заражение через `transmit_sickness`, давление).
- `class ArenaMatch(seed, steps=2000, rl_policy, ai_policy, profile_rl/ai, health_factors_*, sickness_*, wound_*, with_env=False, auto_learn=True)` — два `ArenaAgent` + опциональный `ArenaEnvironment`; состояние `time/step/winner/finished/events/last_rewards/rl_hist/ai_hist/dom_rl/dom_ai/rest_ticks/last_*_action`.
  - `step_tick(forced_rl_action=None, forced_ai_action=None)` — полный такт: наблюдения → действия политик (или форсированные) → `_perform` обоих → среда.tick → `tick_health` → награды `_reward`/`terminal_reward` → `learn` (auto_learn) → `_check_terminal` (смерть/таймаут) → `_check_capture` (доминирование 1.5× подряд 20 тиков → захват 10% силы).
  - `run_duel_tick(left, right, rng)` / `class _DuelTick` / `_resolve_capture` / `check_capture(...)` — функциональный срез такта для внешних циклов (game_engine, lod).
- **Логика:** основной боевой цикл единичной дуэли E/F/H с окном Шмитта, болезнями/ранадами, средой и захватом; источник событий для UI и наград для RL.

## 3. Пакет `agents/` — политики и обучение

### 3.1 `agents/policies.py` (945 строк) — четыре политики + сериализация

Контракт политики: `act(observation, actions, explore=True) -> action`, `observe(transition)`, `state_dict()/load_state_dict(state)`; версия чекпойнта `CHECKPOINT_VERSION`, `checkpoint_version(state)`.
- Признаки: `features(observation, action) -> tuple[float]` (нормированные ~FEATURE_COUNT признаков: доли E/F/H, разница сил, давление, открытость, env_pressure/season, код действия `action_feature_code`); `campaign_features/campaign_weights_from/_campaign_vector` — отдельный вектор для кампаний; `default_actions(observation)`, `dot(l, r)`, `_migrate_qtable_key(key)` — миграция ключей старых чекпойнтов.
- `class RandomPolicy(seed=0)` — равномерный выбор (бейзлайн).
- `class BDIPolicy(desires..., weights, lr, ...)` — belief–desire–intention: `_beliefs_from(observation)` (оценки угрозы/истощения), `score(observation, action)` — линейная свёртка весов по признакам, `_active_weights(observation)` (переключение профилей), `act` — argmax(+шум), `observe(transition)` — онлайн-подстройка весов по TD-ошибке; `save/load(path)`, state_dict с версией.
- `class QTablePolicy(alpha, gamma, epsilon, seed, default_q...)` — табличная Q: `key(observation, action)` — дискретизация признаков в бакеты (строка-ключ), `value`, `act` (ε-greedy), `observe` — Q-learning update по Transition; state_dict переносит всю таблицу.
- `class MLPPolicy(hidden=..., lr, gamma, target_sync, seed...)` — 2-слойный MLP Q-function (чистый python): `_forward(vector)`, `_target_forward`, `_sync_target` (target-сеть), `score/target_score`, `act` (ε-greedy по сетке действий), `observe(transition)` — backprop по MSE(DQN-подобно); `save/load(path)`.
- `make_policy(name, seed=0)` — фабрика ("random"/"bdi"/"q"/"mlp"); `load_policy(path, seed=0, kind=None)` — автоопределение типа по state_dict и загрузка.

### 3.2 `agents/checkpoints.py` (194 строки) — реестр чекпойнтов

- `project_root()`, `default_checkpoint_dir(root)`, `CHECKPOINT_DIR_ENV` (переменная окружения для пути).
- `read_checkpoint(path) -> dict` (json), `checkpoint_kind(path) -> "bdi"/"mlp"/"q"`, `is_loadable(path, kind=None)` — проверка версии и пригодности.
- `_candidates(directory, preferred)`, `list_checkpoints(directory=None, kind=None, ...) -> list[Path]`, `find_checkpoint(...)`, `resolve_checkpoint(path_or_name)` — разбор имени/пути/автовыбор последнего валидного.

### 3.3 `agents/legacy.py` (107 строк) — мост к старому симулятору

- `class PolicyAgent(S.Agent)` — subclass агента `simulation.py`: принимает `policy` из `agents.policies`, `observation()` собирает старый снапшот в новый контракт `Observation`, `actions()` — список CORE_ACTIONS, `sense/observe_reward(reward, done)` → `policy.observe(Transition)`, `form_intention(*args)` — совместимость со старой сигнатурой, `policy_state()` — экспорт весов. Позволяет учить политики на легаси-каноне.

### 3.4 `agents/train.py` (1097 строк) — CLI обучения и оценки

- Конфиг доменов/параметры эпизодов; `_make_env(...)` — сборка DuelEnv/ArenaEnv/CampaignEnv по флагу; `_domain_draw/_apply_domain` — domain randomization; `_reward_for(env, side)`.
- `_play_episode(env, policy, opp_policy, seed, learn, explore, max_steps)` — прогон эпизода с обновлением политики; `_play_campaign_episode` — то же для дневной кампании (CampaignAction).
- `_count_winner(info, wins, losses, draws)`; `_warmup_baseline(...)` — прогрев (случайные эпизоды до обучения).
- `wilson_interval(successes, trials, z=1.96) -> (lo, hi)` — CI для отчётов.
- `evaluate(policy, env spec, episodes, seeds, ...) -> dict` — оценка win-rate с Wilson CI; `evaluate_matrix(...)` — сетка «политика × профиль оппонента × домен».
- `train(kind, episodes, seed, env options, eval_every, out, ...) -> dict` — главный цикл: warmup → эпизоды → периодическая оценка → сохранение лучшего чекпойнта; `_train_seed_worker(payload)` + `train_seeds(...)` — мульти-сид параллельно (через multiprocessing).
- `main(argv=None)` — argparse-CLI (`python -m agents.train --kind mlp --episodes 500 ...`), печать итогов.

### 3.5 Итог по пакетам

`core41` = канон целевой модели (онтология 4-2-1: Е/Ф/H, окно Шмитта, болезни/раны, среда, Gym-срезы); `agents` = слой обучения поверх неё (признаки → политики Q/MLP/BDI → train/evaluate → чекпойнты, подхватываемые `game_engine` и `view`). Оба пакета ранее были только упомянуты в карте репозитория — теперь разобраны полностью.

## 4. Пакет `campaign/` — дневная кампания (дополнение к campaign.md)

### 4.1 `campaign/actor.py` (257 строк) — персонаж на ядре 4-2-1

Проекция шкал кампании на E/F/H арены: `E` — энергия дня (бюджет действий), `F` — `standing` позиции, `H/sickness/wound` — общие с ареной. `actions_left` — совместимая проекция `floor(E / energy_per_action)`, не второй счётчик.
- Константы: `CAMPAIGN_ENERGY_MAX=100.0`, `CAMPAIGN_WOUND_MAX=WOUND_MAX`.
- `campaign_success_chance(...)` — вероятность успеха действия через `core41.model.success_probability` (скилл vs сложность + модификаторы состояния).
- `class CampaignActor(...)`: свойства `energy/max_energy/energy_per_action/actions_left(get/set)/force/max_force/health/max_health/sickness/wound/is_wounded/alive/standing/work_effectiveness`; методы `spend_action()` (списание E), `restore_day()` (восстановление до максимума), `injure(severity)`, `treat_wound(amount)`, `state_dict()/load_state_dict()`. Внутри делегирует `Automaton` из core41.

### 4.2 `campaign/character.py` (93 строки) — NPC-персонаж мира

- `class CampaignCharacter(dict)` — плоский dict-персонаж с нормализацией полей (`_clamp/_ratio`); `sync()` — приведение сырых полей конфига к каноническим диапазонам; `tick()` — медленный возврат отношений/настроения к нейтральному фону (скорость мала, чтобы заработанные игроком связи не исчезали за несколько дней).

### 4.3 `campaign/clock.py` (150 строк) — дневные часы

- `normalize_seconds_per_day(value)`, `normalize_max_catchup(value)`.
- `class CampaignClock(seconds_per_day=120, ...)` — аналог SimulationClock в масштабе дня: `label`, `pause()/resume()`, `advance(dt) -> int` (сколько дней «протекло» фоново, с ограничением догона), `reset_counters()/reset_accumulator()`.
- `offline_days(saved_at, now=None, clock=None) -> int` — сколько дней прошло оффлайном между сейвами (для догона мира при загрузке).
- `background_pause_reason(engine)` — почему фон стоит (сюжет/меню/терминал).

### 4.4 `campaign/planner.py` (189 строк) — намерения и автономия

- `MAX_INTENTS=64`, `AUTONOMY_PERIOD=3`.
- `@dataclass(frozen=True) class Intent(kind, day, node_id?, payload...)` — отложенное намерение (`message` — запись в журнал, `contact` — взаимодействие); `to_dict()/from_dict()`.
- `class IntentQueue(items, limit)` — очередь намерений: `_trim()` (кольцевое ограничение), `__len__/__iter__`, `add(intent)`, `schedule(...)` (создание+добавка), `has(**criteria)`, `due(day)`, `pop_due(day)` (изъятие созревших), `clear()`, `to_list()/load(items)/copy()`. Используется `WorldEngine._run_intents/_schedule_autonomy` — узлы-НПС действуют не каждый день, а раз в AUTONOMY_PERIOD.

### 4.5 `campaign/env.py` (733 строки) — Gym-среда кампании

- `campaign_reward(before, after, outcome_delta=0.0, success=False) -> float` — пошаговая награда из приращений ресурсов позиции/организации; `terminal_campaign_reward(outcome)` — финальная (по исходу сюжета).
- `class CampaignEnv(config=None, profile=None, node_id=None, office_id=None, seed=0, max_days=None, snapshot=None, sickness=0.0, target_mode="all", career_actions=False, engine=None)` — одиночная (single_agent) Gym-среда над WorldEngine: контракт `reset(seed) -> CampaignObservation`, `step(CampaignAction) -> (obs, reward, done, truncated, info)`; `action_space` — пары `(kind, target)`; `legal_actions()` — легальные пары + `END_DAY`.
  - `attach(engine)` — оборачивает живой движок экрана (P0.4: политика меняет тот же мир, что рисует UI и уходит в сейв);
  - `randomize_draw(...)/apply_domain(profile, sickness)` — domain randomization кампании (проблема №7);
  - `_default_start()` (кэш `_resolved_start`) — первый головной узел + головная должность; `_build_engine(seed)`; `_node_stats/_metrics` — агрегаты для наблюдения; `observe()` → CampaignObservation; `_target_ids/_target_id` — проекция целей в действие;
  - служебные self-действия `_treat_self()` (болезнь), `_treat_wound()` (рана); `step(action)` — валидация → execute/end_day → reward/done (смерть, увольнение без замены = терминал, horizon = truncated);
  - `state_dict()/load_state_dict()` — переносимое состояние среды (сейвы/чекпойнты обучения).

### 4.6 `campaign/world.py` (3592 строки) — WorldEngine, ядро кампании

Константы ран/болезней кампании (`CAMPAIGN_WOUND_*`, `CAMPAIGN_ENV_WOUND_CHANCE=0.05`, `CAMPAIGN_ACTION_WOUND_CHANCE=0.15`…), `WOUND_RISKY_ACTIONS=("duel","sabotage","enforce_order","martial_law","embargo","strike")` — рана только при провале силовых ходов; дефолтные пути `configs/worlds/agora_world.json`, `biography.json`.
- Хелперы: `_is_wound_risky(action)`, `class WorldError(CampaignError)`, `_clamp/_as_float/_as_int/_text/_read_json`, `_validate_unique`.
- Конфигурация мира: `load_world(path=None)`, `load_biography(path=None)`, `validate_world(data)` — жёсткая валидация схемы (домены, узлы, должности, действия, связи).
- Профиль героя: `build_player_profile(variables, biography=None, seed=0)` — сборка профиля из ответов анкеты + биографии (+связи `_add_connections`, навыки `_add_skills`); `normalize_profile(profile)`; `office_profile_status(profile, office, skill_labels)` — пригодность к должности (соотношение требований и навыков); `_profile_connection_strength/_profile_skill`.
- `_PlayerResources(dict)` — фасад: записи `energy/force/health/sickness/wound` прозрачно пишутся в `CampaignActor` (обратная совместимость старого кода/сейвов).
- `class WorldEngine(config, profile=None, node_id=None, office_id=None, seed=None, snapshot=None)`:
  - Параметры мира: `days` (сюжетный горизонт), `infinite=True` (день N больше не победа автоматически), `collapse_grace_days`, `offline_progress/seconds_per_day=120/max_offline_days=7`, `actions_per_day=3`;
  - Свойства-делегаты актёра: `actions_left, player_energy/max_energy/force/health/sickness/wound/alive` (get+set);
  - Построение: `_build_nodes()` (иерархия узлов-организаций из конфига), `_build_character(raw)`, `_opening()` (текст старта);
  - Дерево/метки: `domain_label/kind_label/level_label/node_level_label`, `node/node_label/node_path/node_depth/is_descendant/relation`;
  - Должности: `office_templates_for_node/head_office_for_node/_office_authority/office_options`, `attach(node_id, office_id)` — вступление в организацию на должность (главный стартовый ход);
  - Контексты: `_context(node, office, is_player)`, `player_context()`; заражение/условия: `_set_contagion_sickness/_spread_contagion/_advance_conditions/_apply_environment_wounds` (суточные болезни, средовые раны);
  - Организации: `organization_category/organization_groups/organization_status` (агрегат для UI), `_refresh_items/player_items/skill_tree`;
  - Персонажные (неигроковые) действия: `_character_reason_cost/_reason_character/character_action_options/character_preview/_apply_character_effects/execute_character_action`;
  - Действия игрока: `_reason_actor/_reason_target/_reason_requirements/_reason_cost` — цепочка причин отказа; `validate(action_id, target_id, context)`, `action_options(target_id, include_disabled)`, `available_actions`, `preview(action_id, target_id)` (расчёт шансов/эффектов до исполнения); `_cost_text/stat_label/_effect_lines`;
  - Исполнение: `execute(action_id, target_id=None)` — бросок `_roll(token)` (детерминированный хэш-зерно), успех/провал, `_apply_effects`, `_apply_stat_map/_apply_player_map`, рост навыков `_skill_domains/_grow_player_skills`, рана при провале `_apply_action_wound`, доход `_apply_daily_income`, карьерный переход `_career_target_available/_career_transition`;
  - Сюжет: `end_storyline(kind, text)/_apply_ending/_check_storyline/world_outcome()` — финалы (смерть, увольнение, цели сюжета);
  - ИИ узлов: `_ai_targets/_ai_base/_ai_score/_ai_action(node_id)` — выбор действий NPC-руководителями по эвристике приоритетов;
  - Увольнения: `_replacement_office/_dismiss(reason, kind, auto_reassign)/_check_dismissal` — потеря должности при крахе организации (grace-дни);
  - Планировщик: `schedule_intent(...)`, `_run_intents()`, `_apply_intent(intent)`, `_schedule_autonomy()` — отложенные намерения и автономные ходы узлов раз в 3 дня;
  - День: `end_day()` — такт мира: ИИ-узлы, созревшие интенты, условия/болезни/раны, часы персонажа, сброс энергии, проверка сюжетного конца; `advance_days(days, max_days)` — догон (оффлайн);
  - Сериализация: `to_dict()/load_snapshot(snapshot)` — полный снимок мира в сейв (детерминизм через seed+snapshot); `sorted_nodes()`.
- **Логика:** политическая песочница «день = 3 действия»: игрок занимает должность в иерархии организаций, тратит энергию на действия против узлов/персонажей (шансы считаются ядром 4-2-1), мир живёт сам (ИИ узлов, интенты, болезни/раны, увольнения), сюжет завершается целями/смертью/крахом. Поверх — `CampaignEnv` для RL и экран `world_screen` для UI.

## 5. Дополнения к `view/` и `experiments/` (непокрытые файлы)

### 5.1 `view/screens/world_screen.py` (2175 строк) — экран кампании

`class WorldScreen(BaseScreen)` — главный геймплейный экран дневной кампании поверх `WorldEngine`:
- `_initial_target_id/_sync_storyline/_active_group_id/_active_organizations/_active_characters` — состояние вкладок (орг-группы/персонажи/навыки/предметы); списки с прокруткой `_entity_rows/_action_options/_visible_*_rows/_max_*_scroll`; `_option_chance(option)` — отображение шанса;
- выбор цели/хода: `_select_target/_select_character/_select_skill/_select_item/_select_action`, исполнение `_execute_selected()` (→ engine.execute, показ исхода), `_end_day()` (→ engine.end_day + лог дня), `_choose_office()` (стартовый attach), `_accept_outcome()`;
- автопилот RL: `_autopilot_env()` (CampaignEnv.attach(живой engine)), `_autopilot_policy_instance()` (загрузка чекпойнта), `_toggle_autopilot/_autopilot_step` — политика играет текущую кампанию шаг за шагом;
- цикл: `update(dt)` (CampaignClock.advance → фоновые дни), `handle_event(event)` (мышь/клавиши/скролл), геометрия кнопок `_finish_rect/_end_day_rect/_autopilot_rect/_office_rect/_execute_rect`;
- отрисовка: `_draw_panel/_clip_text/_draw_bar` и далее слои дерева организаций, карточек, action-bar (по образцу game_engine).

### 5.2 `view/screens/automaton_select.py` (549 строк) — выбор узла/должности

`class AutomatonSelectScreen(BaseScreen)(app, config_path=None, engine=None)` — пред-игра: список миров/автоматов (`_build_entries`), дерево узлов (`_draw_tree`, `_select_node`), варианты должностей (`_select_office`, `_office_rows_rects`), старт `_start()` → создание WorldEngine и переход на world_screen; навигация `handle_event`, скролл `_visible_rows/_max_scroll`.

### 5.3 `view/support/world_text.py` (257 строк) — текстовая котировка величин

Человеческие ярлыки чисел мира (без чисел в UI): `CHANCE_BANDS` → `chance_label(chance)` («весьма вероятно»), `failure_label`, `outcome_label`, `relation_label`, `scale_label`, `magnitude_word`, `resource_label`, `skill_rank/skill_next_rank` (ранги навыков); форматирование эффектов: `format_effect_map(effects, stat_labels, character_name)`, `summarize_changes(changes)`, `cost_summary(action, ...)`, `reason_text(reason)` (причина отказа действия), `signed_quality(value)`.

### 5.4 `view/ui/world_art.py` (156 строк) — ассеты мира

`class WorldArt(world_id)` — подбор графики из `assets/images/{characters,organizations,...}` с fallback-плейсхолдерами: `portrait(character_id, size)`, `organization_icon(node)`, `item_icon(item)`, `skill_icon(skill_id)`, `background(size)`; внутреннее: `_first_asset(names, size)`, `_tile_files/_load_tile/_build_tileset/_build_background` (процедурная фоновая плитка из tileset'а `agora_world`).

### 5.5 Калибровочные эксперименты

- `experiments/exp_health_calibration.py` (384) — калибровка H-механики арены: monkey-patch `_meter_tick/_meter_damage` (счётчик суммарного урона/регена через contextmanager `metering()`), `_make_match/run_match(overrides)` — прогон ArenaMatch с переопределением констант, `run_batch(...)` — сетка параметров, `_report(...)` — доли исходов (смерть/таймаут/захват), `parse_overrides(text)`, CLI `main(argv)` — подбор констант под целевые распределения боёв.
- `experiments/exp_campaign_calibration.py` (274) — калибровка кампании: `_run_policy(...)` — прогоны CampaignEnv базовыми политиками (эвристика/RL) на N дней, `_median`, `_goals(report)` — проверка целевых показателей (выживаемость, темп прогресса, баланс действий), `_print_report`, CLI `main(argv=None)`.

### 5.6 Тесты нового среза (кратко, 18 файлов)

`test_core41/test_clock/test_environment/test_health/test_sickness` — контракты ядра (детерминизм дуэли, SimulationClock, актор среды, перелив F→H, болезнь/заражение); `test_checkpoints/test_train_cli` — реестр чекпойнтов и CLI обучения; `test_strategy/test_world/test_world_text/test_view_strategy/test_view_world` — стратегический слой, WorldEngine и текстовая котировка; кампанейные тесты: `tests/test_campaign_clock.py` (6 тестов: CampaignClock/offline-догон), `tests/test_campaign_energy.py` (8: трата E действием, restore_day, standing==force, снимок E/F), `tests/test_campaign_env.py` (35: полный RL-контракт CampaignEnv — reset/step/legal_actions/terminal/truncated/лечения), `tests/test_campaign_planner.py` (11: Intent/IntentQueue, автономия, лимит 64); `test_soak` — длительный soak-прогон на стабильность/утечки; `test_docs_core41` — сверка документации с кодом ядра.
