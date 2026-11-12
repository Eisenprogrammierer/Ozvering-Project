# Онбординг: карта проекта по потребностям

> **Роль документа.** Это навигационная карта для первого входа в
> `Ozvering-Project`: что запускать, где лежит нужный слой, какие тесты и
> документы читать. Документ не заменяет канон и спецификации, а помогает
> быстро найти нужный из них.
>
> **Дата сверки:** 2026-11-09. Проверялось по коду, тестам и фактическому
> headless-запуску, а не только по README. Если документ расходится с кодом,
> доверяйте коду и тестам; расхождение лучше сразу исправлять.
>
> **Источник истины:** [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md). Порядок
> приоритетов документов описан в его начале.

---

## 1. За пять минут: запустить и увидеть игру

Все команды выполняются из корня репозитория.

### 1.1. Окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
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
   (`actions_per_turn`, по умолчанию 3); работа или влияние на сеть тратят
   одно действие, а восстанавливаются они со временем. Одноразовые работы
   после выполнения показывают «уже выполнено», работы с лимитом —
   «исчерпано», а условия вроде «сначала нужно: …» видны прямо в списке.
8. «Кодекс» показывает всех персонажей и автоматы, включая органы фракций.
   У записи своей фракции внизу карточки есть кнопки действий: персонажа
   можно повысить, наградить, поддержать или допросить, орган — усилить,
   реформировать, почистить или снабдить. Действие тратит одно действие
   бюджета и применяется сразу. Собственного персонажа усилить нельзя —
   такие действия показывают причину «нельзя применять к самому себе».
9. «Сеть» открывает сетку органов своей фракции, связанных полем
   `links`: `Панцерваффе ↔ Вермахт ↔ Имперская ставка` — это соседство, а
   не вертикаль подчинения; выбранный узел подсвечивает себя и соседей.
   На вкладке «АВТОМАТЫ» выбранный орган отдаёт команду другому автомату
   (цель выбирается кликом по узлу), на вкладке «ВЛИЯНИЕ» можно усилить
   орган, на вкладке «ПЕРСОНАЛ» — повлиять на человека. Клик по органу из
   «ПЕРСОНАЛА» возвращает на «ВЛИЯНИЕ». Чужие фракции в сети недоступны.
   Каждое взаимодействие или команда стоит одно действие; отдельной кнопки
   завершения хода нет.
10. Жёсткого лимита ходов нет. Кампания идёт непрерывно и заканчивается,
    когда срабатывает порог поражения или устойчивое преимущество по
    прогрессу (`score_after` + `score_streak`), после чего показывается
    сюжетная сцена.

«Продолжить» в главном меню открывает только совместимые сохранения —
автоматы, стратегию или мир. Легаси-военные снимки пропускаются: игра не
перебрасывает игрока на старую карту «Долина-1».

Проверено headless-прогоном: меню → выбор роли → редактор личности →
новелла → `AutomataScreen`, затем прогон с бюджетом действий,
кодекс, сеть и отрисовка без исключений. Автотесты этого пути —
`tests/test_identity.py`, `tests/test_campaign.py`,
`tests/test_automata_campaign.py`.

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
| «Хочу запустить конкретный режим» | §1.4, [`UI.md`](UI.md), [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md) | `main.py` | `tests/test_ui.py` |
| «Хочу понять модель мира» | §5.1, [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) | `core41/`, `campaign/`, `simulation.py`, `warfare.py` | `tests/test_core41.py`, `tests/test_canon.py` |
| «Хочу понять формулы» | [`FORMULAS.md`](FORMULAS.md) | `core41/model.py`, `core41/arena.py`, `campaign/` | `tests/test_math_model.py`, профильные тесты |
| «Хочу править контент без кода» | §5.2, [`CONTENT.md`](CONTENT.md) | `configs/` | `tests/test_content_pipeline.py` |
| «Хочу править современный GUI» | §5.3, [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md) | `view/` | `tests/test_gui_smoke.py`, `tests/test_view_*.py` |
| «Хочу править легаси-GUI» | §5.3, [`UI.md`](UI.md) | `ui/` | `tests/test_ui.py` |
| «Хочу менять кампанию автоматов» | §5.4, [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) | `campaign/automata.py`, `campaign/fractal.py`, `campaign/geometry.py`, `configs/campaigns/` | `tests/test_automata_campaign.py`, `tests/test_automata_network.py`, `tests/test_geometry.py` |
| «Хочу обучить агента» | §5.6, [`AGENTS.md`](AGENTS.md), [`HOWTO.md`](HOWTO.md) §2 | `agents/`, `core41/` | `tests/test_train_cli.py` |
| «Хочу добавить механику» | §5.5 | слой по §3.2 | профильные тесты |
| «Хочу понять сейвы» | §5.7 | `view/support/save_system.py` | `tests/test_save_system.py` |
| «Хочу проверить, что ничего не сломал» | §5.9 | `tests/` | `pytest -q` |

---

## 3. Где что лежит

### 3.1. Точка входа и клиенты

`main.py` — единая точка входа. Она только разбирает флаги и передаёт
управление одному из приложений.

| Путь | Что это | Роль |
|---|---|---|
| `main.py` | диспетчер запуска | флаги → `view/`, `ui/`, `game_engine`, `automata/` |
| `view/` | современный клиент | меню, роли, новелла, документ, кампания автоматов, мир, RTS, сейвы |
| `ui/` | легаси-клиент | сценный слой: меню, нарратив, арена, RTS, взаимодействия, пауза |
| `game_engine.py` | автономная арена | `core41`-дуэль + HUD, встраивается в `view/` |
| `automata/` | редактор автоматов | граф состояний/переходов, JSON-хранилище, без игровой модели |
| `core41/` | целевой срез 4-2-1 | арена, дуэль, здоровье/болезнь/раны, часы, среда |
| `campaign/` | дневной мир и кампания | роли, пресеты, `WorldEngine`, `CampaignEnv`, `AutomataCampaign`, сеть органов `fractal.py`, производные активы `faction_state.py`, сейвы |
| `agents/` | обучаемые политики | BDI/QTable/MLP, чекпойнты, `agents.train` |
| `warfare.py` | войсковые автоматы | персонажи, отделения, станы, приказы, мораль, черты |
| `simulation.py` | легаси-канон дуэлей | воспроизводимый baseline, не активный игровой поток |

### 3.2. Слои и зависимости

Упрощённо:

```text
main.py
  ├─ view/        современный GUI + сюжет
  │    ├─ campaign/  мир, пресеты, кампания автоматов
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
* `warfare.py` — персонажи и отделения; кампания автоматов использует его
  для состава фракций и организаций.
* `view/` и `ui/` — представление и ввод. Логику лучше держать в чистых
  модулях (`campaign/`, `ui/battlefield.py`, `interaction/`), а экран — тонким.
* `configs/` — данные, а не код. Новый контент по возможности добавляется
  JSON-файлом и загрузчиком, без новой ветки `if` в Python.

### 3.3. Контент: что уже есть в поставке

Состояние может меняться; перед правкой смотрите сам каталог.

| Путь | Содержимое | Загрузчик |
|---|---|---|
| `configs/roles/roles.json` | четыре роли лорных кампаний | `campaign.roles.RoleCatalog` |
| `configs/storylines/*.json` | сюжеты четырёх фракций и их сцены | `view.support.storyline` |
| `configs/campaigns/*.json` | шаблоны кампаний автоматов | `campaign.preset` |
| `configs/content/*.json` | приказы, документы, диалоги, время | `view.support.content.Content` |
| `configs/characters/traits.json` | 12 черт, архетипы, влияние | `character_traits.load_traits()` |
| `configs/systems/*.json` | среда, события, драматург | `systems.*` |
| `configs/naming/*.json` | лексикон и имена | `naming.*` |
| `configs/worlds/` | миров пока нет (только `.gitkeep`) | `campaign.world.load_world()` |
| `configs/automata/*.json` | графы автоматов для редактора (схема 1) | `automata.storage.AutomataStore` |
| `configs/campaigns/base/automata/*.json` | исполняемые автоматы фракций и органов (схема 2) | `campaign.state_machine` |
| `configs/strategy/`, `configs/environments/`, `configs/presets/`, `configs/classes/`, `configs/view/` | пусто (`.gitkeep`) | соответствующие загрузчики |

Тестовый набор контента лежит отдельно: `tests/fixtures/content/`.
`tests/conftest.py` подменяет рабочие каталоги на фикстуры, поэтому тесты
не зависят от production-сюжетов. Если нужен пример мира для быстрой
кампании, смотрите `tests/fixtures/content/configs/worlds/agora_world.json`,
но не считайте его production-контентом.

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
* Групповой прогон GUI-тестов на 2026-11-05: **128 passed**:
  `pytest -q tests/test_gui_smoke.py tests/test_ui.py
  tests/test_view_world.py tests/test_view_rts.py
  tests/test_view_strategy.py tests/test_campaign.py`.
* Полный путь «Новая игра → роль → новелла → кампания автоматов →
  бюджет действий → сеть → исход» исполнен headless без исключений.

### 4.2. Что играется сейчас

* Главное меню `view/`: новая игра, продолжение, быстрая кампания, арена,
  сохранения, настройки, выход.
* Четыре лорные кампании через `configs/roles/roles.json` и
  `configs/storylines/`: Империя, Республика, Культ Земли, Торговая планета.
* Визуальная новелла, экран кампании автоматов с работами,
  ценой, шансами, журналом и исходом.
* Арена `game_engine` и редактор автоматов.
* Легаси-клиент `ui/` со сценами меню, нарратива, поля боя, взаимодействий,
  паузы и сохранений.

### 4.3. Известные ограничения

* **Быстрая кампания из меню не работает без мира.** В поставке
  `configs/worlds/` пуст, поэтому экран показывает:
  «Добавьте мир в configs/worlds/*.json». Основной путь «Новая игра» от
  этого не зависит: он идёт через кампании автоматов.
* **Ассеты — плейсхолдеры.** `configs/view/presentation.json` в поставке
  отсутствует, поэтому `AssetLoader` использует процедурные заглушки;
  реальные JPG/PNG не обязательны для запуска.
* **Нет экрана «Как играть».** Правила и горячие клавиши не объясняются
  внутри `view/`; это задача B3 из [`RELEASE_READINESS.md`](RELEASE_READINESS.md).
* **Настройки `view/` не применяются полностью.** Часть тумблеров меняет
  локальные флаги, но не сохраняется/не влияет на звук, полный экран и
  анимации (B7).
* **Сейвы и лог пишутся в дерево репозитория** (`saves/`,
  `operation_ozverin.log`), а не в пользовательский data-dir (D6).
* **Схема сейва `view/` версионируется, но миграции ограничены.**
  Проверяйте `SAVE_VERSION` и тесты при изменении снимка.
* **Баланс и полировка — первый срез.** Кампания автоматов проходится, но
  субъективный баланс, читаемость HUD и длинная прогрессия ещё не
  откалиброваны как «игра для игрока».
* **Статусы документов различаются.** README, SUMMARY, SYSTEMS, WORLD и
  этот документ сверены с поставкой 2026-11-09: в `configs/` уже есть роли,
  сюжеты, кампании, среда/события/драматург и имена; пусты только
  `configs/worlds/`, `configs/strategy/`, `configs/environments/`,
  `configs/presets/`, `configs/classes/` и
  `configs/view/`. `docs/code/*` — исторические снимки, а `CAMPAIGN_UI.md`
  содержит и текущий поток, и легаси-разделы; их числа относятся к своим
  датам. Для текущего состояния сверяйтесь с
  [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md), кодом и `configs/`.

---

## 5. Маршруты по задачам

### 5.1. «Хочу понять модель»

Порядок чтения:

1. [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) — цель, онтология 4-2-1,
   принятые решения и границы.
2. [`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md) — детализация целевой
   модели мира.
3. [`MODEL.md`](MODEL.md) — текущий легаси-канон `simulation.py`.
4. [`WARFARE.md`](WARFARE.md) — персонажи, потребности, черты, отделения,
   мораль и паника.
5. [`ALGORITHMS.md`](ALGORITHMS.md) — точные формулы арены, признаки
   политик, TD(0), чекпойнты.
6. [`SUMMARY.md`](SUMMARY.md) — сжатая карта, но проверяйте её по коду.

Код:

* `core41/model.py`, `core41/arena.py`, `core41/duel.py` — целевое ядро и
  арена;
* `warfare.py` — войсковые автоматы;
* `simulation.py` — легаси-канон, не активный игровой поток;
* `campaign/world.py` — дневной мир должностного лица (библиотечный модуль;
  запуск игры — `main.py --view`, не `python3 campaign/world.py`);
* `campaign/automata.py` — кампания фракций-автоматов.

Тесты-опоры: `test_core41.py`, `test_canon.py`, `test_warfare.py`,
`test_campaign_env.py`, `test_math_model.py`.

### 5.2. «Хочу править контент без кода»

Начните с [`CONTENT.md`](CONTENT.md). Типовые действия:

* новая роль — `configs/roles/*.json`;
* новый сюжет — `configs/storylines/<id>.json` + `_scenes.json`;
* новая кампания автоматов — `configs/campaigns/<id>.json` и запись роли
  со ссылкой `storyline_id`;
* общие фракции, органы и работы — `configs/campaigns/base/lore_factions.json`;
* варианты личности героя — `configs/characters/identity.json`
  (происхождение, призвание, ценность, слабость, пол);
* новый мир — `configs/worlds/*.json` (сейчас каталог пуст);
* новый автомат для редактора — `configs/automata/*.json`;
* события/среда/драматург — `configs/systems/*.json`;
* имена — `configs/naming/*.json`;
* черты персонажей — `configs/characters/traits.json`.

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
| современный | `view/` | основной игровой путь, кампании, новые экраны |
| легаси | `ui/` | старые сцены, RTS, взаимодействия, совместимость |
| арена | `game_engine.py` | автономная дуэль и HUD |
| редактор | `automata/` | графовый редактор автоматов |

Каркас современного экрана:

1. Создайте `view/screens/my_screen.py`, наследник
   `view.ui.screen_manager.BaseScreen`.
2. Реализуйте `draw(screen)`, при необходимости `handle_event(event)`,
   `update(dt)`, `on_escape()`.
3. Зарегистрируйте переход в `view/app.py` или в существующем экране.
4. Добавьте headless-тест: конструктор, `draw` на `pygame.Surface`,
   навигация и один-два клика/события.
5. Если экран должен получать HUD времени, выставьте `show_time_hud`;
   если нет — `hide_time_hud`/`show_time_hud = False`.

Легаси-экран устроен похоже, но через `ui.scene.Scene` и
`ui.scene.SceneManager`; см. [`UI.md`](UI.md).

Тесты:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  venv/bin/python -m pytest -q tests/test_gui_smoke.py
venv/bin/python -m pytest -q tests/test_ui.py
```

### 5.4. «Хочу менять кампанию автоматов»

Читайте [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md).

* Шаблон кампании: `configs/campaigns/<id>.json` — фракции, `scenario.mode:
  "automata"`, `actions_per_turn`, модель успеха, условия исхода, среда,
  события. Жёсткого `turns` у production-кампаний нет.
* Данные автоматов: `configs/campaigns/base/automata_defaults.json` —
  базовые потребности и мораль персонажей, формулы и драйверы производных
  активов (`faction_state`), модель органов, статусы, взаимодействия,
  бюджет действий, интервалы реального времени и скорости.
  Ядро (`campaign/automata.py`, `campaign/fractal.py`,
  `campaign/faction_state.py`, `campaign/preset.py`) читает эти значения
  через `campaign/defaults.py`; шаблон может переопределить их через
  `scenario.realtime` и `scenario.model`.
* BDI, деления и события: `configs/characters/bdi.json` (16 желаний,
  убеждения и намерения), `configs/characters/divisions.json` (15 делений),
  `configs/systems/events.json` (условия, вероятность, видимость).
  Загрузчики — `bdi.py`, `campaign/divisions.py`, `systems/events.py`;
  персонажи кампании получают BDI-состояние через `warfare.Character`.
* Роль: `configs/roles/roles.json` — `storyline_id` связывает роль с
  сюжетом.
* Сюжет: `configs/storylines/<id>.json` и `_scenes.json` — новелла и
  `gameplay`, флаг `identity_editor`. Лорные сюжеты не содержат сцен
  `document`: руки и чтение задания удалены, остались новелла и кампания.
* Личность героя: `configs/characters/identity.json`, загрузчик
  `campaign/identity.py`, экран `view/screens/identity_editor.py`.
  Женский пол выбирает `role_title_female`/`leader_title_female`
  («императрица», «председательница парламента», «верховная жрица»,
  «генеральная директриса») и пробрасывает `{player_role_title}` в сцены.
* Логика: `campaign/automata.py` (`AutomataCampaign`, работы, кулдауны,
  бюджет действий, исходы, взаимодействия с органами, персонажами и
  команды автоматов друг другу), `campaign/fractal.py` (целостность и
  связи органов, `links`, downscale/upscale, урон),
  `campaign/geometry.py` (метрический граф без глобальных осей, локальные
  углы, кратчайшие пути, `distance`/`angle` в условиях),
  `campaign/faction_state.py` (производные активы, контекст, драйверы),
  `view/screens/automata_screen.py` (основной экран с описанием выбранной
  работы), `view/screens/automata_network.py` (сетка своей фракции,
  вкладки «АВТОМАТЫ»/«ВЛИЯНИЕ»/«ПЕРСОНАЛ»).
* Пресет: `campaign/preset.py` строит фракции, персонажей, организации,
  органы-автоматы со связями, описания работ и формы титула.
* Кодекс: `view/screens/campaign_codex.py` — просмотр собранного пресета
  и прямые действия по записям своей фракции.

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
   кампании), `warfare` (персонажи/отделения), `view`/`ui` (только
   представление).
2. Сформулируйте инвариант и напишите тест до реализации. Для модели —
   `tests/test_math_model.py`/`test_core41.py`; для кампании —
   `test_campaign_env.py`/`test_world.py`; для GUI — `test_gui_smoke.py`.
3. Если поведение должно быть data-driven, сначала добавьте поле/схему в
   JSON и загрузчик, затем код.
4. Обновите профильный документ и, если меняются константы, `MODEL.md`/
   `ALGORITHMS.md` (это ловит `test_docs_sync.py`).
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

# дневная кампания (в поставке configs/worlds/ пуст, поэтому --world)
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

* Лог: `operation_ozverin.log` в корне; смотрите `view.*`, `asset_loader`,
  `core.storyline`, `view.automata`.
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
  ```

### 5.9. «Хочу понять диалог с агентами»

Читайте [`DIALOGUE_NLG.md`](DIALOGUE_NLG.md). D0 (лексикон, грамматика,
разбор), D1 (read-only вопросы о мире) и D1.5 (композиционный синтез)
реализованы; D2+ — проект. Кратко:

* диалог — read-only слой над BDI и кампанией, без LLM и статистики;
* диалог полностью Data-Driven: онтология, лексикон, грамматика, правила
  вывода, планы, политики, конструкции и морфологические исключения
  лежат в `configs/dialogue/`, Python только интерпретирует их;
* проверка D0–D1.5:

  ```bash
  venv/bin/python -m campaign.dialogue.lint
  venv/bin/python -m campaign.dialogue.repl --side red --ask "Почему Империя считает Республику незаконной?"
  venv/bin/python -m campaign.dialogue.repl --side blue --ask "Кто правит Республикой?" --debug
  venv/bin/python -m pytest -q tests/test_dialogue.py tests/test_d1_dialogue.py tests/test_d1_5_synthesis.py
  ```
* вход: свободная русская фраза → нормализация → морфология →
  грамматический разбор → типизированная логическая форма;
* содержание: неизменяемый снимок знания агента (его убеждения, а не
  глобальная истина) → логический вывод с трассировкой;
* ответ: план выбирает смысл → конструкция из `synthesis.json` →
  композиционный синтез (`realize.py`) → словоформы (`morph.py`,
  словарный `pymorphy3`, не нейросеть);
* расширение: новое отношение, тип, лексема, конструкция, фраза или
  словоформа добавляются JSON-ом; `world.adapter` связывает роли
  адаптера кампании с отношениями без правки Python;
* отладка: `--debug` печатает план, логическую форму и дерево вывода;
* порядок работ: **D0 лексикон/грамматика — сделан**, **D1 read-only
  вопросы о мире — сделан**, **D1.5 композиционный синтез — сделан**,
  D2 состояние диалога, D3 объяснения, D4 речевые действия,
  D5–D6 продвинутый синтез и калибровка.

Связанные решения: G-18/G-19 в
[`DATA_DRIVEN_CORE_GAPS.md`](DATA_DRIVEN_CORE_GAPS.md), фаза P10 в
[`DATA_DRIVEN_CORE_PLAN.md`](DATA_DRIVEN_CORE_PLAN.md), модель работы в
[`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) §3.0.

### 5.10. «Хочу проверить, что ничего не сломал»

```bash
venv/bin/python -m pytest -q
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

---

## 6. Карта тестов

| Область | Файлы | Что проверяют |
|---|---|---|
| Канон `simulation.py` | `test_canon.py`, `test_checks.py`, `test_math_model.py` | воспроизводимость, инварианты, скрипты-проверки |
| Ядро 4-2-1 и арена | `test_core41.py`, `test_clock.py`, `test_health.py`, `test_sickness.py`, `test_environment.py` | энергия/сила/здоровье, болезнь, раны, часы, среда |
| Войсковые автоматы | `test_warfare.py`, `test_lore_characters.py` | персонажи, потребности, черты, отделения, мораль |
| Дневной мир | `test_world.py`, `test_campaign_env.py`, `test_campaign_planner.py`, `test_campaign_clock.py`, `test_campaign_energy.py` | `WorldEngine`, `CampaignEnv`, планировщик, время |
| Кампания автоматов | `test_automata_campaign.py`, `test_identity.py` | работы, кулдауны, исходы, органы, личность, кодекс, детерминизм, снимки |
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
| [`MODEL.md`](MODEL.md) | текущий легаси-канон `simulation.py`, константы |
| [`WARFARE.md`](WARFARE.md) | персонажи, потребности, черты, отделения |
| [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md) | современный клиент `view/`, кампанийные потоки |
| [`UI.md`](UI.md) | легаси-клиент `ui/`, сцены, сейвы, RTS |
| [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) | кампании четырёх фракций-автоматов |
| [`AUTOMATA_GEOMETRY.md`](AUTOMATA_GEOMETRY.md) | семантическая геометрия: метрический граф, локальные углы, пути |
| [`CONTENT.md`](CONTENT.md) | JSON-контент, загрузчики, добавление/правка |
| [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md) | BDI, 15 делений, события и производные активы фракции |
| [`DATA_DRIVEN_CORE_GAPS.md`](DATA_DRIVEN_CORE_GAPS.md) | аудит: что в коде мешает контенту быть данными |
| [`DATA_DRIVEN_CORE_PLAN.md`](DATA_DRIVEN_CORE_PLAN.md) | план P0–P10 до полноценного Data-Driven ядра |
| [`DIALOGUE_NLG.md`](DIALOGUE_NLG.md) | детерминированный диалог на естественном языке без LLM: архитектура, фазы D0–D6 |
| [`CONTENT_PLAN_LORE.md`](CONTENT_PLAN_LORE.md) | контент-план по `лор.pdf`: предикаты, сути, работы, автоматы |
| [`AGENTS.md`](AGENTS.md), [`ALGORITHMS.md`](ALGORITHMS.md) | политики, обучение, формулы, чекпойнты |
| [`AUTOMATA.md`](AUTOMATA.md) | редактор автоматов |
| [`ORGANIZATIONS.md`](ORGANIZATIONS.md), [`NAMING.md`](NAMING.md), [`SYSTEMS.md`](SYSTEMS.md), [`INTERACTION.md`](INTERACTION.md) | профильные инструменты и слои |
| [`WORLD.md`](WORLD.md), [`STRATEGY.md`](STRATEGY.md) | мир должностного лица и легаси-стратегия |
| [`SUMMARY.md`](SUMMARY.md) | сжатая карта, но проверяйте по коду |
| [`SESSION_SUMMARY.md`](SESSION_SUMMARY.md) | саммари последней сессии: решения, находки, следующие шаги |
| [`TODO.md`](TODO.md), [`RELEASE_READINESS.md`](RELEASE_READINESS.md) | что открыто и что считать готовностью |
| [`HOWTO.md`](HOWTO.md) | практические команды: игра, обучение, вклад |

---

## 8. Инварианты и запреты

* `yet_another_project/` — чужой/untracked каталог; не изменять и не
  добавлять в коммиты.
* `.gitignore` содержит правило для PDF (`лор.pdf` и подобные) — не
  удалять его.
* `simulation.py` — легаси-baseline: не менять его поведение без
  обоснования и обновления `BASELINE.md`/`test_canon.py`.
* `core41/` — целевое ядро; изменения физики арены требуют тестов и
  калибровки.
* `campaign/` — дневной мир; не переписывайте аренные константы ради
  кампанийных правил.
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
- [ ] «Дуэль (арена)» открывается и возвращает в меню по `ESC`.
- [ ] `venv/bin/python main.py --automata` открывает редактор.
- [ ] `venv/bin/python main.py --classic` открывает легаси-меню.
- [ ] `venv/bin/python main.py --list-checkpoints` работает без окна.
- [ ] `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy venv/bin/python -m pytest -q
  tests/test_gui_smoke.py` проходит.
- [ ] `venv/bin/python -m pytest -q` проходит (или вы понимаете, какие
  падения уже существуют).
- [ ] Вы знаете, где лежит нужный вам слой по §3.2, и какой документ
  читать по §7.

Если потребность не покрыта таблицей §2, начните с §3.2: определите слой
(ядро, кампания, войска, GUI, контент, агенты), затем откройте профильный
документ из §7 и соответствующий тест из §6. Это самый короткий путь к
нужному коду.
