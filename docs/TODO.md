# TODO: только открытые задачи

> **Дата:** 2026-11-25. Закрытые пункты удалены из трекера; их история
> остаётся в git и в [`history/`](history/). Канон и границы — в
> [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md).

## 0. Легаси и свободный режим

- [ ] **Убрать легаси-слой окончательно.** Цель: в репозитории не остаётся
  второго клиента и второго канона. Объём: `ui/` (клиент, сцены, виджеты,
  сохранения), `simulation.py` (легаси-дуэли и `UtilityAI` как baseline),
  флаги `--classic`/`--ui`/`--interaction` и fallback `--scene` без
  `--view` в `main.py`, каталоги `scenarios/` и верхнеуровневый `campaigns/`,
  если они не нужны активным слоям. Сначала перенести общие зависимости
  (`warfare.Character` и константы `simulation`, если они реально нужны
  активному коду) в активный слой; тесты легаси либо переводятся на
  `view/`/`core41`, либо удаляются вместе с покрытием. Критерий: `main.py`
  имеет один игровой клиент, `grep` по активным пакетам не находит
  `import ui`/`import simulation`, `pytest` зелёный без легаси-тестов.
- [ ] **Свободный режим — в специфике сюжета кампании.** Свободный режим не
  должен быть отдельной игрой и отдельным набором артефактов: он задаётся
  полями того же сюжета кампании (режим, стартовая точка, отсутствие главы
  и `days`), а не отдельным `free_life`-сюжетом. Отдельный
  `configs/storylines/free_life_scenes.json` уже удалён, сцены лежат
  inline в `free_life.json`; осталось свести сам `free_life.json` к
  специфике общего сюжета и убрать артефакты, которые существуют только
  ради отдельного свободного режима. Критерий: один сюжет кампании умеет
  запускаться и как глава, и как свободный мир; в данных нет отдельного
  `free_life`-сюжета.

## 1. Кампания, время и работа

- [ ] Удалить legacy-помощники `_end_turn`/`end_turn` после отказа экранов
  от старых вызовов.
- [ ] Добавить вакансии и перевод персонала между органами длительным
  действием.
- [ ] Дать персонажам личные отношения друг с другом (покровитель,
  соперник, долг), чтобы цели влияли на состав исполнителей.
- [ ] Наполнить `assets/images/characters/` реальными портретами; пока это
  плейсхолдеры.

## 1.1. Сюжет как проекция симуляции

Канон — в [`NARRATIVE_INVARIANT.md`](NARRATIVE_INVARIANT.md), схема и
фазы — в [`LORE_IMPLEMENTATION_PLAN.md`](LORE_IMPLEMENTATION_PLAN.md).
Сюжет не задаётся сценами, выборами или финалами в данных: он собирается
из `AutomataCampaign.narrative` в `campaign/chronicle.py`.

Открытых пунктов нет: причинные связи, курс подфракции, free-life
«Агора», литературный слой и фразы-маркеры закрыты. Шаблоны хроники
проверяются `campaign.content_lint` (категории, обязательные
плейсхолдеры, неизвестные поля), а файловый журнал включается только
флагом `--log`.

## 1.2. Архитектурные разрывы: W1, W2, W4, W6

Из технического SWOT (локальный документ, в репозиторий не входит).

- [x] **W1. BDI и 16 потребностей — у всех персонажей.** `BDIState` с 16
  желаниями есть у `warfare.Character` (арена, automata-кампании, отряды
  RTS), но не у `CampaignCharacter` (NPC дневного мира) и `CampaignActor`
  (игрок мира). Перевести их на `BDIState` или общий `AgentState`, подключить
  `campaign/routine.py` к NPC мира, сохранить снимки и совместимость.
  Отдельно закрыть покрытие: суточная рутина закрывает 8 базовых
  потребностей, а в контенте automata-кампаний у `love` и `reproduction` нет
  ни одного удовлетворяющего действия. Критерий: у каждого персонажа есть
  16 потребностей, каждая растёт, тонет в `F/E` и может быть удовлетворена
  действием; тест «каждый персонаж имеет явный профиль агента».
  Закрыто: `CampaignActor`/`CampaignCharacter` используют `BDIState`,
  снимки и суточная рутина подключены, `love`/`reproduction` и высшие
  желания закрыты социальными работами; тесты — `test_world_needs.py`.
- [x] **W1a. Плоские карты потребностей в обработчиках.** В
  `configs/campaigns/base/handlers/*.json` десятки плоских ключей
  (`friendship`, `loneliness`, `hunger`, `status`, `knowledge`, `health`,
  `fatigue`, `anxiety`, `spirituality`, `skill`) уходили в
  `_apply_assets` и создавали невидимые активы фракции вместо изменения
  потребностей. Семантика закреплена: имена 16 потребностей пишутся
  только во вложенный `needs`, настоящие активы — только в `assets`.
  Все правила кампании переведены на явные карты; `fear` как настоящий
  актив остался в `assets` (`coercion`, `information`, `meaning`, `care`),
  а в `personal_care` страх цели отнесён к `needs`, потому что действие
  утешает человека; `health`/`friendship`/`status` и остальные
  потребности — в `needs`. `campaign/content_lint_handlers.py` запрещает
  плоские ключи-потребности в `receiver.effect`, `sender`,
  `failure.effect` и `failure.sender`, включая ветки `if/then/else`.
  Критерий выполнен: ни одно правило не пишет потребность через актив,
  `content_lint` это ловит; интеграционный тест
  `test_handler_needs_reach_bdi_instead_of_creating_assets` подтверждает,
  что `community_network` меняет BDI, а не создаёт активы. Числовые
  значения перенесены без изменения знака; калибровка магнитуд и знаков
  потребностей — отдельная контентная задача. Golden-снимок
  `empire_seed13.json` обновлён осознанно: из активов исчезли невидимые
  `friendship`/`health`/`hunger`/`skill`/`status`/`anxiety`/
  `spirituality`/`knowledge`, а потребности теперь влияют на решения ИИ;
  исход, ход и сюжетные события не изменились.
- [x] **W2. RL поверх BDI для NPC (базовый гибрид).** Сейчас RL — отдельный слой для арены,
  автопилота игрока и `CampaignEnv`; когниция NPC — BDI плюс эвристики.
  Сделать гибрид: BDI выбирает цель/намерение, политика
  (`BDIPolicy`/`QTablePolicy`/`MLPPolicy`) — действие и параметры; обучение
  на логах кампаний и self-play, детерминированный инференс, версионированные
  чекпойнты. Не заменять BDI и не ломать воспроизводимость. Критерий:
  хотя бы одна фракция/тип NPC выбирает действие обученной политикой поверх
  BDI, есть eval-матрица и откат к эвристике.
  Закрыто: `campaign/npc_policy.py` (`NeedPolicy`) выбирает работу поверх
  весов BDI, с чекпойнтами и детерминированным инференсом; слой включён
  по умолчанию, бэкенд — `soar` с откатом на `legacy`. Остались
  eval-матрица и self-play — см. W2a.
- [ ] **W2a. Eval-матрица и self-play для политики NPC.** Сравнить
  эвристику, `NeedPolicy` и обученные чекпойнты на одинаковых seed,
  зафиксировать метрики и правила отката.
- [x] **W4. Связность и объём.** Разрезать оставшиеся крупные модули
  (`campaign/dialogue/lint.py`, `campaign/preset.py`,
  `campaign/content_lint.py`, `warfare.py`), ввести fitness-функции границ
  (активные слои не импортируют легаси; данные не содержат исполняемой
  логики), сократить дублирование и число документов-статусов. Критерий:
  нет модулей > 1500 строк в активных пакетах, тест границ падает при
  импорте легаси из активного слоя.
- [x] **W6. Баланс и UX.** Экран «Как играть», подсказки «почему действие
  недоступно», читаемый HUD, сохранение и применение настроек (звук,
  полный экран, анимации), первые 10 минут с крючком. Критерий: новая
  сессия объясняет цель и управление без документации; настройки
  переживают перезапуск.
  Закрыто: экран «Как играть» в меню, причины недоступности в HUD
  уже выводятся, настройки (`sound`, `music_volume`, `fullscreen`,
  `animations`, `text_speed`) хранятся в `saves/settings.json` и
  применяются при старте; тест `test_view_settings.py`.

## 1.3. Переход ИИ на Soar + RiveScript

Канон и план — [`SOAR_RIVESCRIPT_MIGRATION.md`](SOAR_RIVESCRIPT_MIGRATION.md).
Цель: Soar — когнитивное ядро (диалог, BDI, NPC, фракции), RiveScript —
языковая поверхность и NLU-триггеры, Python — среда и единственная точка
записи состояния. JSON остаётся источником истины, `.soar`/`.rive`
генерируются.

- [x] **Phase 0a. Фундамент.** Добавлены `campaign/cognition/`
  (`understand`/`decide`, `UtteranceFrame`, `soar_bridge.v1`, золотой
  корпус, parity-метрики), `configs/cognition/backends.json` и флаги
  `ai_backend`/`nlu_backend`. Legacy-бэкенд делегирует в
  `ChartParser`/`NeedPolicy`; `shadow`/`rive` работают, `soar` пока
  отказывает явно. Тесты — `tests/test_cognition_*.py`,
  `tests/test_soar_bridge.py`.
- [x] **Phase 0b. Spike.** Запустить Soar и RiveScript в CI, выбрать
  биндинг, добавить опциональный job с нативными зависимостями.
  Закрыто: RiveScript 1.15, `soar-sml` 9.6 в отдельном job `soar`;
  основной job остаётся кроссплатформенным.
- [x] **Phase 1. RiveScript shadow NLU.** Сделано: компилятор JSON →
  `.rive` + манифест, теневой `RiveNlu`, `! sub` из лексикона, точные
  триггеры, object macros `morph`/`number`/`quality`/`entity`, линтер
  `nlu_lint`, золотой корпус на 144 фразы (`corpus_builder`), parity 1.0,
  `nlu_backend=shadow`, проверки артефактов и корпуса в CI,
  `configs/rive/`. Phase 1d: `grammar_patterns()` компилирует правила
  `S` в триггеры (23 из 67 правил, закрытые классы — литералы, открытые —
  `[*]`), `RiveNlu.report()` считает `fallback_rate` на живом вводе с
  порогом `thresholds.fallback_rate_max`. Основной режим — Phase 4.
- [x] **Phase 2. Soar для NPC (shadow → основной).** Сделано: `configs/soar/`
  (`decision.json` → `npc_policy.soar`), `SoarNpcPolicy` считает оценку
  и выбирает оператора в Soar, `decide(ai_backend=shadow)` пишет выбор
  в `shadow_sink`, parity 100% на реальных кандидатах кампании,
  `soar-sml` в отдельной job CI. Phase 2b: `npc_policy.backend` и
  `backends` включают Soar по фракции, `timeout_ms` ограничивает
  решение, `npc_decision_report()` показывает согласие, ошибки и
  латентность, 20 ходов кампании в тени совпадают с легаси.
  Phase 2c: бюджет прерывается между циклами Soar,
  `npc_outcome_report()` отдаёт удовлетворённость 16 потребностей и
  разнообразие работ, строгий `soar` на 40 ходах совпадает с легаси
  по снимку и метрикам; `save_snapshot()` хранит `ai_model`, поэтому
  загрузка сохраняет `legacy|shadow|soar` и бюджет решения.
  Phase 2d (калибровка исхода): `score_window=12` сглаживает разницу
  прогресса, `score_bias`/`score_margin` пересняты на 20 seed × 60 ходов
  в каждом режиме `npc_policy` (империя 26/14/0, республика 17/20/3,
  культ 16/21/3, корпорация 27/7/6 на 40 прогонах), у культа порог
  поражения по законности опущен до `0.02`; `score_recent` входит в
  `save_snapshot()`, `SCHEMA_VERSION = 3`. Phase 2e (бюджет тика):
  `npc_policy.tick_timeout_ms` (0 — взять `timeouts.tick_ms = 250`)
  ограничивает сумму Soar-решений за ход, каждое решение получает
  `min(timeout_ms, остаток)`, счётчик обнуляется в `begin_turn()`;
  исчерпание бюджета отдаёт остаток хода легаси и помечает прогон
  `ok: false` (ресурсный предел, а не ошибка Soar), настоящие ошибки
  Soar в `soar` не маскируются; `npc_tick_budget()` показывает
  `limit_ms`/`spent_ms`/`left_ms`. Phase 2f (основной режим):
  `ai_backend=soar` и `npc_policy.enabled=true` по умолчанию, строгий
  `soar` на 20 seed × 60 ходов × 4 шаблона даёт те же исходы, что
  легаси, без ошибок (контрольный прогон 2 seed — 560 решений без
  исчерпаний бюджета); без `soar-sml` бэкенд понижается до `legacy` с
  тем же выбором и пометкой `unavailable`, откат —
  `OZVERIN_AI_BACKEND=legacy` или `enabled=false`. Phase 2 закрыта.
- [ ] **Phase 3. Soar shadow для прагматики.** Вывод, раскрытие и план
  ответа в Soar; синтез пока старый.
- [ ] **Phase 4. RiveScript основной NLU.** Поддерживаемое множество
  идёт через RiveScript + Soar, `ChartParser` — fallback.
- [ ] **Phase 5. Soar для BDI, фракций и мира.** Решения агентов в Soar,
  Python — среда; RL-предпочтения после сравнения.
- [ ] **Phase 6. Демонтаж GOFAI.** Удалить старые NLU/эвристики и
  shadow-флаги, обновить канон и fitness-тесты.

## 2. Диалог

- [ ] `avoid_recent` (D5.1): проверить, что ограничение по ходам не даёт
  выбрать неожиданный регистр в длинном разговоре.
- [ ] D3.2: контрфакты не используют `differences`/`removed`/`added`.
  Полноценное «изменилось бы потому, что …» — отдельная задача.
- [ ] D3.2: расширить whitelist из 5 отношений по мере P8/P9.
- [ ] D6.2a: `s_counterfactual_neg` дублирует `s_counterfactual` — удалить
  или оставить как документирующий алиас.
- [ ] `fallback.json`: пополнять лексику по реальным фразам игроков и
  проверять battery-тестом на естественных вопросах.
- [ ] Ротация связок для длинного абзаца (3+ стыка), если понадобится.
- [ ] Проверить интеграционным тестом, что изменения отношений и убеждений
  сразу видны в следующем ответе.

## 3. Приоритет на ближайшую неделю

1. Корпус парафраз и доменных псевдонимов — по мере роста грамматики.
2. Корпус фраз-маркеров режимов разговора: тон уже меняется, содержание
   ответа — не всегда.
3. Факты здравого смысла: расширять курированный слой и покрытие
   runtime-хука стиля.

## 4. Архитектура (следующие шаги)

- [x] `WorldEngine` (`campaign/world.py`, 237 методов) разрезан по швам на
  миксины: `world_core.py`, `world_entities.py`, `world_relations.py`,
  `world_career.py`, `world_actions.py`, `world_day.py`,
  `world_snapshot.py`; общие примитивы — `world_support.py`. Публичный API
  и формат снимка сохранены (AST-сверка 230/230 имён, полный прогон).
- [x] `AutomataCampaign` (`campaign/automata.py`, 190 методов) разрезана
  тем же протоколом: `automata_core.py`, `automata_actions.py`,
  `automata_processes.py`, `automata_ai.py`, `automata_characters.py`,
  `automata_orders.py`, `automata_reports.py`, `automata_snapshot.py`;
  общие примитивы — `automata_support.py`. Алиасы
  `interact_organ`/`interact_automaton`/`interact_character` и
  `to_dict` сохранены; публичный API и формат снимка проверены AST-сверкой.
- [x] Убрать прямые импорты `warfare`/`simulation` из `campaign/` на
  верхнем уровне: `automata_support._character_from_record` и
  `preset._make_character` создают `warfare.Character` лениво; граница
  зафиксирована `tests/test_architecture_boundaries.py` и описана в
  `SOURCE_OF_TRUTH.md` §4.
- [x] View-слой разрезан по тому же протоколу:
  `view/app.py` — фасад `App` + `app_{core,storyline,scenes,flow,dialogue,saves,menu,support}.py`;
  `world_screen.py` + `world_screen_{core,events,draw,detail,personality,support}.py`;
  `rts_screen.py` + `rts_screen_{core,commands,update,events,draw,support}.py`;
  `automata_network.py` +
  `automata_network_{core,selection,actions,events,draw,support}.py`.
  Публичные имена, атрибуты классов и `__init__` сохранены; MRO ставит
  миксины до `BaseScreen`, иначе базовые заглушки перекрывали бы экран.
- [ ] Следующие крупные модули вне экранов: `game_engine.py` (`GameApp`,
  легаси-арена) и `view/support/world.py` (`CampaignEngine`,
  `CampaignState`); это не «божественные объекты» одного класса, но
  кандидаты на такие же швы.
- [ ] Остаётся транзитивная зависимость `campaign → organizations.runtime →
  simulation`: `OrganizationRuntime` наследует `simulation.Environment`.
  Полный разрыв — вынести `Agent`/`Environment` в нейтральный модуль
  (отдельная миграция, менять поведение легаси нельзя).
- [ ] Перенести логи и сейвы из дерева репозитория в пользовательский
  data-dir (XDG), оставив флаг для локальной отладки.

## 5. Перед коммитом

```bash
venv/bin/python -m pytest -q
venv/bin/python -m campaign.content_lint
venv/bin/python -m campaign.dialogue.lint
venv/bin/python -m compileall -q campaign warfare.py view tests
git diff --check
```
