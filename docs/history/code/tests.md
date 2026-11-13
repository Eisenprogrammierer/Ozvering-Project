# `tests`

Справочник собран из docstrings и примечаний к переменным. Номера строк относятся к версии до очистки кода.

## `tests/test_advanced.py`

### Модуль

Строка 1.

Тесты новых слоёв: энтропия смысла, лоссовая наблюдаемость, LOD.

Все слои по умолчанию выключены (``entropy=False``, ``lossy=False``, LOD-1),
поэтому канон ``run_batch`` остаётся неизменным. Здесь проверяются контракты
самих слоёв и их безопасность для канона.

### function `test_capture_scales_force_and_rest_ceiling_together`

Строка 167.

```python
def test_capture_scales_force_and_rest_ceiling_together()
```

F4: ``rest_units -= cap / L_STEP`` — не эвристика, а инвариант.

    ``L = L_BASE + L_STEP * rest_units``, поэтому вычитание ``cap / L_STEP``
    уменьшает потолок ровно на ``cap`` — столько же, сколько силы потерял
    проигравший. Дефицит ``L - F`` (запас до потолка) сохраняется.

## `tests/test_automata.py`

### Модуль

Строка 1.

Тесты чистой модели и хранилища редактора автоматов (без pygame).

## `tests/test_automata_ui.py`

### Модуль

Строка 1.

Headless-тесты графического редактора автоматов.

## `tests/test_battlefield.py`

### Модуль

Строка 1.

Тесты чистой логики стратегического слоя (без pygame).

## `tests/test_breakthrough_balance.py`

### Модуль

Строка 1.

Строгие проверки прорыва, окружения и капитуляции.

Канонический обмен огнём живёт в ``warfare.py``. Здесь проверяется именно
кампанийный слой ``FrontGeometry``: насколько быстро растут суточные потери
после прорыва и что замкнутое кольцо не оставляет роте возможности бесконечно
«терпеть» строчкой в сводке.

### function `_place_ring`

Строка 59.

```python
def _place_ring(state, target, positions=None)
```

Поставить врагов вокруг цели, не трогая остальной мир.

### function `_one_day_loss`

Строка 74.

```python
def _one_day_loss(state, *, breached=False)
```

Один полный кампанийный день без движения войск.

## `tests/test_campaign.py`

### Модуль

Строка 1.

Тесты ролей игрока и детерминированных кампанийных пресетов.

Ядро тестов не требует pygame: каталог ролей, генератор и хранилище — чистый
Python. Интеграция с ``view.support.scenario`` проверяется отдельно и
пропускается, если нет numpy.

### function `test_role_select_screen_constructs_and_draws`

Строка 410.

```python
def test_role_select_screen_constructs_and_draws()
```

Дымовой тест UI: пропускается без pygame.

## `tests/test_campaign_geometry.py`

### Модуль

Строка 1.

Геометрия бригадного боя и исторические суточные потери.

### function `_front_player`

Строка 21.

```python
def _front_player(state)
```

Живая рота на фронте при явном фронте на восток.

### function `_park_enemies`

Строка 34.

```python
def _park_enemies(state)
```

Убрать случайных врагов подальше, чтобы контекст был однозначным.

### function `test_prepared_defense_is_not_three_to_one_at_any_sector`

Строка 56.

```python
def test_prepared_defense_is_not_three_to_one_at_any_sector()
```

Двукратное общее превосходство не даёт троекратного на участке.

### function `test_historical_attrition_is_slow_and_attackers_lose_more`

Строка 108.

```python
def test_historical_attrition_is_slow_and_attackers_lose_more()
```

Три часа боя: потери обороны далеки от «дивизия уничтожена».

### function `_place_red_cross`

Строка 128.

```python
def _place_red_cross(state)
```

Поставить красных крестом: север/юг/восток/запад от центра (10, 12).

### function `test_sector_is_derived_from_facing_not_frozen_on_detachment`

Строка 139.

```python
def test_sector_is_derived_from_facing_not_frozen_on_detachment()
```

Армия смотрит на север, а масса врага — на востоке: это фланг.

### function `test_intact_front_does_not_treat_close_flank_melee_as_rout`

Строка 238.

```python
def test_intact_front_does_not_treat_close_flank_melee_as_rout()
```

Пока линия цела, бой вплотную сам по себе не даёт «разгром».

### function `test_enemy_in_rear_before_formal_breach_is_a_local_overrun`

Строка 255.

```python
def test_enemy_in_rear_before_formal_breach_is_a_local_overrun()
```

Враг уже за спиной — позиция смята даже без общего прорыва.

### function `test_breach_makes_holding_the_lost_line_much_costlier`

Строка 270.

```python
def test_breach_makes_holding_the_lost_line_much_costlier()
```

После прорыва оставаться на потерянном рубеже невыгодно.

### function `test_orderly_withdrawal_avoids_rout_losses_under_overrun`

Строка 315.

```python
def test_orderly_withdrawal_avoids_rout_losses_under_overrun()
```

Один и тот же охват: остаться — разгром, отойти — сохранить роту.

## `tests/test_canon.py`

### Модуль

Строка 1.

Канон: устойчивый исход пакета партий и воспроизводимость (пункт B3 ревью).

Исход ``run_batch(10)`` — зафиксированная базовая линия (docs/BASELINE.md):
RL 1 / UtilityAI 9 / без захвата 0. Тест ловит регрессию механики, а также
недетерминизм в пределах одного процесса. Независимость от рандомизации хэшей
(``PYTHONHASHSEED``) проверяется в ``test_checks.py`` подпроцессом — хэш-сид
фиксируется при старте интерпретатора и в процессе не меняется.

### function `test_canon_batch_outcome`

Строка 16.

```python
def test_canon_batch_outcome()
```

Пакет из 10 партий даёт ожидаемый исход (RL 1 / UtilityAI 9 / нет 0).

### function `test_canon_repeatable_in_process`

Строка 21.

```python
def test_canon_repeatable_in_process()
```

Повторный прогон в том же процессе воспроизводим такт в такт.

## `tests/test_checks.py`

### Модуль

Строка 1.

Обёртка ключевых автотестов-скриптов в pytest (пункт B3 ревью).

Скрипты ``experiments/exp_*`` — самодостаточные проверки с кодом возврата
(``0`` — норма, ``1`` — регрессия). Pytest запускает их подпроцессом — тем же
путём, что и CI (``.github/workflows/ci.yml``), — и требует ``rc=0``.

Детерминизм канона по ``PYTHONHASHSEED`` тоже проверяется подпроцессом:
хэш-сид фиксируется при старте интерпретатора и в процессе не меняется.

### function `test_check_script_passes`

Строка 31.

```python
def test_check_script_passes(name)
```

Скрипт-проверка ``experiments/<name>.py`` завершается с кодом 0.

### function `test_canon_independent_of_hashseed`

Строка 38.

```python
def test_canon_independent_of_hashseed()
```

Канон не зависит от рандомизации хэшей строк (иначе — перебор по ``set()``).

## `tests/test_docs_sync.py`

### Модуль

Строка 1.

Проверка «документация ↔ код» (пункт B4 ревью).

Первопричина расхождений раздела C ревью — согласованность документации ничем
не проверялась. Здесь автоматизированы две проверки:

  1. Таблица констант в ``docs/MODEL.md`` (§8) сверяется со значениями в
     ``simulation.py``: документированное число обязано совпадать с кодом.
  2. Все скрипты ``experiments/*.py``, упомянутые в ``docs/MODEL.md`` и
     ``README.md``, существуют на диске.

Чего тест не проверяет (по-прежнему требует ревью) — смысловую согласованность
формулировок; для этого — чек-лист в ``.github/pull_request_template.md``.

### function `_documented_constants`

Строка 35.

```python
def _documented_constants()
```

Пары ``(имя_константы, документированное_значение)`` из таблицы MODEL.md.

### function `test_model_constants_match_code`

Строка 51.

```python
def test_model_constants_match_code()
```

Таблица констант MODEL.md §8 совпадает со значениями в simulation.py.

### function `test_referenced_experiments_exist`

Строка 65.

```python
def test_referenced_experiments_exist()
```

Скрипты experiments/*.py, упомянутые в доках, существуют.

## `tests/test_domain_audit.py`

### Модуль

Строка 1.

F1, структурный сторож: в ядре взаимодействия нет доменной ветки (docs/TODO.md → F1).

РОЛЬ И ГРАНИЦЫ. Это ОПРЕДЕЛЕНИЕ «единого закона» (предметная область — не
переменная механизма) и СТОРОЖ РЕГРЕССИЙ — НЕ свидетельство: аудит проходит по
построению (области в коде нет) и не должен выдаваться за измерение.
Свидетельство поставляет ``experiments/exp_domain_invariance.py`` (мощность
различителя + инерция доменного индекса); см. разделение ролей в его докстроке.

МЕТОД. Разбор ``simulation.py`` через ``ast``. В телах функций ядра
взаимодействия не должно быть идентификаторов или имён аргументов, помечающих
предметную область. Строки документации и комментарии ``ast`` не видит как имена
— в докстроках области упомянуты законно (нейтральная терминология) и проверку
не ломают. Токен ``type`` сознательно НЕ запрещён: тип энергии — часть единого
закона, а не предметная область.

### function `_identifiers`

Строка 37.

```python
def _identifiers(node)
```

Имена аргументов, ``Name`` и ``Attribute`` в поддереве (без докстрок/комментариев).

### function `test_core_has_no_domain_branch`

Строка 50.

```python
def test_core_has_no_domain_branch()
```

Ядро взаимодействия не содержит доменных идентификаторов (F1, определение).

## `tests/test_interaction.py`

### Модуль

Строка 1.

Тесты чистого фреймворка взаимодействий (без pygame).

## `tests/test_naming.py`

### Модуль

Строка 1.

Тесты конфигурируемого генератора естественных названий (без pygame).

## `tests/test_organization_runtime.py`

### Модуль

Строка 1.

Тесты runtime-слоя организаций и его интеграции с ``warfare``.

Аналитическое ядро проверяется отдельно в ``test_organizations.py``. Здесь
важно, что организация:

* собирает Population из живых персонажей на каждом такте;
* применяет мягкие эффекты к существующим BDI-потребностям, а не вводит новые
  метрики в ``Agent.state``;
* исключает вышедших участников и распадается без желающих;
* остаётся полностью опциональной для ``WarfareSimulation``.

## `tests/test_organizations.py`

### Модуль

Строка 1.

Тесты аналитического слоя организаций и генератора автоматов (без pygame).

## `tests/test_people.py`

### Модуль

Строка 1.

Тесты имён персонажей: реальные культуры и фэнтези (без pygame).

## `tests/test_systems.py`

### Модуль

Строка 1.

Тесты системных автоматов: среда, драматург и события (без pygame).

## `tests/test_ui.py`

### Модуль

Строка 1.

Тесты сценного слоя (``ui/``).

Разделены на две группы:

  * **без графики** — система сохранений/настроек (``ui.save``) и контент
    (``ui.content``): чистый Python, работают и в CI без pygame;
  * **с графикой** — навигация между сценами и отрисовка кадров через
    ``ui.app.App`` под headless-драйвером SDL (``importorskip("pygame")``).

Проверяется, что сценный слой не трогает модель: ``simulation.py`` и канон
``run_batch(10)`` остаются неизменными (см. ``test_canon.py``).

### function `test_audio_never_initialized`

Строка 123.

```python
def test_audio_never_initialized(app)
```

Аудио-подсистема не инициализируется (иначе mixer может зависнуть).

### function `test_interaction_scene_reveals_actions_and_outcomes`

Строка 158.

```python
def test_interaction_scene_reveals_actions_and_outcomes(app)
```

Действия появляются после выбора объекта, исходы — после действия.

### function `test_arena_quit_button_exits`

Строка 276.

```python
def test_arena_quit_button_exits(app)
```

В HUD арены есть кнопка QUIT; клик по ней завершает цикл (rc=False).

### function `test_save_layer_is_pygame_free`

Строка 323.

```python
def test_save_layer_is_pygame_free()
```

``ui.save`` (и контент) импортируются без pygame — доступны в CI.

### function `test_entry_point_importable`

Строка 335.

```python
def test_entry_point_importable()
```

Единая точка запуска ``main.py`` импортируется без графики.

## `tests/test_view.py`

### Модуль

Строка 1.

Тесты кампанийного UI-каркаса ``view`` (без pygame).

### function `test_reserve_spawn_does_not_create_phantom_losses`

Строка 128.

```python
def test_reserve_spawn_does_not_create_phantom_losses()
```

Выход резерва не должен считаться безвозвратными потерями.

    До исправления резерв тикал как самостоятельная среда внутри стана,
    выходил с силой 28.8 вместо штатных 12, а на следующем такте UI
    ограничивал силу до штата и записывал разницу (11) в потери. Из-за
    этого потери дивизии прыгали с 1% до 18% за один такт.

    Бригадный сценарий больше не содержит станов, поэтому регрессия
    проверяется на синтетическом мире с явным резервом.

### function `test_mvp_loss_threshold_allows_meaningful_battle`

Строка 576.

```python
def test_mvp_loss_threshold_allows_meaningful_battle()
```

25% — дивизия теряет боеспособность, но бой не обрывается сразу.

### function `test_camp_stages_use_whole_loss_limit_range`

Строка 758.

```python
def test_camp_stages_use_whole_loss_limit_range(limit)
```

Все три фона достижимы при старом, текущем и запасном лимите.

## `tests/test_view_rts.py`

### Модуль

Строка 1.

Дымовые тесты RTS-экрана (требуют pygame).

### function `test_mandatory_screen_uses_each_camp_variant`

Строка 419.

```python
def test_mandatory_screen_uses_each_camp_variant(monkeypatch)
```

Утренний экран реально проходит fresh -> wounded -> critical.

## `tests/test_warfare.py`

### Модуль

Строка 1.

Тесты войсковых автоматов: персонаж, отделение, стан, приказ, заградотряд.

Модуль ``warfare.py`` надстраивается над каноном и не меняет ``simulation.py``.
Здесь проверяются онтология (16 потребностей, BDI, суперсистемы), пассивный
приказ, принуждение заградотряда, задержка подкрепления и детерминированный
демонстрационный сценарий с паникой/отходом и банзай-атакой.

### function `test_other_needs_multiply_health_degradation`

Строка 198.

```python
def test_other_needs_multiply_health_degradation()
```

Критические нужды ускоряют рост health, закрытые — замедляют.
