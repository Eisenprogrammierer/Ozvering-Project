# Эксперименты

Все скрипты запускаются **из корня репозитория** (они сами добавляют корень в
`sys.path`). Логи в репозитории не хранятся: вывод воспроизводится запуском
(при необходимости перенаправляйте его в файл сами).

Актуальные проверки текущей модели `simulation.py`:

Скрипты с кодом возврата (`0`/`1`) прогоняются в CI через `pytest`
(`tests/test_checks.py`); воспроизведение — `pytest -q` из корня репозитория.

```bash
python3 experiments/exp_balance_ci.py      # CI-тест баланса: доминирование/симметрия (код 0/1)
python3 experiments/exp_schmitt_suite.py   # пороги Шмитта, матрица дуэлей, дребезг
python3 experiments/exp_hypotheses.py      # конкурентные гипотезы H1-H3 о провалах RL
python3 experiments/exp_fix.py             # проверка лечения H-A (сетка ON_FRAC x DECAY_ADOPT)
python3 experiments/exp_environment.py     # среда как IPO-автомат (гипотеза B, §12-13 MODEL.md)
python3 experiments/exp_hierarchy.py       # суперсистемы: эмерджентность и самоподобие (§14)
python3 experiments/exp_hierarchy_depth.py # автотест ГЛУБИНЫ Environment (код 0/1)
python3 experiments/exp_rl_strength.py     # P0 №1: сила RL против UtilityAI (диагноз winner-take-all)
python3 experiments/exp_keffect_regime.py  # P0 №2: режим K_EFFECT (нож-лезвие, устойчивость баланса)
python3 experiments/exp_profile_constitution.py # P1: профиль как «скрытая конституция» (наблюдаемость)
python3 experiments/exp_hidden_marginal.py # A1: маргинал скрытой фазы hidden (априор наблюдателя)
python3 experiments/exp_retaliation_faithful.py # A3: оценка возмездия == состояние после commit (код 0/1)
python3 experiments/exp_env_double_loading.py   # A6: двойное нагружение входа среды (замер)
python3 experiments/exp_rl_sensitivity.py       # A5: чувствительность RL к гиперпараметрам (замер)
```

- `strategies.py` — ЕДИНЫЙ источник референсных скриптовых стратегий и протокола
  дуэли. Набор разделён по роли: конкурентное ядро `COMPETITIVE`
  (PRESSER/TIMING/EAGER) и контроли `CONTROLS` (PASSIVE/MIXED). Подключён в
  `exp_schmitt_suite.py` и `exp_balance_ci.py`, чтобы определения стратегий не
  расходились между скриптами (раньше это давало противоречивые выводы о балансе).
- `exp_balance_ci.py` — CI-тест критерия «конкурентные стратегии не доминируют,
  контроли не обыгрывают конкурентных, зеркальные роли симметричны»; красный код
  возврата — цель калибровки. Актуальные числа — в
  [`docs/BASELINE.md`](../docs/BASELINE.md).
- `exp_rl_strength.py` — диагноз прежнего winner-take-all канона RL-vs-UtilityAI и
  замер усиления (сброс физического состояния между партиями + annealing разведки
  по общему опыту). Показывает также не-доминантность UtilityAI (PRESSER его
  обыгрывает, PASSIVE/TIMING сводят вничью).
- `exp_keffect_regime.py` — переизмерение ножа-лезвия `K_EFFECT` (P0 №2): контроль
  без среды не стагнирует на `K>0`, канон устойчив при `K∈[0.4,0.9]`; остаётся
  чувствительность скриптового баланса к `K` на плато (окно `0.6–0.7`), прототип
  `W0` её надёжно не лечит — фикс не добавляется.
- `exp_profile_constitution.py` — протокол «профиль как скрытая конституция»
  (P1): измеряет наблюдаемость профиля (восстановление `p` из `opp_decay_guess`),
  решительность и вырожденность. Вердикт: при `p ≤ 1` профиль наблюдаем (не
  скрытая конституция), при `p > 1` — вырожден и слеп; ветвь `p > 1` удалена из
  `PROFILES` (допустимый диапазон `p ≤ 1`).
- `exp_hierarchy_depth.py` — автотест глубины `Environment` (утверждения, код 0/1):
  онтология не расширяется на глубине 0–3, единый закон типа, рекурсия такта и
  агрегации до глубины ≥2, рекурсивный `snapshot`.
- `exp_hidden_marginal.py` — замер фактического маргинала скрытой выходной фазы
  `hidden` (A1): показывает коллизию `REST→0 = FIRE→0` и зависимость маргинала от
  политики адресата. Обоснование трактовки равномерности как **априора наблюдателя**
  (см. `docs/MODEL.md` §2).
- `exp_retaliation_faithful.py` — автотест верности оценки возмездия (A3, код 0/1):
  `Agent.committed_work`/`Agent.defense_after` совпадают с фактическим результатом
  `commit` на 100% атакующих тактов канона (см. `docs/MODEL.md` §7).
- `exp_env_double_loading.py` — замер двойного нагружения входа среды-суперсистемы
  (A6): при `members=[rl,ai]` прямой удар и агрегат `member_output` учитывают один
  и тот же труд (агрегат ≈ 0.94 от суммы ударов), возмездие тоже нагружает вход
  среды (≈22% прямого давления). Замер: вход среды +76%, окно 68%→77% тактов, но
  исходы канона не меняются (см. `docs/MODEL.md` §14).
- `exp_rl_sensitivity.py` — замер чувствительности канона RL-vs-UtilityAI к
  гиперпараметрам Q-learning (A5): доля побед RL устойчиво в меньшинстве, заметно
  реагирует лишь на горизонт разведки `EPS_DECAY_STEPS` (3000 → 13%; 6000 → 27%);
  `EPS_MIN`/`alpha`/`gamma` почти не влияют. Конкурентоспособность RL — цель
  проекта, поэтому `1/9` — дефект (см. `docs/TODO.md` → P1).
- `history/treatments/` — замороженные изолированные копии модели для проверки
  гипотезы H-A (не актуальная модель; перенесены из `experiments/treatments/`).
- `history/` — скрипты ранних слоёв механики, не запускаемые против текущей модели
  (ссылаются на удалённые API); сохранены как артефакты обсуждения. Включает
  подкаталог `history/treatments/` (см. выше).

Скрипты ревью кода/документации (эксперименты над задачами `docs/TODO.md`;
работают через monkeypatch глобальных констант модели, файл не меняют):

```bash
python3 experiments/exp_review_p0_keffect.py              # P0: «нож-лезвие» K_EFFECT (дно/плато, канон/контроль)
python3 experiments/exp_review_p0_structfix.py            # P0: структурные кандидаты фикса (ограниченная/сглаженная отдача)
python3 experiments/exp_review_p0_criterion.py            # P0: полный критерий CI (N=20) для порога W0
python3 experiments/exp_review_p0_robust.py               # P0: устойчивость W0 на N=30
python3 experiments/exp_review_p1_rotation_retaliation.py # P1: рекурсия ротации, режим p>1, expected_retaliation
python3 experiments/exp_review_p1_profile.py              # P1: профили (ранавей p>1, исходы, состав state)
```

- Результаты и выводы ревью — в обсуждении задач `docs/TODO.md`; краткая сводка
  зафиксирована в `docs/TODO.md` (раздел «Закрыто»).
