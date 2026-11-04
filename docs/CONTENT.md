# Контент без кода: JSON-файлы и папки

> **Назначение.** Практическая карта источников контента: где лежит каждый
> тип данных, как его добавить, изменить и удалить, чем он проверяется и что
> действительно требует правки кода. Спецификации отдельных подсистем —
> [`AUTOMATA.md`](AUTOMATA.md), [`NAMING.md`](NAMING.md),
> [`SYSTEMS.md`](SYSTEMS.md), [`WORLD.md`](WORLD.md),
> [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md).

> **Поставка пустая.** В репозитории нет игрового JSON-контента: каталоги
> `configs/` и `campaigns/` содержат только `.gitkeep`. Миры, роли,
> сюжеты, автоматы, события, имена и шаблоны добавляются файлами по
> схемам ниже. Старый набор данных сохранён только для тестов в
> `tests/fixtures/content/`; это не игровой контент, и рабочая сборка его
> не видит.

## 1. Правила

1. **Один источник — JSON.** Игровые данные не дублируются в Python-коде.
2. **Добавление файла = добавление контента** там, где загрузчик сканирует
   папку: `configs/automata/`, `configs/naming/classes/`,
   `configs/naming/interactions/`, `configs/storylines/`, `configs/roles/`,
   `configs/worlds/`, `configs/campaigns/`, `configs/content/`,
   `campaigns/`. Каталоги существуют и пусты, поэтому новый файл сразу
   попадает в обход без правки кода.
3. **Удаление файла = удаление контента.** Ссылки на удалённый id должны
   быть убраны из других файлов; загрузчики сообщают об ошибке, а списки
   просто перестают показывать запись.
4. **Правка значения не требует перезапуска кода.** Достаточно сохранить
   JSON и заново открыть экран/создать объект загрузчика.
5. **Ошибки данных не подменяются молча.** Строгие загрузчики
   (`RoleCatalog`, `EventCatalog`, `EnvironmentCatalog`, `AutomataStore`,
   `load_world`) выбрасывают своё исключение с именем файла/поля.
   Мягкие загрузчики (`Content`, `list_storylines`) пропускают битый файл,
   пишут предупреждение в лог и продолжают работу.
6. **Код нужен только для новой механики.** Новые записи, тексты, роли,
   сюжеты, миры, автоматы и классы — данные. Новый тип поведения,
   действие с новой формулой или новый экран — код.

## 2. Карта папок

Все перечисленные каталоги в поставке пусты (кроме `.gitkeep`). Таблица
показывает, куда положить новый JSON и какой загрузчик его прочитает.

| Путь | Что это | Загрузчик | Добавить | Изменить | Удалить |
|---|---|---|---|---|---|
| `configs/automata/*.json` | автоматы для редактора | `automata.storage.AutomataStore` | новый `*.json` или кнопка редактора | редактор/`store.save(automaton, slug)` | `store.delete(slug)` |
| `configs/naming/lexicon.json` | словарь морфологии | `NamingCatalog`/`PersonCatalog` | слово в `words` | значение слова | слово (проверить ссылки) |
| `configs/naming/classes/*.json` | классы автоматов | `NamingCatalog.load()` | новый файл класса | поля класса | файл |
| `configs/naming/interactions/*.json` | типы взаимодействий | `NamingCatalog.load()` | новый файл | поля типа | файл |
| `configs/naming/people.json` | культуры и фэнтези-темы | `PersonCatalog.load()` | запись в `cultures`/`fantasy_themes` | запись | запись |
| `configs/systems/events.json` | категории и шаблоны событий | `EventCatalog.load()` | элемент в `events` (и категорию) | `templates`/вес/категорию | элемент |
| `configs/systems/environment.json` | особенности среды | `EnvironmentCatalog.load()` | элемент в `features` | состояния/действия/дрейф | элемент |
| `configs/systems/playwright.json` | веса и шаблоны драматурга | `PlaywrightConfig.load()` | шаблон в `templates` | веса/ритм/шаблон | шаблон |
| `configs/storylines/<id>.json` | основной сюжет | `view.support.storyline.load_storyline` | новый `<id>.json` | поля сюжета | файл |
| `configs/storylines/<id>_char.json` | шаги создания персонажа | тот же, по полю `character_creation` | новый файл | `steps` | файл (и ссылку) |
| `configs/storylines/<id>_scenes.json` | сцены сюжета | тот же, по полю `scenes` | новый файл | `sequence` | файл (и ссылку) |
| `configs/roles/roles.json` | базовый каталог ролей | `RoleCatalog.load()` | роль в `roles` | поля роли | роль |
| `configs/roles/<name>.json` | дополнительный файл роли | `RoleCatalog.load()` | один объект роли или `{"roles": [...]}` | поля | файл |
| `configs/worlds/*.json` | миры кампании | `campaign.world.load_world(path)` | новый мир | поля мира | файл |
| `configs/worlds/*_strategies.json` | долгосрочные стратегии узлов | `campaign.node_strategy.StrategyBook` | новый файл или поле `strategies` | селекторы/цель/веса | файл |
| `configs/environments/*.json` | многофазные планы среды арены | `core41.environment.load_environment_plan()` | новый файл | `goals`/`ratio`/`horizon` | файл |
| `configs/worlds/biography.json` | таблицы биографии | `load_biography()` | таблицы | значения | файл (если не нужен) |
| `configs/campaigns/*.json` | шаблоны пресетов | `campaign.preset.load_template()` | новый шаблон | фракции/сценарий | файл |
| `configs/content/*.json` | именованный UI-контент | `view.support.content.Content` | новый `*.json` доступен через `get(name)` | содержимое файла | файл |
| `campaigns/*.json` | сохранённые пресеты | `campaign.storage.list_presets()` | `save_preset()` | пересохранить | файл |
| `configs/view/presentation.json` | плейсхолдеры/подписи ассетов | `view.ui.asset_loader` | ключ | значение | ключ |

`configs/presets/` и `configs/classes/` относятся к отдельному
экспериментальному дереву и текущим игровым загрузчиком не используются.

## 3. Минимальные схемы

### Роль (`configs/roles/<name>.json`)

Допустимы два формата: один объект роли или объект с массивом `roles`.

```json
{
  "id": "new_role",
  "label": "Новая роль",
  "short_label": "Новая",
  "description": "Что видит игрок.",
  "leadership": "official",
  "faction_kind": "automaton",
  "faction_slot": "office",
  "faction_choice": false,
  "storyline_id": "mini",
  "available": true,
  "sort_order": 20,
  "grants": {"player_role": "new_role"},
  "tags": ["world"]
}
```

`id` — строчная латиница, цифры и `_`, первый символ — буква.
`roles.json` может отсутствовать, если в папке есть хотя бы один файл роли.

### Мир (`configs/worlds/<name>.json`)

Минимально обязательны непустые `domains`, `polities`, `nodes`, `offices`
и `actions`; связи проверяет `validate_world()`. Биография миром не является
и в `list_worlds()` не попадает.

```json
{
  "id": "mini_world",
  "title": "Мини-мир",
  "domains": [{"id": "court", "levels": [{"id": "low", "rank": 1}]}],
  "polities": [{"id": "city"}],
  "nodes": [{"id": "hall", "domain": "court", "level": "low"}],
  "offices": [{"id": "clerk", "domain": "court", "levels": ["low"]}],
  "actions": [{"id": "inspect", "label": "Осмотреть"}]
}
```

Дополнительные Data-Driven блоки мира:

```json
{
  "strategies_path": "configs/worlds/mini_strategies.json",
  "labor_market": {
    "rivals": 2,
    "refresh_days": 3,
    "structure_quota": 1,
    "quota": {"order": 3},
    "weights": {"skill": 0.4, "standing": 0.6, "connection": 0.1}
  }
}
```

Стратегия узла (в файле `strategies` или внешнем `strategies_path`):

```json
{
  "id": "order_consolidation",
  "label": "Укрепить порядок",
  "nodes": {"domains": ["order"]},
  "target": {"kinds": ["institution"]},
  "horizon_days": 8,
  "goal": {"stat": "legitimacy", "target": 0.78},
  "actions": {"reform": 0.9, "negotiate": 0.5},
  "bonus": 0.25
}
```

Селекторы: `ids`/`id`, `domains`, `levels`, `kinds`, `polities`, `tags`.
План среды (`configs/environments/<name>.json`):

```json
{
  "goals": [
    {"label": "спокойствие", "ratio": 0.45, "horizon": 240},
    {"label": "испытание", "ratio": 0.75, "horizon": 420}
  ]
}
```

### Сюжет (`configs/storylines/mini.json`)

```json
{
  "storyline_id": "mini",
  "title": "Мини-сюжет",
  "world_path": "configs/worlds/mini_world.json",
  "character_creation": "mini_char",
  "scenes": "mini_scenes"
}
```

`list_storylines()` показывает только основные файлы и пропускает
`*_char.json`/`*_scenes.json`. Если `character_creation` или `scenes`
не указаны, соответствующий блок остается пустым.

### Контент UI (`configs/content/<name>.json`)

Любой JSON в папке загружается в `Content.files`; привычные атрибуты
`order_types`, `notebook`, `documents`, `dialogues`, `decisions` —
это просто `get("orders")`, `get("notebook")` и т.д.

```python
from view.support.content import Content

content = Content("configs/content")
tabs = content.get("notebook", {}).get("tabs", [])
custom = content.get("my_new_file", {})
```

### Событие (`configs/systems/events.json`)

```json
{
  "id": "court_intrigue",
  "category": "court",
  "title": "Интрига",
  "templates": ["При дворе случилась {cause}."],
  "severity": 0.5,
  "stakes": 0.6,
  "weight": 1.0,
  "tags": ["court"]
}
```

Категория должна быть объявлена в `categories`. Удаление события не
требует правки кода, если на его id никто не ссылается.

### Автомат (`configs/automata/<slug>.json`)

Один файл — один автомат. Полная схема и редактор —
[`AUTOMATA.md`](AUTOMATA.md). `AutomataStore` сам строит slug из имени,
поэтому новый файл можно создать копированием и правкой.

## 4. Проверка после правки

```bash
# все JSON в configs и тестовых фикстурах читаются
python3 -m pytest -q tests/test_content_pipeline.py

# роли видны каталогу (после добавления configs/roles/*.json)
python3 -m campaign --list-roles

# шаблоны кампаний видны и разрешаются по имени
python3 -m campaign --list-templates
python3 -m campaign --generate --template <template_id> \
  --role <role_id> --out /tmp/preset.json

# пресеты в campaigns/
python3 -m campaign --list-presets
```

Проверки в Python выполняются для тех данных, которые вы добавили:

```python
from campaign.world import list_worlds, load_world
from campaign.roles import RoleCatalog
from view.support.storyline import list_storylines, load_storyline

worlds = list_worlds()
if worlds:
    assert load_world(worlds[0]["path"])["id"] == worlds[0]["world_id"]
roles = RoleCatalog.load()
assert roles.all_roles()
storylines = list_storylines()
if storylines:
    assert load_storyline(storylines[0]["storyline_id"]) is not None
```

Если контента ещё нет, `list_worlds()`, `list_storylines()` и
`RoleCatalog.load()` ведут себя предсказуемо: первые два возвращают пустой
список, а `RoleCatalog` поднимает `RoleError`. UI это переживает: меню
открывается, экран ролей показывает пустое состояние, а быстрая кампания
просит добавить мир.

### Первый запуск без контента

* `load_world()` без пути ищет `configs/worlds/agora_world.json`; если его
  нет, берётся первый валидный `*.json` из `configs/worlds/`. Поэтому новый
  мир можно назвать как угодно — переименовывать файл под код не нужно.
* Если ролей нет, `App` ловит `RoleError`, `RoleSelectScreen` показывает
  пустое состояние, а `python3 -m campaign --list-roles` печатает
  сообщение вместо traceback.
* Если мира нет, быстрая кампания показывает подсказку добавить JSON в
  `configs/worlds/` и не роняет приложение.
* `tests/fixtures/content/` подключается только тестовой фикстурой
  `tests/conftest.py`; это изолированный набор для проверки механик.

## 5. Что проверить при удалении

- На id роли ссылаются сюжет, UI или сохранение — удалите/обновите ссылку.
- У мира остались узлы/должности/действия с ссылками друг на друга —
  `validate_world()` укажет точный id.
- У события осталась категория без событий — это допустимо; событие без
  категории — ошибка.
- У сюжета остались `*_char.json`/`*_scenes.json` без основного файла —
  они не показываются в списке и не загружаются, но занимают место.
- У класса имен остались `need_themes` на удалённую тему — загрузчик
  сообщит об ошибке.

## 6. Границы

- Новые **записи** перечисленных типов добавляются без кода.
- Новые **поля** старых типов можно сохранять в JSON, но UI/формулы увидят
  их только после чтения в коде.
- Новые **типы** контента (например, новая механика действия) требуют
  загрузчика/обработчика.
- Сетевой загрузки, hot-reload и редактора всех типов нет; перезагрузка
  экрана/объекта достаточна.
