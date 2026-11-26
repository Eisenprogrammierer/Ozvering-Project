# Контент без кода: JSON-файлы и папки

> **Назначение.** Практическая карта источников контента: где лежит каждый
> тип данных, как его добавить, изменить и удалить, чем он проверяется и что
> действительно требует правки кода. Спецификации отдельных подсистем —
> [`AUTOMATA.md`](AUTOMATA.md), [`NAMING.md`](NAMING.md),
> [`SYSTEMS.md`](SYSTEMS.md), [`WORLD.md`](WORLD.md),
> [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md),
> [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md).

> **Поставка не пустая.** В `configs/` уже лежит рабочий контент: четыре
> лорных шаблона кампаний, production-мир `agora_world.json`, общие
> фракции/органы/работы, роли, сюжеты (включая свободный `free_life`),
> 12 черт характера, 16 желаний BDI, 15 делений, каталог личности,
> архетипы, имена, события и UI-контент.
> Каталоги `configs/strategy/`, `configs/environments/`,
> `configs/presets/`, `configs/classes/`, `configs/view/` и корневой
> `campaigns/` пока содержат только `.gitkeep` — это заготовки под свои
> данные. `tests/fixtures/content/` остаётся изолированным набором для
> тестов и не является игровым контентом.

## 1. Правила

1. **Один источник — JSON.** Игровые данные не дублируются в Python-коде.
2. **Добавление файла = добавление контента** там, где загрузчик сканирует
   папку: `configs/automata/`, `configs/campaigns/base/automata/`,
   `configs/naming/classes/`,
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
| `configs/automata/*.json` | графы редактора (schema 1) | `automata.storage.AutomataStore` | новый `*.json` или кнопка редактора | редактор/`store.save(automaton, slug)` | `store.delete(slug)` |
| `configs/campaigns/base/automata/*.json` | исполняемые автоматы фракций и органов (schema 2) | `campaign.state_machine` | новый `*.json` с `id`, `kind`, `states` | переходы/эффекты/условия | файл |
| `configs/naming/lexicon.json` | словарь морфологии | `NamingCatalog`/`PersonCatalog` | слово в `words` | значение слова | слово (проверить ссылки) |
| `configs/naming/classes/*.json` | классы автоматов | `NamingCatalog.load()` | новый файл класса | поля класса | файл |
| `configs/naming/interactions/*.json` | типы взаимодействий | `NamingCatalog.load()` | новый файл | поля типа | файл |
| `configs/naming/people.json` | культуры и фэнтези-темы | `PersonCatalog.load()` | запись в `cultures`/`fantasy_themes` | запись | запись |
| `configs/naming/policies.json` | правила имён по фракциям | `PersonPolicyCatalog.load()` | политика и алиасы | веса, эпитеты, режим | политика (проверить алиасы) |
| `configs/systems/events.json` | категории и шаблоны событий | `EventCatalog.load()` | элемент в `events` (и категорию) | `templates`/вес/категорию | элемент |
| `configs/systems/environment.json` | особенности среды | `EnvironmentCatalog.load()` | элемент в `features` | состояния/действия/дрейф | элемент |
| `configs/systems/playwright.json` | веса и шаблоны драматурга | `PlaywrightConfig.load()` | шаблон в `templates` | веса/ритм/шаблон | шаблон |
| `configs/characters/traits.json` | черты характера и их влияние | `character_traits.load_traits()` | черта в `traits`, архетип в `archetypes` | `base`/`scale`/`center`, `need_*`, `intent_bias`, `coefficients` | черта/архетип (проверить ссылки) |
| `configs/characters/bdi.json` | 16 желаний, состояния, предикаты убеждений, сути намерений | `bdi.load_bdi()` | желание в `needs`, предикат, суть | числа, `spillover`, `satisfaction`, `decision`, `conditions` | нельзя удалять 16 канонических желаний |
| `configs/characters/divisions.json` | 15 ролевых делений и культурные пресеты | `campaign.divisions.load_divisions()` | значение в `dimensions.<key>.values`, пресет в `presets` | `label`/`summary`/`values` | значение/пресет (проверить ссылки) |
| `configs/characters/identity.json` | варианты личности героя | `campaign.identity.load_identity_catalog()` | происхождение/призвание/ценность/слабость/пол в своей секции | `label`/`summary`/`text`, `needs`, `traits` | вариант (проверить, что на него не ссылаются сохранения) |
| `configs/characters/archetypes.json` | стартовые архетипы: слой, должность, потребности, черты, разделы личности | `campaign.identity.load_archetypes_catalog()` | архетип в `archetypes` | `social_layer`/`start_offices`/`identity_sections` | архетип (проверить `traits`, `needs` и `free_start`) |
| `configs/storylines/<id>.json` | основной сюжет; `storyline_tags` задают подбор по роли/архетипу | `view.support.storyline.load_storyline` | новый `<id>.json` | поля сюжета, `storyline_tags` | файл |
| `configs/storylines/<id>_char.json` | шаги создания персонажа | тот же, по полю `character_creation` | новый файл | `steps` | файл (и ссылку) |
| `configs/storylines/<id>_scenes.json` | сцены сюжета | тот же, по полю `scenes` | новый файл | `sequence` | файл (и ссылку) |
| `configs/roles/roles.json` | базовый каталог ролей | `RoleCatalog.load()` | роль в `roles` | поля роли | роль |
| `configs/roles/<name>.json` | дополнительный файл роли | `RoleCatalog.load()` | один объект роли или `{"roles": [...]}` | поля | файл |
| `configs/worlds/*.json` | миры кампании; production — `agora_world.json` (44 узла, 72 должности, 65 действий после слияния каталогов, 8 предметов с `automaton`, 6 сцен, `norms`, `sandbox`/`realtime`/`time_speeds`; без `days` и главы) | `campaign.world.load_world(path)` | новый мир | поля мира, `action_catalogs`, `scene_catalog`, `norms` | файл |
| `configs/worlds/actions/*.json` | открытые каталоги мирских действий; подключаются полем `action_catalogs` и сливаются по `id` после `actions` мира | `campaign.actions.merge_action_catalogs` через `load_world` | новый `*.json` с `actions` | `form`/`target.kinds`/`effects` | файл (проверить `action_catalogs`) |
| `configs/worlds/scenes/*.json` | локальные сцены: локация, публика, работы, вход/выход, время; подключаются полем `scene_catalog` | `campaign.scenes.SceneCatalog.load` через `load_world` | новый `*.json` с `scenes` | `location`/`public`/`works`/`requires`/`exit`/`time` | файл (проверить `scene_catalog`) |
| `configs/worlds/handlers/*.json` | обработчики работ дневного мира по формам: правила `when.id` и эффекты `receiver`/`failure`; потребности пишутся только в `needs`, активы — только в `assets` | `campaign.handlers.HandlerRegistry` в `WorldEngine` | новый `*.json` с `form`/`rules` | `form`/`rules`/`default` | файл (проверить `form`, дубли `when.id`; `campaign.content_lint` запрещает плоские ключи-потребности) |
| `configs/worlds/*_strategies.json` | долгосрочные стратегии узлов | `campaign.node_strategy.StrategyBook` | новый файл или поле `strategies` | селекторы/цель/веса | файл |
| `configs/knowledge/commonsense/*.jsonl` | курированные факты здравого смысла: речевые акты, режимы, причины эмоций, свойства предметов; `schema.json` задаёт отношения, правила файлов и `style_hints` (режим → стиль ответа), `raw/` — исходные LLM-выгрузки; подсказка `/смысл`, runtime-хук регистра и корпус парафраз берут отсюда | `campaign.commonsense.load_commonsense` | новый `*.jsonl` + запись в `schema.json.files` | `s`/`r`/`o`/`weight`/`lang`/`origin` | файл (проверить `python -m campaign.commonsense --check`) |
| `configs/environments/*.json` | многофазные планы среды арены | `core41.environment.load_environment_plan()` | новый файл | `goals`/`ratio`/`horizon` | файл |
| `configs/worlds/biography.json` | таблицы биографии | `load_biography()` | таблицы | значения | файл (если не нужен) |
| `configs/campaigns/*.json` | шаблоны пресетов | `campaign.preset.load_template()` | новый шаблон | фракции/сценарий | файл |
| `configs/campaigns/forms.json` | манифест 19 форм работы: `payload_kinds`, `target_kinds`, `default_handler`, теги | `campaign.actions.FormCatalog.load()` | форма в `forms` + обработчик `base/handlers/<id>.json` | адресаты/обработчик | форма (проверить обработчик и действия) |
| `configs/campaigns/base/lore_factions.json` | общие фракции, органы, работы, взаимодействия и геометрия лорных кампаний | `load_template()` по полю `factions_path` | фракция в `factions`, орган в `organs`, работа в `actions`, взаимодействие в `organ_interactions`, геометрия в `geometry.<side>` | цели, активы, титулы, органы, работы, взаимодействия, длины/углы | фракция/орган/работа/взаимодействие/геометрия (проверить `organ_id`, `links` и узлы геометрии) |
| `configs/campaigns/base/automata_defaults.json` | базовые данные кампании автоматов | `campaign.defaults.load_defaults()` | секция в JSON | модель, интервалы реального времени, скорости, взаимодействия, потребности, бюджет, слоты и длительности процессов | секция (ядро читает без хардкода) |
| `configs/campaigns/base/chronicle_phrases.json` | языковые шаблоны хроники: открытия по значимости, шаблоны решения и причины | `campaign.chronicle.load_phrases()` | новый шаблон в списке | `openings`/`decision_patterns`/`cause_patterns` | шаблон (проверить `python -m campaign.content_lint`: категории и плейсхолдеры) |
| `configs/content/payload_kinds.json` | data-driven реестр видов `payload`: обязательные/default/числовые поля, подпись и шаблон описания | `core41.payload.load_payload_kinds()` (по умолчанию при импорте; env `OZVERING_PAYLOAD_KINDS`) | новый вид в `kinds` | `required`/`defaults`/`numeric`/`describe_defaults` | вид (проверить `python -m campaign.content_lint`) |
| `configs/content/*.json` | именованный UI-контент | `view.support.content.Content` | новый `*.json` доступен через `get(name)` | содержимое файла | файл |
| `configs/cognition/backends.json` | флаги и пороги когнитивного слоя: `ai_backend`, `nlu_backend`, `dialogue_backend`, `inference_backend`, `shadow`, `thresholds` (включая `fallback_rate_max`), `timeouts` | `campaign.cognition.load_flags()`; env `OZVERIN_AI_BACKEND`/`OZVERIN_NLU_BACKEND`/`OZVERIN_DIALOGUE_BACKEND`/`OZVERIN_INFERENCE_BACKEND` переопределяют только бэкенд | новый ключ в JSON | бэкенд/порог/таймаут | ключ (проверить `tests/test_cognition_backends.py`) |
| `configs/cognition/golden_corpus.json` | золотой корпус диалога: 144 записи `(seed, snapshot, input) → кадр` legacy-NLU; фиксирует поведение до миграции | `python -m campaign.cognition.corpus_builder --write` | `configs/dialogue/*` (фразы и лексикон) | кадр, слоты, `intent`, `evidence` | `python -m campaign.cognition.corpus_builder --check` |
| `configs/rive/` | сгенерированные `dialogue.rive` и `manifest.json` для RiveScript NLU: точные фразы плюс грамматические триггеры (закрытые классы — литералы, открытые — слот `[*]`); **не редактировать вручную** | `python -m campaign.cognition.rive_compiler --write` | `configs/dialogue/lexicon.json`, `paraphrases.json`, `actions.json`, `grammar.json` | триггер, замена, манифест | `python -m campaign.cognition.rive_compiler --check` |
| `configs/soar/decision.json` | формула и настройки выбора работы NPC: пороги оценки, `epsilon-greedy`, `epsilon`, seed, число циклов | `campaign.cognition.soar_compiler.load_model()` | новый ключ в JSON | формула, порог, режим выбора | `tests/test_cognition_soar.py` |
| `configs/soar/npc_policy.soar` | сгенерированные продукции Soar: оценка кандидата и запись решения в output-link; **не редактировать вручную** | `python -m campaign.cognition.soar_compiler --write` | `configs/soar/decision.json` | продукция, digest | `python -m campaign.cognition.soar_compiler --check` |
| `configs/soar/pragmatics.json` | настройки прагматики диалога: `tie_epsilon` и число циклов решения | `campaign.cognition.pragmatics_compiler.load_model()` | новый ключ в JSON | порог, режим выбора | `tests/test_d6_pragmatics.py` |
| `configs/soar/pragmatics.soar` | сгенерированные продукции Soar: интерпретация кадра, выбор плана и исход раскрытия; **не редактировать вручную** | `python -m campaign.cognition.pragmatics_compiler --write` | `configs/soar/pragmatics.json`, `configs/dialogue/disclosure.json` | продукция, digest | `python -m campaign.cognition.pragmatics_compiler --check` |
| `configs/soar/inference.json` | настройки прямого замыкания вывода: число циклов, таймаут, лимит узлов | `campaign.cognition.inference_compiler.load_model()` | новый ключ в JSON | циклы, таймаут, лимит | `tests/test_d6_inference.py` |
| `configs/soar/inference.soar` | сгенерированные продукции Soar: прямое замыкание `rules.json` под `^node`, высота и экспорт в output-link; **не редактировать вручную** | `python -m campaign.cognition.inference_compiler --write` | `configs/dialogue/rules.json`, `configs/dialogue/ontology.json`, `configs/soar/inference.json` | продукция, digest | `python -m campaign.cognition.inference_compiler --check` |
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

### Сюжет (`configs/storylines/<id>.json`)

Основной файл сюжета; `*_char.json` и `*_scenes.json` — связанные файлы
персонажа и сцен. Сокращённый пример реального `empire_campaign.json`:

```json
{
  "storyline_id": "empire_campaign",
  "title": "Империя: порядок против хаоса",
  "description": "Кампания за Империю: удержать монополию на законность...",
  "campaign_template": "configs/campaigns/empire_campaign.json",
  "campaign_seed": 11,
  "identity_editor": true,
  "scenes": "empire_campaign_scenes",
  "win_conditions": [{"type": "automata_outcome", "value": "win"}],
  "lose_conditions": [{"type": "automata_outcome", "value": "lose"}]
}
```

У automata-кампаний нет `arc`, `win_scene`, `lose_scene`, `variants`,
`variant_by` и `choices`: сюжет собирается из `AutomataCampaign.narrative`
в `campaign/chronicle.py`, а сцены такой кампании — только `gameplay`.
Это проверяет `campaign.content_lint`; инвариант описан в
[`NARRATIVE_INVARIANT.md`](NARRATIVE_INVARIANT.md).

`character_creation` и `scenes` — это **id соседних файлов** в
`configs/storylines/` (`mini_char` → `mini_char.json`), а не пути к мирам.
Свободный режим `free_life` использует сцены `world_briefing` и `world`:
сводка мира собирается `campaign/world_briefing.py` из конфига мира,
профиля и состояния, а не из авторского слайда. Свободный мир не задаёт
`days`, главу и дедлайн: история открыта, а в сводке и эпилоге видны
держава, день, режим и репутация.
Необязательные поля основного файла: `world_path`, `strategy_path`,
`biography_path`, `scenario_path`, `adjutant_orders`,
`storyline_tags`. Теги — свободные строки; `list_storylines(tags=...)`
сортирует совпадения по числу общих тегов, а при нулевом совпадении
возвращает полный список, чтобы выбор сюжета не был пустым.

`list_storylines()` показывает только основные файлы и пропускает
`*_char.json`/`*_scenes.json`. Если `character_creation` или `scenes`
не указаны, соответствующий блок остается пустым. `identity_editor: true`
включает редактор личности перед стартом; сейчас так помечены четыре
лорных сюжета (`empire_campaign`, `republic_campaign`, `cult_campaign`,
`corporation_campaign`).

### Сцена (`configs/worlds/scenes/<name>.json`)

Сцена не заменяет узел мира: она говорит, кто здесь находится, что здесь
уместно и по каким правилам сюда входят. `location` ссылается на узел,
`works` — на существующие `ActionSpec` мира, `public` становится обычными
персонажами `WorldEngine`.

```json
{
  "id": "street",
  "label": "Улица Агоры",
  "location": "agora_street",
  "tags": ["street", "music", "free"],
  "public": [
    {"id": "street_piper", "name": "Тим-дудочник", "trust": 0.12}
  ],
  "works": ["perform_song", "embrace", "ask_favor"],
  "requires": {"domains": ["exchange"]},
  "exit": {"after_days": 3},
  "time": {"slots": 3}
}
```

`requires` поддерживает `attached`, `office_ids`, `domains`,
`has_office`, `day_min`/`day_max` и `tags_any`; `exit` — `when_detached` и
`after_days`. `time.slots` — число действий в сцене, остальные поля времени
берутся из мира. Сцены подключаются к миру полем `scene_catalog` (путь или
список путей); линтер проверяет структуру, дубли и пустые работы,
`validate_world()` — ссылки на узлы и действия.

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
  "probability": 0.8,
  "tags": ["court"],
  "conditions": [
    {"kind": "need", "key": "status", "op": ">=", "value": 0.6}
  ],
  "visibility": {"scope": "global"},
  "speed": 1.0,
  "duration": 4.0,
  "cooldown": 12.0
}
```

Категория должна быть объявлена в `categories`. `conditions` задают
порог допуска, `probability` — личный шанс, `speed`/`duration` — тайминг,
`visibility` — кто видит событие. **Событие ничего не меняет:** у него нет
`effects`, `apply` или `emit`; оно только отражает уже случившиеся
процессы. Доля розыгрыша —
`weight × category.weight × probability`. Удаление события не требует
правки кода, если на его id никто не ссылается. Полное руководство —
[`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md).

### Черты характера (`configs/characters/traits.json`)

Один файл задаёт все 12 черт, их базы, разброс, архетипы и коэффициенты
влияния. 16 желаний и их связи живут в `configs/characters/bdi.json`;
черта лишь сдвигает коэффициенты через блок `coefficients`
(`need:<желание>`, `need_growth`, `force_drain`, `energy_drain`,
`belief_weight`, `intention_weight`). Что именно каждая потребность
значит для действия — данные `model.intent.need_intents` и
`bdi.intention_essences`.

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

Связи органов задаются полем `links` — это сеть:
`"links": ["wehrmacht", "guard"]`. Связь двусторонняя, циклы и кластеры
допустимы; `campaign/fractal.py` проверяет неизвестные id и связь узла с
самим собой. Поле `parent_id` задаёт отдельное дерево вложенности:
`"parent_id": "intelligence"`. Цикл родителей — ошибка; при тике ребёнок
тянется к родителю, а родитель слышит детей.

У органа могут быть собственные шкалы:
`"scales": {"stealth": 0.62}`, `"scale_targets": {"stealth": 0.7}`.
Эффекты пишут `"organs": {"agents": {"scales": {"stealth": -0.1}}}`,
условия читают `{"kind": "organ", "key": "agents", "scale": "stealth"}`,
снимок сохраняет значения.

`kind` органа (`command`, `coercion`, `intelligence`, `information`,
`maintenance`, `legitimacy`, `care`, `meaning`, `exchange`) задаёт его
вклад в производные активы фракции и вес в сетевой модели. Целостность
органа (`integrity`) инициализируется рантаймом, а не JSON:
`campaign/fractal.py` тянет её к уменьшенной копии состояния фракции,
возвращает часть изменения обратно контекстным импульсом и масштабирует
силу работ. Игрок влияет на органы через `organ_interactions`: `reinforce`,
`reform`, `purge`, `resupply` (набор можно менять данными). Взаимодействие
стоит активов, имеет перезарядку, меняет целостность органа и через
`organ_spread` — его фракцию; выполняется через
`AutomataCampaign.advance(organ_action=...)` или экран «Сеть».

Активы фракции (`legitimacy`, `cohesion`, `supply`, `fear`, `morale`,
`influence`, `energy`) больше не хранятся отдельно: это производные
проекции BDI персонажей, целостности сети органов и краткоживущего
контекста взаимодействий. Формулы и драйверы лежат в
`configs/campaigns/base/automata_defaults.json` → `faction_state`; меняя
веса или добавляя метрику, не нужно править Python.

Подробная модель работ, производных активов, сети органов,
взаимодействий и исхода — в
[`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md).

### Геометрия (`geometry` в `lore_factions.json`)

Верхнеуровневый ключ `geometry` задаёт по сторонам семантическую
геометрию органов: длины рёбер, циклический порядок соседей и углы
поворотов. Это не координаты: `layout.x/y` остаётся проекцией для
редактора и игровыми расчётами не читается.

```json
"geometry": {
  "red": {
    "schema": 1,
    "model": "metric_graph",
    "dimension": 2,
    "composition": "shortest_path",
    "edges": [
      {"from": "imperial_staff", "to": "wehrmacht", "length": 1.7}
    ],
    "orientation": {
      "imperial_staff": [{"to": "wehrmacht", "turn": 6.283185307}]
    }
  }
}
```

Каждый узел ориентации обязан быть органом фракции, а `turn` — покрывать
все его `links`. Сумма поворотов вокруг плоского узла равна `2π`.
Дальние расстояния складываются по кратчайшему пути, локальные углы
читаются из порядка соседей. Без блока `geometry` работает совместимый
режим: топология из `links`, единичные длины, равные углы. Проверка —
`python -m campaign.content_lint`. Полная схема и ограничения этапа —
[`AUTOMATA_GEOMETRY.md`](AUTOMATA_GEOMETRY.md).

### Автомат (`configs/automata/<slug>.json`)

Один файл — один автомат. Полная схема редактора —
[`AUTOMATA.md`](AUTOMATA.md). `AutomataStore` сам строит slug из имени,
поэтому новый файл можно создать копированием и правкой.

Исполняемые автоматы кампании лежат отдельно, в
`configs/campaigns/base/automata/<id>.json`: схема 2 с полями `id`, `kind`,
`initial`, `states`, `handlers`. Их читает
`campaign.state_machine.StateMachineCatalog`, а `preset.py` строит из них
граф кодекса. Разделение папок не даёт редактору показывать исполняемые
состояния как пустые графы; загрузчик всё равно пропускает файлы без
`schema: 2`, если они случайно окажутся рядом. Дефолты:
`faction_default.json`, `organ_default.json` и `subfaction_default.json`.
Специализированные файлы выбираются ссылкой из данных: `faction.automaton`,
поле `automaton` подфракции, `organ.automaton_id`, затем `organ.<kind>`.
Проверка — `python -m campaign.content_lint`.

Исполняемые блоки и целые файлы описаны JSON Schema в
`configs/schemas/`: `automaton`, `effects`, `conditions`, `requires`,
`organ`, `subfaction`, `order`, `bdi`, `work`, `lore_factions`,
`automata_defaults`, `campaign_template`, `event`/`event_item`.
Их проверяет `campaign/content_schema.py`; `content_lint` вызывает его
вместе с семантическими проверками ссылок. Линтер обходит
`configs/campaigns`, `configs/systems/events.json` и
`configs/systems/playwright.json`, поэтому опечатка в шаблоне кампании,
событии или `event_id` драматурга видна до запуска.
`jsonschema` — необязательная dev-зависимость: без неё линтер работает
как раньше. Стабильность поведения после правок схем и контента
фиксирует `tests/test_campaign_golden.py`.

Действия кампании идут процессами. Блок
`automata_defaults.json::action_process` задаёт `slots` (сколько дел
одновременно), `duration_scale` (игровые секунды на единицу
`template.duration`), `default_duration`, `min_duration`, повторную
проверку при завершении и возврат цены при срыве. Работа может задать
`duration` напрямую; сценарий кампании — переопределить блок
`scenario.action_process`. Эффект применяется не при клике, а когда
`advance_time` доведёт процесс до нуля. Мгновенный `perform` остаётся
для CLI и старых вызовов. ИИ использует те же слоты: `_advance_ai`
занимает их через `start_action`, а `auto_action` выбирает работу по
`automata_defaults.json::ai_model`. Блок задаёт веса потребностей,
намерения, доктрины, убеждений и повреждённых органов; фракция в
`lore_factions.json` может дополнительно описать `doctrine.forms` и
`doctrine.essences`. Ни intent, ни форма работы не зашиты в Python:
`ai_action_weights()` показывает итоговые веса для диагностики.

Блок `ai_model.npc_policy` включает выбор работы политикой
`NeedPolicy`; по умолчанию `enabled = true`. Поле `backend` задаёт
бэкенд всех сторон (`legacy`, `shadow`, `soar`), `backends` — карту
`фракция → backend`; если ключа `backend` нет, действует глобальный
`ai_backend` из `configs/cognition/backends.json` (по умолчанию
`soar`). `timeout_ms` — бюджет решения (0 — взять общий
`timeouts.decision_ms`). В режиме `shadow` Soar считает решение
параллельно, игра получает выбор легаси, а
`npc_decision_report()` показывает согласие, ошибки и латентность по
сторонам. Если пакет `soar-sml` недоступен (колесо собрано не под все
платформы), `shadow`/`soar` понижаются до `legacy`: Soar повторяет
формулу `NeedPolicy` и tie-break один в один, поэтому выбор тот же, а
`report()["unavailable"]` и `ok: false` показывают, что заявленный
бэкенд не работал. Откат — `enabled = false` или
`OZVERIN_AI_BACKEND=legacy`.
`npc_outcome_report()` добавляет длинные метрики: `needs` — среднее
давление и удовлетворённость (`1 − pressure`) по 16 потребностям
каждой стороны, `jobs` — `distinct`, энтропию, `evenness` и
`top_share` выбранных работ. Метрики живут в памяти и не попадают в
сейв.

Бюджет ограничен на двух уровнях. `timeout_ms` (по умолчанию
`timeouts.decision_ms = 200`) — потолок одного решения;
`tick_timeout_ms` (по умолчанию `timeouts.tick_ms = 250`) — сумма
Soar-решений за ход. Каждое решение получает
`min(timeout_ms, остаток_тика)`, а на новом ходу счётчик
обнуляется. Исчерпание бюджета тика — не ошибка Soar, а ресурсный
предел: остаток хода решает легаси, а факт попадает в
`report()["budget"]`/`errors`, поэтому прогон честно помечается
`ok: false` (в `shadow` и в `soar` одинаково). Настоящие ошибки Soar
(ядро, продукции, неизвестный оператор, превышение `timeout_ms`)
в `soar` не маскируются и прерывают решение.
`npc_tick_budget()` показывает `limit_ms`/`spent_ms`/`left_ms`
текущего хода. Пока бюджет не исчерпан, выбор Soar детерминирован;
исчерпание зависит от загрузки машины, поэтому такой прогон
помечается `ok: false` и не годится для паритетных сравнений
бэкендов.

Прагматика диалога управляется `dialogue_backend` из
`configs/cognition/backends.json` (`legacy`, `shadow`, `soar`; в
поставке `shadow`). В `shadow` ответ строит легаси, а Soar выбирает
план и исход раскрытия рядом и пишет расхождения в
`DialoguePragmatics.report()` (`plan_mismatches`,
`disclosure_mismatches`, `decisions`, `errors`, `elapsed_ms`);
необязательный `shadow_sink` получает записи `plan`/`disclosure` для
корпуса. В `soar` выбор Soar используется, ошибки не маскируются; без
`soar-sml` оба режима понижаются до `legacy` с `unavailable: true`,
`ok: false`. Ответ несёт `pragmatics_backend` и `pragmatics_trace`;
откат — `OZVERIN_DIALOGUE_BACKEND=legacy`.

Логический вывод управляется `inference_backend` из того же JSON
(`legacy`, `shadow`, `soar`; в поставке `soar`). Soar строит прямое
замыкание `rules.json` в `inference.soar`; Python выбирает из него
решения в порядке легаси, проверяет общие переменные правил и отсекает
циклы, поэтому `Solution`/`ProofStep` совпадают с `InferenceEngine`.
В `shadow` ответы и доказательства остаются легаси, расхождения
пишутся в `InferenceBackend.report()` (`queries`, `agreements`,
`disagreements`, `errors`, `elapsed_ms`); в `soar` ошибки не
маскируются; без `soar-sml` — деградация до `legacy` с
`unavailable: true`, `ok: false`. Откат —
`OZVERIN_INFERENCE_BACKEND=legacy`. `CounterfactualEngine` пока
остаётся на легаси.

Отношения — направленная матрица кампании: `relation_model` в
`automata_defaults.json` задаёт оси, лимит и веса форм, а
`effects.relations`, `requires.relations` и условия `kind: relation`
пишут и читают её без правки Python. Взаимодействия персонажей и приказы
дополняют матрицу связью «персонаж ↔ фракция».

Приказы «фракция → персонаж» описываются блоком
`automata_defaults.json::order_model` (или `scenario.order_model`
кампании). `interval`, `max_per_tick`, `cooldown` управляют частотой,
`orders[]` — сами приказы: `when`, `requires`, `recipient`
(`priority`, `leader`, `all`, `lowest_morale`, `highest_morale`),
`effects`, `relations` и `cost`. Эффекты адресуют персонажа через
`character_id`, который подставляет ядро; `recipient: all` применяет
потребности ко всем, не дублируя активы. ИИ отдаёт приказы на
организационном тике только за не-игровые фракции; игрок может вызвать
`issue_order(side, order_id, character_id=None)` тем же путём. Схема —
`configs/schemas/order.schema.json`.

Производственный набор: четыре фракционных автомата, три автомата
подфракций и девять архетипов органов. Добавление нового файла в папку не
меняет поведение, пока на него не сослались; `*.default` остаётся
совместимым fallback.

## 4. Проверка после правки

```bash
# все JSON в configs и тестовых фикстурах читаются
python3 -m pytest -q tests/test_content_pipeline.py

# контракты BDI, делений и рантайм-событий
python3 -m pytest -q tests/test_bdi.py tests/test_divisions.py \
  tests/test_events_runtime.py

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

`campaign/world.py` — библиотечный модуль. Запускайте игру через
`venv/bin/python main.py --view`, а не `python3 campaign/world.py`: при
запуске файлом Python не видит пакет `core41`. Из кода используйте
`from campaign.world import WorldEngine, load_world`.

Флаг `-m` принимает имя модуля через точку, а не путь. Поэтому
`python3 -m campaign/world` — ошибка (`No module named campaign/world`), а
`python3 -m campaign.world` — корректная форма, но она лишь печатает
подсказку: это библиотека, а не игра. То же для `core41/arena.py`:
`python3 -m core41/arena` ошибочно, `python3 -m core41.arena` печатает
подсказку, запуск арены — `python3 main.py --arena`. Краткая справка и демо
ядра: `python3 -m core41` и `python3 -m core41 --demo`.

Если какого-то контента нет, загрузчики ведут себя предсказуемо:
`list_worlds()`/`list_storylines()` возвращают пустой список, а
`RoleCatalog` поднимает `RoleError`. UI это переживает: меню открывается,
экран ролей показывает пустое состояние, а быстрая кампания просит
добавить мир.

### Первый запуск при неполном контенте

* `load_world()` без пути ищет `configs/worlds/agora_world.json`; если его
  нет, берётся первый валидный `*.json` из `configs/worlds/`. Поэтому новый
  мир можно назвать как угодно — переименовывать файл под код не нужно.
* В поставке есть production-мир `configs/worlds/agora_world.json`, поэтому
  «Быстрая кампания» из главного меню запускается без дополнительных
  действий. Основной путь — «Новая игра»: четыре лорные роли с кампаниями
  автоматов или свободный житель с сюжетом `free_life`.
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

- План расширения контента, приоритеты и контракты полей — в
  `docs/CONTENT_ROADMAP.md`.
- Новые **записи** перечисленных типов добавляются без кода.
- Новые **поля** старых типов можно сохранять в JSON, но UI/формулы увидят
  их только после чтения в коде.
- Новые **типы** контента (например, новая механика действия) требуют
  загрузчика/обработчика.
- Сетевой загрузки, hot-reload и редактора всех типов нет; перезагрузка
  экрана/объекта достаточна.
