# `view`

Справочник собран из docstrings и примечаний к переменным. Номера строк относятся к версии до очистки кода.

## `view/__init__.py`

Нет docstrings.

## `view/__main__.py`

### Модуль

Строка 1.

Запуск кампании ``view``: ``python3 -m view``.

## `view/app.py`

### Модуль

Строка 1.

view/app.py
Главное окно приложения.
Инициализирует pygame, загружает контент, строит мир, запускает движок
и управляет стеком экранов. Передаёт ссылку на себя в time_system
и logistics для доступа к модификаторам черт персонажа.
При запуске новой игры открывает экран выбора роли, затем — экран выбора
фракции для роли с ``faction_choice`` или экран выбора сюжета для остальных
ролей. Для ``faction_leader`` создание персонажа пропускается: выбранная
сторона становится ростером игрока, а интерпретатор ведёт по сюжету «Мандат
фракции». Роль и фракция определяют генерируемый пресет кампании
(персонажи, фракции-автоматы, организации, среда и события).
Исход сюжета (победа/поражение) отложен: флаг ставится при пересечении
вечерней границы дня, а финальная сцена показывается в главном цикле
через process_pending_storyline_outcome(), чтобы не переключать экраны
изнутри раскрутки времени.
Слайды визуальных новелл (интро, победная и проигрышная сцены)
поддерживают варианты по переменным сюжета на уровне отдельного
слайда через variant_by/variants.
HUD игрового времени отрисовывается только когда в стеке экранов
присутствует экран с show_time_hud == True (RTSScreen); на самом RTS-экране
он скрыт, потому что время уже показано в его верхней панели.
События инициализации, загрузки, сохранения и переходов между экранами
записываются в журнал operation_ozverin.log в корне проекта и
дублируются в консоль.

### function `_build_logger`

Строка 40.

```python
def _build_logger(name)
```

Создаёт и возвращает журнал с файловым и консольным обработчиками.
Файловый обработчик пишет в operation_ozverin.log в корне проекта
с уровнем DEBUG, консольный выводит сообщения уровня INFO и выше.
Обработчики создаются один раз для каждого имени журнала.
Args:
    name (str): Имя журнала.
Returns:
    logging.Logger: Настроенный журнал.

### function `_find_first_valid_ttf`

Строка 72.

```python
def _find_first_valid_ttf()
```

Ищет первый валидный TTF-шрифт в директории assets/fonts.
Перебирает файлы с расширением .ttf в алфавитном порядке и
возвращает путь к первому, который успешно загружается и
рендерит тестовую строку. Если директория отсутствует или
валидных шрифтов нет, возвращает None.
Returns:
    str | None: Абсолютный путь к валидному TTF-шрифту или None.

### function `load_font`

Строка 104.

```python
def load_font(size)
```

Загружает шрифт заданного размера с фолбэком на встроенный.
Использует первый валидный TTF, найденный в assets/fonts.
При ошибке загрузки или отсутствии шрифта возвращает
встроенный шрифт pygame.
Args:
    size (int): Размер шрифта в пикселях.
Returns:
    pygame.font.Font: Загруженный или встроенный шрифт.

### class `App`

Строка 124.

Главное приложение игры.
Управляет инициализацией pygame, загрузкой контента, построением
мира, запуском движка и стеком экранов. Передаёт ссылку на себя
в time_system и logistics для доступа к модификаторам черт.
Attributes:
    screen (pygame.Surface): Поверхность экрана.
    clock (pygame.time.Clock): Часы для ограничения FPS.
    font_title (pygame.font.Font): Шрифт заголовков.
    font_body (pygame.font.Font): Основной шрифт.
    font_small (pygame.font.Font): Мелкий шрифт.
    font_tiny (pygame.font.Font): Очень мелкий шрифт.
    running (bool): Флаг работы главного цикла.
    scenario_path (str): Путь к текущему сценарию.
    storyline_interpreter (StorylineInterpreter | None): Интерпретатор сюжета.
    pending_storyline_outcome (str | None): Отложенный исход сюжета.
    music (MusicManager): Менеджер фоновой музыки.
    content (Content): Загруженный контент интерфейса.
    engine (TickEngine): Игровой движок.
    player_idx (int): Индекс сущности игрока.
    time_system (GameTimeSystem): Система игрового времени.
    time_hud (TimeHUD): HUD игрового времени.
    manager (ScreenManager): Менеджер стека экранов.

### method `App.__init__`

Строка 150.

```python
def __init__(self)
```

Инициализирует приложение, pygame, загружает контент и строит мир.
Создаёт окно, загружает шрифты, контент, строит начальное
состояние мира, инициализирует движок, систему времени,
менеджер музыки и стек экранов. Начальный экран — главное меню.

### method `App.finish_storyline_outcome`

Строка 203.

```python
def finish_storyline_outcome(self, outcome)
```

Зафиксировать победу/поражение и отдать сцену главному циклу.

        Метод не переключает экраны сам: ``process_pending_storyline_outcome``
        сделает это на ближайшем кадре. Повторные вызовы идемпотентны.

### method `App.check_storyline_end_of_day`

Строка 220.

```python
def check_storyline_end_of_day(self)
```

Проверка исходов сюжета по пороговым условиям. Idempotent.

Вызывается на вечерней границе и после каждого войскового такта,
поэтому потеря 90% дивизии завершает операцию сразу, а не ждёт ночи.
Ставит флаг pending_storyline_outcome, но не переключает экраны;
финальная сцена показывается в главном цикле через
process_pending_storyline_outcome().

### method `App.apply_to_player`

Строка 245.

```python
def apply_to_player(self, channel, delta)
```

Применяет дельту к каналу напряжения игрока.
Args:
    channel (str): Имя канала напряжения.
    delta (float): Изменение значения канала.

### method `App.toggle_fullscreen`

Строка 255.

```python
def toggle_fullscreen(self)
```

Переключает полноэкранный режим.

### method `App.advance_turn`

Строка 269.

```python
def advance_turn(self)
```

Выполняет один тик движка (старый режим).

### method `App.open_turn_log`

Строка 281.

```python
def open_turn_log(self)
```

Открывает оверлей лога последнего тика.

### method `App.execute_player_action`

Строка 287.

```python
def execute_player_action(self, action_id, on_completed=None)
```

Выполняет действие игрока через time_system.
Обрабатывает прерывания, обязательные сцены и завершение.
При статусе completed вызывает on_completed callback.
Args:
    action_id (str): ID действия из time_actions.json.
    on_completed (callable | None): Callback при завершении.

### method `App.new_game`

Строка 323.

```python
def new_game(self)
```

Открывает выбор роли, затем выбор сюжета.

### method `App._campaign_seed`

Строка 332.

```python
def _campaign_seed(self, storyline)
```

Seed кампании из сюжета; по умолчанию 7 (как у бригады).

### method `App.start_storyline`

Строка 340.

```python
def start_storyline(self, storyline, faction_id=None)
```

Запускает сюжет: пересобирает мир, инициализирует интерпретатор
и запускает первую сцену.
Args:
    storyline (dict): Конфигурация сюжета из load_storyline().
    faction_id (str | None): Выбранная игроком фракция.

### method `App._play_next_scene`

Строка 450.

```python
def _play_next_scene(self)
```

Запускает следующую сцену из последовательности.

### method `App._resolve_slides`

Строка 465.

```python
def _resolve_slides(self, block)
```

Возвращает слайды блока новеллы с разрешёнными вариантами.
Каждый слайд прогоняется через resolve_variant интерпретатора,
поэтому отдельный слайд может содержать variant_by/variants
(например, выбор изображения по полу персонажа) без
дублирования всего списка слайдов.
Args:
    block (dict): Блок сцены с ключом slides.
Returns:
    list[dict]: Список разрешённых слайдов.

### method `App._play_scene`

Строка 483.

```python
def _play_scene(self, scene)
```

Запускает сцену соответствующего типа.
Неизвестный тип сцены пропускается с переходом к следующей.
Args:
    scene (dict): Конфигурация сцены.

### method `App._play_character_creation`

Строка 514.

```python
def _play_character_creation(self, scene)
```

Запускает экран создания персонажа.
Args:
    scene (dict): Конфигурация сцены (не используется напрямую,
        шаги берутся из storyline.character_creation).

### method `App._play_visual_novel`

Строка 536.

```python
def _play_visual_novel(self, scene)
```

Запускает визуальную новеллу.
Слайды разрешаются через _resolve_slides, поэтому каждый
слайд может иметь собственные варианты по переменным сюжета.
Args:
    scene (dict): Конфигурация сцены с полем slides.

### method `App._play_document`

Строка 556.

```python
def _play_document(self, scene)
```

Запускает сцену с документом.
Args:
    scene (dict): Конфигурация сцены с полями title,
        content_stylized, content_plain, hands_asset.

### method `App._play_dialogue`

Строка 584.

```python
def _play_dialogue(self, scene)
```

Запускает диалог.
Args:
    scene (dict): Конфигурация сцены с полем node_id.

### method `App._play_mandatory_scene`

Строка 599.

```python
def _play_mandatory_scene(self, scene)
```

Запускает обязательную сцену.
Args:
    scene (dict): Конфигурация сцены с полем scene_id.

### method `App._play_gameplay`

Строка 613.

```python
def _play_gameplay(self, scene)
```

Запускает интерактивную RTS-карту вместо командного пункта.

### method `App._show_win_scene`

Строка 619.

```python
def _show_win_scene(self)
```

Показывает победную сцену.
Блок win_scene прогоняется через resolve_variant целиком,
а затем каждый слайд разрешается отдельно, чтобы первый
слайд мог выбирать изображение по полу персонажа без
дублирования всего списка слайдов.

### method `App._show_lose_scene`

Строка 645.

```python
def _show_lose_scene(self)
```

Показывает проигрышную сцену.
Блок lose_scene и каждый слайд прогоняются через
resolve_variant для симметрии с победной сценой.

### method `App._return_to_menu`

Строка 669.

```python
def _return_to_menu(self)
```

Возвращает в главное меню.

### method `App.process_pending_storyline_outcome`

Строка 678.

```python
def process_pending_storyline_outcome(self)
```

Обрабатывает отложенный исход сюжета.
Вызывается в главном цикле. Если pending_storyline_outcome
установлен, показывает соответствующую финальную сцену.

### method `App.process_pending_mandatory_scene`

Строка 693.

```python
def process_pending_mandatory_scene(self)
```

Обрабатывает отложенную обязательную сцену.
Показывает обязательную сцену только если в стеке есть
экран с show_time_hud == True и текущий экран не является
MandatorySceneScreen или InterruptModal.

### method `App.save_game`

Строка 718.

```python
def save_game(self, slot_name)
```

Сохраняет игру в указанный слот.
Args:
    slot_name (str): Имя слота сохранения.
Returns:
    str | None: Путь к файлу сохранения или None при ошибке.

### method `App.load_game`

Строка 745.

```python
def load_game(self, slot_name)
```

Загружает игру из указанного слота.
Мир пересобирается из сценария, поверх применяется снимок.
Стек экранов заменяется на RTSScreen.
Args:
    slot_name (str): Имя слота сохранения.
Returns:
    bool: True при успешной загрузке, False при ошибке.

### method `App.continue_game`

Строка 832.

```python
def continue_game(self)
```

Продолжает последнее сохранение.

### method `App.open_saves`

Строка 841.

```python
def open_saves(self)
```

Открывает меню сохранений.

### method `App.open_settings`

Строка 847.

```python
def open_settings(self)
```

Открывает меню настроек.

### method `App.quit`

Строка 853.

```python
def quit(self)
```

Завершает приложение.

### method `App.run`

Строка 858.

```python
def run(self)
```

Главный цикл приложения.
Обрабатывает события pygame, обновляет менеджер экранов
и музыку, проверяет отложенные исходы сюжета и обязательные
сцены, отрисовывает стек экранов и HUD (при наличии
show_time_hud экрана в стеке).

### function `main`

Строка 908.

```python
def main(argv=None)
```

Точка входа интерфейса ``view`` (``python3 main.py --view``).

## `view/screens/__init__.py`

Нет docstrings.

## `view/screens/adjutant_orders.py`

### Модуль

Строка 1.

view/screens/adjutant_orders.py

Экран приказов адъютанту.

Отображает список приказов с пагинацией по PAGE_SIZE записей на страницу.
Список приказов читается из активного сюжетного конфига (поле
adjutant_orders); при отсутствии сюжета или поля используется встроенный
фолбэк-список DEFAULT_ADJUTANT_ORDERS.

Выбор приказа применяет его эффект через EffectInterpreter, записывает
ответ адъютанта в лог мира и журнал, показывает реплику на экране
и тратит игровое время через действие планирования приказов.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль средствами core.log_journal.

### class `AdjutantOrdersScreen`

Строка 179.

Экран приказов адъютанту с пагинацией.

Читает список приказов из активного сюжета или использует
фолбэк-список. При выборе приказа применяет эффект, показывает
реплику адъютанта и тратит игровое время на планирование.

Attributes:
    panel (Panel): Фоновая панель экрана.
    orders (list[dict]): Список доступных приказов.
    page (int): Индекс текущей страницы.
    order_buttons (list[Button]): Кнопки приказов текущей страницы.
    prev_btn (Button): Кнопка перехода на предыдущую страницу.
    next_btn (Button): Кнопка перехода на следующую страницу.
    close_btn (Button): Кнопка закрытия экрана.
    issued (bool): Флаг выдачи приказа (режим ответа).
    ack_text (str): Текст реплики адъютанта после выдачи приказа.
    btn_close_after (Button): Кнопка закрытия в режиме ответа.

### method `AdjutantOrdersScreen.__init__`

Строка 200.

```python
def __init__(self, app)
```

Инициализирует экран приказов адъютанту.

Загружает список приказов из сюжета или фолбэка, создаёт
кнопки навигации и первую страницу приказов.

Args:
    app: Экземпляр приложения (App).

### method `AdjutantOrdersScreen._resolve_orders`

Строка 234.

```python
def _resolve_orders(self)
```

Загружает список приказов из активного сюжета или фолбэка.

Если storyline_interpreter отсутствует или в сюжете нет
поля adjutant_orders, возвращает DEFAULT_ADJUTANT_ORDERS.

Returns:
    list[dict]: Список словарей приказов.

### method `AdjutantOrdersScreen._page_count`

Строка 252.

```python
def _page_count(self)
```

Возвращает общее число страниц списка приказов.

Returns:
    int: Число страниц (минимум 1).

### method `AdjutantOrdersScreen._build_buttons`

Строка 261.

```python
def _build_buttons(self)
```

Строит кнопки приказов для текущей страницы.

Создаёт до PAGE_SIZE кнопок, начиная с индекса
page * PAGE_SIZE. Каждая кнопка привязывает замыкание
к конкретному приказу через параметр по умолчанию.

### method `AdjutantOrdersScreen.issue`

Строка 281.

```python
def issue(self, order)
```

Применяет выбранный приказ.

Выполняет эффект приказа через EffectInterpreter, выбирает
случайную реплику адъютанта, записывает событие в лог мира,
переводит экран в режим ответа и тратит игровое время
через действие issue_order (или plan_orders_1 как фолбэк).

Args:
    order (dict): Словарь приказа с полями effect и label.

### method `AdjutantOrdersScreen.prev_page`

Строка 313.

```python
def prev_page(self)
```

Переключает на предыдущую страницу и перестраивает кнопки.

### method `AdjutantOrdersScreen.next_page`

Строка 319.

```python
def next_page(self)
```

Переключает на следующую страницу и перестраивает кнопки.

### method `AdjutantOrdersScreen.handle_event`

Строка 325.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для экрана приказов.

В режиме ответа обрабатывается только кнопка закрытия.
В обычном режиме обрабатываются кнопки навигации,
закрытия и выбора приказа.

Args:
    event (pygame.event.Event): Событие pygame.

### method `AdjutantOrdersScreen.draw`

Строка 349.

```python
def draw(self, screen)
```

Отрисовывает экран приказов адъютанту.

В режиме ответа рисует затемнение, панель, заголовок
«Приказ отдан», центрированную реплику адъютанта и кнопку
закрытия. В обычном режиме рисует заголовок, кнопки приказов,
кнопки навигации, номер страницы и кнопку закрытия.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/aftermath.py`

### Модуль

Строка 1.

view/screens/aftermath.py

Экран последствий после боя или события.

Отображает фон лагеря, зависящий от сегмента condition подразделения,
и две кнопки: «Диалоги» и «Решения».

Экран решений отображает список решений из контентной конфигурации;
выбор решения вызывает правило метаморфозы и/или применяет эффект
к подразделению, после чего экран закрывается.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль.

### class `AftermathScreen`

Строка 29.

Экран последствий.

Отображает фон лагеря, зависящий от сегмента condition
подразделения, и две кнопки: «Диалоги» и «Решения».

Attributes:
    unit_idx (int): Индекс подразделения в WorldState.
    bg (pygame.Surface): Фоновое изображение лагеря.
    buttons (list[Button]): Кнопки экрана.

### method `AftermathScreen.__init__`

Строка 42.

```python
def __init__(self, app, unit_idx)
```

Инициализирует экран последствий.

Выбирает фон в зависимости от сегмента condition юнита:
при condition >= 2 используется «свежий» лагерь,
иначе — «побитый». Создаёт кнопки «Диалоги» и «Решения».

Args:
    app: Экземпляр приложения (App).
    unit_idx (int): Индекс подразделения в WorldState.

### method `AftermathScreen.open_dialogues`

Строка 71.

```python
def open_dialogues(self)
```

Открывает диалог, связанный с последствиями.

Помещает в стек экран DialogueScreen с узлом
``aftermath_lt_orlov``.

### method `AftermathScreen.open_decisions`

Строка 82.

```python
def open_decisions(self)
```

Открывает экран решений для текущего подразделения.

Формирует временный диалоговый узел ``_aftermath_decisions``
на основе списка решений из ``app.content.decisions``
и помещает в стек AftermathDecisionScreen.

### method `AftermathScreen.handle_event`

Строка 113.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для данного экрана.

Событие последовательно передаётся всем кнопкам экрана.
Если одна из кнопок обработала событие, дальнейшая обработка
прекращается.

Args:
    event (pygame.event.Event): Событие pygame.

### method `AftermathScreen.draw`

Строка 128.

```python
def draw(self, screen)
```

Отрисовывает экран последствий.

Рисует фоновое изображение лагеря и кнопки управления.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### class `AftermathDecisionScreen`

Строка 142.

Экран выбора решений для подразделения.

Отображает список решений, сформированный на основе
`app.content.decisions`. При выборе решения может быть
вызвано правило метаморфозы и/или применён эффект.

Attributes:
    unit_idx (int): Индекс подразделения в WorldState.
    choices (list[dict]): Список доступных решений.
    panel (Panel): Фоновая панель.
    buttons (list[Button]): Кнопки решений.

### method `AftermathDecisionScreen.__init__`

Строка 157.

```python
def __init__(self, app, node_id, unit_idx)
```

Инициализирует экран решений.

Читает диалоговый узел по node_id и создаёт кнопку
для каждого решения из узла.

Args:
    app: Экземпляр приложения (App).
    node_id (str): Идентификатор диалогового узла.
    unit_idx (int): Индекс подразделения в WorldState.

### method `AftermathDecisionScreen.choose`

Строка 197.

```python
def choose(self, i)
```

Обрабатывает выбор решения.

Если у решения указан ``rule``, вызывает
``RuleEngine.try_decision`` для текущего подразделения.
Затем применяет эффект решения через ``EffectInterpreter``.
Если цель эффекта не указана явно, эффект применяется
к текущему подразделению. После обработки экран закрывается.

Args:
    i (int): Индекс выбранного решения.

### method `AftermathDecisionScreen.handle_event`

Строка 230.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для данного экрана.

Событие последовательно передаётся всем кнопкам решений.
Если одна из кнопок обработала событие, дальнейшая обработка
прекращается.

Args:
    event (pygame.event.Event): Событие pygame.

### method `AftermathDecisionScreen.draw`

Строка 245.

```python
def draw(self, screen)
```

Отрисовывает экран решений.

Рисует панель, заголовок «Решения» и кнопки вариантов.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/character_creation.py`

### Модуль

Строка 1.

view/screens/character_creation.py

Экран создания персонажа.

Отображает последовательность шагов создания персонажа,
описанную в конфигурации сюжета. Каждый шаг содержит текст
и варианты выбора. Выбор может устанавливать переменные
сюжета и применять эффекты к создаваемой сущности.

Поддерживает условное отображение шагов через поле requires
и подстановку вариантов текста через поле variant_by.

При завершении создания записывает пол персонажа в
state.player_gender и выбранную черту в переменную trait
для использования в игровой механике.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль средствами core.log_journal.

### class `CharacterCreationScreen`

Строка 45.

Экран создания персонажа.

Последовательно отображает шаги создания из конфигурации.
Каждый шаг содержит текст и варианты выбора. При выборе
устанавливаются переменные сюжета и применяются эффекты.

Поддерживает условное отображение шагов через поле requires
и подстановку вариантов текста через поле variant_by.

Attributes:
    steps (list[dict]): Список шагов создания персонажа.
    current_step (int): Индекс текущего видимого шага.
    panel (Panel): Фоновая панель экрана.
    buttons (list[Button]): Кнопки вариантов выбора текущего шага.

### method `CharacterCreationScreen.__init__`

Строка 63.

```python
def __init__(self, app, steps)
```

Инициализирует экран создания персонажа.

Создаёт фоновую панель, пропускает невидимые шаги в начало
и строит кнопки для первого видимого шага.

Args:
    app: Экземпляр приложения (App).
    steps (list[dict]): Список шагов создания персонажа.
        Каждый шаг — словарь с полями text, choices и
        опциональными requires, variant_by, variants.

### method `CharacterCreationScreen._resolve_variant`

Строка 88.

```python
def _resolve_variant(self, step)
```

Подставляет вариант текста шага по переменной сюжета.

Если шаг содержит поле variant_by, ищет значение переменной
в variants и возвращает соответствующий вариант, объединённый
с исходным шагом. Если переменная не установлена или ключ
отсутствует, возвращает исходный шаг без изменений.

Args:
    step (dict): Словарь шага из конфигурации.

Returns:
    dict: Разрешённый шаг с подставленным текстом.

### method `CharacterCreationScreen._is_step_visible`

Строка 119.

```python
def _is_step_visible(self, step)
```

Проверяет, должен ли шаг быть отображён.

Шаг отображается, если у него нет поля requires,
или если все условия requires выполнены.
Условия requires проверяются через storyline_interpreter.

Args:
    step (dict): Словарь шага из конфигурации.

Returns:
    bool: True, если шаг должен быть отображён.

### method `CharacterCreationScreen._skip_to_visible_step`

Строка 144.

```python
def _skip_to_visible_step(self)
```

Пропускает невидимые шаги вперёд.

Вызывается при инициализации и после выбора варианта,
чтобы текущий шаг всегда был видимым. Если все оставшиеся
шаги невидимы, current_step устанавливается за пределы
списка шагов.

### method `CharacterCreationScreen._get_text_lines`

Строка 158.

```python
def _get_text_lines(self, text)
```

Разбивает текст на строки с ограничением по высоте.

Переносит текст по ширине TEXT_MAX_WIDTH и обрезает до
максимального числа строк, помещающихся в TEXT_MAX_HEIGHT.
Если текст обрезается, к последней строке добавляется «...».

Args:
    text (str): Исходный текст шага.

Returns:
    list[str]: Список строк, умещающихся в TEXT_MAX_HEIGHT.

### method `CharacterCreationScreen._build_buttons`

Строка 181.

```python
def _build_buttons(self)
```

Строит кнопки вариантов выбора для текущего шага.

Если текущий шаг находится за пределами списка шагов,
кнопки не создаются. Для каждого варианта выбора создаётся
кнопка с текстом и callback, вызывающим choose(i).

### method `CharacterCreationScreen.choose`

Строка 212.

```python
def choose(self, i)
```

Обрабатывает выбор варианта на текущем шаге.

Если указано set_variable, устанавливает переменную сюжета
через storyline_interpreter. Если указан effect и состояние
мира содержит сущности, применяет эффект через EffectInterpreter.
Переходит к следующему видимому шагу или завершает создание.

Args:
    i (int): Индекс выбранного варианта в списке choices.

### method `CharacterCreationScreen._finish`

Строка 266.

```python
def _finish(self)
```

Завершает создание персонажа.

Сохраняет начальное значение U_manpower в состоянии сюжета
для условия manpower_loss_above. Записывает пол персонажа
в state.player_gender. Закрывает экран и запускает
следующую сцену последовательности через app._play_next_scene().

Если мир пуст, initial_manpower устанавливается в 0.0.

### method `CharacterCreationScreen.handle_event`

Строка 308.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для данного экрана.

Событие последовательно передаётся всем кнопкам вариантов
выбора текущего шага. Если одна из кнопок обработала событие,
дальнейшая обработка прекращается.

Args:
    event (pygame.event.Event): Событие pygame.

### method `CharacterCreationScreen._wrap_text`

Строка 324.

```python
def _wrap_text(text, font, max_w)
```

Выполняет перенос текста по заданной максимальной ширине.

Разбивает текст на слова и собирает строки, не превышающие
max_w пикселей при отрисовке заданным шрифтом.

Args:
    text (str): Исходный текст.
    font (pygame.font.Font): Шрифт для измерения ширины.
    max_w (int): Максимальная ширина строки в пикселях.

Returns:
    list[str]: Список перенесённых строк.

### method `CharacterCreationScreen.draw`

Строка 351.

```python
def draw(self, screen)
```

Отрисовывает экран создания персонажа.

Порядок отрисовки:
1. Полупрозрачное затемнение всего экрана.
2. Фоновая панель.
3. Текст текущего шага с переносом по ширине.
4. Кнопки вариантов выбора.
5. Индикатор прогресса (текущий видимый шаг / всего видимых).

Если все шаги пройдены, отрисовка текста и кнопок пропускается.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/dialogue.py`

### Модуль

Строка 1.

view/screens/dialogue.py

Экран диалога.

Отображает диалоговый узел из контентной конфигурации
(app.content.dialogues): имя говорящего, текст и список вариантов
выбора. Выбор применяет эффект через EffectInterpreter, переходит
к следующему узлу диалога или закрывает экран и расходует игровое
время через действие dialogue_choice. События узла и выбора
записываются в журнал operation_ozverin.log и дублируются в консоль.

### class `DialogueScreen`

Строка 24.

Экран диалога.

Загружает диалоговый узел по идентификатору из
app.content.dialogues, отображает имя говорящего, текст и кнопки
выбора. При выборе варианта применяется эффект (если задан),
расходуется игровое время и происходит переход к следующему узлу
или закрытие экрана.

Attributes:
    node_id (str): Идентификатор текущего диалогового узла.
    speaker (str): Имя говорящего.
    text (str): Текст диалога.
    choices (list[dict]): Список вариантов выбора.
    panel (Panel): Фоновая панель диалога.
    buttons (list[Button]): Кнопки вариантов выбора.

### method `DialogueScreen.__init__`

Строка 43.

```python
def __init__(self, app, node_id)
```

Инициализирует экран диалога.

Загружает узел диалога из app.content.dialogues по node_id,
извлекает speaker, text и choices, создаёт кнопку для каждого
варианта выбора. Если choices отсутствуют, создаётся дефолтная
кнопка «Продолжить».

Args:
    app: Экземпляр приложения (App).
    node_id (str): Идентификатор диалогового узла.

### method `DialogueScreen.choose`

Строка 86.

```python
def choose(self, i)
```

Обрабатывает выбор варианта диалога.

Применяет эффект выбора через EffectInterpreter (если задан),
затем переходит к следующему узлу диалога (если указан next)
или закрывает экран. После навигации расходует игровое время
через действие dialogue_choice.

Args:
    i (int): Индекс выбранного варианта.

### method `DialogueScreen.handle_event`

Строка 118.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для данного экрана.

Событие последовательно передаётся всем кнопкам выбора.
Если одна из кнопок обработала событие, дальнейшая обработка
прекращается.

Args:
    event (pygame.event.Event): Событие pygame.

### method `DialogueScreen._wrap`

Строка 133.

```python
def _wrap(self, text, font, max_w)
```

Выполняет перенос текста по заданной максимальной ширине.

Разбивает входную строку на список строк, каждая из которых
не превышает max_w пикселей при отрисовке заданным шрифтом.

Args:
    text (str): Исходный текст.
    font (pygame.font.Font): Шрифт для измерения ширины.
    max_w (int): Максимальная ширина строки в пикселях.

Returns:
    list[str]: Список перенесённых строк.

### method `DialogueScreen.draw`

Строка 159.

```python
def draw(self, screen)
```

Отрисовывает экран диалога.

Порядок отрисовки:
1. Фоновая панель.
2. Имя говорящего.
3. Текст диалога (не более 4 строк, с переносом по ширине).
4. Кнопки вариантов выбора.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/document_intro.py`

### Модуль

Строка 1.

view/screens/document_intro.py

Экран интро с документом в руках.

Отображает изображение рук, держащих бумагу, со стилизованным текстом
приказа. Безопасная зона текста задаётся отдельно для каждого ассета
рук (таблица HANDS_TEXT_RECTS), чтобы текст лежал строго на бумаге и
не задевал пальцы ни в одном варианте рук. Текст центрируется
построчно и автоматически подбирает кегль, чтобы целиком уместиться
в безопасной зоне. Переносы строк из конфига уважаются.

Кнопка «Прочитать внимательно» открывает читалку с прокруткой
(колесо мыши, стрелки, PageUp/PageDown).

Поведение ESC: при открытой читалке закрывает только её, при
закрытой — игнорируется.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль.

### function `_load_font`

Строка 53.

```python
def _load_font(size)
```

Загружает моноширинный шрифт заданного размера с фолбэком.

Пытается загрузить DejaVuSansMono.ttf из assets/fonts/.
При ошибке или отсутствии файла возвращает встроенный
шрифт pygame того же размера.

Args:
    size (int): Размер шрифта в пикселях.

Returns:
    pygame.font.Font: Загруженный или встроенный шрифт.

### class `DocumentIntroScreen`

Строка 75.

Экран интро с документом в руках.

Текст приказа размещается в безопасной зоне, подобранной под
конкретный ассет рук, центрируется построчно и подбирает кегль,
чтобы целиком уместиться на бумаге, не задевая пальцы.

Attributes:
    doc (dict): Данные документа (title, content_stylized,
        content_plain, hands_asset).
    on_finish (callable): Callback завершения («К делу»).
    hands_img (pygame.Surface): Изображение рук с бумагой.
    text_rect (pygame.Rect): Безопасная зона текста на бумаге.
    btn_read (Button): Кнопка открытия/закрытия читалки.
    btn_proceed (Button): Кнопка перехода к делу.
    show_reader (bool): Флаг отображения читалки.
    reader_scroll (int): Смещение прокрутки читалки в строках.

### method `DocumentIntroScreen.__init__`

Строка 97.

```python
def __init__(self, app, document_data, on_finish_callback)
```

Инициализирует экран интро с документом.

Загружает ассет рук, подбирает безопасную зону текста,
предварительно рендерит текст на бумаге с оптимальным кеглем,
создаёт кнопки управления и инициализирует состояние читалки.

Args:
    app: Экземпляр приложения (App).
    document_data (dict): Данные документа с ключами title,
        content_stylized, content_plain, hands_asset.
    on_finish_callback (callable): Функция, вызываемая при
        нажатии кнопки «К делу».

### method `DocumentIntroScreen.toggle_reader`

Строка 147.

```python
def toggle_reader(self)
```

Переключает видимость читалки и сбрасывает прокрутку.

### method `DocumentIntroScreen.proceed`

Строка 155.

```python
def proceed(self)
```

Завершает интро и вызывает callback перехода к делу.

### method `DocumentIntroScreen.on_escape`

Строка 163.

```python
def on_escape(self)
```

Обрабатывает ESC: закрывает только открытую читалку.

### method `DocumentIntroScreen._wrap_text`

Строка 170.

```python
def _wrap_text(text, font, max_width)
```

Переносит текст по ширине с уважением переносов строк.

Пустые строки конфига дают пустые строки на бумаге.
Символы \n в тексте интерпретируются как переносы строк.

Args:
    text (str): Исходный текст.
    font (pygame.font.Font): Шрифт для измерения ширины.
    max_width (int): Максимальная ширина строки в пикселях.

Returns:
    list[str]: Список строк после переноса.

### method `DocumentIntroScreen._prepare_paper_text`

Строка 203.

```python
def _prepare_paper_text(self)
```

Подбирает наибольший кегль, при котором весь текст приказа
умещается в безопасной зоне бумаги текущего ассета рук.

Перебирает размеры шрифта от большего к меньшему из
PAPER_FONT_SIZES. Возвращает первый размер, при котором
общая высота текста не превышает высоту безопасной зоны.
Если ни один размер не подходит, использует наименьший.

Returns:
    tuple: Кортеж (шрифт, список строк, высота строки).

### method `DocumentIntroScreen._reader_lines_cached`

Строка 229.

```python
def _reader_lines_cached(self)
```

Возвращает кэшированный список строк читалки.

При первом вызове разбивает content_plain по ширине
READER_TEXT_RECT и кэширует результат. Последующие вызовы
возвращают кэш без повторного вычисления.

Returns:
    list[str]: Список строк текста для читалки.

### method `DocumentIntroScreen._reader_visible_lines`

Строка 248.

```python
def _reader_visible_lines(self)
```

Возвращает число строк, видимых в окне читалки.

Вычисляется как целая часть от деления высоты текстовой
области читалки на высоту строки текущего шрифта.

Returns:
    int: Количество видимых строк (минимум 1).

### method `DocumentIntroScreen._scroll_reader`

Строка 261.

```python
def _scroll_reader(self, delta)
```

Смещает прокрутку читалки с клампом по границам текста.

Args:
    delta (int): Смещение в строках (положительное — вниз,
        отрицательное — вверх).

### method `DocumentIntroScreen.handle_event`

Строка 275.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для экрана.

При открытой читалке принимает прокрутку колесом мыши,
кнопками 4/5 и клавишами вверх/вниз/PageUp/PageDown.
Иначе обрабатывает кнопки «Прочитать внимательно» и «К делу»;
ENTER эквивалентен нажатию «К делу».

Args:
    event (pygame.event.Event): Событие pygame.

### method `DocumentIntroScreen.draw`

Строка 309.

```python
def draw(self, screen)
```

Отрисовывает экран интро с документом.

Порядок: руки с бумагой, текст приказа по центру безопасной
зоны с подобранным кеглем и поворотом под наклон бумаги,
кнопки, поверх — читалка с прокруткой и ползунком, если
она открыта.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### method `DocumentIntroScreen._draw_reader`

Строка 346.

```python
def _draw_reader(self, screen)
```

Рисует читалку: затемнение, панель, заголовок, прокручиваемый
текст с обрезкой по видимой области и ползунок.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/documents.py`

### Модуль

Строка 1.

view/screens/documents.py

Экран просмотра документов в виде раскрытой папки.

Текст документов раскладывается по разворотам: каждый документ
начинается с нового разворота. Заголовки и строки заполняют левый
лист, затем правый; при переполнении обоих листов создаётся
следующий разворот (в рамках того же документа). Текст выводится
на прозрачной поверхности, наклоняется под углом листа и накладывается
внутрь белого листа с внутренними полями. Навигация осуществляется
стрелками листания, закрытие — кнопкой и ESC.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль.

### function `_ensure_journal`

Строка 39.

```python
def _ensure_journal()
```

Создаёт корневой журнал проекта при первом вызове.

Настраивает файловый обработчик для записи в operation_ozverin.log
и консольный обработчик для вывода в stdout. Повторные вызовы
не создают дублирующихся обработчиков.

Returns:
    logging.Logger: Настроенный корневой журнал.

### class `DocumentsScreen`

Строка 75.

Экран документов с постраничной навигацией.

Отображает документы в виде раскрытой папки с разворотами страниц.
Каждый документ начинается с нового разворота. Текст размещается
на наклонённых поверхностях с учётом внутренних полей страницы.
Навигация осуществляется стрелками или кликами по зонам листания.

Attributes:
    documents (list[dict]): Список документов для отображения.
    page (int): Индекс текущего разворота.
    folder_img (pygame.Surface): Изображение папки.
    spreads (list[tuple]): Список разворотов (левые, правые строки).
    prev_rect (pygame.Rect): Зона клика для перехода назад.
    next_rect (pygame.Rect): Зона клика для перехода вперёд.
    close_btn (Button): Кнопка закрытия экрана.

### method `DocumentsScreen.__init__`

Строка 94.

```python
def __init__(self, app, documents)
```

Инициализирует экран документов.

Загружает изображение папки, строит список разворотов из
документов и создаёт элементы управления навигацией.

Args:
    app: Экземпляр приложения (App).
    documents (list[dict]): Список документов. Каждый документ —
        словарь с ключами title (str) и lines (list[str]).

### method `DocumentsScreen._line_height`

Строка 137.

```python
def _line_height(self, kind)
```

Возвращает высоту строки для заданного типа текста.

Для заголовков используется font_body с дополнительным
отступом 10px. Для обычного текста — font_small с отступом 6px.

Args:
    kind (str): Тип текста ("heading" или "line").

Returns:
    int: Высота строки в пикселях.

### method `DocumentsScreen._wrap_text`

Строка 154.

```python
def _wrap_text(self, text, font, max_width)
```

Переносит текст по ширине с учётом максимальной ширины строки.

Разбивает текст на слова и формирует строки, не превышающие
max_width пикселей при отрисовке заданным шрифтом.

Args:
    text (str): Исходный текст.
    font (pygame.font.Font): Шрифт для измерения ширины.
    max_width (int): Максимальная ширина строки в пикселях.

Returns:
    list[str]: Список строк после переноса.

### method `DocumentsScreen._build_spreads`

Строка 184.

```python
def _build_spreads(self)
```

Строит список разворотов из документов.

Каждый документ начинается с нового разворота. Внутри документа
текст заполняет левый лист, затем правый. При переполнении
обоих листов создаётся следующий разворот. Текст не залезает
на нижнюю зону листания (TEXT_BOTTOM_MARGIN).

Returns:
    list[tuple[list, list]]: Список разворотов. Каждый разворот —
        кортеж (строки левого листа, строки правого листа).
        Каждая строка — кортеж (kind, text).

### method `DocumentsScreen._blit_page`

Строка 242.

```python
def _blit_page(self, screen, lines, page_rect, angle)
```

Отрисовывает страницу с текстом на наклонённой поверхности.

Создаёт прозрачную поверхность, размещает на ней текст,
поворачивает на заданный угол и накладывает на экран
по центру целевого прямоугольника страницы.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.
    lines (list[tuple]): Список строк (kind, text).
    page_rect (pygame.Rect): Прямоугольник страницы.
    angle (float): Угол поворота в градусах.

### method `DocumentsScreen._draw_arrow`

Строка 277.

```python
def _draw_arrow(self, screen, rect, direction)
```

Рисует стрелку навигации в заданном прямоугольнике.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.
    rect (pygame.Rect): Прямоугольник, в котором рисуется стрелка.
    direction (str): Направление стрелки ("prev" или "next").

### method `DocumentsScreen.prev_page`

Строка 300.

```python
def prev_page(self)
```

Переходит на предыдущий разворот.

### method `DocumentsScreen.next_page`

Строка 308.

```python
def next_page(self)
```

Переходит на следующий разворот.

### method `DocumentsScreen.close_menu`

Строка 316.

```python
def close_menu(self)
```

Закрывает экран документов.

### method `DocumentsScreen.handle_event`

Строка 321.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для экрана документов.

Обрабатывает клик по кнопке закрытия и клики по зонам
навигации (стрелкам листания).

Args:
    event (pygame.event.Event): Событие pygame.

### method `DocumentsScreen.draw`

Строка 339.

```python
def draw(self, screen)
```

Отрисовывает экран документов.

Порядок отрисовки: затемнение фона, изображение папки,
левая и правая страницы текущего разворота, индикатор
номера страницы, стрелки навигации, кнопка закрытия.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/faction_select.py`

### Модуль

Строка 1.

view/screens/faction_select.py

Экран выбора фракции для роли с номинальным лидерством.

### class `FactionSelectScreen`

Строка 33.

Экран выбора фракции-автомата, которой будет управлять игрок.

### method `FactionSelectScreen.select`

Строка 74.

```python
def select(self, faction_id)
```

Запустить кампанию за выбранную фракцию.

## `view/screens/interrupt_modal.py`

### Модуль

Строка 1.

view/screens/interrupt_modal.py

Модальное окно прерывания.

Отображается, когда текущее действие игрока прерывается срочным событием.
Предоставляет два варианта реакции: принять прерывание или игнорировать его.
Экран не закрывается по ESC (escape_action = "none").

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль средствами core.log_journal.

### class `InterruptModal`

Строка 24.

Модальное окно срочного прерывания.

Блокирует взаимодействие с нижележащими экранами до тех пор,
пока игрок не примет решение. ESC отключён (escape_action = "none").

Attributes:
    interrupt: Объект прерывания (InterruptEvent) или None.
    panel (Panel): Фоновая панель окна.
    btn_accept (Button): Кнопка принятия прерывания.
    btn_ignore (Button): Кнопка игнорирования прерывания.

### method `InterruptModal.__init__`

Строка 40.

```python
def __init__(self, app, interrupt)
```

Инициализирует модальное окно прерывания.

Создаёт панель и две кнопки: «Принять» и «Игнорировать».

Args:
    app: Экземпляр приложения (App).
    interrupt: Объект прерывания (InterruptEvent).
        Может быть None; в этом случае draw()
        отрисует только панель без содержимого.

### method `InterruptModal.accept`

Строка 77.

```python
def accept(self)
```

Обработчик принятия прерывания.

Уведомляет time_system о принятии прерывания и закрывает окно.
Если time_system или объект прерывания отсутствуют,
окно закрывается без дополнительных действий.

### method `InterruptModal.ignore`

Строка 91.

```python
def ignore(self)
```

Обработчик игнорирования прерывания.

Уведомляет time_system об игнорировании прерывания и закрывает окно.
Если time_system или объект прерывания отсутствуют,
окно закрывается без дополнительных действий.

### method `InterruptModal._wrap_text`

Строка 106.

```python
def _wrap_text(text, font, max_width)
```

Разбивает текст на строки по заданной максимальной ширине.

Args:
    text (str): Исходный текст.
    font (pygame.font.Font): Шрифт для измерения ширины.
    max_width (int): Максимальная ширина строки в пикселях.

Returns:
    list[str]: Список строк, каждая из которых не превышает max_width.

### method `InterruptModal.handle_event`

Строка 133.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для данного экрана.

Событие передаётся кнопкам «Принять» и «Игнорировать».
Если одна из кнопок обработала событие, дальнейшая обработка
прекращается.

Args:
    event (pygame.event.Event): Событие pygame.

### method `InterruptModal.draw`

Строка 149.

```python
def draw(self, screen)
```

Отрисовывает модальное окно прерывания.

Порядок отрисовки:
1. Полупрозрачное затемнение всего экрана.
2. Фоновая панель.
3. Если объект прерывания отсутствует — выход.
4. Заголовок прерывания.
5. Текст прерывания (с переносом по ширине).
6. Приоритет прерывания.
7. Кнопки «Принять» и «Игнорировать».

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/main_menu.py`

### Модуль

Строка 1.

view/screens/main_menu.py

Экран главного меню.

Отображает фоновое изображение, заголовок игры и кнопки навигации:
Новая игра, Продолжить, Сохранения, Настройки, Выход.
Кнопка «Продолжить» отключается, если в saves/ нет ни одного
сохранения: она не реагирует на клики и рисуется приглушённой.
ESC в главном меню намеренно отключён (escape_action = "none"),
чтобы игрок не мог случайно выйти из меню.

События экрана записываются в журнал operation_ozverin.log в корне
проекта и дублируются в консоль.

### class `MainMenuScreen`

Строка 28.

Экран главного меню игры.

Является корневым экраном, из которого игрок может начать
новую игру, продолжить сохранение, открыть настройки или выйти.
ESC на данном экране игнорируется.

Attributes:
    bg (pygame.Surface): Фоновое изображение главного меню.
    buttons (list[Button]): Список кнопок меню.
    btn_continue (Button): Кнопка «Продолжить»; отключена,
        если сохранений нет.

### method `MainMenuScreen.__init__`

Строка 45.

```python
def __init__(self, app)
```

Инициализирует главное меню.

Загружает фоновое изображение и создаёт пять кнопок:
Новая игра, Продолжить, Сохранения, Настройки, Выход.
Кнопка «Продолжить» доступна только при наличии сохранений.

Args:
    app: Экземпляр приложения (App).

### method `MainMenuScreen.handle_event`

Строка 75.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для главного меню.

Событие последовательно передаётся всем кнопкам меню.
Если одна из кнопок обработала событие, дальнейшая обработка
прекращается.

Args:
    event (pygame.event.Event): Событие pygame.

### method `MainMenuScreen.draw`

Строка 90.

```python
def draw(self, screen)
```

Отрисовывает главное меню.

Порядок отрисовки:
1. Фоновое изображение.
2. Заголовок игры по центру верхней части экрана.
3. Кнопки меню.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/mandatory_screen.py`

### Модуль

Строка 1.

view/screens/mandatory_screen.py

Экран обязательной сцены (утренний/вечерний осмотр).

Фоновые ассеты и тексты берутся из configs/content/mandatory_scenes.json;
при отсутствии файла или отдельных ключей используются встроенные
фолбэки. Утренний осмотр выбирает фон по калькуляции потерь дивизии
относительно порога поражения из сюжета: до 40% лимита — camp_fresh,
до 80% — camp_wounded, дальше — camp_critical. Поэтому все три варианта
остаются достижимыми и при лимите 20%, и при 25%, и при 45%. Вечерний
осмотр использует фон hq_evening с более сильным затемнением. Текст и
кнопки выводятся в полупрозрачной панели внизу экрана, чтобы игрок видел
лагерь и его детали; затемнение фона минимальное.

ESC игнорируется (escape_action = "none").
При открытии создаётся автосейв в слот autosave.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль.

### function `_load_scenes`

Строка 81.

```python
def _load_scenes()
```

Загружает данные обязательных сцен из конфига.

Читает configs/content/mandatory_scenes.json. При отсутствии
файла, ошибке парсинга или неверном типе возвращает пустой
словарь, и экран работает на встроенных фолбэках.

Returns:
    dict: Данные сцен по идентификаторам.

### class `MandatorySceneScreen`

Строка 96.

Экран обязательной сцены.

Блокирует действия игрока до завершения сцены. ESC не закрывает
экран (escape_action = "none"), клики вне кнопок игнорируются.
Фон и текст зависят от конфига и калькуляции потерь дивизии.

Attributes:
    scene_id (str): Идентификатор сцены.
    title (str): Заголовок сцены.
    text (str): Текст сцены с подставленными потерями.
    bg (pygame.Surface): Фоновая сцена лагеря.
    camp_state (str | None): Состояние лагеря (fresh/wounded/
        critical) для утренней сцены.
    loss_percent (int): Округлённые потери дивизии в процентах.
    btn_continue (Button | None): Кнопка «Продолжить».
    btn_night_duty (Button | None): Кнопка «Ночное дежурство».
    btn_sleep (Button | None): Кнопка «Спать».
    forced_sleep (bool): Флаг принудительного сна.

### method `MandatorySceneScreen.__init__`

Строка 120.

```python
def __init__(self, app, scene_id)
```

Инициализирует экран обязательной сцены.

Сливает данные конфига с фолбэками, вычисляет потери дивизии,
выбирает фон и текст, создаёт кнопки и автосейв.

Args:
    app: Экземпляр приложения (App).
    scene_id (str): Идентификатор сцены
        ("morning_inspection" или "evening_inspection").

### method `MandatorySceneScreen._player_loss_percent`

Строка 213.

```python
def _player_loss_percent(self)
```

Потери дивизии игрока в процентах.

        Использует накопленный счётчик ``Detachment.losses``: текущая сила
        может колебаться в бою, поэтому она не годится для отчёта о
        безвозвратных потерях.

### method `MandatorySceneScreen._loss_limit_percent`

Строка 226.

```python
def _loss_limit_percent(self)
```

Порог поражения дивизии в процентах из сюжетного конфига.

### method `MandatorySceneScreen._autosave`

Строка 232.

```python
def _autosave(self)
```

Создаёт автосейв в слот autosave.

Исключения подавляются, чтобы не прерывать показ сцены.

### method `MandatorySceneScreen.finish_scene`

Строка 244.

```python
def finish_scene(self)
```

Завершает сцену без дополнительных действий.

Уведомляет time_system о завершении сцены и закрывает экран.

### method `MandatorySceneScreen.choose_night_duty`

Строка 256.

```python
def choose_night_duty(self)
```

Обрабатывает выбор ночного дежурства.

Завершает сцену, передаёт выбор в time_system и закрывает экран.

### method `MandatorySceneScreen.choose_sleep`

Строка 269.

```python
def choose_sleep(self)
```

Обрабатывает выбор сна.

Завершает сцену, передаёт отказ от дежурства в time_system
и закрывает экран.

### method `MandatorySceneScreen._wrap_text`

Строка 284.

```python
def _wrap_text(text, font, max_width)
```

Переносит текст по ширине.

Args:
    text (str): Исходный текст.
    font (pygame.font.Font): Шрифт для измерения ширины.
    max_width (int): Максимальная ширина строки в пикселях.

Returns:
    list[str]: Список строк.

### method `MandatorySceneScreen.handle_event`

Строка 307.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для данного экрана.

События передаются только кнопкам сцены; клики вне кнопок
игнорируются, ESC не закрывает экран.

Args:
    event (pygame.event.Event): Событие pygame.

### method `MandatorySceneScreen.draw`

Строка 327.

```python
def draw(self, screen)
```

Отрисовывает экран обязательной сцены.

Порядок: фоновая сцена лагеря, лёгкое затемнение,
полупрозрачная панель внизу, заголовок, текст сцены с
переносом по ширине, кнопки управления.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/role_select.py`

### Модуль

Строка 1.

view/screens/role_select.py

Экран выбора роли игрока.

Роли читаются из ``configs/roles/roles.json``. Сейчас доступна одна роль —
номинальный лидер фракции-автомата. После выбора роль сохраняется в
``app.selected_role``; сюжет при запуске генерирует по ней кампанийный
пресет (персонажи, фракции, организации, среда, события).

Экран не знает о конкретных ролях: новая роль появляется в JSON и сразу
становится доступной, если не скрыта флагом ``available``.

### function `_wrap`

Строка 24.

```python
def _wrap(font, text, max_width)
```

Разбить текст на строки по ширине шрифта.

### class `RoleSelectScreen`

Строка 42.

Экран выбора роли.

Показывает доступные роли крупными кнопками и пояснение под каждой.
Клик по роли сразу переводит к выбору фракции, если у роли включён
``faction_choice``, иначе — к выбору сюжета. Роль меняет смысл кампании,
но не блокирует дальнейший поток.

### method `RoleSelectScreen.select`

Строка 78.

```python
def select(self, role_id)
```

Зафиксировать роль и перейти к выбору фракции или сюжета.

## `view/screens/rts_screen.py`

### Модуль

Строка 1.

Интерактивная 2-D изометрическая карта кампании (RTS-слой).

Экран заменяет прежний командный пункт. Он получает состояние из
``warfare.WarfareSimulation`` через ``CampaignEngine`` и показывает:

* изометрическую сетку 24×24 с плавно интерполированными иконками юнитов
  и разведением перекрывающихся жетонов при плотном контакте;
* выделение рамкой, приказы движения/атаки/обороны/отдыха;
* явную цель для сосредоточенного огня (клик по врагу или ПКМ);
* боевые частицы — трассеры, вспышки выстрелов и дуги ближнего боя;
* реальное время с паузой и множителем скорости (x1/x2/x4/x8; часы идут
  по минутам, войсковой такт — раз в 5 игровых минут);
* масштабирование карты колесом мыши, клавишами +/- и кнопками;
* информационную панель потребностей выбранного подразделения
  (самообеспечение) и отдельную панель личных потребностей командира;
* быстрый доступ к приказам адъютанта, журналу, логистике и рации.

Графика юнитов — намеренные плейсхолдеры: цветные жетоны, полосы силы и
морали. Позже их можно заменить спрайтами без изменения логики экрана.

### class `Particle`

Строка 91.

Простейшая боевая частица.

### class `RTSScreen`

Строка 160.

Основной игровой экран кампании.

### method `RTSScreen._build_terrain`

Строка 235.

```python
def _build_terrain(self)
```

Один раз нарисовать изометрическую подложку.

### method `RTSScreen._project`

Строка 270.

```python
def _project(self, cell)
```

Спроецировать клетку на экран с учётом текущего масштаба.

### method `RTSScreen._scaled_terrain`

Строка 289.

```python
def _scaled_terrain(self)
```

Кэш масштабированной подложки карты.

### method `RTSScreen._loss_limit_percent`

Строка 437.

```python
def _loss_limit_percent(self)
```

Порог поражения по потерям дивизии из сюжетного конфига.

### method `RTSScreen.select_all_units`

Строка 443.

```python
def select_all_units(self)
```

Выделить все живые подразделения игрока (Ctrl+A / клик по «ВСЕ»).

### method `RTSScreen._group_indices`

Строка 452.

```python
def _group_indices(self, number)
```

Живые индексы отделений, записанных в группу ``number``.

### method `RTSScreen.assign_group`

Строка 460.

```python
def assign_group(self, number)
```

Записать текущее выделение в группу (Ctrl+1…6).

### method `RTSScreen.select_group`

Строка 475.

```python
def select_group(self, number)
```

Выбрать группу под общий приказ (Shift/Alt+1…6).

### method `RTSScreen._unit_at`

Строка 495.

```python
def _unit_at(self, pos)
```

Индекс подразделения под курсором (или None).

### method `RTSScreen._prune_selection`

Строка 520.

```python
def _prune_selection(self)
```

Убрать из выделения уничтоженные/исчезнувшие подразделения.

### method `RTSScreen.command_plan_hold`

Строка 562.

```python
def command_plan_hold(self)
```

Армейский план: занять и держать рубеж.

### method `RTSScreen.command_plan_advance`

Строка 571.

```python
def command_plan_advance(self)
```

Армейский план: наступать на выбранную цель.

### method `RTSScreen._issue_plan_target`

Строка 589.

```python
def _issue_plan_target(self, cell)
```

Shift+ПКМ: перенести рубеж или направление плана.

### method `RTSScreen.command_attack_nearest`

Строка 629.

```python
def command_attack_nearest(self)
```

Атаковать выбранную цель, иначе — ближайшего для каждого.

### method `RTSScreen._issue_attack`

Строка 696.

```python
def _issue_attack(self, enemy_idx)
```

Сосредоточить огонь выделенных подразделений на одной цели.

### method `RTSScreen.command_focus_hover`

Строка 719.

```python
def command_focus_hover(self)
```

Сконцентрировать огонь на враге под курсором (клавиша F).

### method `RTSScreen._report_loss_status`

Строка 797.

```python
def _report_loss_status(self)
```

Показать и записать в журнал приближение к порогу поражения.

### method `RTSScreen._trigger_battle_outcome`

Строка 823.

```python
def _trigger_battle_outcome(self)
```

Передать исход боя в общий сюжетный обработчик победы/поражения.

### method `RTSScreen._combat_interval_real`

Строка 886.

```python
def _combat_interval_real(self)
```

Сколько реальных секунд длится один 5-минутный войсковой такт.

### method `RTSScreen._sync_render_positions`

Строка 899.

```python
def _sync_render_positions(self, dt=0.0, snap=False)
```

Плавно провести жетоны между клетками боевой сетки.

        Ядро двигает отделение на клетку за такт. Рендер растягивает этот
        переход на весь реальный интервал такта, поэтому движение выглядит
        непрерывным, а не рывком раз в несколько секунд.

### method `RTSScreen._update_display_positions`

Строка 952.

```python
def _update_display_positions(self, dt=0.0)
```

Развести жетоны, чтобы плотный контакт не превращался в кашу.

        Покоящиеся жетоны служат якорями. Для идущих добавляется короткое
        сглаживание: даже если соседи на секунду переставили их местами,
        картинка не дёргается, а плавно догоняет новую точку.

### method `RTSScreen._handle_ui_click`

Строка 1210.

```python
def _handle_ui_click(self, pos, mods=0)
```

Клик по списку юнитов, группам, масштабу и потребностям.

### method `RTSScreen._draw_groups`

Строка 1363.

```python
def _draw_groups(self, screen)
```

Компактные чипы групп: клик — выбрать, ПКМ/Ctrl — записать.

### method `RTSScreen._draw_plan_overlay`

Строка 1558.

```python
def _draw_plan_overlay(self, screen)
```

Показать рубеж или стрелу наступления на карте.

### method `RTSScreen._contact_frontline_points`

Строка 1651.

```python
def _contact_frontline_points(self)
```

Средние точки боёв: по ним рисуется линия соприкосновения.

### method `RTSScreen._draw_contact_lines`

Строка 1669.

```python
def _draw_contact_lines(self, screen)
```

Показать фактическую линию соприкосновения сторон.

        Это не граница секторов и не приказ: линия строится только по
        реальным парам ``engine.engagements``, поэтому исчезает, когда бой
        прекращается. Тонкие связи между парами показывают, кто именно
        держит фронт, а пунктир — его общий контур.

### method `RTSScreen._draw_sector_status`

Строка 1821.

```python
def _draw_sector_status(self, screen)
```

Компактная сводка четырёх проекций: сила, нажим, прорыв.

### method `RTSScreen._draw_commander_panel`

Строка 2020.

```python
def _draw_commander_panel(self, screen)
```

Личные потребности командира: без действий за подразделения.

## `view/screens/saves_menu.py`

### Модуль

Строка 1.

view/screens/saves_menu.py

Экран меню сохранений.

Отображает список доступных файлов сохранений из директории saves,
отсортированный по имени, не более MAX_VISIBLE_SAVES записей.
Позволяет выбрать сохранение для загрузки, создать новое сохранение
и удалить существующее. При отсутствии сохранений отображает
сообщение «Пока пусто».

Операции меню фиксируются в журнале operation_ozverin.log в корне
проекта и дублируются в консоль.

### class `SavesMenuScreen`

Строка 33.

Экран меню сохранений.

Строит фоновую панель, кнопки списка сохранений (не более
MAX_VISIBLE_SAVES), кнопки удаления для каждой записи, кнопку
нового сохранения и кнопку «Назад».

Attributes:
    panel (Panel): Фоновая панель меню.
    buttons (list[Button]): Кнопки списка, удаления,
        нового сохранения и «Назад».
    empty (bool): Флаг отсутствия сохранений.

### method `SavesMenuScreen.__init__`

Строка 48.

```python
def __init__(self, app)
```

Инициализирует экран меню сохранений.

Сканирует файлы сохранений через list_saves, создаёт кнопки
для первых MAX_VISIBLE_SAVES записей, кнопки удаления,
кнопку нового сохранения и кнопку «Назад».

Args:
    app: Экземпляр приложения (App).

### method `SavesMenuScreen.load`

Строка 104.

```python
def load(self, name)
```

Обрабатывает выбор файла сохранения для загрузки.

Вызывает app.load_game для восстановления состояния.

Args:
    name (str): Имя выбранного файла сохранения.

### method `SavesMenuScreen.delete`

Строка 116.

```python
def delete(self, name)
```

Обрабатывает удаление файла сохранения.

Удаляет файл через delete_save и перестраивает экран
для отображения обновлённого списка.

Args:
    name (str): Имя удаляемого файла сохранения.

### method `SavesMenuScreen.new_save`

Строка 131.

```python
def new_save(self)
```

Обрабатывает создание нового сохранения.

Формирует имя слота на основе текущего игрового дня и
времени, вызывает app.save_game и перестраивает экран.
Если time_system отсутствует, операция не выполняется.

### method `SavesMenuScreen.handle_event`

Строка 148.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для данного экрана.

Событие последовательно передаётся всем кнопкам меню.
Если одна из кнопок обработала событие, дальнейшая
обработка прекращается.

Args:
    event (pygame.event.Event): Событие pygame.

### method `SavesMenuScreen.draw`

Строка 163.

```python
def draw(self, screen)
```

Отрисовывает экран меню сохранений.

Порядок отрисовки:
1. Фоновая панель.
2. Заголовок «Сохранения».
3. При отсутствии сохранений — сообщение «Пока пусто».
4. Кнопки списка сохранений, кнопки удаления, кнопка
   нового сохранения и кнопка «Назад».

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/settings_menu.py`

### Модуль

Строка 1.

view/screens/settings_menu.py

Экран настроек игры.

Отображает переключаемые параметры (звук, полный экран, анимации боя)
в виде кнопок с текущим состоянием. Каждое переключение перестраивает
список кнопок. Кнопка «Назад» закрывает экран.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль.

### class `SettingsMenuScreen`

Строка 23.

Экран настроек.

Хранит словарь настроек и список кнопок. Каждое переключение
значения перестраивает список кнопок для отображения нового
состояния.

Attributes:
    panel (Panel): Фоновая панель экрана.
    settings (dict): Словарь настроек вида {имя: bool}.
    buttons (list[Button]): Кнопки параметров и кнопка «Назад».

### method `SettingsMenuScreen.__init__`

Строка 37.

```python
def __init__(self, app)
```

Инициализирует экран настроек.

Создаёт фоновую панель, задаёт начальные значения настроек
и строит список кнопок.

Args:
    app: Экземпляр приложения (App).

### method `SettingsMenuScreen._rebuild`

Строка 57.

```python
def _rebuild(self)
```

Перестраивает список кнопок по текущим значениям настроек.

Для каждой настройки создаётся кнопка с текстом
«Имя: вкл» или «Имя: выкл». В конце добавляется кнопка «Назад».

### method `SettingsMenuScreen.toggle`

Строка 86.

```python
def toggle(self, name)
```

Переключает значение указанной настройки на противоположное.

После переключения перестраивает список кнопок.

Args:
    name (str): Имя настройки для переключения.

### method `SettingsMenuScreen.handle_event`

Строка 103.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для данного экрана.

Событие последовательно передаётся всем кнопкам настроек.
Если одна из кнопок обработала событие, дальнейшая обработка
прекращается.

Args:
    event (pygame.event.Event): Событие pygame.

### method `SettingsMenuScreen.draw`

Строка 118.

```python
def draw(self, screen)
```

Отрисовывает экран настроек.

Порядок отрисовки:
1. Фоновая панель.
2. Заголовок «Настройки».
3. Кнопки параметров и кнопка «Назад».

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/storyline_select.py`

### Модуль

Строка 1.

view/screens/storyline_select.py

Экран выбора сюжета.

Сканирует директорию configs/storylines/ через list_storylines,
отображает выбранную роль, список доступных сюжетов с названиями и
кнопку «Назад». При выборе сюжета загружает его конфигурацию и запускает
процесс создания персонажа через app.start_storyline; тот же вызов
генерирует кампанийный пресет по роли.

События сканирования и выбора сюжета записываются в журнал
operation_ozverin.log в корне проекта и дублируются в консоль.

### class `StorylineSelectScreen`

Строка 26.

Экран выбора сюжета.

Отображает фоновую панель, заголовок, до пяти кнопок сюжетов
и кнопку «Назад». При отсутствии сюжетов показывает сообщение
«Пока пусто».

Attributes:
    panel (Panel): Фоновая панель экрана.
    buttons (list[Button]): Кнопки списка сюжетов и кнопка «Назад».
    empty (bool): Флаг отсутствия доступных сюжетов.

### method `StorylineSelectScreen.__init__`

Строка 40.

```python
def __init__(self, app)
```

Инициализирует экран выбора сюжета.

Сканирует доступные сюжеты, создаёт кнопки для первых пяти
записей и кнопку «Назад».

Args:
    app: Экземпляр приложения (App).

### method `StorylineSelectScreen.select`

Строка 81.

```python
def select(self, storyline_id)
```

Обрабатывает выбор сюжета.

Загружает конфигурацию сюжета по идентификатору и запускает
процесс создания персонажа. Если конфигурация не загружена,
запуск не выполняется.

Args:
    storyline_id (str): Идентификатор выбранного сюжета.

### method `StorylineSelectScreen.handle_event`

Строка 102.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для данного экрана.

Событие последовательно передаётся всем кнопкам.
Если одна из кнопок обработала событие, дальнейшая
обработка прекращается.

Args:
    event (pygame.event.Event): Событие pygame.

### method `StorylineSelectScreen.draw`

Строка 117.

```python
def draw(self, screen)
```

Отрисовывает экран выбора сюжета.

Порядок отрисовки:
1. Фоновая панель.
2. Заголовок «Выбор сюжета».
3. Если сюжетов нет — сообщение «Пока пусто».
4. Кнопки списка сюжетов и кнопка «Назад».

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/screens/visual_novel.py`

### Модуль

Строка 1.

view/screens/visual_novel.py

Экран визуальной новеллы.

Отображает последовательность слайдов с изображениями и текстом.
ESC или кнопка «Пропустить» пропускают интро и вызывают callback
завершения, который обычно выполняет replace_all следующего экрана.
Экран не pop'ит сам себя: следующую ступень ставит коллбэк.

События инициализации, перелистывания, пропуска и завершения
записываются в журнал operation_ozverin.log в корне проекта
и дублируются в консоль.

### class `VisualNovelScreen`

Строка 27.

Экран визуальной новеллы.

Показывает слайды по порядку. Каждый слайд содержит изображение
и текст. Игрок может перейти к следующему слайду или пропустить
всю последовательность.

Attributes:
    slides (list[dict]): Список слайдов. Каждый слайд — словарь
        с ключами "image" (имя ассета) и "text" (текст слайда).
    current_slide (int): Индекс текущего слайда.
    on_finish (callable): Callback, вызываемый при завершении
        или пропуске новеллы. Обычно выполняет replace_all.
    images (list[pygame.Surface]): Загруженные поверхности
        изображений для каждого слайда.
    btn_next (Button): Кнопка «Далее».
    btn_skip (Button): Кнопка «Пропустить».

### method `VisualNovelScreen.__init__`

Строка 49.

```python
def __init__(self, app, slides, on_finish_callback)
```

Инициализирует экран визуальной новеллы.

Загружает изображения для каждого слайда. Если изображение
не указано, используется чёрная заглушка.

Args:
    app: Экземпляр приложения (App).
    slides (list[dict]): Список слайдов. Каждый слайд — словарь
        с ключами "image" (имя ассета) и "text" (текст).
    on_finish_callback (callable): Callback завершения новеллы.

### method `VisualNovelScreen._finish`

Строка 85.

```python
def _finish(self)
```

Завершает визуальную новеллу.

Вызывает callback завершения, который обычно выполняет
replace_all следующего экрана. Новелла не остаётся в стеке.

### method `VisualNovelScreen.next_slide`

Строка 100.

```python
def next_slide(self)
```

Переключает на следующий слайд.

Если слайдов больше нет, завершает новеллу.

### method `VisualNovelScreen.skip`

Строка 115.

```python
def skip(self)
```

Пропускает всю последовательность слайдов.

Сразу вызывает завершение новеллы.

### method `VisualNovelScreen.on_escape`

Строка 128.

```python
def on_escape(self)
```

Обработчик нажатия ESC (escape_action == "custom").

ESC эквивалентен нажатию кнопки «Пропустить».

### method `VisualNovelScreen.handle_event`

Строка 136.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для данного экрана.

Поддерживает:
- Клик левой кнопкой мыши (не по кнопкам) — следующий слайд.
- Пробел или Enter — следующий слайд.
- Кнопки «Далее» и «Пропустить».

Args:
    event (pygame.event.Event): Событие pygame.

### method `VisualNovelScreen.draw`

Строка 162.

```python
def draw(self, screen)
```

Отрисовывает текущий слайд визуальной новеллы.

Порядок отрисовки:
1. Фоновое изображение текущего слайда (или чёрный фон).
2. Полупрозрачная панель для текста в нижней части экрана.
3. Текст текущего слайда с переносом по ширине.
4. Индикатор прогресса (номер слайда / всего).
5. Кнопки «Далее» и «Пропустить».

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### method `VisualNovelScreen._wrap_text`

Строка 203.

```python
def _wrap_text(text, font, max_width)
```

Разбивает текст на строки по заданной максимальной ширине.

Args:
    text (str): Исходный текст.
    font (pygame.font.Font): Шрифт для измерения ширины.
    max_width (int): Максимальная ширина строки в пикселях.

Returns:
    list[str]: Список строк, каждая из которых не превышает
        max_width.

## `view/support/__init__.py`

Нет docstrings.

## `view/support/camp_state.py`

### Модуль

Строка 1.

Выбор варианта утреннего лагеря по потерям дивизии.

Пороги не задаются абсолютными процентами: предел поражения меняется
вместе с сюжетом. Поэтому весь диапазон ``0..предел`` делится на три
полосы, и каждый фон ``camp_fresh`` / ``camp_wounded`` / ``camp_critical``
остаётся достижимым при любом разумном лимите.

### function `camp_state_for_loss`

Строка 16.

```python
def camp_state_for_loss(loss_percent, loss_limit_percent)
```

Вернуть ``fresh``, ``wounded`` или ``critical`` для потерь.

    ``loss_percent`` — округлённые потери дивизии в процентах,
    ``loss_limit_percent`` — порог поражения из сюжета. Если лимит
    некорректен, используется безопасное значение 1, чтобы не делить на
    ноль; для кампании это нештатная ситуация.

## `view/support/config_loader.py`

### Модуль

Строка 1.

Безопасная загрузка JSON-конфигов для UI-слоя.

### function `load_json`

Строка 11.

```python
def load_json(path, default=None)
```

Прочитать JSON; вернуть ``default`` при отсутствии/ошибке.

## `view/support/content.py`

### Модуль

Строка 1.

Контент интерфейса: приказы, документы, блокнот, диалоги, решения.

Файлы лежат в ``configs/content/``. Это данные UI-слоя, а не математическая
модель; загрузчик не трогает ``simulation.py`` и ``warfare.py``.

### class `Content`

Строка 15.

Контейнер JSON-контента, используемого экранами ``view``.

## `view/support/effects.py`

### Модуль

Строка 1.

Декларативные эффекты приказов и решений.

Поддерживаются поля ``targets`` (``player`` или entity id), ``add_voltages``,
``set_segments`` и ``log``. Эффекты применяются к адаптеру ``CampaignState``,
который переводит их в приказы/состояние отделений нового войскового слоя.

### class `EffectInterpreter`

Строка 13.

Применить декларативный эффект к кампании.

## `view/support/geometry.py`

### Модуль

Строка 1.

Геометрия бригадного боя и историческая модель потерь.

Бой в ``view`` ведётся не «стенка на стенку»: у бригады есть четыре
проекции (фронт, левый фланг, правый фланг и тыл). На каждом направлении
может развернуться ограниченное число рот — *фронт* участка. Поэтому
двукратное общее превосходство противника ещё не даёт троекратного
превосходства в точке соприкосновения, необходимого для прорыва
подготовленной обороны.

Модель потерь намеренно отделена от тактического ядра ``warfare``:
``CampaignEngine`` после каждого пятиминутного такта восстанавливает силу,
которую ядро потратило на «обмен огнём», и начисляет потери по историческим
суточным нормам. Это позволяет сохранить каноническое поведение
``simulation.py`` и ``build_demo_scenario`` и при этом получить правдоподобную
динамику кампании:

* оборона не прорвана — до 4% потерь дивизии в сутки;
* оборона прорвана — 12–15% в сутки;
* после прорыва рота, у которой противник уже в фланге/тылу, теряет
  значительно больше, а организованный отход ограничивает потери;
* пока оборона держится, атакующий теряет больше обороняющегося;
* разные проекции несут разные потери и дают разный вклад силы.

### class `CombatContext`

Строка 174.

Локальный контекст роты на прорванном участке.

    Это «сообщение» между геометрией суперсистемы (фронт/проекции/прорыв)
    и автоматом отделения: насколько близко противник подошёл к его флангу
    или тылу и сохраняет ли рота боевой порядок при отходе. Потери начисляет
    по-прежнему ``FrontGeometry``, канонические ``simulation``/``warfare``
    не меняются.

### method `CombatContext.routed`

Строка 204.

```python
def routed(self)
```

Позиция смята, а организованного отхода нет.

        Полное окружение считается разгромом даже при приказе на отход:
        коридора для сохранения порядка уже нет.

### class `FrontGeometry`

Строка 213.

Четыре проекции бригады, фронтаж и модель истощения.

### method `FrontGeometry.sector_daily_rate`

Строка 270.

```python
def sector_daily_rate(self, side, sector)
```

Суточная потеря силы на конкретной проекции.

        Общая суточная норма распределяется по проекциям с разными весами,
        поэтому фронт, фланги и тыл теряют неодинаково. Возвращается доля
        силы *этого* участка за сутки.

### method `FrontGeometry._ordered_retreat`

Строка 300.

```python
def _ordered_retreat(det)
```

Отход с сохранением порядка, а не паническое бегство.

### method `FrontGeometry._threat_multiplier`

Строка 308.

```python
def _threat_multiplier(max_multiplier, threat_force, local_force)
```

Смягчить множитель, если в охват попала лишь малая часть сил.

### method `FrontGeometry._bearing`

Строка 314.

```python
def _bearing(self, det, enemy, facing)
```

Вернуть проекцию врага относительно роты и дистанцию.

### method `FrontGeometry._encirclement`

Строка 331.

```python
def _encirclement(self, det)
```

Измерить, замкнут ли вокруг роты коридор.

        Окружение — это не «много врагов рядом», а отсутствие свободного
        направления: угловые разрывы между ближайшими врагами не должны
        превышать ``ENCIRCLE_MAX_GAP``. Четыре роты с одной стороны фронта
        такой замер не проходят.

### method `FrontGeometry.combat_context`

Строка 370.

```python
def combat_context(self, det)
```

Оценить, чем для роты обернулся прорыв.

        До формального прорыва действует только один локальный сигнал:
        враг уже вплотную за спиной (``OVERRUN_REAR_RADIUS``). После
        прорыва учитываются фланг и тыл в более широком радиусе. Если рота
        отходит по приказу ``withdrawal``, её потери ограничиваются, даже
        когда позиция уже потеряна: она сохраняет боевые порядки, а не
        остаётся на разгром. Исключение — полное локальное окружение: там
        коридора нет, поэтому отход не отменяет капитуляцию.

### method `FrontGeometry.unit_daily_rate`

Строка 498.

```python
def unit_daily_rate(self, det)
```

Суточная потеря конкретной роты с учётом контекста прорыва.

### method `FrontGeometry._default_facing`

Строка 533.

```python
def _default_facing(self, side)
```

Фронт по умолчанию — в сторону центра масс противника.

### method `FrontGeometry.set_facing`

Строка 550.

```python
def set_facing(self, side, vector)
```

Явно задать фронт стороны (для приказов, снимков и тестов).

        В обычной кампании фронт выводится из движения строя; явное значение
        сохраняется, пока его не сбросят через ``clear_facing``.

### method `FrontGeometry.clear_facing`

Строка 564.

```python
def clear_facing(self, side=None)
```

Вернуть автоматический вывод фронта из движения.

### method `FrontGeometry._update_facing_from_motion`

Строка 580.

```python
def _update_facing_from_motion(self)
```

Повернуть фронт вслед за перемещением центра строя.

        Пока армия стоит, фронт не меняется. Как только центр сместился
        заметнее ``FACING_MOVE_EPSILON``, направление движения становится
        новым фронтом. Именно поэтому удар с востока по армии, идущей на
        север, считается ударом в правый (восточный) фланг, а не «фронтом».

### method `FrontGeometry._is_surrounded`

Строка 614.

```python
def _is_surrounded(self, center, enemies)
```

Проверить, что противник охватил строй по всему кругу.

        Используется максимальный угловой разрыв между направлениями на
        врагов: если он не больше ``SURROUND_MAX_GAP``, свободного выхода
        из кольца нет. Обычная линия фронта даёт разрыв около 180–300°.

### method `FrontGeometry._sector_for`

Строка 664.

```python
def _sector_for(self, det, frame)
```

Определить проекцию роты внутри уже посчитанного строя.

### method `FrontGeometry._infer_sector`

Строка 698.

```python
def _infer_sector(self, det)
```

Осторожная эвристика без строя (пустой снимок/старый сценарий).

### method `FrontGeometry.refresh_sectors`

Строка 711.

```python
def refresh_sectors(self)
```

Пересчитать проекции всех рот по текущему положению и фронту.

### method `FrontGeometry.sector_of`

Строка 725.

```python
def sector_of(self, det)
```

Проекция роты — всегда производная, а не сохранённая метка.

### method `FrontGeometry.recompute`

Строка 748.

```python
def recompute(self)
```

Пересобрать группы по проекциям и посчитать фронтаж.

### method `FrontGeometry.effective_force`

Строка 764.

```python
def effective_force(self, side, sector)
```

Сила, которую сторона реально может подать на проекцию.

        Учитывается фронтаж: в глубине могут стоять ещё роты, но на узком
        участке одновременно разворачивается лишь ``SECTOR_CAPACITY``.

### method `FrontGeometry.update`

Строка 810.

```python
def update(self, engaged_sides=None, tick=None)
```

Обновить давление на проекциях и зафиксировать прорывы.

        Прорыв не случается от одного численного перевеса: нужен устойчивый
        нажим. Это отделяет «бот старается» от «бот мгновенно сломал оборону».

### method `FrontGeometry._update_encirclement_clocks`

Строка 868.

```python
def _update_encirclement_clocks(self)
```

Продвинуть часовой механизм полного окружения.

        Счётчик живёт только пока рота активна и кольцо действительно
        замкнуто. Как только появился коридор, значение снимается: это не
        накопительный «штраф за нахождение рядом с врагом».

### method `FrontGeometry._surrender`

Строка 891.

```python
def _surrender(self, det, reason)
```

Сдать окружённую роту: полные потери, ``broken`` и флаг сдачи.

        Каноническое ядро не знает о кампанийном окружении, поэтому здесь
        выставляется тот же ``broken``, который оно использует для выбывших
        отделений. Остаток силы переводится в безвозвратные потери, иначе
        сдавшаяся рота выглядела бы в сводке как «живая».

### method `FrontGeometry.apply_attrition`

Строка 922.

```python
def apply_attrition(self, force_before, engaged_sides=None)
```

Начислить потери за прошедший такт по историческим нормам.

        Ядро уже потратило часть силы на обмен огнём и вернуло трение
        ``K_EFFECT``. Перед начислением потерь вызывающий код восстанавливает
        силу к началу такта, поэтому здесь учитываются только потери модели:
        так суточная норма не зависит от случайной силы удара.

## `view/support/log_journal.py`

### Модуль

Строка 1.

Служебный журнал UI-слоя ``view``.

Пишет в ``operation_ozverin.log`` в корне проекта и дублирует сообщения
уровня INFO и выше в консоль. Журнал не является частью математической
модели: это только диагностика интерфейса.

### function `get_logger`

Строка 15.

```python
def get_logger(name)
```

Вернуть именованный журнал с файловым и консольным обработчиками.

## `view/support/logistics.py`

### Модуль

Строка 1.

Логистика кампании: запасы, расход, подвоз и операции.

Модуль намеренно не меняет боевую математику ``warfare.py``: он ведёт
снабженческие запасы дивизии, переводит их в готовность подразделений
(``ui_supply``) и выполняет операции из ``configs/content/logistics.json``.
Потребности персонажей живут в ``needs.py``; логистика лишь поставляет
ресурсы, которые эти действия расходуют.

Классы запасов (I–VII) совпадают с конфигом и раскладываются в общий
словарь ``CampaignState.supplies``:

    I   — продовольствие      -> food
    II  — боеприпасы          -> ammo
    III — горючее             -> fuel
    IV  — медикаменты         -> medicine
    V   — инженерное имущество-> engineering
    VI  — вода                -> water
    VII — предметы морали     -> morale

«Влияние» (``influence``) — отдельный командирский ресурс: за него
запрашиваются конвои и штабные операции, но им не кормят людей.

### class `UnitSupply`

Строка 130.

Совместимый снимок снабжения одного отделения.

### class `Convoy`

Строка 143.

Конвой в пути: груз, ETA, риск и признак бесплатной автоколонны.

### class `LogisticsSystem`

Строка 189.

Запасы дивизии, готовность подразделений и операции снабжения.

### method `LogisticsSystem.daily_need`

Строка 297.

```python
def daily_need(self, key)
```

Оценка суточного расхода по всем живым подразделениям игрока.

### method `LogisticsSystem.on_tick`

Строка 327.

```python
def on_tick(self, seconds=300, engaged_names=None)
```

Списать довольствие и обновить готовность подразделений.

        Расход идёт по фактическому составу. Если запасов не хватает,
        готовность падает и мораль проседает; при покрытии — готовность
        медленно восстанавливается. Это единственное место, где логистика
        влияет на войска, и оно не вмешивается в ``warfare``.

### method `LogisticsSystem._adjust_morale`

Строка 395.

```python
def _adjust_morale(self, det, delta)
```

Изменить мораль роты через персонажей.

        ``refresh_psychology`` восстанавливает ``det.morale`` как среднее по
        персонажам, поэтому правка только агрегата была бы потеряна на
        следующем такте.

### method `LogisticsSystem._accrue_influence`

Строка 411.

```python
def _accrue_influence(self, minutes)
```

Начислить пассивное влияние и, если подошло время, автоколонну.

        Влияние — не топливо и не еда, поэтому оно не тратится на
        самообеспечение. Прирост дробный; интерфейс округляет его при
        отображении, но запас растёт уже с первого такта.

### method `LogisticsSystem.next_free_convoy_minutes`

Строка 433.

```python
def next_free_convoy_minutes(self)
```

Сколько игровых минут осталось до следующей автоколонны.

### method `LogisticsSystem._deliver_free_convoy`

Строка 439.

```python
def _deliver_free_convoy(self)
```

Отправить редкую бесплатную автоколонну (без влияния).

        Название метода сохранено для совместимости, но доставка теперь
        отложенная: сначала конвой едет, затем может прибыть полностью,
        частично или не прибыть вовсе.

### method `LogisticsSystem._schedule_convoy`

Строка 468.

```python
def _schedule_convoy(self, kind, cargo, free=False, risk=None, risk_scale=1.0, eta_minutes=None)
```

Поставить конвой в очередь и вернуть объект ``Convoy``.

### method `LogisticsSystem._process_convoys`

Строка 501.

```python
def _process_convoys(self, minutes)
```

Продвинуть конвои и разрешить прибывшие.

### method `LogisticsSystem._arrive_convoy`

Строка 514.

```python
def _arrive_convoy(self, convoy)
```

Разрешить один конвой. Вернуть конвой, если он задержан атакой.

### method `LogisticsSystem.convoy_status_rows`

Строка 565.

```python
def convoy_status_rows(self)
```

Активные конвои для оверлея логистики.

### method `LogisticsSystem._self_care`

Строка 581.

```python
def _self_care(self, det, coverage, minutes, engaged)
```

Автоматическое самообеспечение отделения из общих запасов.

        Эффект сознательно слабее ручных действий: подвоз поддерживает
        людей, но не отменяет усталость, страх и боевой стресс.

### method `LogisticsSystem.operation_cost`

Строка 613.

```python
def operation_cost(self, operation_id, count=1)
```

Стоимость операции на ``count`` выбранных подразделений.

        Базовая цена в конфиге задана за одну роту; при действии на несколько
        рот расход умножается на их число. Это не даёт «бесплатно» снабдить
        всю дивизию одной операцией и оставляет выбор, кого снабжать.

### method `LogisticsSystem._resolve_targets`

Строка 637.

```python
def _resolve_targets(self, targets=None)
```

Привести индексы/имена/объекты к живым ротам игрока.

        ``None`` означает «все живые роты игрока» (совместимость со старым
        вызовом). Пустой список — сознательный отказ от целей: игрок может
        не снабжать никого и тем самым лишить конкретные роты помощи.

### method `LogisticsSystem.apply_operation`

Строка 673.

```python
def apply_operation(self, operation_id, targets=None)
```

Выполнить операцию для одной или нескольких рот.

        ``targets`` может быть индексом, именем, объектом-отделением или
        списком таких значений. Стоимость умножается на число целей, а
        проверка запасов — общая (all-or-nothing): нельзя оплатить половину
        и оставить остальные роты без эффекта.

### method `LogisticsSystem.request_convoy`

Строка 744.

```python
def request_convoy(self, kind='general', risk=None)
```

Отправить конвой. Стоимость — влияние; прибытие отложенное.

        ``risk`` — необязательное переопределение вероятности атаки для
        тестов и сценарных проверок. В обычной игре риск вычисляется из
        обстановки, маршрута и черты командира.

### method `LogisticsSystem.morning_resupply`

Строка 781.

```python
def morning_resupply(self)
```

Ночной подвоз: небольшой бесплатный приток запасов.

        Это тоже колонна, а не телепорт: она отправляется утром и прибывает
        через несколько часов, поэтому игрок должен планировать запас.

### method `LogisticsSystem.status_rows`

Строка 803.

```python
def status_rows(self)
```

Строки для оверлея логистики.

## `view/support/needs.py`

### Модуль

Строка 1.

Потребности и их удовлетворение в кампанийном UI.

Модель 16 потребностей уже живёт в ``warfare.Character``. Этот модуль —
RPG-прослойка между интерфейсом и персонажами:

* хранит ресурсы (продовольствие, вода, медикаменты, влияние);
* выполняет **личные** действия командира и списывает ресурсы;
* ведёт кулдауны, чтобы одно действие не применялось каждый кадр;
* каждый такт «прокручивает» потребности подразделений, которые не были
  в бою (в бою это делает ``Detachment.after_combat``);
* выполняет лагерное довольствие утром и сон/дежурство вечером.

Подразделения больше не являются целями действий игрока: их базовые
потребности закрываются автоматически логистикой (``LogisticsSystem``),
а игрок заботится только о собственном персонаже-командире. Старый вызов
``apply(idx, action_id)`` сохранён для внутренних сценариев и регрессионных
тестов, но RTS-интерфейс его не использует.

Никакой новой математики боя здесь нет: действия меняют только
``Character.needs``, а агрегаты отделения пересчитываются штатным
``refresh_psychology``.

### class `NeedsSystem`

Строка 205.

Ресурсы, действия и пассивное движение потребностей.

### method `NeedsSystem.set_commander_trait`

Строка 259.

```python
def set_commander_trait(self, trait)
```

Зафиксировать черту из пролога без повторного применения бонусов.

### method `NeedsSystem._trait_action_definition`

Строка 266.

```python
def _trait_action_definition(self, action_id)
```

Личное действие с учётом черты командира.

### method `NeedsSystem.player_dead`

Строка 293.

```python
def player_dead(self)
```

Погиб ли персонаж игрока (здоровье достигло критического).

### method `NeedsSystem.can_apply`

Строка 307.

```python
def can_apply(self, idx, action_id)
```

Проверить действие без его выполнения.

### method `NeedsSystem.apply`

Строка 321.

```python
def apply(self, idx, action_id)
```

Выполнить действие удовлетворения для подразделения.

### method `NeedsSystem.status`

Строка 358.

```python
def status(self, idx)
```

Состояние действий для панели выбранного подразделения.

### method `NeedsSystem.player_needs_summary`

Строка 375.

```python
def player_needs_summary(self)
```

Средние (фактические) потребности персонажа игрока.

### method `NeedsSystem.can_apply_player`

Строка 382.

```python
def can_apply_player(self, action_id)
```

Проверить личное действие командира без его выполнения.

### method `NeedsSystem.apply_player`

Строка 397.

```python
def apply_player(self, action_id)
```

Выполнить личное действие командира (не подразделения).

### method `NeedsSystem.status_player`

Строка 427.

```python
def status_player(self)
```

Состояние личных действий для оверлея «Нужды».

### method `NeedsSystem._tick_player`

Строка 445.

```python
def _tick_player(self, seconds, engaged_names)
```

Прокрутить личные потребности командира за прошедший интервал.

### method `NeedsSystem._commander_self_care`

Строка 483.

```python
def _commander_self_care(self, seconds)
```

Базовое питание и вода командира из общих запасов.

        Без этого личные потребности росли бы независимо от склада, и
        командир умирал бы от жажды при полных цистернах. Расход маленький
        по сравнению с ротами, но реальный.

### method `NeedsSystem._apply_trait_morale`

Строка 524.

```python
def _apply_trait_morale(self, seconds)
```

Суточное влияние черты на мораль рот игрока.

        ``Detachment.refresh_psychology`` пересчитывает мораль из персонажей,
        поэтому менять надо именно персонажей, а не только агрегат.

### method `NeedsSystem.on_tick`

Строка 550.

```python
def on_tick(self, seconds=TICK_SECONDS, engaged_names=None)
```

Прокрутить потребности и кулдауны на один такт.

        Подразделения, которые участвовали в паре, уже получили
        ``after_combat`` внутри ``warfare``. Остальным нужен «мирный» такт,
        иначе их голод и усталость никогда не меняются.

### method `NeedsSystem.camp_morning`

Строка 598.

```python
def camp_morning(self)
```

Утреннее довольствие лагеря: бесплатное, но не полное.

### method `NeedsSystem.camp_night`

Строка 618.

```python
def camp_night(self, slept=True)
```

Ночь в лагере: сон восстанавливает силы, дежурство — нет.

## `view/support/rules.py`

### Модуль

Строка 1.

Минимальные правила решений для UI-каркаса.

Легаси-``RuleEngine`` менял битовые маски и метаморфозы мира. Здесь решения
интерфейса применяются через ``EffectInterpreter``; правило оставлено как
совместимый no-op, чтобы экран последствий работал без легаси-ядра.

### class `RuleEngine`

Строка 9.

Совместимый фасад: правила UI не меняют математическое ядро.

## `view/support/save_system.py`

### Модуль

Строка 1.

Сохранения UI-кампании.

Файлы лежат в ``saves/campaign/`` и не пересекаются со слотами арены из
``ui.save``. Сохраняется снимок ``CampaignState``, время и состояние сюжета.

### function `save_game`

Строка 51.

```python
def save_game(state, time_system, slot_name, scenario_path=None, storyline_snapshot=None, campaign_role=None, campaign_preset=None)
```

Записать снимок кампании. Вернуть путь к файлу.

### function `load_game`

Строка 81.

```python
def load_game(slot_name)
```

Прочитать сохранение или вернуть None.

### function `deserialize_world_state`

Строка 96.

```python
def deserialize_world_state(state, snapshot)
```

Применить снимок кампании к уже собранному состоянию.

### function `list_saves`

Строка 102.

```python
def list_saves()
```

Список сохранений, новые первыми.

### function `delete_save`

Строка 126.

```python
def delete_save(slot_name)
```

Удалить сохранение. Вернуть True, если файл существовал.

## `view/support/scenario.py`

### Модуль

Строка 1.

Сборка мира для UI-каркаса и загрузка карты.

Кампанийный UI играет за стрелковую бригаду: 16 рот против 32 рот
противника (двукратное общее превосходство). Математическое ядро остаётся
каноническим ``warfare``; геометрия четырёх проекций и исторические
суточные потери живут в ``view.support.geometry``.

Канонический ``warfare.build_demo_scenario`` не используется для UI-боя:
он остаётся эталонным демо-сценарием и не должен менять поведение при
изменениях интерфейса.

### function `load_map`

Строка 66.

```python
def load_map(map_name)
```

Загрузить ``scenarios/maps/<map_name>.npz`` или вернуть заглушку.

### function `_archetypes_for`

Строка 80.

```python
def _archetypes_for(side, index, sector)
```

Четыре человека в роте; состав зависит от роли и проекции.

### function `_characters_from_roster`

Строка 124.

```python
def _characters_from_roster(roster, side, prefix, index, sector, seed)
```

Собрать четырёх персонажей роты из пресета кампании.

    Пресет задаёт имя, seed, архетип и стартовые потребности. Если в ростере
    меньше четырёх человек (старый/неполный пресет), недостающих добирает
    штатный генератор архетипов — сценарий не должен ломаться.

### function `build_brigade_scenario`

Строка 199.

```python
def build_brigade_scenario(seed=7, turns=CAMPAIGN_TURNS, rosters=None)
```

Собрать UI-сценарий: 16 рот игрока против 32 рот бота.

    Штатная сила роты из четырёх человек — 14. Итого у игрока 224, у
    противника 448: ровно 1:2. Для прорыва подготовленной обороны этого
    недостаточно; на каждом участке фронтаж ограничивает одновременный
    ввод сил.

    ``rosters`` — необязательный словарь ``{side: [[character, ...], ...]}``
    из пресета кампании. Он подменяет только имена, seed, архетипы и
    стартовые потребности персонажей; численность и баланс рот остаются
    штатными.

### function `_coerce_preset`

Строка 261.

```python
def _coerce_preset(value)
```

Принять пресет объектом, словарём или путём к JSON.

### function `_attach_preset_organizations`

Строка 290.

```python
def _attach_preset_organizations(sim, preset, state)
```

Подключить организации пресета к канонической симуляции.

### function `build_world`

Строка 317.

```python
def build_world(scenario_path=None, campaign_snapshot=None, content=None, seed=7, campaign_preset=None, campaign_role=None)
```

Собрать ``CampaignState`` из бригадного UI-сценария.

    ``scenario_path`` принимается ради совместимости с сюжетными конфигами,
    но не подменяет математическую модель. Снимок кампании применяется
    поверх восстановленного на нужный такт мира.

    ``campaign_preset`` — необязательный пресет (``CampaignPreset``, dict или
    путь). Он добавляет имена/потребности персонажей, организации-автоматы и
    метаданные роли, не меняя штатное соотношение 16 против 32.

## `view/support/storyline.py`

### Модуль

Строка 1.

core/storyline.py

Интерпретатор сюжетов.

Загружает конфигурации сюжетов из configs/storylines/, проверяет
условия победы и поражения, управляет последовательностью сцен,
разрешает варианты сцен по переменным сюжета и предоставляет
сериализацию состояния для системы сохранений.

Сюжет состоит из трёх файлов: основного (метаданные, условия,
финальные сцены, приказы адъютанту), файла создания персонажа
(шаги с выборами) и файла сцен (последовательность). Сканер
list_storylines показывает в меню выбора только основные файлы;
файлы с суффиксами _char и _scenes считаются вспомогательными.

Условия сюжета интерпретируются только данным модулем и не связаны
с условиями правил (RuleEngine) или боевых фаз (CombatSystem).
Неизвестный тип условия возвращает False. Исходы проверяются
ежедневно на вечерней границе через app.check_storyline_end_of_day.

События загрузки, проверки условий и навигации по сценам
фиксируются в журнале operation_ozverin.log и дублируются в консоль.

### function `_build_logger`

Строка 43.

```python
def _build_logger()
```

Создаёт и возвращает журнал модуля storyline.

Файловый обработчик пишет в operation_ozverin.log в корне проекта
с уровнем DEBUG, консольный выводит сообщения уровня INFO и выше.
Обработчики добавляются один раз; повторный вызов возвращает
уже настроенный журнал без дублирования.

Returns:
    logging.Logger: Настроенный журнал.

### function `loss_limit_percent`

Строка 82.

```python
def loss_limit_percent(storyline, default=DEFAULT_LOSS_LIMIT_PERCENT)
```

Порог поражения дивизии в процентах из конфига сюжета.

    Ищет ``manpower_loss_above`` в ``lose_conditions``, включая вложенные
    ``all_of``/``any_of``. Значение в конфиге хранится долей (0.25), а
    интерфейсу нужен целый процент (25). Если условие не найдено или
    повреждено, возвращается ``default``.

### function `list_storylines`

Строка 114.

```python
def list_storylines()
```

Сканирует директорию сюжетов и возвращает список доступных сюжетов.

Читает только основные JSON-файлы (без суффиксов _char и _scenes).
Для каждого файла извлекает storyline_id, title и description.
Повреждённые файлы пропускаются без исключения.

Returns:
    list[dict]: Список словарей с полями storyline_id, title,
        description для каждого найденного сюжета.

### function `load_storyline`

Строка 148.

```python
def load_storyline(storyline_id)
```

Загружает полную конфигурацию сюжета по идентификатору.

Объединяет основной файл сюжета, файл создания персонажа и
файл сцен в единый словарь. Если основной файл не найден,
возвращает None. Отсутствие вспомогательных файлов не является
ошибкой: соответствующие поля загружаются пустыми.

Args:
    storyline_id: Идентификатор сюжета (имя файла без .json).

Returns:
    dict | None: Полная конфигурация сюжета или None, если
        основной файл не найден.

### function `_unit_alive`

Строка 204.

```python
def _unit_alive(state, idx)
```

Проверяет, живо ли подразделение.

Подразделение считается уничтоженным, если сегмент condition
равен 0 или канал U_manpower <= 0.

Args:
    state: Состояние игрового мира (WorldState).
    idx: Индекс сущности.

Returns:
    bool: True, если подразделение живо.

### function `_all_enemies_destroyed`

Строка 228.

```python
def _all_enemies_destroyed(state)
```

Проверяет, уничтожены ли все вражеские подразделения.

Врагами считаются военные юниты, чья фракция отличается от
фракции игрока и не является нейтральной.

Args:
    state: Состояние игрового мира (WorldState).

Returns:
    bool: True, если все враги уничтожены или state is None.

### function `_all_player_units_destroyed`

Строка 256.

```python
def _all_player_units_destroyed(state)
```

Проверить, что у игрока не осталось живых боевых подразделений.

### function `_player_dead`

Строка 272.

```python
def _player_dead(state)
```

Погиб ли персонаж игрока (командир).

    Смерть наступает, когда потребность ``health`` доходит до критического
    значения (``1.0``; в интерфейсе — 100). Состояние хранится в
    ``NeedsSystem.commander`` и переживает сохранение/загрузку.

### function `check_storyline_condition`

Строка 293.

```python
def check_storyline_condition(condition, state, time_system, storyline_state)
```

Проверяет одно условие сюжета.

Поддерживаемые типы: day_at_least, manpower_loss_above, player_dead,
all_enemies_destroyed, all_player_units_destroyed, all_of, any_of.
Неизвестный тип возвращает False. Пустое или None-условие
возвращает False.

Для manpower_loss_above требуется initial_manpower в
storyline_state (создание персонажа завершено). Порог считается по
накопленным потерям всей дивизии, а не по силе одного отделения.

Args:
    condition: Словарь условия с полем type.
    state: Состояние игрового мира (WorldState).
    time_system: Система игрового времени (GameTimeSystem).
    storyline_state: Служебное состояние сюжета (dict).

Returns:
    bool: Результат проверки условия.

### class `StorylineInterpreter`

Строка 359.

Интерпретатор сюжета.

Управляет последовательностью сцен, переменными сюжета,
проверкой условий победы/поражения и сериализацией состояния.
Не содержит захардкоженной сюжетной логики — только
интерпретацию декларативных конфигов.

Attributes:
    app: Экземпляр приложения (App).
    storyline: Полная конфигурация сюжета (dict).
    current_scene_index: Индекс текущей сцены в последовательности.
    variables: Переменные сюжета (пол, происхождение и т.д.).
    state: Служебное состояние (initial_manpower и прочее).
    finished: Флаг завершения сюжета.

### method `StorylineInterpreter.__init__`

Строка 377.

```python
def __init__(self, app, storyline)
```

Инициализирует интерпретатор сюжета.

Args:
    app: Экземпляр приложения (App).
    storyline: Полная конфигурация сюжета (dict),
        возвращённая load_storyline.

### method `StorylineInterpreter.get_current_scene`

Строка 398.

```python
def get_current_scene(self)
```

Возвращает текущую сцену из последовательности.

Returns:
    dict | None: Словарь сцены или None, если
        последовательность исчерпана.

### method `StorylineInterpreter.advance`

Строка 418.

```python
def advance(self)
```

Продвигает индекс текущей сцены на единицу.

### method `StorylineInterpreter.set_variable`

Строка 425.

```python
def set_variable(self, key, value)
```

Устанавливает переменную сюжета.

Args:
    key: Имя переменной.
    value: Значение переменной.

### method `StorylineInterpreter.get_variable`

Строка 436.

```python
def get_variable(self, key, default=None)
```

Возвращает значение переменной сюжета.

Args:
    key: Имя переменной.
    default: Значение по умолчанию, если переменная не установлена.

Returns:
    Значение переменной или default.

### method `StorylineInterpreter.interpolate`

Строка 449.

```python
def interpolate(self, text)
```

Подставить переменные сюжета в строку без изменения неизвестных.

### method `StorylineInterpreter.resolve_variant`

Строка 479.

```python
def resolve_variant(self, scene)
```

Разрешает вариант сцены по переменной сюжета.

Если сцена содержит поле variant_by, ищет значение
соответствующей переменной в variants и возвращает
объединённый словарь. Если переменная не установлена
или ключ отсутствует, возвращает исходную сцену.

Args:
    scene: Словарь сцены.

Returns:
    dict: Разрешённая сцена (исходная или с подставленным вариантом).

### method `StorylineInterpreter.check_win_conditions`

Строка 509.

```python
def check_win_conditions(self)
```

Проверяет условия победы.

Все условия из win_conditions должны быть истинны.
При пустом списке возвращает False.

Returns:
    bool: True, если все условия победы выполнены.

### method `StorylineInterpreter.check_lose_conditions`

Строка 531.

```python
def check_lose_conditions(self)
```

Проверяет условия поражения.

Достаточно любого истинного условия из lose_conditions.
При пустом списке возвращает False.

Returns:
    bool: True, если хотя бы одно условие поражения выполнено.

### method `StorylineInterpreter.get_save_snapshot`

Строка 553.

```python
def get_save_snapshot(self)
```

Возвращает сериализуемый снимок состояния интерпретатора.

Включает storyline_id, индекс текущей сцены, переменные,
служебное состояние и флаг завершения.

Returns:
    dict: Снимок состояния для сохранения.

### method `StorylineInterpreter.load_from_snapshot`

Строка 574.

```python
def load_from_snapshot(self, snapshot)
```

Восстанавливает состояние интерпретатора из снимка.

Применяет индекс сцены, переменные, служебное состояние
и флаг завершения. Пустой или None-снимок игнорируется.

Args:
    snapshot: Словарь снимка из сохранения или None.

## `view/support/time_system.py`

### Модуль

Строка 1.

Игровое время UI-каркаса.

Это упрощённая замена легаси-``GameTimeSystem``: она ведёт часы по
минутам, выполняет действия из ``configs/content/time_actions.json`` и раз в
несколько игровых минут (по умолчанию 5) продвигает войсковой такт
``warfare``. Никакой отдельной математической модели времени здесь нет.

### class `CampaignTimeSystem`

Строка 38.

Часы кампании и очередь действий игрока.

### method `CampaignTimeSystem.advance`

Строка 109.

```python
def advance(self, seconds)
```

Продвинуть часы по минутам и выполнить накопившиеся такты.

        Войсковой такт выполняется не каждую минуту, а раз в
        ``combat_tick_seconds`` (по умолчанию 5 минут). Это позволяет часам
        идти по минутам, не превращая бой в 300-кратную прокрутку.

## `view/support/traits.py`

### Модуль

Строка 1.

Личностные черты командира и их игровые модификаторы.

Черта выбирается в прологе и хранится в переменной сюжета ``trait``.
Раньше она влияла только на шум разведки; теперь это единый реестр
модификаторов, который используют потребности, логистика и интерфейс.

Все коэффициенты — множители (1.0 — нейтрально), кроме ``morale_baseline``
(пункты морали), ``troop_morale_per_day`` (пункты морали в сутки) и
``action_bonus`` (множители к конкретным личным действиям).

### function `normalize_trait`

Строка 131.

```python
def normalize_trait(trait)
```

Вернуть известный ключ черты или ``None``.

### function `trait_label`

Строка 137.

```python
def trait_label(trait)
```

Человекочитаемое название черты для интерфейса.

### function `trait_summary`

Строка 145.

```python
def trait_summary(trait)
```

Короткое описание эффекта черты для интерфейса.

### function `trait_modifiers`

Строка 153.

```python
def trait_modifiers(trait)
```

Полный набор модификаторов для черты (с нейтральными значениями).

### function `get_report_noise_modifier`

Строка 172.

```python
def get_report_noise_modifier(app)
```

Множитель шума разведки (1.0 — нейтрально).

## `view/support/world.py`

### Модуль

Строка 1.

Адаптер нового войскового слоя (``warfare.py``) к экранам ``view``.

Легаси-UI ожидал ``WorldState`` с массивами сегментов/напряжений и движок
с приказами. Здесь эти ожидания реализованы как тонкий *presентера*: данные
берутся из ``WarfareSimulation``, а действия игрока переводятся в пассивные
приказы ``warfare.Order``. Математическое ядро не изменяется.

### function `_distance`

Строка 43.

```python
def _distance(a, b)
```

Манхэттенское расстояние между клетками поля.

### function `_clamp_cell`

Строка 48.

```python
def _clamp_cell(point)
```

Привести точку сетки 24×24 к допустимой клетке.

### function `_unit_vector`

Строка 56.

```python
def _unit_vector(vector, fallback=(1.0, 0.0))
```

Нормировать вектор; при нулевой длине вернуть запасной.

### class `ArmyPlan`

Строка 66.

Замысел армии: держать рубеж или наступать по оси.

    ``line`` хранится двумя клетками рубежа, ``target`` — точкой, которую
    выбрал игрок. Если цели нет, наступление автоматически ведёт армию к
    центру противника. План сериализуется в снимок кампании.

### class `SegmentLayout`

Строка 132.

Совместимый носитель описания сегментов (для UI).

### class `VoltageLayout`

Строка 139.

Совместимый носитель описания каналов (для UI).

### class `ClassConfig`

Строка 146.

Минимальная конфигурация класса боевой единицы.

### class `OrderType`

Строка 188.

Совместимая запись таблицы приказов.

### class `OrderTable`

Строка 196.

Таблица приказов с атрибутом ``orders`` как в легаси.

### class `CampaignState`

Строка 218.

Состояние кампании поверх ``warfare.WarfareSimulation``.

### method `CampaignState.projected_force`

Строка 373.

```python
def projected_force(self, det)
```

Сила роты с учётом проекции (фронт/фланг/тыл).

### method `CampaignState.casualty_fraction`

Строка 380.

```python
def casualty_fraction(self, idx)
```

Доля безвозвратных потерь отделения (0..1).

        Считается по накопленному ``Detachment.losses``, а не по текущей
        силе: сила может колебаться в бою, но понесённые потери не исчезают.

### method `CampaignState.division_loss_percent`

Строка 393.

```python
def division_loss_percent(self)
```

Потери дивизии игрока в процентах (все боевые подразделения).

### class `CampaignEngine`

Строка 721.

Минимальный движок для UI: такт, приказы и цели перемещения.

### method `CampaignEngine._sync_focus_targets`

Строка 881.

```python
def _sync_focus_targets(self)
```

Передать UI-цели в боевое ядро для сосредоточенного огня.

### method `CampaignEngine.set_focus_target`

Строка 885.

```python
def set_focus_target(self, idx, enemy)
```

Явно назначить противника целью отделения.

        ``enemy`` может быть индексом, именем или объектом отделения.
        Возвращает True, если цель принята.

### method `CampaignEngine.clear_focus_target`

Строка 909.

```python
def clear_focus_target(self, idx_or_name=None)
```

Снять явную цель (для одного отделения или для всех).

### method `CampaignEngine.plan_for`

Строка 936.

```python
def plan_for(self, side=None)
```

Вернуть план стороны (по умолчанию — игрока).

### method `CampaignEngine._advance_target`

Строка 970.

```python
def _advance_target(self, side, axis, center=None)
```

Начальная цель наступления — центр противостоящей стороны.

        Цель фиксируется, а не пересчитывается на центр врага каждый такт.
        Иначе после прохода армий друг друга ось разворачивалась на 180°,
        и роты бесконечно дёргались поперёк фронта.

### method `CampaignEngine._default_hold_line`

Строка 1011.

```python
def _default_hold_line(self, units, side=None)
```

Рубеж по текущему построению, перпендикулярно фронту.

        Если армия уже стоит линией, план не заставляет её сдвигаться:
        каждый сохраняет своё место, но получает явную цель «держать
        рубеж». После выбора точки на карте рубеж переносится туда.

### method `CampaignEngine._line_through`

Строка 1031.

```python
def _line_through(self, target, units, side=None)
```

Построить рубеж через выбранную точку.

### method `CampaignEngine._deactivate_ui_orders`

Строка 1051.

```python
def _deactivate_ui_orders(self, side)
```

Погасить прежние ручные приказы при включении плана.

        Иначе армейский приказ суммировался бы со старыми сигналами рот,
        хотя план уже снова охватил всю сторону.

### method `CampaignEngine._apply_plan_order`

Строка 1066.

```python
def _apply_plan_order(self, side, plan)
```

Выдать широкий пассивный приказ, соответствующий плану.

### method `CampaignEngine.set_auto_plan`

Строка 1093.

```python
def set_auto_plan(self, mode, target=None, line=None, side=None, axis=None, auto=False, silent=False, keep_exemptions=False)
```

Включить армейский план.

        Args:
            mode: ``hold`` (занять рубеж) или ``advance`` (наступать).
            target: клетка сетки 24×24; для обороны задаёт точку рубежа,
                для наступления — направление/цель.
            line: явные две точки рубежа (приоритетнее ``target``).
            side: сторона; по умолчанию игрок.
            axis: явная ось наступления, если цель не задана.
            auto: план выставлен ИИ, а не игроком.
            silent: не писать событие в журнал (инициализация мира).
            keep_exemptions: не снимать ручные исключения (перенос
                рубежа/направления без повторного охвата всей армии).

### method `CampaignEngine.clear_auto_plan`

Строка 1193.

```python
def clear_auto_plan(self, side=None, silent=False)
```

Снять автоплан и остановить его оперативные цели.

### method `CampaignEngine._mark_plan_exempt`

Строка 1310.

```python
def _mark_plan_exempt(self, det)
```

Ручной приказ роте временно выводит её из армейского плана.

### method `CampaignEngine.plan_status_text`

Строка 1322.

```python
def plan_status_text(self, side=None)
```

Короткая строка для панели приказов.

### method `CampaignEngine._ensure_default_plans`

Строка 1352.

```python
def _ensure_default_plans(self)
```

Загрузить планы из снимка или включить наступление ИИ.

### method `CampaignEngine._step_with_avoidance`

Строка 1376.

```python
def _step_with_avoidance(self, det, target, blocked, steps=1)
```

Шаг к цели, не заходя на занятые противником клетки.

        Автоплан ведёт роту в глубину, поэтому прямая линия к цели может
        проходить через чужой жетон. В этом случае выбирается боковой
        вариант с минимальным расстоянием до цели — это и есть манёвр
        вдоль фронта, а не «прошивание» строя насквозь.

### method `CampaignEngine._nearest_forward_enemy`

Строка 1440.

```python
def _nearest_forward_enemy(self, det, axis, max_distance=None)
```

Ближайший противник в передней полусфере плана.

### method `CampaignEngine._contact_maneuver`

Строка 1460.

```python
def _contact_maneuver(self, det, goal, axis)
```

Движение в соприкосновении: давление или обход.

        Если рота сильнее локальной группы врага, она продавливает цель
        плана. Если слабее — смещается вдоль фронта, ищет стык и не стоит
        вечно на одной и той же дистанции. Это ключевое отличие от старого
        поведения, где обе стороны замирали на ``engage_range``.

### method `CampaignEngine._advance_ai`

Строка 1576.

```python
def _advance_ai(self)
```

Движение войск по приказу или армейскому автоплану.

        Явно выбранная цель (``set_focus_target``) имеет приоритет над
        ближайшим врагом. Ручной приказ роте временно исключает её из
        автоплана. План ведёт роты к своим полосам, а в соприкосновении
        позволяет давить или обходить, а не стоять на одной дистанции.

### method `CampaignEngine.set_cell_target`

Строка 1721.

```python
def set_cell_target(self, idx, target)
```

Поставить цель движения в координатах боевой сетки 24x24.

## `view/ui/__init__.py`

Нет docstrings.

## `view/ui/asset_loader.py`

### Модуль

Строка 1.

view/ui/asset_loader.py

Загрузчик графических ассетов с кэшированием, рекурсивным поиском
и автоматическим созданием плейсхолдеров при отсутствии файла.

Поддерживаемые форматы: PNG, JPG, JPEG.

Порядок поиска:
1. Прямой относительный путь внутри assets/images, включая
   вложенные директории, указанные в имени ассета;
2. Рекурсивный поиск по базовому имени во всех вложенных
   директориях assets/images.

Если файл не найден, создаётся полупрозрачный плейсхолдер
серо-синего цвета с рамкой.

События разрешения путей, загрузки и создания плейсхолдеров
записываются в журнал operation_ozverin.log в корне проекта
и дублируются в консоль.

### class `AssetLoader`

Строка 69.

Статический загрузчик изображений с кэшированием.

Ищет изображения в директории assets/images. Сначала пытается
использовать имя как прямой относительный путь (с подстановкой
расширений .png, .jpg, .jpeg). Если файл не найден, выполняет
рекурсивный поиск по базовому имени во всех вложенных
директориях assets/images.

Все загруженные изображения кэшируются по ключу (имя, размер).
Разрешённые абсолютные пути кэшируются по имени, чтобы не
выполнять повторный обход директорий.

Class Attributes:
    BASE_DIR (str): Абсолютный путь к корню проекта.
    IMAGES_DIR (str): Абсолютный путь к директории с изображениями.
    _cache (dict): Кэш загруженных поверхностей по ключу (name, size).
    _path_cache (dict): Кэш разрешённых путей по имени (name -> path|None).

### method `AssetLoader._direct_path`

Строка 100.

```python
def _direct_path(name)
```

Проверяет имя ассета как прямой относительный путь
внутри assets/images.

Если базовое имя содержит расширение, сначала проверяется
точное совпадение пути. Затем последовательно пробуются
расширения "", ".png", ".jpg", ".jpeg".

Args:
    name (str): Имя ассета (относительный путь, возможно
        с расширением).

Returns:
    str | None: Абсолютный путь к файлу или None.

### method `AssetLoader._recursive_path`

Строка 129.

```python
def _recursive_path(name)
```

Выполняет рекурсивный поиск файла ассета по базовому имени
во всех вложенных директориях assets/images.

Обход детерминированный: директории и файлы обходятся в
сортированном порядке, первое совпадение побеждает.

Если имя содержит явное расширение, ищется точное совпадение
базового имени с расширением. Иначе ищется файл с тем же
стеблом и любым поддерживаемым расширением.

Args:
    name (str): Имя ассета.

Returns:
    str | None: Абсолютный путь к файлу или None.

### method `AssetLoader._resolve_path`

Строка 171.

```python
def _resolve_path(name)
```

Разрешает имя ассета в абсолютный путь.

Сначала проверяет прямой путь, затем рекурсивный поиск.
Результат (включая None) кэшируется в _path_cache.

Args:
    name (str): Имя ассета.

Returns:
    str | None: Абсолютный путь к файлу или None.

### method `AssetLoader.load`

Строка 194.

```python
def load(name, size=None)
```

Загружает изображение по имени с опциональным масштабированием.

Порядок поиска:
1. Прямой относительный путь внутри assets/images.
2. Рекурсивный поиск по базовому имени во всех вложенных
   директориях assets/images.

Если файл не найден ни одним способом, создаётся плейсхолдер.
Результат кэшируется. При повторном вызове с теми же
аргументами возвращается кэшированная поверхность.

Args:
    name (str): Имя ассета (относительный путь без расширения
        или с расширением).
    size (tuple[int, int] | None): Целевой размер (width, height).
        Если None, изображение не масштабируется
        (плейсхолдер создаётся размером 320x200).

Returns:
    pygame.Surface: Загруженное или сгенерированное изображение.

## `view/ui/music_manager.py`

### Модуль

Строка 1.

view/ui/music_manager.py

Менеджер фоновой музыки с очередью категорий и мягким затуханием.

Категории: overture, ambient, victorious, tragic.
Треки категории лежат в music/<category>/.

Поведение:
- текущий трек всегда доигрывает до конца, затем стартует следующий
  трек текущей категории либо очередь сменой категории;
- смена категории без fade ждёт окончания текущего трека;
- смена категории с fade мягко глушит текущий трек и стартует новую.

События загрузки треков, переключения категорий и ошибок
воспроизведения записываются в журнал operation_ozverin.log
и дублируются в консоль средствами core.log_journal.

### class `MusicManager`

Строка 33.

Менеджер фоновой музыки по категориям.

Сканирует поддиректории music/<category>/ при инициализации,
поддерживает очередь смены категорий, мягкое затухание через
pygame.mixer.music.fadeout и автоматический переход к следующему
треку внутри категории. Метод update() должен вызываться каждый
кадр из главного цикла приложения.

Attributes:
    music_dir (str): Путь к корневой директории музыки.
    tracks (dict[str, list[str]]): Списки путей к трекам по категориям.
    _index (dict[str, int]): Текущие индексы воспроизведения по категориям.
    current_category (str | None): Текущая активная категория.
    pending_category (str | None): Категория, ожидающая запуска.
    fade_pending (bool): Флаг активного затухания.
    enabled (bool): Флаг доступности микшера pygame.

### method `MusicManager.__init__`

Строка 53.

```python
def __init__(self, music_dir: str)
```

Инициализирует менеджер музыки.

Сканирует поддиректории категорий, инициализирует микшер
pygame. При отсутствии директории или ошибке инициализации
микшера устанавливает enabled=False и логирует предупреждение.

Args:
    music_dir: Путь к корневой директории музыки.

### method `MusicManager._scan`

Строка 79.

```python
def _scan(self)
```

Сканирует поддиректории категорий и заполняет плейлисты.

Для каждой категории из CATEGORIES ищет директорию
music/<category>/, сортирует файлы по имени и фильтрует
по поддерживаемым расширениям. Отсутствующие директории
пропускаются с предупреждением.

### method `MusicManager._has_tracks`

Строка 106.

```python
def _has_tracks(self, cat: str)
```

Проверяет наличие треков в указанной категории.

Args:
    cat: Имя категории.

Returns:
    bool: True, если в категории есть хотя бы один трек.

### method `MusicManager.request_category`

Строка 118.

```python
def request_category(self, cat: str, fade: bool=False)
```

Запрашивает смену музыкальной категории.

Без fade текущий трек доигрывается до конца, после чего
запускается первый трек новой категории. С fade текущий
трек мягко затухает через FADE_OUT_MS миллисекунд, и новая
категория стартует после завершения затухания. Если запрошена
та же категория и нет ожидающей смены, запрос игнорируется.
Если категория пуста или микшер отключён, запрос игнорируется.

Args:
    cat: Имя категории из CATEGORIES.
    fade: Если True, выполнить мягкое затухание текущего трека.

### method `MusicManager._start_category`

Строка 150.

```python
def _start_category(self, cat: str)
```

Запускает воспроизведение категории с первого трека.

Устанавливает текущую категорию, сбрасывает индекс
воспроизведения и запускает первый трек.

Args:
    cat: Имя категории для запуска.

### method `MusicManager._play_track`

Строка 164.

```python
def _play_track(self, cat: str, idx: int)
```

Загружает и однократно запускает трек по индексу.

Индекс оборачивается по длине списка треков категории.
При ошибке загрузки или воспроизведения логирует
предупреждение и не меняет текущую категорию.

Args:
    cat: Имя категории.
    idx: Индекс трека в списке категории.

### method `MusicManager.update`

Строка 191.

```python
def update(self)
```

Обрабатывает переходы между треками и категориями.

Должен вызываться каждый кадр из главного цикла.
При активном затухании ждёт его завершения и запускает
ожидающую категорию. При завершении текущего трека
запускает ожидающую категорию или следующий трек текущей.
Не выполняет никаких действий, если микшер отключён
или музыка уже играет.

## `view/ui/needs_overlay.py`

### Модуль

Строка 1.

Личные потребности командира и способы их удовлетворения.

Слева — все 16 потребностей персонажа игрока, их значения и подсказка,
какое действие или событие их снижает. Справа — личные действия командира
с эффектами, стоимостью и кулдауном. Подразделения в этом экране не
выбираются и не «кормятся» вручную: их самообеспечение выполняет
``LogisticsSystem`` автоматически.

Экран не вводит новой математики: он вызывает ``NeedsSystem.apply_player``
и показывает её состояние.

### class `NeedsOverlay`

Строка 45.

Все личные потребности командира и действия по ним.

### method `NeedsOverlay._selected_idx`

Строка 61.

```python
def _selected_idx(self)
```

Оставлено для совместимости; действия больше не адресованы юниту.

## `view/ui/orders_overlay.py`

### Модуль

Строка 1.

Оверлей приказов выбранным подразделениям.

Экран открывается с RTS-карты и перечисляет все приказы из
``configs/content/orders.json``. Выбор применяется к текущему выделению
через ``CampaignEngine.assign_order``. Если на карте выбрана явная цель,
наступательные приказы сосредоточивают огонь на ней; иначе используется
ближайший противник. Точное движение по-прежнему задаётся правым кликом.

### class `UnitOrdersOverlay`

Строка 35.

Список приказов, применимых к выделенным подразделениям.

## `view/ui/overlays.py`

### Модуль

Строка 1.

view/ui/overlays.py

Оверлеи: блокнот, бинокль, рация, логистика, лог тика.

Блокнот отображает контент вкладок и живых донесений в виде текста
на страницах открытого блокнота: строки заполняют левую страницу,
затем правую; при переполнении обоих листов создаётся следующий
разворот. Текст выводится на прозрачной поверхности, наклоняется
под углом листа и накладывается внутрь белого листа с внутренними
полями. Навигация осуществляется стрелками листания, закрытие —
кнопкой и ESC.

Бинокль ведёт поэтапную разведку сектора: донесение уточняется по
стадиям, а погрешность оценки умножается на усталость наблюдателя
и черту персонажа (report_noise_mult). Текст донесения переносится
по ширине панели и клипсуется внутри неё, не налезая на кнопки.

Рация поддерживает пагинацию списка подразделений, отображает
ролевые имена и выводит журнал связи в отдельной зоне.

События записываются в журнал operation_ozverin.log и дублируются
в консоль.

### function `_wrap_text`

Строка 66.

```python
def _wrap_text(text, font, max_width)
```

Разбивает текст на строки по максимальной ширине.

Args:
    text (str): Исходный текст.
    font (pygame.font.Font): Шрифт для измерения ширины.
    max_width (int): Максимальная ширина строки в пикселях.

Returns:
    list[str]: Список строк, каждая из которых не превышает
        max_width пикселей.

### class `OverlayScreen`

Строка 95.

Базовый оверлей с панелью и кнопкой закрытия.

Attributes:
    panel (Panel): Фоновая панель оверлея.
    close_btn (Button): Кнопка закрытия.

### method `OverlayScreen.__init__`

Строка 104.

```python
def __init__(self, app, rect)
```

Инициализирует базовый оверлей.

Args:
    app: Экземпляр приложения (App).
    rect (tuple): Прямоугольник панели (x, y, w, h).

### method `OverlayScreen.draw_base`

Строка 121.

```python
def draw_base(self, screen, title)
```

Рисует затемнение, панель, заголовок и кнопку закрытия.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.
    title (str): Заголовок оверлея.

### class `NotebookOverlay`

Строка 138.

Оверлей открытого блокнота.

Контент вкладок и живой сводки донесений раскладывается по
разворотам увеличенного блокнота: текст заполняет левую
страницу, затем правую; при переполнении обоих листов
создаётся следующий разворот. Текст выводится на прозрачной
поверхности, наклоняется под углом листа и накладывается
внутрь белого листа с внутренними полями. Навигация
осуществляется стрелками листания, закрытие — кнопкой.

Attributes:
    notebook_img (pygame.Surface): Изображение открытого блокнота.
    spreads (list[tuple]): Список разворотов (левые, правые строки).
    page (int): Индекс текущего разворота.
    prev_rect (pygame.Rect): Зона клика для перехода назад.
    next_rect (pygame.Rect): Зона клика для перехода вперёд.

### method `NotebookOverlay.__init__`

Строка 158.

```python
def __init__(self, app)
```

Инициализирует блокнот.

Загружает изображение блокнота, формирует единый поток
текста из вкладок и живой сводки, раскладывает его по
разворотам страниц и создаёт элементы навигации.

Args:
    app: Экземпляр приложения (App).

### method `NotebookOverlay._order_label`

Строка 206.

```python
def _order_label(self, st, idx)
```

Возвращает название текущего приказа сущности.

Args:
    st: Состояние игрового мира (WorldState).
    idx (int): Индекс сущности.

Returns:
    str: Название приказа или «—».

### method `NotebookOverlay._unit_report_line`

Строка 226.

```python
def _unit_report_line(self, st, idx)
```

Формирует строку донесения о подразделении.

Args:
    st: Состояние игрового мира (WorldState).
    idx (int): Индекс сущности.

Returns:
    str: Строка донесения.

### method `NotebookOverlay._build_live_tab`

Строка 259.

```python
def _build_live_tab(self, app)
```

Строит живую вкладку донесений.

Args:
    app: Экземпляр приложения (App).

Returns:
    dict: Вкладка с донесениями о всех военных юнитах.

### method `NotebookOverlay._line_height`

Строка 278.

```python
def _line_height(self, kind)
```

Возвращает высоту строки для заданного типа текста.

Args:
    kind (str): Тип текста ("heading", "separator" или "line").

Returns:
    int: Высота строки в пикселях.

### method `NotebookOverlay._build_spreads`

Строка 294.

```python
def _build_spreads(self)
```

Строит список разворотов из потока строк контента.

Текст переносится по ширине узкой из двух страниц, заполняет
левую страницу, затем правую. При переполнении обоих листов
создаётся следующий разворот. Текст не заходит в нижнюю зону
страниц, где расположены стрелки листания.

Returns:
    list[tuple[list, list]]: Список разворотов. Каждый
        разворот — кортеж (строки левой страницы, строки
        правой страницы). Каждая строка — кортеж (kind, text).

### method `NotebookOverlay._blit_page`

Строка 353.

```python
def _blit_page(self, screen, lines, page_rect, angle)
```

Отрисовывает страницу с текстом на наклонённой поверхности.

Создаёт прозрачную поверхность, размещает на ней текст,
поворачивает на заданный угол и накладывает на экран
по центру целевого прямоугольника страницы.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.
    lines (list[tuple]): Список строк (kind, text).
    page_rect (pygame.Rect): Прямоугольник страницы.
    angle (float): Угол поворота в градусах.

### method `NotebookOverlay._draw_arrow`

Строка 399.

```python
def _draw_arrow(self, screen, rect, direction)
```

Рисует стрелку навигации в заданном прямоугольнике.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.
    rect (pygame.Rect): Прямоугольник, в котором рисуется стрелка.
    direction (str): Направление стрелки ("prev" или "next").

### method `NotebookOverlay.prev_page`

Строка 422.

```python
def prev_page(self)
```

Переходит на предыдущий разворот.

### method `NotebookOverlay.next_page`

Строка 428.

```python
def next_page(self)
```

Переходит на следующий разворот.

### method `NotebookOverlay.handle_event`

Строка 434.

```python
def handle_event(self, event)
```

Обрабатывает события: закрытие, прокрутка колесом мыши
и клики по стрелкам листания.

Args:
    event (pygame.event.Event): Событие pygame.

### method `NotebookOverlay.draw`

Строка 456.

```python
def draw(self, screen)
```

Отрисовывает открытый блокнот.

Порядок отрисовки: затемнение фона, увеличенное изображение
открытого блокнота, левая и правая страницы текущего
разворота, индикатор номера разворота внизу правой страницы,
стрелки навигации в нижних углах страниц, кнопка закрытия.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### class `BinocularsOverlay`

Строка 491.

Бинокль с выбором сектора и стадиями наблюдения.

Донесение уточняется по стадиям: стадия 0 — начало наблюдения;
стадия 1 — качественная оценка (много/немало, тип с возможной
ошибкой); стадия 2 — вилка числа рот и тенденция приказа
противника (соседние приказы могут путаться); стадия 3 —
численная оценка с небольшой погрешностью. Погрешность
умножается на усталость наблюдателя и черту персонажа
(report_noise_mult). Текст донесения переносится по ширине
панели и клипсуется внутри неё, не налезая на кнопки.

Attributes:
    SECTORS (tuple): Названия секторов.
    PANEL_RECT (pygame.Rect): Область панели донесения.
    TEXT_RECT (pygame.Rect): Область текста внутри панели.
    LINE_HEIGHT (int): Высота строки текста.
    STAGE_WAIT_SECONDS (int): Время ожидания между стадиями.
    TYPE_LABELS (dict): Подписи типов целей.
    ORDER_SCALE (tuple): Шкала приказов по агрессивности.
    TENDENCY_LABELS (dict): Подписи тенденций приказов.
    current (int): Индекс текущего сектора.
    stage (int): Текущая стадия наблюдения (0–3).
    sector_buttons (list[Button]): Кнопки выбора сектора.
    close_btn (Button): Кнопка закрытия.
    panel (Panel): Панель донесения.
    btn_stop (Button): Кнопка прекращения наблюдения.
    btn_continue (Button): Кнопка продолжения/завершения.

### method `BinocularsOverlay.__init__`

Строка 547.

```python
def __init__(self, app)
```

Инициализирует бинокль.

Args:
    app: Экземпляр приложения (App).

### method `BinocularsOverlay.set_view`

Строка 606.

```python
def set_view(self, i)
```

Переключает сектор и сбрасывает стадию наблюдения.

Args:
    i (int): Индекс сектора (0–2).

### method `BinocularsOverlay.cancel_and_close`

Строка 617.

```python
def cancel_and_close(self)
```

Отменяет наблюдение и закрывает оверлей.

### method `BinocularsOverlay.advance_observation`

Строка 628.

```python
def advance_observation(self)
```

Продвигает стадию наблюдения, тратя игровое время.

### method `BinocularsOverlay._fatigue`

Строка 640.

```python
def _fatigue(self)
```

Возвращает текущую усталость наблюдателя (0..1).

Returns:
    float: Усталость наблюдателя.

### method `BinocularsOverlay._noise_mult`

Строка 652.

```python
def _noise_mult(self)
```

Возвращает множитель погрешности наблюдателя.

Черта персонажа (report_noise_mult), умноженная на фактор
усталости. Ограничен, чтобы отчёт не становился абсурдным.

Returns:
    float: Множитель погрешности [0.25, 3.0].

### method `BinocularsOverlay._noise_rng`

Строка 666.

```python
def _noise_rng(self, sector)
```

Детерминированный генератор шума для сектора и дня.

Args:
    sector (str): Название сектора.

Returns:
    random.Random: Генератор случайных чисел.

### method `BinocularsOverlay._is_dead`

Строка 681.

```python
def _is_dead(self, idx)
```

Проверяет, уничтожено ли подразделение.

Args:
    idx (int): Индекс сущности.

Returns:
    bool: True, если подразделение уничтожено.

### method `BinocularsOverlay._voltage`

Строка 701.

```python
def _voltage(self, idx, channel)
```

Возвращает напряжение канала или 0, если канала нет.

Args:
    idx (int): Индекс сущности.
    channel (str): Имя канала.

Returns:
    float: Значение напряжения.

### method `BinocularsOverlay._order_id`

Строка 718.

```python
def _order_id(self, idx)
```

Возвращает строковый ID текущего приказа сущности.

Args:
    idx (int): Индекс сущности.

Returns:
    str: ID приказа или "rest".

### method `BinocularsOverlay._order_label`

Строка 738.

```python
def _order_label(self, order_id)
```

Возвращает человекочитаемое название приказа.

Args:
    order_id (str): ID приказа.

Returns:
    str: Название приказа.

### method `BinocularsOverlay._sector_enemies`

Строка 755.

```python
def _sector_enemies(self, sector)
```

Возвращает индексы живых противников в секторе.

Args:
    sector (str): Название сектора.

Returns:
    list[int]: Индексы противников в секторе.

### method `BinocularsOverlay._sector_stats`

Строка 794.

```python
def _sector_stats(self, sector)
```

Агрегирует силы противника в секторе по ротам (size == 1).

Иерархия не даёт двойного счёта: учитываются только
сущности с сегментом size == 1 (роты).

Args:
    sector (str): Название сектора.

Returns:
    dict: Статистика сектора с ключами companies,
        manpower, tanks, guns, orders.

### method `BinocularsOverlay._dominant_order`

Строка 837.

```python
def _dominant_order(self, stats)
```

Возвращает приказ с наибольшим числом рот.

Args:
    stats (dict): Статистика сектора.

Returns:
    str: ID доминирующего приказа или "rest".

### method `BinocularsOverlay._tendency_of`

Строка 852.

```python
def _tendency_of(self, order_id)
```

Возвращает ключ тенденции приказа.

Args:
    order_id (str): ID приказа.

Returns:
    str: Ключ тенденции (attack, move, defense, rest).

### method `BinocularsOverlay._noised_order`

Строка 878.

```python
def _noised_order(self, rng, mult, order_id)
```

Возвращает приказ с шумом.

С вероятностью, растущей от множителя наблюдателя, приказ
сдвигается на соседний по шкале агрессии (агрессивная
путается с умеренной, но не с осторожной).

Args:
    rng (random.Random): Генератор случайных чисел.
    mult (float): Множитель погрешности.
    order_id (str): Исходный ID приказа.

Returns:
    str: Возможно изменённый ID приказа.

### method `BinocularsOverlay._true_type`

Строка 903.

```python
def _true_type(self, stats)
```

Возвращает истинный доминирующий тип цели в секторе.

Args:
    stats (dict): Статистика сектора.

Returns:
    str: Тип цели (tanks, fortifications, infantry).

### method `BinocularsOverlay._report_lines`

Строка 923.

```python
def _report_lines(self, sector)
```

Формирует строки донесения для текущей стадии наблюдения.

Погрешность растёт от множителя наблюдателя (черта и
усталость); в конце выводится строка поправки.

Args:
    sector (str): Название сектора.

Returns:
    list[str]: Строки донесения.

### method `BinocularsOverlay._view_asset`

Строка 1038.

```python
def _view_asset(self)
```

Подбирает ассет вида по оценке наблюдателя.

На ранних стадиях тип может быть определён с ошибкой,
на поздних — точно; количество — по численности.

Returns:
    str | None: Путь к ассету или None.

### method `BinocularsOverlay.handle_event`

Строка 1067.

```python
def handle_event(self, event)
```

Обрабатывает события кнопок бинокля.

Args:
    event (pygame.event.Event): Событие pygame.

### method `BinocularsOverlay.draw`

Строка 1084.

```python
def draw(self, screen)
```

Рисует бинокль.

Ассет вида, панель донесения, текст донесения с переносом
и клипсой внутри панели (не налезает на кнопки), кнопки
управления и сектора.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### class `LogisticsOverlay`

Строка 1132.

Склад, суточный расход, готовность и операции снабжения.

    Операции можно применять сразу к нескольким ротам: слева у каждой роты
    есть переключатель цели. Игрок может нажать «Все», «Никого» и вручную
    оставить без снабжения конкретные подразделения. Стоимость операции
    умножается на число выбранных целей.

### method `LogisticsOverlay._player_units`

Строка 1191.

```python
def _player_units(self)
```

Живые роты игрока — те же, что принимает логистика.

### method `LogisticsOverlay._init_targets`

Строка 1201.

```python
def _init_targets(self)
```

По умолчанию — выделенные в RTS роты, иначе все роты игрока.

### class `RadioOverlay`

Строка 1496.

Рация с пагинацией списка подразделений.

Отображает ролевые имена и выводит журнал связи в отдельной
зоне.

Attributes:
    units (list[tuple]): Список (индекс, entity_id) юнитов игрока.
    selected (int): Индекс выбранного юнита в списке units.
    page (int): Текущая страница списка.
    log (str): Текст журнала связи.
    radio_img (pygame.Surface): Изображение открытой рации.
    btn_connect (Button): Кнопка установки связи.
    btn_prev (Button): Кнопка предыдущей страницы.
    btn_next (Button): Кнопка следующей страницы.
    buttons (list[Button]): Кнопки юнитов текущей страницы.

### method `RadioOverlay.__init__`

Строка 1515.

```python
def __init__(self, app)
```

Инициализирует рацию.

Args:
    app: Экземпляр приложения (App).

### method `RadioOverlay._page_count`

Строка 1560.

```python
def _page_count(self)
```

Возвращает число страниц списка подразделений.

Returns:
    int: Число страниц (не менее 1).

### method `RadioOverlay._display_name`

Строка 1571.

```python
def _display_name(self, st, idx)
```

Строит ролевое имя: тактический индекс плюс роль внутри
дивизии.

Args:
    st: Состояние игрового мира (WorldState).
    idx (int): Индекс сущности.

Returns:
    str: Ролевое имя (не более 30 символов).

### method `RadioOverlay._build_unit_buttons`

Строка 1603.

```python
def _build_unit_buttons(self)
```

Строит кнопки подразделений текущей страницы.

### method `RadioOverlay.prev_page`

Строка 1620.

```python
def prev_page(self)
```

Листает страницы списка назад.

### method `RadioOverlay.next_page`

Строка 1626.

```python
def next_page(self)
```

Листает страницы списка вперёд.

### method `RadioOverlay.select`

Строка 1632.

```python
def select(self, i)
```

Выбирает подразделение по индексу.

Args:
    i (int): Индекс в списке units.

### method `RadioOverlay.connect`

Строка 1641.

```python
def connect(self)
```

Устанавливает связь и формирует сводку.

### method `RadioOverlay._order_label`

Строка 1682.

```python
def _order_label(self, st, idx)
```

Возвращает название текущего приказа сущности.

Args:
    st: Состояние игрового мира (WorldState).
    idx (int): Индекс сущности.

Returns:
    str: Название приказа или «—».

### method `RadioOverlay.handle_event`

Строка 1702.

```python
def handle_event(self, event)
```

Обрабатывает события кнопок рации.

Args:
    event (pygame.event.Event): Событие pygame.

### method `RadioOverlay.draw`

Строка 1725.

```python
def draw(self, screen)
```

Рисует рацию.

Список юнитов, кнопки пагинации, кнопка связи,
изображение рации, журнал связи в отдельной зоне.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### class `TurnLogOverlay`

Строка 1780.

Оверлей лога последнего тика.

Отображает последние 30 событий текущего тика.

Attributes:
    close_btn (Button): Кнопка закрытия.

### method `TurnLogOverlay.__init__`

Строка 1790.

```python
def __init__(self, app)
```

Инициализирует оверлей лога тика.

Args:
    app: Экземпляр приложения (App).

### method `TurnLogOverlay.handle_event`

Строка 1799.

```python
def handle_event(self, event)
```

Обрабатывает события: только закрытие.

Args:
    event (pygame.event.Event): Событие pygame.

### method `TurnLogOverlay.draw`

Строка 1809.

```python
def draw(self, screen)
```

Рисует лог тика.

Показывает последние 30 событий или сообщение об
отсутствии событий.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/ui/placeholders.py`

### Модуль

Строка 1.

view/ui/placeholders.py

Детерминированные процедурные плейсхолдеры для сцен ``view``.

### function `make_placeholder`

Строка 75.

```python
def make_placeholder(name, size=None, label='PLACEHOLDER')
```

Создать поверхность-плейсхолдер для имени ассета.

## `view/ui/screen_manager.py`

### Модуль

Строка 1.

view/ui/screen_manager.py

Стек экранов с централизованной обработкой ESC через атрибут
escape_action каждого экрана.

BaseScreen — базовый класс для всех экранов и оверлеев.
ScreenManager — менеджер стека экранов, обрабатывающий события,
обновление и отрисовку.

Операции над стеком (push, pop, replace_all, обработка ESC)
записываются в журнал operation_ozverin.log в корне проекта
и дублируются в консоль.

### function `_build_logger`

Строка 22.

```python
def _build_logger(name)
```

Создаёт и возвращает журнал с файловым и консольным обработчиками.

Файловый обработчик пишет в operation_ozverin.log в корне проекта
с уровнем DEBUG, консольный — с уровнем INFO.
Обработчики навешиваются один раз на имя журнала.

Args:
    name (str): Имя журнала.

Returns:
    logging.Logger: Настроенный журнал.

### class `BaseScreen`

Строка 64.

Базовый класс для всех экранов и оверлеев.

Каждый экран определяет поведение ESC через атрибут escape_action:
- "pop"    — ESC закрывает экран (оверлеи, меню, диалоги);
- "none"   — ESC игнорируется (главное меню);
- "custom" — экран сам обрабатывает ESC в методе on_escape().

Классовый атрибут show_time_hud управляет отрисовкой HUD
игрового времени: HUD отображается только тогда, когда в стеке
экранов присутствует хотя бы один экран с show_time_hud == True
(игровые сцены), и скрывается в меню, новеллах, сюжетах
и прочих неигровых экранах.

Attributes:
    app: Экземпляр приложения (App).
    escape_action (str): Поведение при нажатии ESC.
    show_time_hud (bool): Флаг отображения HUD игрового времени.

### method `BaseScreen.__init__`

Строка 88.

```python
def __init__(self, app)
```

Инициализирует экран.

Args:
    app: Экземпляр приложения (App).

### method `BaseScreen.handle_event`

Строка 97.

```python
def handle_event(self, event)
```

Обрабатывает событие pygame.

Вызывается ScreenManager.handle_event для текущего экрана.
По умолчанию ничего не делает. Подклассы переопределяют
этот метод для обработки ввода.

Args:
    event (pygame.event.Event): Событие pygame.

### method `BaseScreen.on_escape`

Строка 110.

```python
def on_escape(self)
```

Вызывается только при escape_action == "custom".

Позволяет экрану самостоятельно определить поведение ESC.
По умолчанию ничего не делает. Подклассы переопределяют
этот метод при необходимости.

### method `BaseScreen.update`

Строка 120.

```python
def update(self, dt)
```

Обновляет состояние экрана.

Вызывается ScreenManager.update каждый кадр.
По умолчанию ничего не делает. Подклассы переопределяют
этот метод для анимаций и логики.

Args:
    dt (float): Время, прошедшее с последнего кадра, в секундах.

### method `BaseScreen.draw`

Строка 133.

```python
def draw(self, screen)
```

Отрисовывает экран на поверхности.

Вызывается ScreenManager.draw для каждого экрана в стеке.
По умолчанию ничего не делает. Подклассы переопределяют
этот метод для отрисовки.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### class `ScreenManager`

Строка 147.

Менеджер стека экранов.

Управляет стеком экранов: добавление, удаление, замена.
Обрабатывает события, обновление и отрисовку, делегируя их
экранам в стеке. Отрисовка происходит для всех экранов в стеке,
а события и обновление — только для текущего (верхнего) экрана.

Attributes:
    stack (list): Стек экранов. Последний элемент — текущий экран.

### method `ScreenManager.__init__`

Строка 160.

```python
def __init__(self)
```

Инициализирует менеджер с пустым стеком экранов.

### method `ScreenManager.current`

Строка 165.

```python
def current(self)
```

Возвращает текущий (верхний) экран в стеке.

Returns:
    BaseScreen | None: Текущий экран или None, если стек пуст.

### method `ScreenManager.push`

Строка 174.

```python
def push(self, screen)
```

Добавляет экран на вершину стека.

Новый экран становится текущим. Предыдущий экран остаётся
в стеке и будет отрисован под новым.

Args:
    screen (BaseScreen): Экран для добавления.

### method `ScreenManager.pop`

Строка 191.

```python
def pop(self)
```

Удаляет верхний экран из стека.

Если в стеке только один экран, он не удаляется.

Returns:
    BaseScreen | None: Удалённый экран или None, если стек
        содержит один или ноль экранов.

### method `ScreenManager.replace_all`

Строка 212.

```python
def replace_all(self, screen)
```

Заменяет весь стек одним экраном.

Все текущие экраны удаляются, и переданный экран становится
единственным в стеке.

Args:
    screen (BaseScreen): Экран, заменяющий весь стек.

### method `ScreenManager.handle_escape`

Строка 225.

```python
def handle_escape(self)
```

Обрабатывает нажатие ESC для текущего экрана.

Поведение определяется атрибутом escape_action текущего экрана:
- "none"   — ничего не происходит;
- "custom" — вызывается метод on_escape() текущего экрана;
- "pop"    — верхний экран удаляется из стека (если стек
  содержит более одного экрана).

### method `ScreenManager.handle_event`

Строка 258.

```python
def handle_event(self, event)
```

Передаёт событие pygame текущему экрану.

Если стек пуст, событие игнорируется.

Args:
    event (pygame.event.Event): Событие pygame.

### method `ScreenManager.update`

Строка 270.

```python
def update(self, dt)
```

Обновляет состояние текущего экрана.

Если стек пуст, обновление не происходит.

Args:
    dt (float): Время, прошедшее с последнего кадра, в секундах.

### method `ScreenManager.draw`

Строка 282.

```python
def draw(self, screen)
```

Отрисовывает все экраны в стеке.

Экраны отрисовываются в порядке от нижнего к верхнему,
что обеспечивает корректное наложение оверлеев.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### method `ScreenManager.has_time_hud_screen`

Строка 295.

```python
def has_time_hud_screen(self)
```

Проверяет, присутствует ли в стеке экран, требующий
отображения HUD игрового времени.

Returns:
    bool: True, если хотя бы один экран в стеке имеет
        атрибут show_time_hud со значением True.

## `view/ui/text_layout.py`

### Модуль

Строка 1.

Автоподбор текста под прямоугольник.

Экраны ``view`` рисуют текст напрямую через ``pygame.font``. Этот модуль
даёт общий алгоритм: перенести строки по ширине, подобрать самый крупный
шрифт из набора и вернуть готовые строки. Благодаря этому длинные реплики
не обрезаются и не залезают под кнопки.

Модуль намеренно не зависит от ``App``: вызывающая сторона передаёт список
шрифтов от крупного к мелкому, например ``[app.font_body, app.font_small,
app.font_tiny]``.

### function `wrap_text`

Строка 18.

```python
def wrap_text(font, text, max_width)
```

Перенести текст по ширине с сохранением пустых абзацев.

    Переносы ``\n`` в исходной строке трактуются как границы абзацев.
    Пустые абзацы сохраняются пустой строкой, чтобы не терять структуру
    документа.

### function `line_height`

Строка 57.

```python
def line_height(font, spacing=1.18)
```

Вернуть комфортную высоту строки для шрифта.

### function `fit_lines`

Строка 62.

```python
def fit_lines(fonts, text, rect, spacing=1.18)
```

Подобрать шрифт и строки, полностью помещающиеся в ``rect``.

    Args:
        fonts: Итерируемый набор шрифтов от крупного к мелкому.
        text: Исходный текст.
        rect: ``pygame.Rect`` доступной области.
        spacing: Множитель межстрочного интервала.

    Returns:
        tuple: ``(lines, font, line_height_px, overflow)``. Если даже самый
        мелкий шрифт не помещается, ``overflow`` равно True; строки при этом
        не обрезаются, чтобы вызывающая сторона могла включить прокрутку.

### function `draw_fitted`

Строка 89.

```python
def draw_fitted(surface, fonts, text, rect, color, spacing=1.18, align='left', valign='top', shadow=False)
```

Нарисовать текст, который гарантированно остаётся внутри ``rect``.

    Args:
        surface: Целевая поверхность.
        fonts: Набор шрифтов от крупного к мелкому.
        text: Исходный текст.
        rect: Доступная область (``pygame.Rect``).
        color: Цвет текста.
        spacing: Множитель межстрочного интервала.
        align: ``left``, ``center`` или ``right``.
        valign: ``top``, ``center`` или ``bottom``.
        shadow: Рисовать ли мягкую тень для читаемости на фоне.

    Returns:
        tuple: ``(lines, font, overflow)``.

## `view/ui/time_hud.py`

### Модуль

Строка 1.

view/ui/time_hud.py

HUD игрового времени.

Отображает в левом верхнем углу экрана текущее игровое время,
уровень усталости игрока, текущее выполняемое действие с полосой
прогресса и предупреждение об ожидающей обязательной сцене.

События отображения фиксируются в журнале operation_ozverin.log
в корне проекта и дублируются в консоль.

### function `_get_logger`

Строка 20.

```python
def _get_logger(name)
```

Возвращает журнал с файловым и консольным обработчиками.

Файловый обработчик пишет в operation_ozverin.log в корне проекта,
консольный выводит сообщения в стандартный поток вывода.
Обработчики создаются один раз для каждого имени журнала.

Args:
    name (str): Имя журнала.

Returns:
    logging.Logger: Настроенный журнал.

### class `TimeHUD`

Строка 60.

HUD игрового времени.

Рисует информационную панель в левом верхнем углу экрана.
Если в приложении отсутствует time_system, отрисовка не выполняется.

Attributes:
    app: Экземпляр приложения (App).

### method `TimeHUD.__init__`

Строка 71.

```python
def __init__(self, app)
```

Инициализирует HUD игрового времени.

Args:
    app: Экземпляр приложения (App).

### method `TimeHUD.draw`

Строка 83.

```python
def draw(self, screen)
```

Отрисовывает HUD игрового времени на экране.

Порядок отрисовки:
1. Часы (текущее игровое время).
2. Уровень усталости.
3. Текущее действие с полосой прогресса (если выполняется).
4. Предупреждение об обязательной сцене (если ожидает).

Изменения отображаемого времени и появление обязательной сцены
фиксируются в журнале.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

## `view/ui/widgets.py`

### Модуль

Строка 1.

view/ui/widgets.py

Базовые виджеты пользовательского интерфейса: кнопки, панели, вкладки.

Используются всеми экранами и оверлеями игры. Кнопка отслеживает
наведение курсора и клик левой кнопкой мыши, поддерживает полную
непрозрачность и полупрозрачность через параметр alpha. Панель
рисует полупрозрачный фон с рамкой и служит подложкой для оверлеев.
Вкладка отображает список вкладок равной ширины и переключает
активную по клику, подсвечивая её акцентным цветом.

События взаимодействия (клики кнопок, переключение вкладок)
записываются в журнал operation_ozverin.log и дублируются в консоль.

### class `Button`

Строка 31.

Кнопка пользовательского интерфейса.

Отслеживает наведение курсора и клик левой кнопкой мыши.
При клике в пределах области вызывает callback и возвращает True.
Поддерживает полную непрозрачность и полупрозрачность через
параметр alpha. При alpha < 255 рисует полупрозрачную поверхность
с рамкой вместо сплошного прямоугольника.

Attributes:
    rect (pygame.Rect): Прямоугольная область кнопки.
    text (str): Текст на кнопке.
    font (pygame.font.Font): Шрифт для отрисовки текста.
    callback (callable | None): Функция, вызываемая при клике.
    alpha (int): Прозрачность кнопки (0–255).
    hovered (bool): Флаг наведения курсора на кнопку.

### method `Button.__init__`

Строка 50.

```python
def __init__(self, rect, text, font, callback=None, alpha=255)
```

Инициализирует кнопку.

Args:
    rect (tuple): Координаты и размеры кнопки (x, y, width, height).
    text (str): Текст на кнопке.
    font (pygame.font.Font): Шрифт для отрисовки текста.
    callback (callable | None): Функция, вызываемая при клике.
    alpha (int): Прозрачность кнопки (0–255). По умолчанию 255.

### method `Button.draw`

Строка 68.

```python
def draw(self, screen)
```

Отрисовывает кнопку на экране.

При alpha >= 255 рисует сплошной прямоугольник с подсветкой
при наведении. При alpha < 255 рисует полупрозрачную
поверхность с рамкой. Текст центрируется внутри кнопки.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### method `Button.handle_event`

Строка 102.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для кнопки.

Отслеживает наведение курсора (MOUSEMOTION) и клик левой
кнопкой мыши (MOUSEBUTTONDOWN). При клике в пределах области
вызывает callback и возвращает True, иначе False.

Args:
    event (pygame.event.Event): Событие pygame.

Returns:
    bool: True, если клик был обработан, иначе False.

### class `Panel`

Строка 126.

Панель с полупрозрачным фоном и рамкой.

Служит фоновой подложкой для оверлеев и экранов. Рисует
полупрозрачный прямоугольник с закруглённой рамкой.

Attributes:
    rect (pygame.Rect): Прямоугольная область панели.

### method `Panel.__init__`

Строка 137.

```python
def __init__(self, rect)
```

Инициализирует панель.

Args:
    rect (tuple): Координаты и размеры панели (x, y, width, height).

### method `Panel.draw`

Строка 146.

```python
def draw(self, screen)
```

Отрисовывает панель на экране.

Рисует полупрозрачный фон и рамку по границам панели
с закруглением 8 пикселей.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### class `TabBar`

Строка 162.

Панель вкладок.

Отображает список вкладок равной ширины и переключает активную
по клику. Активная вкладка подсвечивается акцентным цветом,
неактивные — стандартным цветом кнопки.

Attributes:
    rect (pygame.Rect): Прямоугольная область панели вкладок.
    tabs (list[str]): Список названий вкладок.
    font (pygame.font.Font): Шрифт для отрисовки текста вкладок.
    active (int): Индекс активной вкладки.

### method `TabBar.__init__`

Строка 177.

```python
def __init__(self, rect, tabs, font, active=0)
```

Инициализирует панель вкладок.

Args:
    rect (tuple): Координаты и размеры панели (x, y, width, height).
    tabs (list[str]): Список названий вкладок.
    font (pygame.font.Font): Шрифт для отрисовки текста.
    active (int): Индекс активной вкладки по умолчанию.

### method `TabBar.draw`

Строка 192.

```python
def draw(self, screen)
```

Отрисовывает панель вкладок на экране.

Каждая вкладка занимает равную долю ширины панели.
Активная вкладка подсвечивается акцентным цветом,
текст центрируется внутри каждой вкладки.

Args:
    screen (pygame.Surface): Поверхность для отрисовки.

### method `TabBar.handle_event`

Строка 211.

```python
def handle_event(self, event)
```

Обрабатывает события pygame для панели вкладок.

При клике левой кнопкой мыши определяет вкладку под курсором
и устанавливает её активной. Логирует переключение.

Args:
    event (pygame.event.Event): Событие pygame.

Returns:
    bool: True, если клик по вкладке был обработан, иначе False.
