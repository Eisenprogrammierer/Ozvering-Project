# BDI, деления и события: контент персонажа

> **Назначение.** Практическое руководство по трём слоям, которые
> описывают персонажа и мир без правки формул: BDI (желания, убеждения,
> намерения), 15 ролевых делений и рантайм-события. Все определения —
> в JSON; Python реализует только алгоритмы чтения, проверки, течения
> времени и выбора.

> **Граница модели.** У автомата есть ровно две метрики — `force` и
> `energy`. Здоровье, раны, болезнь, страх и прочие состояния живут в BDI
> и влияют на силу/энергию через коэффициенты. Персонаж умирает, когда
> `force <= 0`; отдельного порога смерти по здоровью нет.

## 1. BDI: `configs/characters/bdi.json`

Загрузчик — `bdi.load_bdi()`; живое состояние — `bdi.BDIState`. Файл
задаёт 16 канонических желаний, состояния, предикаты убеждений, сути
намерений и веса решений.

### 1.1. Желание

```json
{
  "needs": {
    "hunger": {
      "label": "голод",
      "good": "продовольствие",
      "initial": 0.18,
      "growth": 0.0038,
      "threshold": 0.72,
      "force_drain": 0.06,
      "energy_drain": 0.03,
      "spillover": {"fatigue": 0.24, "health": 0.16},
      "satisfaction": {"force": 0.02, "energy": 0.08}
    }
  }
}
```

| Поле | Смысл |
|---|---|
| `label`, `good` | подписи для UI и логов |
| `initial` | стартовое значение в шкале `0..1` |
| `growth` | прирост за игровые сутки (при `seconds_per_unit=1800`) |
| `threshold` | порог, после которого желание начинает давить |
| `force_drain`, `energy_drain` | давление на метрики выше порога |
| `spillover` | во что превращается пренебрежение: `желание → прирост` |
| `satisfaction` | сколько силы/энергии возвращает удовлетворение |

Набор из 16 ключей фиксирован контрактом `bdi.NEEDS`: `hunger`, `thirst`,
`fatigue`, `health`, `fear`, `anxiety`, `loneliness`, `reproduction`,
`knowledge`, `creativity`, `boredom`, `status`, `spirituality`, `skill`,
`love`, `friendship`. Добавлять или переименовывать ключи нельзя — это
контракт модели; менять числа, тексты и связи `spillover` — можно.

### 1.2. Убеждение — тройка

Убеждение всегда `(subject, predicate, object)`: субъект-автомат,
предикат-свойство/отношение, объект-автомат. Предикаты объявляются в
`belief_predicates`:

```json
{
  "belief_predicates": {
    "trusts": {"label": "доверяет", "inverse": "trusted_by"},
    "fears": {"label": "боится", "inverse": "feared_by"}
  }
}
```

```python
actor.believe("actor-1", "trusts", "actor-2")
actor.beliefs_about("actor-2")   # тройки, где субъект или объект — actor-2
actor.forget("actor-1", "trusts")
```

`BDIState.believe()` заменяет прежнюю тройку с теми же `subject` и
`predicate`. Обратный предикат добавляется только при
`strict_predicates: true`.

### 1.3. Намерение — пара

Намерение всегда `(target, essence)`: объект намерения и суть.

```json
{
  "intention_essences": {
    "eat": {"label": "утолить голод", "need": "hunger"},
    "attack": {"label": "напасть", "need": "fear", "belief_bonus": 0.15},
    "defend": {"label": "защитить", "need": "fear"},
    "probe": {"label": "прощупать", "need": "anxiety"}
  }
}
```

`target` может быть:

* именем желания (`hunger`) — тогда `target_kind == "need"`;
* `character:<id>` или `automaton:<id>` — явный вид;
* любым другим идентификатором — считается автоматом.

Старые тактические виды действий (`assault`, `fire`, `hold`, `rest`,
`retreat`) остаются совместимым слоем и проецируются на сути
(`attack`, `probe`, `defend`, `rest`, `retreat`).

### 1.4. Состояния вместо метрик

`conditions` описывают болезнь и раны. Это не отдельные шкалы автомата:
они растут, лечатся, давят на `force`/`energy` и повышают желание
`health`.

```json
{
  "conditions": {
    "sickness": {
      "label": "болезнь",
      "max": 1.0,
      "progress": 0.004,
      "rest_recovery": 0.01,
      "treat_rate": 0.08,
      "work_penalty": 0.6,
      "work_floor": 0.4,
      "force_drain": 0.15,
      "energy_drain": 0.1,
      "health_need_growth": 0.008
    }
  }
}
```

### 1.5. Решение и смерть

`decision` задаёт веса выбора намерения: `need_weight`,
`belief_weight`, `intention_weight`, `novelty` и
`predicate_weights`. `death.metric` обязан быть `"force"`; любое другое
значение отвергается загрузчиком.

```json
{
  "death": {
    "metric": "force",
    "at_or_below": 0.0,
    "note": "Здоровье — состояние BDI, а не порог смерти."
  }
}
```

## 2. Деления: `configs/characters/divisions.json`

Загрузчик — `campaign.divisions.load_divisions()`. Деления отвечают на
вопрос «кем персонаж является для мира»: земля, сословие, экономика,
политика, вера, этнос, возраст, пол, профессия, институт, миграция,
образование, собственность, право, семья. Это ролевой слой: он не меняет
формулы силы и энергии, но его читают события, видимость и проверки.

```json
{
  "dimensions": {
    "social": {
      "label": "сословие",
      "summary": "Место в социальной иерархии.",
      "values": [
        {"id": "elite", "label": "элита", "summary": "Власть по рождению."},
        {"id": "middle", "label": "середина", "summary": "Ремесло и служба."},
        {"id": "worker", "label": "работник", "summary": "Труд руками."}
      ]
    }
  },
  "presets": {
    "germanic": {"social": "elite", "family": "clan"}
  }
}
```

Ровно 15 измерений заданы контрактом `campaign.divisions.DIMENSIONS`:
`territorial`, `social`, `economic`, `political`, `religious`, `ethnic`,
`age`, `sex`, `professional`, `institutional`, `migratory`,
`educational`, `property`, `legal`, `family`.

* `Divisions.set(key, value)` проверяет значение и выбрасывает
  `DivisionError` для неизвестного измерения/значения.
* `validate()` при `strict: false` молча отбрасывает неизвестные ключи;
  при `strict: true` — выбрасывает ошибку.
* `presets` — готовые наборы по культурам. Пресет не обязан заполнять все
  15 измерений: пол, возраст и семейное положение часто задаются отдельно.
* `Divisions.tags()` даёт теги `dimension:value` для событий, а
  `snapshot()` — подписи и описания для UI.

Деления персонажа автоматически попадают в контекст кампанийных событий
(`campaign.automata.AutomataCampaign._story_context`) как `divisions` и
`tags`.

## 3. Фракционные активы как следствие BDI

У фракции-автомата нет собственного независимого набора ролевых активов.
`legitimacy`, `cohesion`, `supply`, `fear`, `morale`, `influence` и
`energy` — производные проекции:

* потребностей, черт, морали, `force` и `energy` персонажей;
* целостности органов сети, сгруппированных по `kind`;
* краткоживущего контекста работ, приказов, влияний и событий.

Формулы и драйверы лежат не в Python, а в
`configs/campaigns/base/automata_defaults.json` → `faction_state`:

```json
{
  "faction_state": {
    "assets": {
      "legitimacy": [
        {"metric": "characters.mean:satisfaction.status", "weight": 0.30},
        {"metric": "organs.kind:legitimacy", "weight": 0.20},
        {"metric": "context.legitimacy", "weight": 0.12}
      ]
    },
    "drivers": {
      "legitimacy": [
        {"target": "characters", "need": "status", "weight": -0.55},
        {"target": "organs", "kind": "legitimacy", "weight": 0.65}
      ]
    }
  }
}
```

`metric` читает агрегат (`characters.mean:...`, `organs.kind:...`,
`organization.*`, `network.*`, `context.*`), а `drivers` описывает, как
изменение актива раскладывается обратно: в потребность, черту, состояние,
мораль, `force`/`energy` персонажа или целостность органа. Поэтому
«усилить законность» означает накормить статус людей, поддержать
легитимный орган и оставить след в контексте, а не подвинуть отдельную
шкалу. `FactionRuntime.assets` — живое представление; запись в него не
создаёт второго хранилища.

Органы при этом связаны полем `links`, а не `parent_id`: сеть допускает
циклы и кластеры, а `campaign.fractal` считает расстояния, степени и
плотность связей. Старые `subordinate`/`superior` в командах автоматов
читаются как сетевые соседи.

## 4. События: `configs/systems/events.json`

Загрузчик — `systems.events.EventCatalog.load()`, рантайм —
`EventEngine`. Содержимое (тексты, условия, видимость, скорость,
длительность) — данные; код только фильтрует, разыгрывает и двигает время.

### 4.1. События — только чтение

**Событие — ролевой компонент, а не часть ядра.** Это архитектурный
контракт, а не пожелание:

* событие **ничего не производит**: у него нет `effects`, `apply`,
  `emit`; оно не меняет `force`, `energy`, потребности, состояния,
  активы, убеждения и флаги;
* событие **не порождается событием**: очередь событий не является
  причиной состояния, и одно событие не вызывает другое;
* событие **только отражает** уже случившиеся процессы: у него есть
  `conditions` (что видно), `visibility`, `weight`, `category` и
  `text`/`templates`;
* состояние меняют работы (`actions`), переходы автоматов и действия
  игрока. Если нужно рассказать о последствиях работы, событие просто
  получает условие на уже изменившийся актив/потребность/убеждение.

Следствия:

| Место | Поведение |
|---|---|
| `campaign.automata._advance_story_events` | только фиксирует событие в журнале, состояние не трогает |
| `campaign/content_lint.py` | отклоняет событие с `effects`, `apply` или `emit` |
| `systems/events.py` | `EventDefinition.effects` и `EventEngine.effects()` — **легаси**; кампания их не применяет |
| `configs/systems/events.json` | исторические `effects` подлежат удалению; новые события их не получают |

### 4.2. Шаблон события

```json
{
  "id": "hunger_riot",
  "category": "unrest",
  "title": "Голодный бунт",
  "templates": ["{actor} не выдержал: на {place} начался голодный бунт."],
  "weight": 1.2,
  "probability": 0.75,
  "severity": 0.6,
  "stakes": 0.7,
  "tags": ["unrest", "hunger"],
  "conditions": [
    {"kind": "need", "key": "hunger", "op": ">=", "value": 0.7},
    {"kind": "division", "key": "social", "op": "in",
     "value": ["worker", "peasant", "outcast"]}
  ],
  "visibility": {
    "scope": "faction",
    "divisions": ["social:worker", "social:peasant"]
  },
  "speed": 2.0,
  "duration": 6.0,
  "cooldown": 24.0
}
```

| Поле | Смысл |
|---|---|
| `weight` | базовый вес в розыгрыше |
| `probability` | личный шанс после выбора, `0..1` |
| `conditions` | список условий, объединяются через `AND` |
| `visibility` | кто видит событие |
| `speed` | сколько секунд копится до публикации |
| `duration` | сколько секунд событие остаётся активным |
| `cooldown` | пауза до повторного выбора этого шаблона |

Поля `effects` в шаблоне **нет**: см. §4.1. Всё, что событие «делает», —
это выбирает текст и тон по текущему состоянию.

Доля вероятности считается как
`weight × category.weight × probability`; доли нормируются к `1`.
Событие без подходящих условий не попадает в розыгрыш.

### 4.3. Условия

```json
{"kind": "need", "key": "fear", "op": ">=", "value": 0.6}
{"kind": "trait", "key": "courage", "op": "<", "value": 0.4}
{"kind": "division", "key": "religious", "op": "==", "value": "official"}
{"kind": "force", "op": "<=", "value": 0.2}
{"kind": "condition", "key": "wound", "op": ">=", "value": 0.5}
{"kind": "belief", "subject": "actor-1", "predicate": "trusts",
 "object": "actor-2"}
{"kind": "tag", "key": "winter"}
```

Поддерживаются `kind`: `need`/`desire`, `trait`, `division`, `force`,
`energy`, `condition`/`sickness`/`wound`, `belief`, `tag`, `category`,
`side`, `faction`, `role`, `alive`, `time`, а также произвольный ключ
контекста. Операции: `>=`, `<=`, `>`, `<`, `==`, `!=`, `in`,
`not in`. Флаг `negate: true` инвертирует результат.

Для `belief`, `tag` и `alive` без явных `op`/`value` условие означает
«присутствует/жив» и проверяется как `== true`.

### 4.4. Видимость

```json
{
  "scope": "global",
  "divisions": ["social:noble"],
  "sides": ["player"],
  "factions": ["crown"],
  "roles": ["leader"],
  "min_force": 0.2,
  "max_force": 1.0,
  "min_energy": 0.1,
  "max_energy": 1.0
}
```

`scope` бывает `global`, `character`, `faction`, `hidden`. Для
`character` нужен `id` зрителя; `hidden` не виден никому. Деления
проверяются либо по тегу `dimension:value` в `tags`, либо по словарю
`divisions`. Сила и энергия зрителя — нормированные значения `0..1`.

### 4.5. Рантайм

```python
from systems.events import EventCatalog, EventEngine

catalog = EventCatalog.load()
engine = EventEngine(catalog=catalog, seed=7)
instance = engine.trigger(context={
    "needs": {"hunger": 0.8},
    "divisions": {"social": "worker"},
    "force": 0.5,
    "energy": 0.4,
})
for event in engine.advance(1.0, context=viewer_context):
    print(event.title, event.text, event.progress)
```

`EventEngine.visible(viewer)` возвращает только зрелые и видимые
экземпляры. `advance()` двигает `speed`/`duration`, удаляет истёкшие
события и возвращает новые видимые. `snapshot()` сохраняет время,
активные события, историю и перезарядки.

`EventEngine.effects()` остаётся в `systems/events.py` для обратной
совместимости старых тестов, но **не является частью игрового контракта**:
кампания его не вызывает, а событие не должно описывать запись в
состояние. Миграция — удалить `effects` из контента и из загрузчика.

### 4.6. События в кампании

`campaign.automata.AutomataCampaign` создаёт `EventEngine` и периодически
вызывает `trigger()` с контекстом лидера: `needs`, `traits`, `divisions`,
`tags`, `conditions`, `beliefs`, `force`, `energy`, `alive`, `time`.
Записи попадают в `story_events` и в снимок кампании; **состояние не
меняется** — поле `effects` в записи всегда пустое. Интервал спавна —
`max(4.0, organization_interval_seconds × 0.5)` в масштабированных
секундах.

## 5. Черты и коэффициенты: `configs/characters/traits.json`

Черты не добавляют новых формул, а сдвигают коэффициенты уже
существующих алгоритмов. Блок `coefficients` использует ту же линейную
формулу `base + scale × (value - center)`:

```json
{
  "traits": {
    "endurance": {
      "coefficients": {
        "need_growth": {"base": 1.0, "scale": -0.25, "center": 0.5},
        "need:fatigue": {"base": 1.0, "scale": -0.2, "center": 0.5},
        "force_drain": {"base": 1.0, "scale": -0.3, "center": 0.5},
        "energy_drain": {"base": 1.0, "scale": -0.35, "center": 0.5}
      }
    }
  }
}
```

Поддерживаемые ключи: `need:<желание>`, `need_growth`, `force_drain`,
`energy_drain`, `belief_weight`, `intention_weight`. Неизвестный ключ
игнорируется и возвращает нейтральный множитель `1.0`. Одинаковый
коэффициент у нескольких черт перемножается.

```python
from character_traits import load_traits

model = load_traits()
factors = model.coefficient_factors({"endurance": 0.9})
assert factors["energy_drain"] < 1.0
```

## 6. Проверка после правки

```bash
venv/bin/python -m pytest -q tests/test_bdi.py \
  tests/test_divisions.py tests/test_events_runtime.py
venv/bin/python -m pytest -q
venv/bin/python -m campaign --list-templates
```

Быстрые проверки в Python:

```python
import bdi
from campaign.divisions import load_divisions
from systems.events import EventCatalog

config = bdi.load_bdi()
assert len(config.needs) == 16
assert config.death["metric"] == "force"

catalog = load_divisions()
assert len(catalog.dimensions) == 15
assert catalog.preset("germanic")

events = EventCatalog.load()
assert events.eligible({"needs": {"knowledge": 0.9}})
```

## 7. Что осталось кодом

* формулы роста, затухания, `spillover`, давления и восстановления;
* проверка контракта 16 желаний, 15 делений, тройки/пары;
* фильтрация условий, нормирование вероятностей, тайминг событий;
* сериализация состояния и совместимость старых полей
  `health`/`sickness`/`wound`.

Всё остальное — тексты, числа, пороги, предикаты, сути, деления,
пресеты, события и коэффициенты — остаётся в JSON.
