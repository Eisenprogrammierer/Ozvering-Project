# `naming`

Справочник собран из docstrings и примечаний к переменным. Номера строк относятся к версии до очистки кода.

## `naming/__init__.py`

### Модуль

Строка 1.

Конфигурируемые естественные названия автоматов и имена персонажей.

Пакет не импортирует pygame и не меняет редактор ``automata``. Он читает
лексикон, профили и ``people.json`` из ``configs/naming`` и предоставляет:

* ``NameGenerator.automaton_name(mode, need, level)``;
* ``NameGenerator.interaction_name(type_id)``;
* ``PersonNameGenerator.real/fantasy/generate_many``;
* доступ к онтологии класса и пятёрке типа взаимодействия через
  ``NamingCatalog``.

### function `automaton_name`

Строка 52.

```python
def automaton_name(mode, need=None, level=1, theme=None, seed=0)
```

Короткий функциональный вход для одного названия.

### function `interaction_name`

Строка 58.

```python
def interaction_name(type_id, seed=0)
```

Короткий функциональный вход для названия взаимодействия.

### function `person_name`

Строка 63.

```python
def person_name(culture=None, theme=None, gender=None, seed=0)
```

Короткий функциональный вход для имени персонажа.

## `naming/__main__.py`

### Модуль

Строка 1.

CLI: предпросмотр названий и онтологий.

    python3 -m naming --list
    python3 -m naming --mode order --need fear --level 3 --count 5 --seed 7
    python3 -m naming --interaction coercion --count 5 --seed 7
    python3 -m naming --mode order --ontology

## `naming/catalog.py`

### Модуль

Строка 1.

Загрузка и проверка конфигов имён.

Конфиги лежат в ``configs/naming``:
``lexicon.json`` — морфология слов; ``classes/*.json`` — классы автоматов;
``interactions/*.json`` — семантические типы взаимодействий.

### class `NamingError`

Строка 28.

Ошибка конфигурации имён.

### function `_descriptor`

Строка 70.

```python
def _descriptor(value, label, allowed_kinds=None)
```

Проверить один элемент онтологии или пятёрки.

### class `Pool`

Строка 88.

Набор ссылок на словарь для одного класса/темы/уровня.

### class `NamingCatalog`

Строка 326.

Лексикон + классы автоматов + типы взаимодействий.

## `naming/distribution.py`

### Модуль

Строка 1.

Вероятностное распределение длины названия.

Длина измеряется в словах. Используется усечённое дискретное логистическое
распределение с модой 2: однословные и двусловные названия наиболее вероятны,
длинные — быстро затухают. Жёсткий потолок — 10 слов; всё, что выпало бы за
него, перераспределяется внутри допустимого диапазона.

### function `word_count_weights`

Строка 33.

```python
def word_count_weights(min_words=MIN_WORDS, max_words=MAX_WORDS, location=LOCATION, scale=SCALE)
```

Нормализованные вероятности для каждого числа слов.

    Возвращает словарь ``{1: p1, ..., 10: p10}``. Сумма равна 1.

### function `sample_word_count`

Строка 51.

```python
def sample_word_count(rng, weights: Optional[Dict[int, float]]=None)
```

Выбрать длину названия; ``rng`` — экземпляр ``random.Random``.

## `naming/generator.py`

### Модуль

Строка 1.

Генератор естественных русских названий автоматов и взаимодействий.

Название собирается из ограниченной грамматики:

    [прилагательные] существительное [родительные группы] [фраза]

Количество слов задаётся усечённым логистическим распределением (мода 2,
потолок 10). Падежи и согласование выводятся морфологией, а не подстановкой
готовых строк.

### class `Recipe`

Строка 26.

Сколько слотов каждого вида использовать.

### class `NameResult`

Строка 42.

Готовое название и его падежные формы.

### function `_root_key`

Строка 100.

```python
def _root_key(word)
```

Грубый корень для запрета тавтологий вроде «резервный резерв».

### function `_with_primary`

Строка 106.

```python
def _with_primary(pool)
```

Для классов заменить широкие пулы на ядро «тема + уровень».

### function `_plans`

Строка 131.

```python
def _plans(pool, target: int)
```

Все рецепты, дающие ровно ``target`` слов.

### class `NameGenerator`

Строка 164.

Детерминированный по seed генератор названий.

### method `NameGenerator.automaton_name`

Строка 177.

```python
def automaton_name(self, mode, need=None, level=1, theme=None, seed=None)
```

Название автомата класса ``mode``.

### method `NameGenerator.interaction_name`

Строка 189.

```python
def interaction_name(self, type_id, seed=None)
```

Название семантического типа взаимодействия.

### method `NameGenerator.generate_many`

Строка 196.

```python
def generate_many(self, mode, need=None, level=1, theme=None, count=10, seed=None)
```

Несколько разных названий для одного класса.

## `naming/morphology.py`

### Модуль

Строка 1.

Морфология русских слов для генератора названий.

Словари содержат только опорные формы (именительный и родительный падеж для
существительных, именительный для прилагательных). Остальные формы выводятся
по регулярным правилам. Это не академический морфологический анализатор:
слой рассчитан на ограниченный, вручную выверенный лексикон названий и хранит
исключения в поле ``forms``.

### class `MorphologyError`

Строка 34.

Некорректная словарная статья или форма слова.

### class `Noun`

Строка 76.

Существительное с опорными формами и необязательными исключениями.

### class `Adjective`

Строка 194.

Прилагательное; формы выводятся из именительного и характера основы.

### class `Phrase`

Строка 329.

Неизменяемая готовая фраза (например, «особого назначения»).

## `naming/people.py`

### Модуль

Строка 1.

Генератор имён персонажей: реальные культуры и фэнтезийные темы.

Конфиг лежит в ``configs/naming/people.json``. В отличие от генератора
названий автоматов, этот слой не пытается строить морфологию: имена — это
собственные имена, а не русские нарицательные конструкции. Шаблоны текста
используют имя в именительном падеже, поэтому генератору достаточно вернуть
готовую строку.

Слой чистый: он не импортирует pygame, ``simulation`` или ``warfare``.

### class `PeopleError`

Строка 30.

Ошибка конфига или запроса генератора имён.

### function `_pool`

Строка 52.

```python
def _pool(value, label)
```

Пул имён: либо список для обоих полов, либо объект ``m``/``f``.

### class `PersonCulture`

Строка 89.

Культура или фэнтезийная тема с пулами имён и шаблонами.

### class `PersonName`

Строка 169.

Готовое имя персонажа и его происхождение.

### class `PersonCatalog`

Строка 208.

Загруженный набор реальных культур и фэнтезийных тем.

### function `_render_pattern`

Строка 315.

```python
def _render_pattern(pattern, values)
```

Подставить слоты, не падая на необязательных частях имени.

### class `PersonNameGenerator`

Строка 324.

Детерминированный по seed генератор имён персонажей.

### method `PersonNameGenerator.real`

Строка 335.

```python
def real(self, culture=None, gender=None, seed=None)
```

Имя из реальной культуры (по умолчанию — случайной).

### method `PersonNameGenerator.fantasy`

Строка 345.

```python
def fantasy(self, theme=None, gender=None, seed=None)
```

Имя из фэнтезийной темы (по умолчанию — случайной).

### method `PersonNameGenerator.generate`

Строка 355.

```python
def generate(self, culture=None, theme=None, gender=None, seed=None)
```

Имя в реальном или фэнтезийном стиле.

        ``culture`` и ``theme`` взаимоисключающи. Без них стиль выбирается
        случайно с небольшим перевесом в сторону реальных культур.

### method `PersonNameGenerator.generate_many`

Строка 379.

```python
def generate_many(self, count=10, culture=None, theme=None, gender=None, seed=None)
```

Несколько разных имён, детерминированно по seed.
