# Контент без кода: JSON-файлы и папки

> **Назначение.** Практическая карта источников контента: где лежит каждый
> тип данных, как его добавить, изменить и удалить, чем он проверяется и что
> действительно требует правки кода. Спецификации отдельных подсистем —
> [`AUTOMATA.md`](AUTOMATA.md), [`NAMING.md`](NAMING.md),
> [`SYSTEMS.md`](SYSTEMS.md), [`WORLD.md`](WORLD.md),
> [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md).

> **Поставка не пустая.** В `configs/` уже лежит рабочий контент: четыре
> лорных шаблона кампаний, общие фракции/органы/работы, роли, сюжеты,
> 12 черт характера, каталог личности, имена, события и UI-контент.
> Часть каталогов (`configs/worlds/`, `configs/automata/`, `campaigns/`)
> пока содержит только `.gitkeep` — это заготовки под свои данные.
> `tests/fixtures/content/` остаётся изолированным набором для тестов и
> не является игровым контентом.

## 1. Правила

1. **Один источник — JSON.** Игровые данные не дублируются в Python-коде.
2. **Добавление файла = добавление контента** там, где загрузчик сканирует
   папку: `configs/automata/`, `configs/naming/classes/`,
   `configs/naming/interactions/`, `configs/storylines/`, `configs/roles/`,
   `configs/worlds/`, `configs/campaigns/`, `configs/content/`,
   `configs/characters/`, `campaigns/`. Новый файл сразу попадает в обход
   без правки кода. Общие фракции и работы кампаний подключаются не
   сканированием, а полем `factions_path` из шаблона.
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

Таблица показывает, куда положить новый JSON и какой загрузчик его
прочитает. Каталоги без файлов (`.gitkeep`) — заготовки: новый файл в них
начинает работать без правки кода, если загрузчик сканирует папку.

| Путь | Что это | Загрузчик | Добавить | Изменить | Удалить |
|---|---|---|---|---|---|
| `configs/automata/*.json` | автоматы для редактора | `automata.storage.AutomataStore` | новый `*.json` или кнопка редактора | редактор/`store.save(automaton, slug)` | `store.delete(slug)` |
| `configs/naming/lexicon.json` | словарь морфологии | `NamingCatalog`/`PersonCatalog` | слово в `words` | значение слова | слово (проверить ссылки) |
| `configs/naming/classes/*.json` | классы автоматов | `NamingCatalog.load()` | новый файл класса | поля класса | файл |
| `configs/naming/interactions/*.json` | типы взаимодействий | `NamingCatalog.load()` | новый файл | поля типа | файл |
| `configs/naming/people.json` | культуры и фэнтези-темы | `PersonCatalog.load()` | запись в `cultures`/`fantasy_themes` | запись | запись |
| `configs/naming/policies.json` | правила имён по фракциям | `PersonPolicyCatalog.load()` | политика и алиасы | веса, эпитеты, режим | политика (проверить алиасы) |
| `configs/systems/events.json` | категории и шаблоны событий | `EventCatalog.load()` | элемент в `events` (и категорию) | `templates`/вес/категорию | элемент |
| `configs/systems/environment.json` | особенности среды | `EnvironmentCatalog.load()` | элемент в `features` | состояния/действия/дрейф | элемент |
| `configs/systems/playwright.json` | веса и шаблоны драматурга | `PlaywrightConfig.load()` | шаблон в `templates` | веса/ритм/шаблон | шаблон |
| `configs/characters/traits.json` | черты характера и их влияние | `character_traits.load_traits()` | черта в `traits`, архетип в `archetypes` | `base`/`scale`/`center`, `need_*`, `intent_bias` | черта/архетип (проверить ссылки) |
| `configs/characters/identity.json` | варианты личности героя | `campaign.identity.load_identity_catalog()` | происхождение/призвание/ценность/слабость/пол в своей секции | `label`/`summary`/`text`, `needs`, `traits` | вариант (проверить, что на него не ссылаются сохранения) |
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
| `configs/campaigns/base/lore_factions.json` | общие фракции, органы, работы и взаимодействия лорных кампаний | `load_template()` по полю `factions_path` | фракция в `factions`, орган в `organs`, работа в `actions`, взаимодействие в `organ_interactions` | цели, активы, титулы, органы, работы, взаимодействия | фракция/орган/работа/взаимодействие (проверить `organ_id` и ссылки шаблонов) |
| `configs/campaigns/base/automata_defaults.json` | базовые данные кампании автоматов | `campaign.defaults.load_defaults()` | секция в JSON | модель, интервалы реального времени, скорости, взаимодействия, потребности, бюджет | секция (ядро читает без хардкода) |
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
  "scenes": "mini_scenes",
  "identity_editor": false
}
```

`list_storylines()` показывает только основные файлы и пропускает
`*_char.json`/`*_scenes.json`. Если `character_creation` или `scenes`
не указаны, соответствующий блок остается пустым. `identity_editor: true`
включает редактор личности перед стартом; сейчас так помечены четыре
лорных сюжета (`empire_campaign`, `republic_campaign`, `cult_campaign`,
`corporation_campaign`).

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

### Черты характера (`configs/characters/traits.json`)

Один файл задаёт все 12 черт, их базы, разброс, архетипы и коэффициенты
влияния. Потребности остаются в коде (`warfare.NEEDS`), потому что это
контракт модели; что именно каждая потребность значит для действия —
данные `model.intent.need_intents`.

```json
{
  "traits": {
    "courage": {
      "label": "Смелость",
      "summary": "Сопротивляется страху и панике.",
      "base": 0.55,
      "need_urgency": {"fear": {"base": 0.75, "scale": 0.60}},
      "need_growth": {"fear": {"base": 1.45, "scale": -0.90}},
      "intent_bias": {
        "assault": {"base": 0.0, "scale": 0.10, "center": 0.5},
        "retreat": {"base": 0.0, "scale": -0.15, "center": 0.5}
      }
    }
  },
  "archetypes": {
    "veteran": {"label": "Ветеран", "modifiers": {"courage": 0.18}}
  }
}
```

Эффект считается как `base + scale · (value − center)`. Для
`need_urgency`/`need_growth` `center` обычно равен 0 (множитель), для
`intent_bias` — 0.5 (поправка к нейтральной черте). `model.morale`,
`model.mind`, `model.intent` и `model.detachment` содержат пороги, таймеры
и агрегаты отделения.

### Личность героя (`configs/characters/identity.json`)

Файл задаёт варианты, из которых редактор личности собирает героя перед
стартом кампании автоматов. Секции `genders`, `origins`, `vocations`,
`values`, `flaws` — словари `id → вариант`. Главная черта выбирается из
12 черт `configs/characters/traits.json`, поэтому отдельной секции `traits`
в файле личности нет.

```json
{
  "schema": 1,
  "label": "Личность героя",
  "default_name": "Новый правитель",
  "genders": {"male": {"label": "Мужчина"}},
  "origins": {
    "frontier": {
      "label": "Пограничная дорога",
      "summary": "Заставы, проводники и привычка не верить обещаниям.",
      "text": "Вы выросли там, где власть заканчивается у заставы.",
      "needs": {"health": 0.04, "fear": 0.03},
      "traits": {"courage": 0.05, "endurance": 0.04}
    }
  },
  "vocations": {}, "values": {}, "flaws": {}
}
```

`label` обязателен, `summary`/`text` необязательны (тогда описание
совпадает с названием). `needs` и `traits` — сдвиги к значениям персонажа,
а не абсолютные значения. Личность применяется к уже собранному пресету:
имя, биография, потребности, черты, подпись лидера и форма титула
меняются, а seed, состав фракций и баланс — нет. Пол выбирает форму
`role_title_female`/`leader_title_female`; например, для Империи это
«императрица», а не «император».

### Фракции, органы и работы (`configs/campaigns/base/lore_factions.json`)

Общие данные четырёх лорных кампаний. Шаблон подключает файл полем
`factions_path`. У фракции есть `goals`, `assets`, `actions`, `organs` и
`organ_interactions`; каждая работа ссылается на орган через `organ_id`, а
пресет превращает каждый орган в отдельный автомат
`automaton_organ_<side>_<organ>` и сам выводит `action_ids` органа из работ.

```json
{
  "organs": [
    {
      "id": "justice",
      "name": "Ведомство юстиции",
      "kind": "maintenance",
      "description": "Суды, эдикты и право говорить от имени закона."
    }
  ],
  "actions": [
    {
      "id": "imperial_edict",
      "label": "Опубликовать имперский эдикт",
      "description": "Эдикт объявляет мятеж незаконным; сомнение в нём само становится преступлением.",
      "organ_id": "justice",
      "cooldown": 2,
      "form": "information"
    }
  ],
  "organ_interactions": [
    {
      "id": "reinforce",
      "label": "Усилить орган",
      "description": "Перебросить людей и ресурсы: целостность органа растёт.",
      "cost": {"supply": 0.04},
      "integrity": 0.12,
      "faction": {"cohesion": 0.015},
      "cooldown": 2
    }
  ]
}
```

`description` работы необязательно, но пресет всегда его заполняет:
берёт явный текст, затем `effects.text`/`failure.text`, затем собирает
подпись. Поэтому экран может показать описание даже у старых работ.

`kind` органа (`command`, `coercion`, `intelligence`, `information`,
`maintenance`, `legitimacy`, `care`, `meaning`, `exchange`) задаёт его
проекцию на актив фракции и вес в фрактальной модели. Целостность органа
(`integrity`) инициализируется рантаймом, а не JSON: `campaign/fractal.py`
тянет её к уменьшенной копии состояния фракции, возвращает часть изменения
обратно и масштабирует силу работ. Игрок влияет на органы через
`organ_interactions`: `reinforce`, `reform`, `purge`, `resupply` (набор
можно менять данными). Взаимодействие стоит активов, имеет перезарядку,
меняет целостность органа и через `organ_spread` — его фракцию; выполняется
через `AutomataCampaign.advance(organ_action=...)` или экран «Сеть».

Подробная модель работ, активов, фрактала, взаимодействий и исхода — в
[`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md).

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
from character_traits import load_traits
from view.support.storyline import list_storylines, load_storyline

traits = load_traits()
assert len(traits.traits) == 12

worlds = list_worlds()
if worlds:
    assert load_world(worlds[0]["path"])["id"] == worlds[0]["world_id"]
roles = RoleCatalog.load()
assert roles.all_roles()
storylines = list_storylines()
if storylines:
    assert load_storyline(storylines[0]["storyline_id"]) is not None
```

Если какого-то контента нет, загрузчики ведут себя предсказуемо:
`list_worlds()`/`list_storylines()` возвращают пустой список, а
`RoleCatalog` поднимает `RoleError`. UI это переживает: меню открывается,
экран ролей показывает пустое состояние, а быстрая кампания просит
добавить мир.

### Первый запуск при неполном контенте

* `load_world()` без пути ищет `configs/worlds/agora_world.json`; если его
  нет, берётся первый валидный `*.json` из `configs/worlds/`. Поэтому новый
  мир можно назвать как угодно — переименовывать файл под код не нужно.
* В текущей поставке `configs/worlds/` пуст, поэтому «Быстрая кампания»
  из главного меню просит добавить мир. Основной рабочий путь — «Новая
  игра» с четырьмя лорными ролями и кампаниями автоматов.
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
