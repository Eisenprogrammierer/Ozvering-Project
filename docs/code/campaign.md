# `campaign`

Справочник собран из docstrings и примечаний к переменным. Номера строк относятся к версии до очистки кода.

## `campaign/__init__.py`

### Модуль

Строка 1.

Кампанийный слой: роли игрока и детерминированные пресеты.

Пакет не импортирует pygame. Его можно использовать из тестов, CLI и
headless-сценариев:

    python3 -m campaign --list-roles
    python3 -m campaign --generate --seed 7 --out campaigns/test.json

## `campaign/__main__.py`

### Модуль

Строка 1.

CLI кампанийного слоя.

    python3 -m campaign --list-roles
    python3 -m campaign --list-presets
    python3 -m campaign --generate --seed 7
    python3 -m campaign --generate --seed 7 --out campaigns/test.json
    python3 -m campaign --show campaigns/test.json

## `campaign/errors.py`

### Модуль

Строка 1.

Общие ошибки кампанийного слоя.

### class `CampaignError`

Строка 6.

Базовая ошибка ролей, пресетов и кампанийного хранилища.

## `campaign/preset.py`

### Модуль

Строка 1.

Детерминированный генератор кампанийного пресета.

Пресет — это не сохранение партии и не боевой сценарий ``warfare``. Это
декларативный срез кампании:

* роль игрока (сейчас только первое лицо гражданской коалиции);
* гражданские фракции, группы опоры и их аналитические автоматы;
* именованные персонажи с потребностями, чертами и невоенными постами;
* организации, имущество, институты, особенности среды, события и актёры
  драматурга;
* для стратегического шаблона — ``scenario.mode = "strategy"`` и пустой
  список ``units``;
* для легаси-шаблона ``test_skirmish`` — роспись рот, которую
  ``view.support.scenario`` накладывает на бригадный сценарий 16 против 32.

Генератор чистый и детерминированный: один и тот же seed даёт один и тот же
JSON. Он не импортирует pygame и не меняет канон ``simulation.py`` /
``warfare.py``.

### class `CampaignPresetError`

Строка 53.

Ошибка шаблона или сгенерированного пресета.

### function `load_template`

Строка 172.

```python
def load_template(path=None)
```

Загрузить шаблон генерации из ``configs/campaigns``.

### function `_make_needs`

Строка 238.

```python
def _make_needs(randomizer, priority_needs)
```

Начальные потребности: штатные значения плюс профиль фракции.

### function `_make_character`

Строка 259.

```python
def _make_character(randomizer, name, side, cfg, unit_id, char_id, post, archetype, force, priority_needs, char_seed, is_player=False, is_leader=False)
```

Собрать один именованный персонаж и его стартовые BDI-поля.

### class `CampaignPreset`

Строка 421.

Сгенерированный или загруженный кампанийный пресет.

### method `CampaignPreset.roster_by_side`

Строка 534.

```python
def roster_by_side(self)
```

Вернуть ``{side: [[character, ...], ...]}`` в порядке рот.

### class `CampaignPresetGenerator`

Строка 660.

Детерминированно собрать тестовую кампанию из шаблона.

### function `generate_preset`

Строка 1098.

```python
def generate_preset(role_id='faction_leader', seed=None, preset_id=None, template=None, template_path=None, catalog=None, player_faction_id=None)
```

Короткий функциональный вход для генерации тестовой кампании.

## `campaign/roles.py`

### Модуль

Строка 1.

Роли игрока: декларативный каталог и стабильный выбор роли.

Роль — это не класс персонажа и не боевая специальность. Это позиция
игрока в кампании: кем он входит в мир, какие права и ограничения получает.
Первый каталог намеренно содержит только одну доступную роль —
``faction_leader`` (первое лицо гражданской коалиции). Игрок — конкретный
человек, а не фракция и не государство. Будущие роли добавляются в
``configs/roles/roles.json`` без изменения кода генератора и экрана выбора.

Слой чистый: он не импортирует pygame и не зависит от ``view``.

### class `RoleError`

Строка 27.

Ошибка каталога ролей или выбранной роли.

### class `RoleSpec`

Строка 63.

Одна роль игрока из каталога.

    Attributes:
        id: Стабильный машинный идентификатор (например, ``faction_leader``).
        label: Название для игрока.
        short_label: Короткое название для HUD и кнопок.
        description: Пояснение, что роль значит в кампании.
        leadership: Режим лидерства (``nominal``, затем, возможно, другие).
        faction_kind: Тип фракции, к которой относится роль.
        faction_slot: Слот фракции в пресете (``player``/``enemy``).
        faction_choice: Показывать ли выбор фракции после роли.
        storyline_id: Сюжет, который запускается для этой роли.
        available: Можно ли выбрать роль в текущей сборке.
        sort_order: Порядок в каталоге и на экране выбора.
        grants: Переменные, которые роль передаёт сюжету/кампании.
        tags: Смысловые теги для будущих правил и фильтров.

### class `RoleCatalog`

Строка 176.

Каталог ролей, загруженный из ``configs/roles/roles.json``.

### method `RoleCatalog.select`

Строка 247.

```python
def select(self, role_id=None)
```

Выбрать роль; ``None`` означает первую доступную.

## `campaign/storage.py`

### Модуль

Строка 1.

Хранилище сгенерированных пресетов кампаний.

Пресеты не являются сохранениями партии: сохранения лежат в ``saves/`` и
игнорируются git, а пресеты — это проверяемые данные в ``campaigns/``.

### class `CampaignStorageError`

Строка 16.

Ошибка чтения/записи пресета.

### function `save_preset`

Строка 41.

```python
def save_preset(preset, path=None, directory=None)
```

Сохранить пресет и вернуть путь к JSON.

### function `load_preset`

Строка 54.

```python
def load_preset(path_or_id, directory=None)
```

Загрузить пресет по пути или идентификатору в ``campaigns/``.

### function `list_presets`

Строка 65.

```python
def list_presets(directory=None)
```

Вернуть краткие сведения о пресетах, новые первыми.

## `campaign/strategy.py`

Чистая модель гражданской стратегии «Хартия Агоры». Не импортирует pygame
и не создаёт отделений `warfare.py`.

### class `StrategyEngine`

Строит доступные сущности из гражданского пресета и статического JSON,
проверяет совместимость действий, цену и требования, выполняет
детерминированный бросок, применяет немедленные и отложенные эффекты,
хранит обязательства и cooldowns, завершает день и проверяет исход.

Основные методы: `sorted_entities()`, `action_options(entity_id)`,
`available_actions(entity_id)`, `preview(action_id, entity_id)`,
`execute(action_id, entity_id)`, `end_day()`, `to_dict()`,
`load_snapshot(snapshot)`.

### function `load_strategy`

Загружает и валидирует JSON стратегии; по умолчанию —
`configs/strategy/agora_charter.json`.

### class `StrategyError`

Ошибка чтения или структуры стратегии.
