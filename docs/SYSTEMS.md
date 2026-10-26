# SYSTEMS.md — среда, драматург и события

> **Статус.** Чистый Python-слой без pygame. Он не меняет канон
> `simulation.py` / `warfare.py`, не подключается к UI автоматически и не
> затрагивает редактор `automata/`. Всё поведение задаётся JSON-конфигами из
> [`configs/systems/`](../configs/systems); имена персонажей — из
> [`configs/naming/people.json`](../configs/naming/people.json).

Пакет [`systems/`](../systems) добавляет два самостоятельных системных
автомата и общий каталог событий:

| Слой | Автомат | Назначение |
|---|---|---|
| `systems/environment.py` | 13 природных особенностей | поле боя как набор автоматов, с которыми можно взаимодействовать через `Target`/`ActionSpec`/`OutcomeSpec` |
| `systems/playwright.py` | «Драматург» | эпизодически и стохастически подталкивает акторов к поступкам с драматическими последствиями |
| `systems/events.py` | каталог событий | 88 событий и 176 текстовых шаблонов; автоматически подставляет имена персонажей и организаций |
| `naming/people.py` | генератор имён | 21 реальная культура и 19 фэнтезийных тем |

Общий примитив — `systems.core.SystemAutomaton`: обычный
`automata.model.Automaton` плюс текущее состояние и история переходов. Среда и
драматург используют один и тот же протокол `fire(event)`, `set_state(id)` и
`snapshot()`, поэтому их поведение остаётся структурным, а не набором
специальных случаев.

## 1. Среда как автомат

`EnvironmentCatalog` загружает `environment.json`. В поставке 13 особенностей:
`river`, `ravine`, `swamp`, `forest`, `mountain_pass`, `storm`, `wildfire`,
`ruins`, `fog`, `cave`, `snowfield`, `crossroads`, `spring`. У них 40 состояний
и 46 действий.

Каждая особенность содержит:

* `states` — состояния автомата (первое состояние конфига является начальным);
* `transitions` — переходы с `source`, `target`, `event` и весом;
* `actions` — взаимодействия, доступные актору;
* `drift_chance` — вероятность дрейфа за такт (по умолчанию берётся из
  каталога).

Состояние может менять доступность действий и вероятности исходов:

```json
{
  "id": "flood",
  "name": "Паводок",
  "description": "Река вышла из берегов; брод скрыт под мутной водой.",
  "difficulty": 0.9,
  "passable": false,
  "tags": ["hazard", "barrier"],
  "outcome_bias": {"crossed": 0.2, "swept": 2.0, "lost": 1.5},
  "blocked_actions": ["ford"],
  "uncertainty": 0.15
}
```

Действие описывается как обычный `ActionSpec`; исходы могут нести
произвольные числовые/строковые `effects` и необязательный `next_state`:

```json
{
  "id": "build_bridge",
  "label": "Навести переправу",
  "description": "Связать брёвна и верёвки, чтобы переправа стала надёжной.",
  "outcomes": [
    {
      "id": "built",
      "label": "Переправа готова",
      "probability": 2.5,
      "tone": "positive",
      "effects": {"progress": 1.0, "time": 1.0, "noise": 0.3},
      "next_state": "bridged"
    },
    {
      "id": "washed_away",
      "label": "Переправу смыло",
      "probability": 1.0,
      "tone": "negative",
      "effects": {"time": 1.0, "lost": 0.2},
      "next_state": "flood"
    }
  ]
}
```

`effects` намеренно не мутируют неизвестного актора: среда возвращает их
вызывающему коду. Так системный слой остаётся совместимым с любым runtime —
`warfare.Character`, организацией или будущим актором.

### API

```python
from systems.environment import EnvironmentCatalog, EnvironmentRuntime

catalog = EnvironmentCatalog.load()
runtime = EnvironmentRuntime(catalog, seed=7)

feature = runtime.feature("river")
print(feature.machine.current)       # calm
print(feature.state().name)          # Спокойное течение

target = feature.as_target()         # interaction.Target
result = runtime.interact("actor-1", "river", "ford", seed=7)
if result is not None:
    print(result.text)
    print(result.effects)            # {"progress": 1.0, "fatigue": 0.15, ...}
    print(result.state_before, result.state_after)

shifts = runtime.tick()              # дрейф всех особенностей
```

`EnvironmentRuntime` детерминирован по seed. Явный `seed=` у `interact()`
фиксирует `InteractionModel`, а `tick(seed=...)` — локальный RNG дрейфа.
Действия, заблокированные состоянием, возвращают `None` ещё до разрешения
исхода. Если исход содержит `next_state`, состояние особенности меняется
автоматически.

## 2. Драматург

`Playwright` — системный автомат с состояниями `dormant → watching →
tempting → pushing → withdrawing → dormant`. Он не отдаёт приказы: он
периодически оценивает доступных кандидатов и предлагает актору соблазн.

### Оценка

Для кандидата считаются четыре компонента в диапазоне `[0, 1]`:

| Компонент | Смысл |
|---|---|
| `uncertainty` | насколько исход непредсказуем |
| `coherence` | насколько поступок вытекает из характера и контекста |
| `novelty` | насколько поступок отличается от недавних толчков |
| `stakes` | насколько высока цена ошибки; учитывает ставки вовлечённых акторов |

Итоговая оценка — взвешенная сумма с нормализованными весами:

```text
total = Σ weight[k] * component[k]
```

В `configs/systems/playwright.json` веса по умолчанию:
`uncertainty=0.28`, `coherence=0.24`, `novelty=0.26`, `stakes=0.22`.
Новизна дополнительно снижается после похожих и особенно повторных толчков:

```text
novelty = base_novelty
          * (1 - novelty_decay * similarity)
          * (1 - repetition_penalty * exact_repeat)
```

Выбор не жёсткий: кандидаты сортируются по `total`, отбрасываются ниже
`min_score`, затем выбираются через softmax с температурой. Небольшой
`exploration` позволяет иногда выбрать не самого сильного кандидата — это
соблазн, а не диктат.

### Эпизоды

`episode_chance` задаёт вероятность того, что такт вообще станет эпизодом.
После толчка включается `cooldown`, поэтому драматург не срабатывает каждый
такт. В поставке: `episode_chance=0.38`, `cooldown=2`, `temperature=0.32`,
`novelty_decay=0.55`, `repetition_penalty=0.60`, `min_score=0.18`,
`exploration=0.05`.

18 шаблонов задают действия вроде тайной сделки, предательства, вызова
лидеру, жертвы, начала войны, мира, раскрытия правды, мести, заявки на трон и
договора с врагом. Шаблон содержит `event_id`, поэтому толчок сразу получает
текст из каталога событий.

### API

```python
from systems.events import EventCatalog, EventTextGenerator
from systems.playwright import DramaActor, Playwright, PlaywrightConfig

config = PlaywrightConfig.load()
events = EventTextGenerator(EventCatalog.load(), seed=7)
playwright = Playwright(config, seed=7, event_generator=events)

actors = [
    DramaActor("a", "Анна", "Орден", tags=("war", "ambition"), stakes=0.8),
    DramaActor("b", "Борис", "Гильдия", tags=("trade", "secret"), stakes=0.6),
    DramaActor("c", "Вера", "Совет", tags=("power", "duty"), stakes=0.4),
]
candidates = playwright.spawn_candidates(actors)

for turn in range(20):
    push = playwright.tick(turn, actors, candidates)
    if push is not None:
        print(push.turn, push.candidate.action, push.score.total)
        print(push.text)
```

`spawn_candidates()` строит кандидатов из пар акторов и шаблонов, ограничивая
их число `max_candidates`. `score()` возвращает `DramaScore` с разложением по
компонентам, `choose()` — стохастический выбор, `snapshot()` — состояние
автомата, конфиг и историю. `DramaActor.from_character(character)` — адаптер
для `warfare.Character` без импорта `warfare`.

## 3. Каталог событий

`EventCatalog` загружает `events.json`: 12 категорий, 88 событий и 176
шаблонов. Каждое событие содержит два варианта текста; все шаблоны используют
хотя бы один слот имени персонажа или организации.

| Категория | Что покрывает |
|---|---|
| `life` | рождение, взросление, брак, воспитание, болезнь, смерть, похороны, возвращение |
| `choices` | призвание, обучение, дружба, предательство, тайна, жертва, соблазн, изгнание |
| `society` | мирный договор, восстание, закон, суд, праздник, переселение, голод, мор |
| `war` | объявление войны, осада, набег, перемирие, дезертирство, подвиг, плен, после битвы |
| `economy` | торговый путь, урожай, нехватка, долг, наследство, обвал, караван, рудник |
| `disaster` | наводнение, пожар, землетрясение, эпидемия, оползень, кораблекрушение, степной пожар |
| `crime` | кража, убийство, мошенничество, наказание, изгнание, заговор, коррупция, контрабанда |
| `discovery` | реликвия, новая земля, древний текст, изобретение, лекарство, скрытая правда |
| `mystery` | пророчество, видение, исчезновение, проклятие, портал, культ, откровение |
| `romance` | первая и запретная любовь, ухаживание, ревность, побег, разрыв, старая любовь |
| `culture` | песня, театр, архив, ересь, покровительство, легенда |
| `politics` | союз, выборы, реформа, ультиматум, коронация, наследование, дипломатия |

Слоты: `{actor}`, `{target}`, `{child}`, `{rival}`, `{organization}`,
`{rival_organization}`, `{place}`, `{object}`, `{cause}`, `{consequence}`,
`{amount}`. Если контекст не задан, `EventTextGenerator` создаёт его сам:
берёт имена из `naming.people`, названия организаций из `naming.NameGenerator`,
а места/предметы/причины — из встроенных пулов. Недостающие слоты закрываются
безопасными fallback-значениями.

```python
from systems.events import EventCatalog, EventTextGenerator

catalog = EventCatalog.load()
events = EventTextGenerator(catalog, seed=7)

event = events.render(
    "marriage",
    context={
        "actor": "Анна",
        "target": "Борис",
        "organization": "Орден",
    },
    seed=11,
)
print(event.title, event.category)
print(event.text)

random_event = events.generate(category="war", seed=3)
many = events.generate_many(count=5, tags=["secret"], seed=3)
```

Выбор события учитывает `weight`, `stakes` и вес категории. Один и тот же
`seed` даёт одинаковый текст; явный `context` заменяет только переданные слоты,
остальные имена генерируются детерминированно.

## 4. Имена персонажей

`naming.people.PersonNameGenerator` — отдельный слой, не меняющий семь классов
автоматов и восемь типов взаимодействий из `naming`. Конфиг содержит 21
реальную культуру (`anglo`, `arabic`, `celtic`, `chinese`, `french`,
`germanic`, `greek`, `hebrew`, `iberian`, `indian`, `italian`, `japanese`,
`korean`, `mesoamerican`, `nordic`, `persian`, `polynesian`, `russian`,
`swahili`, `turkic`, `yoruba`) и 19 фэнтезийных тем (`high_elf`, `dark_elf`,
`wood_elf`, `dwarf`, `orc`, `halfling`, `fae`, `dragonkin`, `tiefling`,
`undead`, `celestial`, `shadow`, `frost_kin`, `sea_folk`, `sand_nomad`,
`rune`, `steampunk`, `cyberpunk`, `cosmic`).

```python
from naming import PersonNameGenerator

generator = PersonNameGenerator(seed=7)

real = generator.real(culture="russian", gender="f", seed=11)
fantasy = generator.fantasy(theme="cyberpunk", seed=11)
mixed = generator.generate_many(count=12, seed=11)

print(real.full, real.culture, real.gender)
print(fantasy.full, fantasy.theme)
```

Реальные имена учитывают культуру, пол и порядок «фамилия — имя» там, где это
принято. Фэнтезийные темы используют собственные пулы имён, фамилий/прозвищ и
шаблоны. `generate_many()` детерминирован по seed и старается не повторять
полные имена. Слой чистый: без pygame и без морфологии русского языка —
имена возвращаются в именительном падеже готовой строкой.

## 5. CLI

```bash
# среда
python3 -m systems --list
python3 -m systems --environment river
python3 -m systems --environment river --interact ford --seed 7
python3 -m systems --environment river --tick 5 --seed 7
python3 -m systems --environment --feature river --json

# события
python3 -m systems --event birth_child --seed 7
python3 -m systems --event --category war --count 3 --seed 7
python3 -m systems --event --tags secret risk --count 3 --seed 7

# драматург
python3 -m systems --playwright --turns 20 --seed 7
python3 -m systems --playwright --turns 12 --seed 7 --json

# имена персонажей
python3 -m naming --person --count 5 --seed 7
python3 -m naming --person --culture russian --gender f --count 3 --seed 7
python3 -m naming --person --fantasy high_elf --count 3 --seed 7
python3 -m naming --list-people
```

`--list` показывает особенности среды, категории событий и шаблоны
драматурга. `--json` печатает структурированный результат. Демо драматурга
создаёт четырёх акторов из генератора имён и проигрывает заданное число
тактов, поэтому один и тот же `--seed` даёт одинаковую последовательность
эпизодов.

## 6. Границы

* Среда не заменяет `simulation.Environment` и не является физической моделью
  местности. Это контентный слой взаимодействий: эффекты возвращаются, но не
  применяются к незнакомому актору.
* Драматург не гарантирует «хорошую историю». Он формализует соблазн через
  четыре компонента и стохастический выбор; итоговая драматургия зависит от
  качества шаблонов и контекста.
* Тексты событий — русскоязычные заготовки. Они не переводятся и не
  проверяются синтаксически; грамматические ограничения снижаются выбором
  нейтральных формулировок.
* Все слои детерминированы по seed, но порядок вызовов `tick()`/`interact()`
  входит в состояние. Для воспроизводимого сценария seed нужно передавать
  явно.
* Слой не импортирует pygame, `simulation` и `warfare`; проверки —
  `tests/test_systems.py`, `tests/test_people.py`.
