# Онбординг: карта проекта по потребностям

> **Роль документа.** Это навигационная карта для первого входа в
> `Ozvering-Project`: что запускать, где лежит нужный слой, какие тесты и
> документы читать. Документ не заменяет канон и спецификации, а помогает
> быстро найти нужный из них.
>
> **Дата сверки:** 2026-11-24. Проверялось по коду и тестам, а не только
> по README. Полный набор — 2076 тестов, прогон зелёный (1098 с). Если документ
> расходится с кодом, доверяйте коду и тестам; расхождение лучше сразу
> исправлять.
>
> **Источник истины:** [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md). Порядок
> приоритетов документов описан в его начале.
>
> **Дата обновления §3.2, §3.3, §4.1, §4.3, §5.9, §5.10, §6:**
> 2026-11-14 (после D3.2, D5.4, D6.2a–d и D6.3).

---

## 1. За пять минут: запустить и увидеть игру

Все команды выполняются из корня репозитория.

### 1.1. Окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
# опционально: Soar SML для Phase 2 (только manylinux x86_64)
pip install -r requirements-soar.txt
```

Используйте `venv/bin/python`: системный Python может не иметь `pygame-ce`.
Для GUI нужен реальный дисплей. Для тестов и проверки отрисовки — dummy SDL:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy venv/bin/python -m pytest -q
```

### 1.2. Основной запуск

```bash
venv/bin/python main.py
```

Без флага открывается современный клиент `view/` — главное меню
«Операция „Озверин“». Это основной игровой путь.

### 1.3. Первый игровой сценарий

1. «Новая игра».
2. Выберите роль: Император, Председатель парламента, Верховный жрец или
   Генеральный директор. Слева — список, справа — полное описание роли;
   выбор подсвечивается, но кампания ещё не стартует.
3. Нажмите «Продолжить».
4. Заполните личность героя: имя, пол, происхождение, призвание, ценность,
   слабость и главную черту. Для каждого раздела показано полное описание
   и влияние на потребности/черты; есть «Случайное имя» и «Случайная
   личность».
5. Нажмите «Начать кампанию» и пролистайте новеллу
   («Далее»/«Пропустить»).
6. После новеллы начинается сцена `gameplay`.
7. Откроется кампания автоматов: четыре фракции, работы игрока с органом-
   исполнителем, журнал, кнопки «Выполнить · 1 действие», «Ускорить · ×N»,
   «Медленнее · ×N» и «Кодекс». Кампания идёт в реальном времени: `1×` —
   физическая секунда, кнопка ускорения повышает множитель (по умолчанию
   до `×32`), а «Медленнее» отменяет одно ускорение и не опускается ниже
   `1×`; паузы и отката нет. Доступно несколько действий
   (`actions_per_cycle`, по умолчанию 3; старый ключ
   `actions_per_turn` читается как псевдоним); работа или влияние на сеть тратят
   одно действие, а восстанавливаются они со временем. Одноразовые работы
   после выполнения показывают «уже выполнено», работы с лимитом —
   «исчерпано», а условия вроде «сначала нужно: …» видны прямо в списке.
8. Кнопка «СВЯЗЬ» в свободной области сверху справа открывает игровой чат
   с агентом (`view/screens/dialogue_chat.py`): выбор фракции, персонажа и
   стиля ответа. Ответ агента проходит парсер, состояние диалога, вывод,
   план, социальный и дискурсивный слои, затем регистровый синтез. Если
   фраза разобрана как приказ, угроза или обещание, чат сначала пробует
   `act` и меняет кампанию; обычный вопрос остаётся read-only. Приказы
   доступны только для своей стороны. Подробности — §5.9.
9. «Кодекс» показывает всех персонажей и автоматы, включая органы фракций.
   У записи своей фракции внизу карточки есть кнопки действий: персонажа
   можно повысить, наградить, поддержать или допросить, орган — усилить,
   реформировать, почистить или снабдить. Действие тратит одно действие
   бюджета и применяется сразу. Собственного персонажа усилить нельзя —
   такие действия показывают причину «нельзя применять к самому себе».
10. «Сеть» открывает сетку органов своей фракции, связанных полем
    `links`: `Панцерваффе ↔ Вермахт ↔ Имперская ставка` — это соседство, а
    не вертикаль подчинения; выбранный узел подсвечивает себя и соседей.
    На вкладке «АВТОМАТЫ» выбранный орган отдаёт команду другому автомату
    (цель выбирается кликом по узлу), на вкладке «ВЛИЯНИЕ» можно усилить
    орган, на вкладке «ПЕРСОНАЛ» — повлиять на человека. Клик по органу из
    «ПЕРСОНАЛА» возвращает на «ВЛИЯНИЕ». Чужие фракции в сети недоступны.
    Каждое взаимодействие или команда стоит одно действие; отдельной кнопки
    завершения хода нет.
11. Жёсткого лимита ходов нет. Кампания идёт непрерывно и заканчивается,
    когда срабатывает порог поражения или устойчивое преимущество по
    прогрессу (`score_after` + `score_streak`), после чего показывается
    финал, собранный из состояния. По ходу кампании лента заполняется
    хроникой: эпизодами работ, взаимодействий и решений по докладам.

«Продолжить» в главном меню открывает только совместимые сохранения —
автоматы, стратегию или мир. Легаси-военные снимки пропускаются: игра не
перебрасывает игрока на старую карту «Долина-1».

Проверено headless-прогоном: меню → выбор роли → редактор личности →
новелла → `AutomataScreen`, затем прогон с бюджетом действий,
кодекс, сеть, чат и отрисовка без исключений. Автотесты этого пути —
`tests/test_identity.py`, `tests/test_campaign.py`,
`tests/test_automata_campaign.py`, `tests/test_d4_social.py`.

### 1.4. Остальные режимы

| Что открыть | Команда | Состояние |
|---|---|---|
| Современная кампания (по умолчанию) | `venv/bin/python main.py` | работает |
| То же явно | `venv/bin/python main.py --view` / `--campaign` | работает |
| Арена-дуэль | `venv/bin/python main.py --arena` | работает |
| Редактор автоматов | `venv/bin/python main.py --automata` | работает |
| Легаси-клиент `ui/` | `venv/bin/python main.py --classic` | работает |
| Экран взаимодействий | `venv/bin/python main.py --interaction` | работает |
| Легаси RTS-поле сразу | `venv/bin/python main.py --scene battlefield` | работает |
| Альтернативные точки входа | `venv/bin/python -m view`, `-m ui`, `-m automata` | работают |

`--scene` без `--view` уходит в легаси-клиент `ui/`; это сохранено для
старых команд. `--fullscreen`/`-f`, `--checkpoint`, `--speed`,
`--sickness`, `--health-factors`, `--no-auto-checkpoint`,
`--checkpoints-dir` пробрасываются выбранному приложению.
`--list-checkpoints` печатает список и не открывает окно.
Журнал включается только флагом `--log`; `--log-file PATH` задаёт свой
путь и тоже включает запись. Файл перезаписывается при каждом запуске,
размер ограничен.

`-m` принимает имя модуля через точку, а не путь: `python3 -m campaign/world`
и `python3 -m core41/arena` — синтаксически неверные команды. Модули
`campaign.world` и `core41.arena` библиотечные, поэтому корректные
`python3 -m campaign.world`/`-m core41.arena` только печатают подсказку.
Игра запускается через `main.py --view`/`--arena`, а справка и демо ядра —
через `python3 -m core41` и `python3 -m core41 --demo`.

---

## 2. Навигатор: потребность → маршрут

| Потребность | С чего начать | Ключевые файлы | Проверка |
|---|---|---|---|
| «Хочу просто поиграть» | §1.3, [`HOWTO.md`](HOWTO.md) §1 | `main.py`, `view/app.py` | `tests/test_gui_smoke.py` |
| «Хочу запустить конкретный режим» | §1.4, [`history/UI.md`](history/UI.md), [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md) | `main.py` | `tests/test_ui.py` |
| «Хочу понять модель мира» | §5.1, [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) | `core41/`, `campaign/`, `simulation.py`, `warfare.py` | `tests/test_core41.py`, `tests/test_canon.py` |
| «Хочу понять формулы» | [`FORMULAS.md`](FORMULAS.md) | `core41/model.py`, `core41/arena.py`, `campaign/` | `tests/test_math_model.py`, профильные тесты |
| «Хочу править контент без кода» | §5.2, [`CONTENT.md`](CONTENT.md) | `configs/` | `tests/test_content_pipeline.py` |
| «Хочу править современный GUI» | §5.3, [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md) | `view/` | `tests/test_gui_smoke.py`, `tests/test_view_*.py` |
| «Хочу править легаси-GUI» | §5.3, [`history/UI.md`](history/UI.md) | `ui/` | `tests/test_ui.py` |
| «Хочу менять кампанию автоматов» | §5.4, [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) | `campaign/automata.py`, `campaign/fractal.py`, `campaign/geometry.py`, `configs/campaigns/` | `tests/test_automata_campaign.py`, `tests/test_automata_network.py`, `tests/test_geometry.py` |
| «Хочу обучить агента» | §5.6, [`AGENTS.md`](AGENTS.md), [`HOWTO.md`](HOWTO.md) §2 | `agents/`, `core41/` | `tests/test_train_cli.py` |
| «Хочу добавить механику» | §5.5 | слой по §3.2 | профильные тесты |
| «Хочу понять сейвы» | §5.7 | `view/support/save_system.py` | `tests/test_save_system.py` |
| «Хочу понять диалог с агентами» | §5.9 | `campaign/dialogue/`, `configs/dialogue/` | `tests/test_d0*.py` … `tests/test_d5_*.py` |
| «Хочу понять план перехода ИИ на Soar + RiveScript» | [`SOAR_RIVESCRIPT_MIGRATION.md`](SOAR_RIVESCRIPT_MIGRATION.md) | `campaign/cognition/` (фасад, компиляторы, `RiveNlu`, `SoarNpcPolicy`, `SoarNpcPool`, `SoarIntentionPool`, `SoarRlTrainer`, macros, `corpus_builder`), `campaign/npc_decisions.py`, `configs/rive/`, `configs/soar/` и `configs/cognition/golden_corpus.json` | `tests/test_cognition_*.py`, `tests/test_soar_full_runs.py`, `tests/test_npc_decisions.py`, `tests/test_soar_bridge.py`; `python -m campaign.cognition.rive_compiler --check`; `python -m campaign.cognition.nlu_lint`; `python -m campaign.cognition.corpus_builder --check`; `python -m campaign.cognition.soar_compiler --check`; `python -m campaign.cognition.intention_compiler --check`; `python -m campaign.cognition.faction_compiler --check`; `python -m campaign.cognition.reaction_compiler --check`; `python -m campaign.cognition.rl_compiler --check` |
| «Хочу проверить, что ничего не сломал» | §5.10 | `tests/` | `pytest -q` |

---

## 3. Где что лежит

### 3.1. Точка входа и клиенты

`main.py` — единая точка входа. Она только разбирает флаги и передаёт
управление одному из приложений.

| Путь | Что это | Роль |
|---|---|---|
| `main.py` | диспетчер запуска | флаги → `view/`, `ui/`, `game_engine`, `automata/` |
| `view/` | современный клиент | меню, роли, новелла, документ, кампания автоматов, мир, RTS, чат, сейвы |
| `ui/` | легаси-клиент | сценный слой: меню, нарратив, арена, RTS, взаимодействия, пауза |
| `game_engine.py` | автономная арена | `core41`-дуэль + HUD, встраивается в `view/` |
| `automata/` | редактор автоматов | граф состояний/переходов, JSON-хранилище, без игровой модели |
| `core41/` | целевой срез 4-2-1 | арена, дуэль, здоровье/болезнь/раны, часы, среда |
| `campaign/` | дневной мир и кампания | роли, пресеты, `WorldEngine`, `CampaignEnv`, `AutomataCampaign`, BDI игрока и NPC (`actor.py`, `character.py`), суточная рутина `routine.py`, политика NPC `npc_policy.py` и метрики решений `npc_decisions.py`, сеть органов `fractal.py`, производные активы `faction_state.py`, доклады (`dispatch.py` + `dispatch_*.py`), метрики `qualitative.py`, аудит `audit.py`, сейвы |
| `campaign/dialogue/` | детерминированный диалог | парсер, вывод, план ответа, синтез, стили, дискурс, сравнения, контрфакты, речевые действия, память |
| `agents/` | обучаемые политики | BDI/QTable/MLP, чекпойнты, `agents.train` |
| `warfare.py` | войсковые автоматы | персонажи (`warfare_character.py`), константы и приказы (`warfare_core.py`), отделения, станы, симуляция |
| `simulation.py` | легаси-канон дуэлей | воспроизводимый baseline, не активный игровой поток |

### 3.2. Слои и зависимости

Упрощённо:

```text
main.py
  ├─ view/        современный GUI + сюжет
  │    ├─ campaign/  мир, пресеты, кампания автоматов
  │    │    ├─ campaign/dialogue/  диалоговый слой (D0–D5.4, D3.2, D6.2a–d, D6.3, D6.4, D7.0–D7.4)
  │    │    └─ warfare.py / core41
  │    ├─ view/support/  адаптеры, сейвы, время, эффекты
  │    └─ view/ui/       менеджер экранов, HUD, виджеты, ассеты
  ├─ ui/          легаси GUI
  │    └─ game_engine.py → core41
  ├─ game_engine.py
  └─ automata/    независимый редактор
```

Практические правила:

* `core41/` — целевое ядро 4-2-1; менять физику арены нужно здесь.
* `campaign/` — дневной мир и кампанийные правила; не переписывайте аренные
  константы без перекалибровки.
* `campaign/dialogue/` — диалоговый слой: парсер, вывод, планы, синтез,
  стили, состояние, речевые действия, дискурсивный слой, сравнения,
  контрфакты, цели/мост к действиям и headless-текстовик. Полностью
  Data-Driven: данные в `configs/dialogue/`, Python только
  интерпретирует. Сквозные ограничения контрфактов и отрицания
  описаны в §5.9.
* `warfare.py` — персонажи и отделения (персонаж вынесен в
  `warfare_character.py`, константы — в `warfare_core.py`); кампания автоматов использует его
  для состава фракций и организаций. Импорт ленивый (внутри фабрик
  персонажей), поэтому `import campaign.automata` не загружает `warfare`;
  границу стережёт `tests/test_architecture_boundaries.py`.
* `view/` и `ui/` — представление и ввод. Логику лучше держать в чистых
  модулях (`campaign/`, `ui/battlefield.py`, `interaction/`), а экран — тонким.
* `configs/` — данные, а не код. Новый контент по возможности добавляется
  JSON-файлом и загрузчиком, без новой ветки `if` в Python.

### 3.3. Контент: что уже есть в поставке

Состояние может меняться; перед правкой смотрите сам каталог.

| Путь | Содержимое | Загрузчик |
|---|---|---|
| `configs/roles/roles.json` | четыре роли лорных кампаний и `free_citizen` | `campaign.roles.RoleCatalog` |
| `configs/storylines/*.json` | сюжеты четырёх фракций, `free_life` и их сцены | `view.support.storyline` |
| `configs/campaigns/*.json` | шаблоны кампаний автоматов | `campaign.preset` |
| `configs/content/*.json` | приказы, документы, диалоги, время | `view.support.content.Content` |
| `configs/characters/traits.json` | 12 черт, архетипы, влияние | `character_traits.load_traits()` |
| `configs/characters/bdi.json` | 16 желаний | `bdi.py`, `warfare.py` |
| `configs/characters/divisions.json` | 15 делений | `campaign.divisions` |
| `configs/systems/*.json` | среда, события, драматург | `systems.*` |
| `configs/naming/*.json` | лексикон и имена | `naming.*` |
| `configs/dialogue/` | диалоговый слой: онтология, лексикон, грамматика, правила, факты, планы, синтез, стили и автовыбор, состояние, соц. действия, дискурс, сравнения, контрфакты, цели, псевдонимы действий, текстовый интерфейс, мост к миру | `campaign.dialogue.loader` |
| `configs/worlds/` | production-мир: `agora_world.json` (44 узла, 72 должности, 65 действий после слияния каталогов, 8 предметов, 6 сцен), `actions/`, `scenes/`, `handlers/` (70 правил), `agora_strategies.json`, `biography.json` | `campaign.world.load_world()`, `campaign.actions`, `campaign.scenes`, `campaign.node_strategy` |
| `configs/automata/*.json` | **пусто** (только `.gitkeep`): редактор читает каталог, но графов автоматов в поставке нет | `automata.storage.AutomataStore` |
| `configs/campaigns/base/automata/*.json` | исполняемые автоматы фракций и органов (схема 2) | `campaign.state_machine` |
| `configs/strategy/`, `configs/environments/`, `configs/presets/`, `configs/classes/`, `configs/view/` | пусто (`.gitkeep`) | соответствующие загрузчики |

Тестовый набор контента лежит отдельно: `tests/fixtures/content/`.
`tests/conftest.py` подменяет рабочие каталоги на фикстуры, поэтому тесты
не зависят от production-сюжетов. Production-мир для быстрой кампании —
`configs/worlds/agora_world.json`; такая же копия в
`tests/fixtures/content/configs/worlds/` нужна только тестам.

---

## 4. GUI: что готово, а что нет

### 4.1. Фактическое состояние

GUI существует и играется, но это **рабочий первый срез, а не релизная
полировка**.

Проверено:

* `tests/test_gui_smoke.py` поднимает настоящий цикл `view.App.run()` под
  dummy SDL: меню, переход в кампанию, экран мира, быстрая кампания.
* `tests/test_ui.py` проверяет все легаси-сцены, навигацию, паузу, сейвы,
  настройки, поле боя, взаимодействия.
* `tests/test_view_world.py`, `tests/test_view_rts.py`,
  `tests/test_view_strategy.py`, `tests/test_campaign.py` содержат
  headless-проверки современного клиента.
* Полный набор 2026-11-24: **2076 тестов**, зелёный (1098 с).
* Профильные диалоговые тесты D0–D5.4 зелёные: `test_dialogue.py`,
  `test_d1_dialogue.py`, `test_d1_5_synthesis.py`, `test_d2_state.py`,
  `test_d3_comparison.py`, `test_d4_social.py`, `test_d5_discourse.py`,
  `test_d5_registers.py`, `test_d5_discourse_paragraph.py`.
* Для D3.2 (контрфакты), D6.2a (отрицание), D6.2b («то»-клауза) и
  D6.2c (`predicate_relations`) есть `tests/test_d3_counterfactual.py`
  (17 тестов).
* Для D6.2d (условия, уступки, косвенная/прямая речь) —
  `tests/test_d6_grammar.py` (16 тестов).
* Для beam D6.2d — `tests/test_d6_parse_beam.py` (11 тестов):
  приоритет видов, ширина, детерминизм, канонический порядок.
* Для корпуса парафраз D6.2d — `tests/test_d6_paraphrases.py`
  (58 тестов, 52 фразы в `configs/dialogue/paraphrases.json`).
* Для D6.3 (раскрытие и ложь) — `tests/test_d6_disclosure.py`
  (19 тестов).
* Полный путь «Новая игра → роль → новелла → кампания автоматов →
  бюджет действий → сеть → чат → исход» исполнен headless без исключений.

### 4.2. Что играется сейчас

* Главное меню `view/`: новая игра, продолжение, быстрая кампания, арена,
  сохранения, настройки, выход.
* Четыре лорные кампании через `configs/roles/roles.json` и
  `configs/storylines/`: Империя, Республика, Культ Земли, Торговая планета.
* Визуальная новелла, экран кампании автоматов с работами,
  ценой, шансами, журналом и исходом; сюжет — хроника из
  `AutomataCampaign.narrative`, финал и стартовая сводка из состояния.
* Игровой чат с агентом: кнопка «СВЯЗЬ» на экране автоматов открывает
  `DialogueChatScreen` (§5.9); приказ или речевой акт меняет кампанию,
  обычный вопрос остаётся read-only.
* Арена `game_engine` и редактор автоматов.
* Легаси-клиент `ui/` со сценами меню, нарратива, поля боя, взаимодействий,
  паузы и сохранений.

### 4.3. Известные ограничения

* **Быстрая кампания из меню использует production-мир.**
  `configs/worlds/agora_world.json` входит в поставку, поэтому экран
  запускается сразу. Если файл удалён, появится просьба добавить мир в
  `configs/worlds/*.json`. «Новая игра» от этого не зависит: она идёт
  через кампании автоматов или свободный режим `free_life`.
* **Ассеты — плейсхолдеры.** `configs/view/presentation.json` в поставке
  отсутствует, поэтому `AssetLoader` использует процедурные заглушки;
  реальные JPG/PNG не обязательны для запуска.
* **Нет экрана «Как играть».** Правила и горячие клавиши не объясняются
  внутри `view/`; это задача B3 из исторического среза
  [`history/RELEASE_READINESS.md`](history/RELEASE_READINESS.md).
* **Настройки `view/` не применяются полностью.** Часть тумблеров меняет
  локальные флаги, но не сохраняется/не влияет на звук, полный экран и
  анимации (B7).
* **Сейвы пишутся в дерево репозитория** (`saves/`), а не в
  пользовательский data-dir (D6). Журнал `operation_ozverin.log` тоже
  лежит в корне, но создаётся только с `--log`/`--log-file` и
  перезаписывается при запуске.
* **Схема сейва `view/` версионируется, но миграции ограничены.**
  Проверяйте `SAVE_VERSION` и тесты при изменении снимка.
* **Баланс и полировка — первый срез.** Кампания автоматов проходится, но
  субъективный баланс, читаемость HUD и длинная прогрессия ещё не
  откалиброваны как «игра для игрока».
* **Диалоговый слой — D6.2a–d и D6.3 закрыты.** Сделаны: D0
  (лексикон и разбор), D1 (вопросы о мире), D1.5 (композиционный
  синтез), D2 (QUD, референты, память), D3.1 (сравнения, расширенное
  «почему»), D4 (речевые действия), D5.1 (дискурсивный планировщик),
  D5.2 (автовыбор регистра в API сессии), D5.3 (агрегация, анафора,
  тема-рема), D5.4 (механизм абзаца через `topics`), D3.2 (движок
  контрфактов), D6.2a (отрицание), D6.2b («то»-клауза), D6.2c
  (`predicate_relations`), D6.2d (условия, уступки, косвенная и прямая
  речь, детерминированный beam по `parsing.json`),
  D6.3 (политика раскрытия и детерминированная ложь),
  D6.4 (цели разговора, планировщик, мост к действиям, императивы и
  псевдонимы действий), D7.0 (headless-текстовик, история, откат,
  подсказки), D7.1 (речевые действия через мост: `social_command`
  и другие interactions, гейты `has_authority`/`trusts`), D7.2
  (перемещение через текст: `movement.json`, маршрут по геометрии
  игрока, «рядом/далеко», read-only по умолчанию), D7.3 (время через
  текст: `time.json`, ожидание и фазы суток, темп, read-only план),
  D7.4 (нарративный слой: `narrator.json`, видимые story-события,
  работы из `log`, `/look`, read-only).
  Сквозные контрфакты достижимы: `believe → considers_outlaw`,
  `have → has_organ`, `fight → at_war_with` дают `changed`. В чате стиль
  выбирается вручную; авто-режим `DialogueSession(style_id=None)`
  доступен только через API сессии. Открыто: расширение доменных
  псевдонимов по мере контента и runtime-хук стилевых подсказок;
  `has_leverage`/`blackmail` закрыты.

---

## 5. Маршруты по задачам

### 5.1. «Хочу понять модель»

Порядок чтения:

1. [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) — цель, онтология 4-2-1,
   принятые решения и границы.
2. [`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md) — детализация целевой
   модели мира.
3. [`history/MODEL.md`](history/MODEL.md) — историческая спецификация
   легаси-`simulation.py`.
4. [`WARFARE.md`](WARFARE.md) — персонажи, потребности, черты, отделения,
   мораль и паника.
5. [`ALGORITHMS.md`](ALGORITHMS.md) — точные формулы арены, признаки
   политик, TD(0), чекпойнты.
6. [`SUMMARY.md`](SUMMARY.md) — сжатая карта, но проверяйте её по коду.

Код:

* `core41/model.py`, `core41/arena.py`, `core41/duel.py` — целевое ядро и
  арена;
* `warfare.py` — войсковые автоматы (фасад: `warfare_core.py`,
  `warfare_character.py`);
* `simulation.py` — легаси-канон, не активный игровой поток;
* `campaign/world.py` — дневной мир должностного лица: фасад
  `WorldEngine`, реализация — в `world_core.py`, `world_entities.py`,
  `world_relations.py`, `world_career.py`, `world_actions.py`,
  `world_day.py`, `world_snapshot.py`, общие примитивы — в
  `world_support.py` (библиотечный модуль; запуск игры — `main.py --view`,
  не `python3 campaign/world.py`);
* `campaign/automata.py` — кампания фракций-автоматов: фасад
  `AutomataCampaign`, реализация — в `automata_core.py`,
  `automata_actions.py`, `automata_processes.py`, `automata_ai.py`,
  `automata_characters.py`, `automata_orders.py`, `automata_reports.py`,
  `automata_snapshot.py`, общие примитивы — в `automata_support.py`;
* `view/app.py` — фасад `App` и `main`; реализация — в `app_core.py`,
  `app_storyline.py`, `app_scenes.py`, `app_flow.py`, `app_dialogue.py`,
  `app_saves.py`, `app_menu.py`, общие помощники — в `app_support.py`;
* `view/screens/world_screen.py`, `rts_screen.py`,
  `automata_network.py` — фасады экранов; их методы разложены по
  `*_core.py`, `*_events.py`, `*_draw.py` и профильным модулям
  (`world_screen_detail.py`, `world_screen_personality.py`,
  `rts_screen_commands.py`, `rts_screen_update.py`,
  `automata_network_selection.py`, `automata_network_actions.py`),
  константы — в `*_support.py`.

Тесты-опоры: `test_core41.py`, `test_canon.py`, `test_warfare.py`,
`test_campaign_env.py`, `test_math_model.py`.

### 5.2. «Хочу править контент без кода»

Начните с [`CONTENT.md`](CONTENT.md). Типовые действия:

* новая роль — `configs/roles/*.json`;
* новый сюжет — `configs/storylines/<id>.json` + `_scenes.json`;
* новая кампания автоматов — `configs/campaigns/<id>.json` и запись роли
  со ссылкой `storyline_id`;
* общие фракции, органы и работы — `configs/campaigns/base/lore_factions.json`;
* варианты личности героя — `configs/characters/identity.json`;
* стартовые архетипы — `configs/characters/archetypes.json` и
  `free_start` в `configs/storylines/free_life.json`;
* новый мир — `configs/worlds/*.json` (production-пример —
  `agora_world.json`; тестовый — в `tests/fixtures/content/`); для
  свободного режима в мире задаются `sandbox`, `realtime`,
  `seconds_per_day` и `time_speeds`; `days` и главу свободный мир не
  задаёт — история не ограничена;
* новый автомат для редактора — `configs/automata/*.json`;
* события/среда/драматург — `configs/systems/*.json`;
* имена — `configs/naming/*.json`;
* черты персонажей — `configs/characters/traits.json`;
* диалоговые данные — `configs/dialogue/*.json` (§5.9).

Проверка после правки:

```bash
venv/bin/python -m pytest -q tests/test_content_pipeline.py
venv/bin/python -m pytest -q tests/test_docs_sync.py
```

Если добавили новый тип загрузчика или поля, нужен ещё и тест в
`tests/test_content_pipeline.py`.

### 5.3. «Хочу править GUI»

Сначала решите, какой клиент вам нужен:

| Клиент | Папка | Когда использовать |
|---|---|---|
| современный | `view/` | основной игровой путь, кампании, новые экраны, чат |
| легаси | `ui/` | старые сцены, RTS, взаимодействия, совместимость |
| арена | `game_engine.py` | автономная дуэль и HUD |
| редактор | `automata/` | графовый редактор автоматов |

Каркас современного экрана:

1. Создайте `view/screens/my_screen.py`, наследник
   `view.ui.screen_manager.BaseScreen`.
2. Реализуйте `draw(screen)`, при необходимости `handle_event(event)`,
   `update(dt)`, `on_escape()`.
3. Зарегистрируйте переход в `view/app.py` (фасад) или в существующем
   экране. Крупные экраны собираются из миксинов: смотрите
   `world_screen.py`/`rts_screen.py`/`automata_network.py` и их
   `*_core.py`/`*_draw.py`-модули.
4. Добавьте headless-тест: конструктор, `draw` на `pygame.Surface`,
   навигация и один-два клика/события.
5. Если экран должен получать HUD времени, выставьте `show_time_hud`;
   если нет — `hide_time_hud`/`show_time_hud = False`.

Легаси-экран устроен похоже, но через `ui.scene.Scene` и
`ui.scene.SceneManager`; см. [`history/UI.md`](history/UI.md).

Тесты:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  venv/bin/python -m pytest -q tests/test_gui_smoke.py
venv/bin/python -m pytest -q tests/test_ui.py
```

### 5.4. «Хочу менять кампанию автоматов»

Читайте [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md).

* Шаблон кампании: `configs/campaigns/<id>.json` — фракции, `scenario.mode:
  "automata"`, `actions_per_cycle`, модель успеха, условия исхода, среда,
  события. Жёсткого `turns` у production-кампаний нет.
* Данные автоматов: `configs/campaigns/base/automata_defaults.json` —
  базовые потребности и мораль персонажей, формулы и драйверы производных
  активов (`faction_state`), модель органов, статусы, взаимодействия,
  бюджет действий, интервалы реального времени и скорости.
  Ядро (`campaign/automata.py` + `campaign/automata_*.py`,
  `campaign/fractal.py`, `campaign/faction_state.py`,
  `campaign/preset.py`) читает эти значения через `campaign/defaults.py`;
  шаблон может переопределить их через `scenario.realtime` и
  `scenario.model`.
* BDI, деления и события: `configs/characters/bdi.json` (16 желаний,
  убеждения и намерения), `configs/characters/divisions.json` (15 делений),
  `configs/systems/events.json` (условия, вероятность, видимость).
* Роль: `configs/roles/roles.json` — `storyline_id` связывает роль с
  сюжетом.
* Сюжет: `configs/storylines/<id>.json` и `_scenes.json` — метаданные и
  `gameplay`, флаг `identity_editor`. У лорных кампаний нет авторских
  сцен, выборов и финалов: их собирает `campaign/chronicle.py` из
  `AutomataCampaign.narrative`.
* Личность героя: `configs/characters/identity.json`, загрузчик
  `campaign/identity.py`, экран `view/screens/identity_editor.py`.
* Логика: `campaign/automata.py` (`AutomataCampaign`: фасад, работы,
  кулдауны, бюджет действий, исходы, взаимодействия с органами,
  персонажами и команды автоматов друг другу; реализация — в
  `automata_*.py`), `campaign/work.py` (capability →
  `WorkPlan`/`Work`), `campaign/handlers.py` (JSON-правила получателя по
  `form`), `campaign/work_trace.py` (trace и баланс),
  `campaign/effects.py` (движок проекций `apply_report`),
  `configs/campaigns/base/handlers/*.json` (эффекты вместо `effects` в
  записи), `campaign/fractal.py` (целостность и
  связи органов, `links`, downscale/upscale, урон), `campaign/geometry.py`
  (метрический граф без глобальных осей, локальные углы, кратчайшие пути,
  `distance`/`angle` в условиях), `campaign/faction_state.py` (производные
  активы, контекст, драйверы), `view/screens/automata_screen.py` (основной
  экран с описанием выбранной работы), `view/screens/automata_network.py`
  (сетка своей фракции, вкладки «АВТОМАТЫ»/«ВЛИЯНИЕ»/«ПЕРСОНАЛ»),
  `view/screens/dialogue_chat.py` (игровой чат, §5.9).

Проверки:

```bash
venv/bin/python -m pytest -q tests/test_automata_campaign.py
venv/bin/python -m pytest -q tests/test_identity.py
venv/bin/python -m pytest -q tests/test_automata_network.py
venv/bin/python -m pytest -q tests/test_lore_characters.py
venv/bin/python -m pytest -q tests/test_gui_smoke.py
```

Не меняйте `score_margin`/`score_bias`/`outcome` без прогона полного набора
кампаний: это баланс, а не только текст.

### 5.5. «Хочу добавить механику»

1. Определите слой: `core41` (физика арены), `campaign` (дневной мир,
   кампании), `campaign/dialogue` (диалог), `warfare` (персонажи/
   отделения), `view`/`ui` (только представление).
2. Сформулируйте инвариант и напишите тест до реализации. Для модели —
   `tests/test_math_model.py`/`test_core41.py`; для кампании —
   `test_campaign_env.py`/`test_world.py`; для GUI — `test_gui_smoke.py`;
   для диалога — `test_d0*.py` … `test_d5_*.py`.
3. Если поведение должно быть data-driven, сначала добавьте поле/схему в
   JSON и загрузчик, затем код.
4. Обновите профильный документ; для арены — `ALGORITHMS.md`, для
   легаси-констант `simulation.py` — `history/MODEL.md` (это ловит
   `test_docs_sync.py`).
5. Прогоните `pytest -q` и `git diff --check`.

Не добавляйте доменные ветки в ядро: `test_domain_audit.py` следит за
инвариантностью.

### 5.6. «Хочу обучить агента»

Кратко:

```bash
# арена, self-play
venv/bin/python -m agents.train --episodes 500 --seed 0

# дуэльный срез
venv/bin/python -m agents.train --episodes 500 --seed 0 --env duel

# дневная кампания (production-мир; --world переопределяет путь)
venv/bin/python -m agents.train --episodes 100 --seed 0 --env campaign \
  --policy bdi \
  --world tests/fixtures/content/configs/worlds/agora_world.json

# с сохранением и held-out матрицей
venv/bin/python -m agents.train --episodes 2000 --seed 0 \
  --eval-episodes 50 --eval-seed 100000 \
  --eval-opponents bdi,qtable,random,mlp \
  --out saves/bdi.json --eval-out saves/eval.json
```

Полный список флагов и интерпретация результатов — [`HOWTO.md`](HOWTO.md)
§2 и [`AGENTS.md`](AGENTS.md). Аренный чекпойнт не подходит для кампании:
контракт `supports_campaign` отвергает его до `act()`.

### 5.7. «Хочу разобраться с сохранениями»

* `view/support/save_system.py` — слоты кампании, `SAVE_VERSION`, миграции.
* `ui/save.py` — настройки и слоты легаси-арены.
* `saves/` — рабочий каталог (не коммитится).
* `tests/test_save_system.py`, `tests/test_ui.py` — версии, битый JSON,
  запись/чтение, загрузка из паузы.

При изменении формы снимка добавьте миграцию и тест со старым файлом.
Полное состояние арены не сериализуется: партия детерминирована по seed и
доигрывается до сохранённого такта.

### 5.8. «Хочу отладить»

* Лог включается флагом: `venv/bin/python main.py --log` (файл
  `operation_ozverin.log` в корне, перезапись при запуске, лимит 5 МиБ)
  или `--log-file PATH`. Без флага файл не создаётся. Смотрите `view.*`,
  `asset_loader`, `core.storyline`, `view.automata`,
  `view.dialogue_chat`.
* Headless-запуск без окна:

  ```bash
  SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy venv/bin/python -m ui --scene menu
  ```

* Чекпойнты без окна: `venv/bin/python main.py --list-checkpoints`.
* Точечные тесты быстрее полного прогона:

  ```bash
  venv/bin/python -m pytest -q tests/test_gui_smoke.py
  venv/bin/python -m pytest -q tests/test_automata_campaign.py
  venv/bin/python -m pytest -q tests/test_campaign.py
  venv/bin/python -m pytest -q tests/test_d4_social.py
  venv/bin/python -m pytest -q tests/test_d5_discourse.py
  venv/bin/python -m pytest -q tests/test_d5_registers.py
  venv/bin/python -m pytest -q tests/test_d5_discourse_paragraph.py
  venv/bin/python -m pytest -q tests/test_d3_comparison.py
  ```

### 5.9. «Хочу понять диалог с агентами»

Читайте [`DIALOGUE_NLG.md`](DIALOGUE_NLG.md) и
[`CHAT_STYLES_PLAN.md`](CHAT_STYLES_PLAN.md). Кратко:

* диалог — read-only слой над BDI и кампанией, без LLM и статистики;
* диалог полностью Data-Driven: онтология, лексикон, грамматика, правила
  вывода, планы, политики состояния, конструкции синтеза, стили,
  `style_context`, `discourse`, `comparison`, `counterfactual`, `social`
  лежат в `configs/dialogue/`, Python только интерпретирует их;
* проверка D0–D5.4:

  ```bash
  venv/bin/python -m campaign.dialogue.lint
  venv/bin/python -m campaign.dialogue.repl --side red --ask "Почему Империя считает Республику незаконной?"
  venv/bin/python -m campaign.dialogue.repl --side blue --ask "Кто правит Республикой?" --debug
  venv/bin/python -m pytest -q tests/test_dialogue.py \
    tests/test_d1_dialogue.py tests/test_d1_5_synthesis.py \
    tests/test_d2_state.py tests/test_d3_comparison.py \
    tests/test_d5_discourse.py tests/test_d5_discourse_paragraph.py \
    tests/test_d5_registers.py tests/test_d4_social.py
  ```
* вход: свободная русская фраза → нормализация → морфология →
  грамматический разбор → типизированная логическая форма;
* связность: `campaign/dialogue/state.py` ведёт QUD, активных референтов
  и память по политике `configs/dialogue/state.json`; короткие реплики
  («А у Республики?», «Почему?», «А он?») восстанавливаются из
  предыдущего хода;
* содержание: неизменяемый снимок знания агента → логический вывод с
  трассировкой;
* ответ: план выбирает смысл → конструкция из `synthesis.json` →
  композиционный синтез (`realize.py`) → словоформы (`morph.py`,
  словарный `pymorphy3`, не нейросеть);
* **D5.1 — дискурсивный планировщик**: `discourse.json` (moves,
  patterns, connectives), `_discourse` в `answers.py`,
  `render_moves` в `realize.py`. Нейтральный стиль не разбивает ответ
  на ходы;
* **D5.2 — автовыбор регистра**: `style_context.json` (rules с
  `fact`/`field`-условиями), `StyleEngine.resolve_for_context`.
  Явный стиль игрока побеждает правила. `DialogueSession(style_id=None)`
  = авто-режим; экран чата `DialogueChatScreen` авто-режим не
  показывает и всегда передаёт выбранный вручную стиль;
* **D5.3 — агрегация, анафора, тема-рема**: `discourse.connectives
  [].mode: plain|clause`, `discourse.patterns[].topic`,
  `discourse.anaphora` (типы, виды ходов, местоимения, min_length);
* **D5.4 — абзац 4+ хода**: `DiscoursePattern.topics`, порядок
  `topics → topic → moves` в `_ordered_moves`, флаги `detail` и
  `connectives`, линтер `_discourse_problems`. Production-паттерн
  `explanation_detailed` включается просьбой «Подробнее» или
  уточнением «Почему?»; тесты — `test_d5_discourse_paragraph.py`
  и `test_d5_discourse_detail.py`;
* **D3.1 — сравнения**: `comparison.json` (relation, args,
  key_prefix, конструкции исходов), `_answer_comparison` без
  `if a > b`. Расширенное «почему» через `max_premises` в плане;
* **D3.2 — контрфакты**: `counterfactual.py`
  (`CounterfactualEngine.with_facts`/`compare`/`_differences`),
  `counterfactual.json` (whitelist `belief`/`asset`/`at_war_with`/
  `considers_outlaw`/`has_organ`, `max_steps`, `outcomes`), планы
  `cf_explain`, `cf_explain_with` и `cf_explain_yesno`; грамматика
  `s_counterfactual*` включая consequent и past forms. Разбираются
  «Что если …?», «Что, если бы …?», «Что было бы, если бы …?» и
  «…, то …». `world.predicate_relations` резолвит предикат разбора в
  отношение мира, поэтому `believe`, `have` и `fight` дают `changed`;
* **D6.2a–c — отрицание, следствие и маппинг предикатов**:
  `part:not` в `NEG`, правила `np_neg_v_np*`, `negated: true` и обмен
  `remove`/`add`; `concept:then` и `consequent` как цель сравнения;
  `predicate_relations` с исходным фактом `remove` для производных
  отношений. Тесты — `tests/test_d3_counterfactual.py`;
* **D6.2d — условия, уступки, речь и beam**:
  `s_conditional` (`если … то …`), `s_concessive` (`хотя …`,
  «несмотря на»), `s_indirect_speech` (`NP сказал, что S`),
  `s_direct_speech` (цитата в «…»), лексемы `concept:although`/
  `concept:despite`/`concept:that`/`quote:*`/`verb:say`; beam —
  `parsing.json` (`beam_width`, `kind_priority`, `prefer_depth`);
  корпус парафраз — `paraphrases.json`.
  Тесты — `tests/test_d6_grammar.py`, `tests/test_d6_parse_beam.py`
  и `tests/test_d6_paraphrases.py`;
* **D6.3 — политика раскрытия и ложь**: `disclosure.json` с политиками
  `honest/partial/withhold/evasive/lie`, `disclosure` и
  `lie_probability` у персоны, SHA-256-бросок от seed/хода/темы,
  трассировка `lied`/`truth_text` в `Answer.data`. Тесты —
  `tests/test_d6_disclosure.py`;
* речевые действия: `social.json` — акты (`command/promise/threat/
  offer/apology`), реакции (`accept/reject/evade/counter/clarify`),
  условия (`AtomSpec`), эффекты (`commitment/refusal/evasion/
  counter_offer/clarification`). В игровом чате фраза-приказ для своей
  стороны идёт через `DialogueSession.act`: мост проверяет доступное
  действие и исполняет его в кампании, а при отказе возвращает причину.
  Обычный вопрос всегда идёт через `respond` и не меняет мир;
* память: `DialogueMemoryStore` хранит значимые факты и сводки по
  агентам в блоке `dialogue` сейва версии 3;
* расширение: новое отношение, тип, лексема, конструкция, фраза,
  словоформа, фрагмент эллипсиса, речевой акт, стиль, правило
  автовыбора, связка, ход, сравнение, отношение контрфакта добавляются
  JSON-ом;
* отладка: `--debug` печатает план, логическую форму и дерево вывода;
  `Answer.data["discourse_trace"]` — трасса дискурсивного слоя
  (`connective`/`anaphora`); `Answer.data["social_trace"]` — трасса
  речевого действия;
* статус: **D0, D1, D1.5, D2, D3.1, D3.2, D4, D5.1–D5.4, D6.1,
  D6.2a–d, D6.3, D6.4, D7.0–D7.4 — сделаны**. Открыто: расширение
  доменных псевдонимов и runtime-хук стилевых подсказок;
  `has_leverage`/`blackmail` закрыты.

Связанные документы: открытые задачи диалога —
[`TODO.md`](TODO.md), архитектура —
[`DIALOGUE_NLG.md`](DIALOGUE_NLG.md) (история фаз D0–D7 —
[`history/DIALOGUE_NLG_PHASES.md`](history/DIALOGUE_NLG_PHASES.md)),
стилевой слой — [`CHAT_STYLES_PLAN.md`](CHAT_STYLES_PLAN.md).

### 5.10. «Хочу проверить, что ничего не сломал»

```bash
venv/bin/python -m pytest -q
venv/bin/python -m campaign.dialogue.lint
venv/bin/python -m pycodestyle $(git ls-files '*.py')
git diff --check
```

Для GUI-изменений дополнительно:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  venv/bin/python -m pytest -q tests/test_gui_smoke.py tests/test_ui.py
```

Для контента:

```bash
venv/bin/python -m pytest -q tests/test_content_pipeline.py tests/test_docs_sync.py
```

Для диалога:

```bash
venv/bin/python -m campaign.dialogue.lint
venv/bin/python -m pytest -q tests/test_dialogue.py \
  tests/test_d1_dialogue.py tests/test_d1_5_synthesis.py \
  tests/test_d2_state.py tests/test_d3_comparison.py \
  tests/test_d5_discourse.py tests/test_d5_discourse_paragraph.py \
  tests/test_d5_registers.py tests/test_d4_social.py
```

---

## 6. Карта тестов

| Область | Файлы | Что проверяют |
|---|---|---|
| Канон `simulation.py` | `test_canon.py`, `test_checks.py`, `test_math_model.py` | воспроизводимость, инварианты, скрипты-проверки |
| Ядро 4-2-1 и арена | `test_core41.py`, `test_clock.py`, `test_health.py`, `test_sickness.py`, `test_environment.py` | энергия/сила/здоровье, болезнь, раны, часы, среда |
| Войсковые автоматы | `test_warfare.py`, `test_lore_characters.py` | персонажи, потребности, черты, отделения, мораль |
| Границы архитектуры | `test_architecture_boundaries.py` | в `campaign/` нет верхнеуровневых импортов `warfare`/`simulation`; `campaign.automata` не грузит `warfare` |
| Дневной мир | `test_world.py`, `test_campaign_env.py`, `test_campaign_planner.py`, `test_campaign_clock.py`, `test_campaign_energy.py` | `WorldEngine`, `CampaignEnv`, планировщик, время |
| Кампания автоматов | `test_automata_campaign.py`, `test_identity.py` | работы, кулдауны, исходы, органы, личность, кодекс, детерминизм, снимки |
| Доклады и вести | `test_campaign_dispatch.py`, `test_campaign_reports_overlay.py`, `test_campaign_overlays.py` | очередь докладов, искажение, выбор игрока, память источника, слухи, перехваты и контрмеры |
| Рутина, метрики, аудит | `test_campaign_routine.py`, `test_campaign_stats.py`, `test_domain_audit.py` | суточная рутина BDI, `CampaignStats`, качественные уровни, сводки |
| Work и схемы контента | `test_world_work.py`, `test_action_processes.py`, `test_content_lint.py`, `test_content_schema.py` | единый Work-путь, процессы действий, семантический линтер и JSON Schema |
| Восприятие и провенанс | `test_perception.py`, `test_provenance.py`, `test_items.py`, `test_free_clock.py` | видимость, источник знаний, предметы-автоматы, свободные часы |
| Диалог D0 | `test_dialogue.py` | онтология, лексикон, грамматика, golden-разборы, JSON-only расширение |
| Диалог D1 | `test_d1_dialogue.py` | вопросы о мире, доказательства, незнание, детерминизм, read-only |
| Диалог D1.5 | `test_d1_5_synthesis.py` | композиционный синтез, морфология, расширяемость JSON-ом |
| Диалог D2 | `test_d2_state.py` | QUD, местоимения, эллипсис, память партии, сейв |
| Диалог D3.1 (сравнения) | `test_d3_comparison.py` | greater/less/equal/unknown, key_prefix, max_premises |
| Диалог D3.2 (контрфакты) | `test_d3_counterfactual.py` | исходы, whitelist, read-only, `predicate_relations`, consequent |
| Диалог D4 | `test_d4_social.py` | акты, реакции, условия, эффекты, `commitments`, JSON-only расширение |
| Диалог D5.1 | `test_d5_discourse.py` | moves, patterns, connectives, нейтральный путь, антиповтор связок |
| Диалог D5.2–D5.3 | `test_d5_registers.py` | регистры, автовыбор по контексту, явный стиль побеждает, пустой каталог |
| Диалог D5.3–D5.4 | `test_d5_discourse_paragraph.py` | mode plain/clause, анафора, тема-рема, `topics` и порядок 4+ ходов |
| Диалог D6.2a–c | `test_d3_counterfactual.py` | разбор `NEG`, обмен `remove`/`add`, «то»-клауза, маппинг предикатов |
| Диалог D6.2d | `test_d6_grammar.py`, `test_d6_parse_beam.py`, `test_d6_paraphrases.py` | условия, уступки, косвенная/прямая речь, beam, корпус парафраз, JSON-only, детерминизм |
| Диалог D6.3 | `test_d6_disclosure.py` | политики, исходы, детерминированная ложь, тема, read-only |
| Диалог D6.4 | `test_d6_planner.py`, `test_d6_bridge.py`, `test_d6_actions.py` | цели из JSON, порядок шагов, проверки `done`/`blocked`, мост выключен по умолчанию, реальное действие, read-only `ask`, императивы и псевдонимы действий |
| Диалог D6.1 | `test_d6_lexicon.py` | псевдоним не дублирует собственную форму, линтер замечает дубль, полезные псевдонимы сохранены |
| D7.0 (текстовик) | `test_d7_console.py` | история, откат диалога и кампании, подсказки из данных, команды и лимит истории |
| D7.1 (social-действия) | `test_d7_social.py` | `interaction` у актов, пять interactions кампании, гейты authority/trusts, actions_disabled, TextGame-маршрутизация, откат |
| D7.2 (перемещение) | `test_d7_movement.py` | `movement.json`, разбор `move`, маршрут и band по геометрии игрока, read-only, `already`/unknown/no path, TextGame и откат локации |
| D7.3 (время) | `test_d7_time.py` | `time.json`, разбор `wait`/`speed`, ожидание и фазы суток, множитель темпа, лимиты, read-only, TextGame и откат времени |
| D7.4 (описание) | `test_d7_narrator.py` | `narrator.json`, видимость story, работы из `log` без дубля, виды событий, fallback, важность/формы/исходы, лимит и хронология, read-only, `/look` |
| GUI `view/` | `test_gui_smoke.py`, `test_campaign.py`, `test_view_world.py`, `test_view_rts.py`, `test_view_strategy.py` | живой цикл, экраны, навигация, отрисовка |
| GUI `ui/` | `test_ui.py`, `test_battlefield.py` | сцены, пауза, сейвы, RTS-логика |
| Контент | `test_content_pipeline.py`, `test_story_arcs.py`, `test_docs_sync.py` | загрузка/правка/удаление JSON, ссылки |
| Агенты | `test_train_cli.py`, `test_checkpoints.py`, `test_health.py`, `test_sickness.py` | CLI, чекпойнты, политики |
| Инструменты | `test_automata.py`, `test_automata_ui.py`, `test_naming.py`, `test_people.py`, `test_organizations.py`, `test_systems.py`, `test_interaction.py` | редактор, имена, организации, системы, взаимодействия |
| Сейвы и долгие прогоны | `test_save_system.py`, `test_soak.py` | миграции, совместимость, длинная игра |

`tests/conftest.py` подменяет production-контент на
`tests/fixtures/content/`. Если тест должен читать production-конфиг,
он делает это явно.

---

## 7. Карта документации

| Документ | Когда читать |
|---|---|
| [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) | первый; цель, онтология, приоритет решений |
| [`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md) | детализация целевой модели 4-2-1 |
| [`history/MODEL.md`](history/MODEL.md) | историческая спецификация легаси-`simulation.py`, константы |
| [`history/BASELINE.md`](history/BASELINE.md), [`history/DESIGN_ADVANCED.md`](history/DESIGN_ADVANCED.md) | исторические базовая линия и дизайн lossy/LOD/энтропии |
| [`WARFARE.md`](WARFARE.md) | персонажи, потребности, черты, отделения |
| [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md) | современный клиент `view/`, кампанийные потоки |
| [`history/UI.md`](history/UI.md) | исторический легаси-клиент `ui/`, сцены, сейвы, RTS |
| [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) | кампании четырёх фракций-автоматов, конвейер работы и правила обработчика |
| [`history/WORK_MECHANIC_GAP.md`](history/WORK_MECHANIC_GAP.md) | исходный GAP-анализ работы как сообщения и статус закрытия (§0.1) |
| [`WORK_MECHANIC_PLAN.md`](WORK_MECHANIC_PLAN.md) | статус и остаток миграции работы |
| [`AUTOMATA_GEOMETRY.md`](AUTOMATA_GEOMETRY.md) | семантическая геометрия: метрический граф, локальные углы, пути |
| [`CONTENT.md`](CONTENT.md) | JSON-контент, загрузчики, добавление/правка |
| [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md) | BDI, 15 делений, события и производные активы фракции |
| [`DATA_DRIVEN_CORE_GAPS.md`](DATA_DRIVEN_CORE_GAPS.md) | только открытые GAP-пункты; полный аудит — в `history/` |
| [`DATA_DRIVEN_CORE_PLAN.md`](DATA_DRIVEN_CORE_PLAN.md) | только открытые фазы; полный план — в `history/` |
| [`DIALOGUE_NLG.md`](DIALOGUE_NLG.md) | диалог без LLM: архитектура, разбор, синтез, эпистемика |
| [`CHAT_STYLES_PLAN.md`](CHAT_STYLES_PLAN.md) | стилевой слой: регистровый профиль, автовыбор, дискурс |
| [`CONTENT_PLAN_LORE.md`](CONTENT_PLAN_LORE.md) | контент-план по `лор.pdf`: предикаты, сути, работы, автоматы |
| [`AGENTS.md`](AGENTS.md), [`ALGORITHMS.md`](ALGORITHMS.md) | политики, обучение, формулы, чекпойнты |
| [`AUTOMATA.md`](AUTOMATA.md) | редактор автоматов |
| [`ORGANIZATIONS.md`](ORGANIZATIONS.md), [`NAMING.md`](NAMING.md), [`SYSTEMS.md`](SYSTEMS.md), [`INTERACTION.md`](INTERACTION.md) | профильные инструменты и слои |
| [`WORLD.md`](WORLD.md), [`history/STRATEGY.md`](history/STRATEGY.md) | мир должностного лица и легаси-стратегия |
| [`SUMMARY.md`](SUMMARY.md) | сжатая карта, но проверяйте по коду |
| [`TODO.md`](TODO.md) | что открыто и что делать дальше |
| [`HOWTO.md`](HOWTO.md) | практические команды: игра, обучение, вклад |

---

## 8. Инварианты и запреты

* `.gitignore` содержит правило для PDF (`лор.pdf` и подобные) — не
  удалять его.
* Работа кампании идёт одним путём: capability → `campaign/work.py` →
  `campaign/handlers.py` → `WorkReport` → `campaign/effects.apply_report`.
  Не добавляйте `effects`/`failure` обратно в capability: эффект живёт в
  `configs/campaigns/base/handlers/*.json`.
* `simulation.py` — легаси-baseline: не менять его поведение без
  обоснования и обновления `history/BASELINE.md`/`test_canon.py`.
* `core41/` — целевое ядро; изменения физики арены требуют тестов и
  калибровки.
* `campaign/` — дневной мир; не переписывайте аренные константы ради
  кампанийных правил.
* `campaign/dialogue/` — диалоговый слой; правила Data-Driven
  обязательны. Новый акт, реакция, конструкция, фраза, стиль, правило
  автовыбора, связка, ход, сравнение или лексема добавляются JSON-ом;
  Python только интерпретирует. LLM, эмбеддинги, статистическое
  ранжирование запрещены. 16 потребностей в
  `configs/characters/bdi.json` не трогать. `realization.json` — только
  аварийный fallback.
* `configs/` — данные. Новый контент не должен требовать правки кода, если
  для него уже есть загрузчик.
* Детерминизм по seed — часть контракта; не добавляйте необоснованный
  `random`/время в игровые расчёты.
* Сохранения версионируются; изменение формы снимка требует миграции и
  теста.
* Публичные модули и функции — с docstrings; стиль — `black`/`pycodestyle`,
  длина строки 79.

---

## 9. Чек-лист первого дня

- [ ] `venv/bin/python main.py` открывает главное меню.
- [ ] «Новая игра» → роль → новелла → кампания автоматов.
- [ ] «СВЯЗЬ» открывает чат, агент отвечает, стиль меняется.
- [ ] После работы в ленте появляется эпизод хроники, а финал содержит
  счёт, пороги и решающие эпизоды.
- [ ] «Дуэль (арена)» открывается и возвращает в меню по `ESC`.
- [ ] `venv/bin/python main.py --automata` открывает редактор.
- [ ] `venv/bin/python main.py --classic` открывает легаси-меню.
- [ ] `venv/bin/python main.py --list-checkpoints` работает без окна.
- [ ] `venv/bin/python -m campaign.dialogue.lint` печатает
  «диалоговые данные в порядке».
- [ ] `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy venv/bin/python -m pytest -q
  tests/test_gui_smoke.py` проходит.
- [ ] `venv/bin/python -m pytest -q` проходит (или вы понимаете, какие
  падения уже существуют).
- [ ] Вы знаете, где лежит нужный вам слой по §3.2, и какой документ
  читать по §7.

Если потребность не покрыта таблицей §2, начните с §3.2: определите слой
(ядро, кампания, диалог, войска, GUI, контент, агенты), затем откройте
профильный документ из §7 и соответствующий тест из §6. Это самый короткий
путь к нужному коду.
