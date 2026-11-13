# `systems`

Справочник собран из docstrings и примечаний к переменным. Номера строк относятся к версии до очистки кода.

## `systems/__init__.py`

### Модуль

Строка 1.

Системные автоматы: среда, драматург и тексты событий.

Пакет не импортирует pygame и не меняет канон ``simulation.py`` /
``warfare.py``. Он даёт два самостоятельных автомата:

* ``EnvironmentCatalog`` / ``EnvironmentRuntime`` — природные особенности
  поля боя, с которыми можно взаимодействовать как с обычными целями;
* ``Playwright`` — эпизодический соблазнитель, который оценивает
  драматические действия по неопределённости, связности, новизне и ставкам.

Третий слой — ``EventCatalog`` / ``EventTextGenerator`` — наполняет шаблоны
событий именами персонажей и организаций.

## `systems/__main__.py`

### Модуль

Строка 1.

CLI системных автоматов.

    python3 -m systems --list
    python3 -m systems --environment river
    python3 -m systems --environment river --interact ford --seed 7
    python3 -m systems --event birth_child --seed 7
    python3 -m systems --event --category war --count 3 --seed 7
    python3 -m systems --playwright --turns 20 --seed 7

## `systems/core.py`

### Модуль

Строка 1.

Общие примитивы системных автоматов.

Системный автомат — это обычный ``automata.model.Automaton`` плюс текущее
состояние и история переходов. Слой не рисует граф и не знает pygame: он нужен
среде и драматургу, чтобы их поведение было выражено тем же языком состояний и
переходов, что и остальные автоматы проекта.

### class `SystemError`

Строка 17.

Ошибка конфигурации или работы системного автомата.

### class `SystemAutomaton`

Строка 60.

Обёртка над ``Automaton`` с текущим состоянием.

    ``fire(event)`` ищет исходящий переход из текущего состояния, у которого
    совпадает ``event`` (и, если задан, ``guard``). Это минимальный протокол,
    достаточный для среды и драматурга.

### method `SystemAutomaton.fire`

Строка 108.

```python
def fire(self, event, guard=None)
```

Совершить первый подходящий переход; вернуть его или ``None``.

### function `make_state_id`

Строка 155.

```python
def make_state_id(value, prefix='s')
```

Проверить/нормализовать id состояния из конфига.

## `systems/environment.py`

### Модуль

Строка 1.

Среда как системный автомат.

Среда — это не «фон» и не набор модификаторов, а коллекция автоматов-особенностей
(река, овраг, лес, буря, руины...). У каждой особенности есть собственные
состояния и переходы, а взаимодействие с ней описано теми же ``Target`` /
``ActionSpec`` / ``OutcomeSpec``, что и остальные взаимодействия проекта.

Ключевой контракт:

* ``EnvironmentFeature.machine`` — настоящий ``SystemAutomaton``;
* ``EnvironmentFeature.as_target()`` — объект для ``interaction.InteractionModel``;
* ``EnvironmentRuntime.interact(actor, feature, action)`` — actor-автомат
  взаимодействует с feature-автоматом, получает исход и эффекты, а состояние
  особенности может измениться.

Слой чистый: pygame, ``simulation`` и ``warfare`` не импортируются.

### class `EnvironmentError`

Строка 36.

Ошибка конфигурации среды.

### class `EnvironmentCatalog`

Строка 560.

Набор особенностей среды из ``configs/systems/environment.json``.

### class `EnvironmentRuntime`

Строка 621.

Живая среда: такты дрейфа и взаимодействия actor → feature.

## `systems/events.py`

### Модуль

Строка 1.

Шаблоны игровых событий и их наполнение именами.

Событие — это не только текст: у него есть категория, теги, серьёзность и
ставки. Драматург использует эти поля как один из входов, а генератор текста
подставляет имена персонажей и организаций, места и предметы.

Слой чистый и детерминированный: один и тот же seed даёт одну и ту же историю.
Если контекст не задан, имена генерируются через ``naming.people`` и
``naming.NameGenerator``.

### class `EventError`

Строка 24.

Ошибка конфигурации или генерации события.

### class `EventCatalog`

Строка 173.

Категории и шаблоны событий из ``configs/systems/events.json``.

### class `EventTextGenerator`

Строка 275.

Наполняет шаблоны событий именами и контекстом.

### method `EventTextGenerator.default_context`

Строка 312.

```python
def default_context(self, seed=None, rng=None)
```

Сгенерировать полный контекст: персонажи, организации, место, вещь.

### method `EventTextGenerator.generate`

Строка 377.

```python
def generate(self, event_id=None, category=None, tags=None, context=None, seed=None)
```

Отрисовать конкретное событие или выбрать подходящее по весам.

## `systems/playwright.py`

### Модуль

Строка 1.

Драматург — системный автомат, который искушает акторов.

Драматург не управляет персонажами напрямую. Он периодически (эпизодически)
оценивает доступные драматические действия и стохастически выбирает одно,
подталкивая актора к поступку. Оценка складывается из четырёх компонентов:

* **неопределённость** — насколько исход непредсказуем;
* **связность** — насколько поступок вытекает из характера и контекста;
* **новизна** — насколько поступок отличается от недавних толчков;
* **ставки** — насколько высока цена ошибки.

Чем выше итоговая оценка, тем охотнее драматург выбирает действие. Выбор идёт
через softmax-температуру, поэтому это именно соблазн, а не жёсткий диктат.

Слой чистый: он не импортирует pygame, ``simulation`` или ``warfare``.

### class `PlaywrightError`

Строка 41.

Ошибка конфигурации или работы драматурга.

### class `DramaActor`

Строка 87.

Актор, которого драматург может подтолкнуть к поступку.

### method `DramaActor.from_character`

Строка 126.

```python
def from_character(cls, character, organization='', stakes=None)
```

Адаптер для ``warfare.Character`` без импорта warfare.

### class `DramaticAction`

Строка 178.

Кандидат на драматический поступок.

### class `DramaticTemplate`

Строка 232.

Шаблон действия, из которого рождаются кандидаты.

### class `DramaScore`

Строка 300.

Разложенная по компонентам оценка соблазна.

### class `DramaPush`

Строка 327.

Свершившийся толчок драматурга.

### class `PlaywrightConfig`

Строка 359.

Веса, ритм эпизодов и шаблоны соблазна.

### class `Playwright`

Строка 463.

Системный автомат-драматург.

### method `Playwright.tick`

Строка 588.

```python
def tick(self, turn, actors=None, candidates=None, seed=None)
```

Сделать один такт. Возвращает ``DramaPush`` или ``None``.

### method `Playwright.spawn_candidates`

Строка 664.

```python
def spawn_candidates(self, actors, templates=None)
```

Построить кандидатов из шаблонов и списка акторов.
