# NAMING.md — естественные названия автоматов и взаимодействий

> **Статус.** Чистый Python-слой без pygame. Он читает декларативные конфиги
> из [`configs/naming/`](../configs/naming), строит русские названия по
> морфологическим правилам и не меняет схему редактора `automata/`. Пакет
> [`naming/`](../naming) можно использовать отдельно от UI и от runtime
> организаций.

## 1. Зачем отдельный слой

Названия автоматов не должны быть ни жёстко зашитыми строками, ни простой
конкатенацией `<ярлык> — <потребность>`. При этом редактор автоматов остаётся
структурным: он не обязан знать про потребности, темы и падежи.

Поэтому введены три независимых уровня:

1. **структура** — состояния, переходы, начальные/финальные узлы (`automata/`);
2. **функциональный профиль** — класс автомата, потребность, уровень и
   тематические пулы слов (`configs/naming/classes/`);
3. **язык** — морфология, согласование, распределение длины и seed
   (`naming/`).

`organizations.generator` использует слой названий по умолчанию, а
`build_automaton(analysis, name=...)` остаётся явным переопределением.

## 2. Структура конфигов

```text
configs/naming/
├── lexicon.json              # словарь: существительные, прилагательные, фразы
├── classes/
│   ├── order.json            # безопасность, принуждение, закон
│   ├── meaning.json          # смысл, ритуал, авторитет
│   ├── provision.json        # снабжение, производство, логистика
│   ├── status.json           # ранги, престиж, доступ
│   ├── knowledge.json        # знание, обучение, мастерство
│   ├── care.json             # забота, лечение, община
│   └── exchange.json         # обмен, рынок, договор
└── interactions/
    ├── coercion.json         # принуждение
    ├── exchange.json         # обмен
    ├── instruction.json      # наставление
    ├── care.json             # забота
    ├── ritual.json           # ритуал
    ├── recruitment.json      # вербовка
    ├── reconnaissance.json   # разведка
    └── negotiation.json      # переговоры
```

`configs/classes/*.json` — старые игровые классы; они **не** переиспользуются
как таксономия названий. Новая таксономия живёт только в `configs/naming/`.

## 3. Классы: функция + потребность + уровень

Класс автомата — это не жёсткий архетип, а **функциональный режим**:

| Класс | Что производит | Примеры тем |
|---|---|---|
| `order` | безопасность, принуждение, закон | military, police, civil, elite, sanitary |
| `meaning` | смысл, ритуал, авторитет | temple, mystery, charity, order |
| `provision` | продовольствие, снабжение, ремонт | harvest, logistics, production, trade |
| `status` | ранги, престиж, доступ | gang, noble, elite, court |
| `knowledge` | знание, обучение, мастерство | academy, archive, craft, school |
| `care` | заботу, лечение, приют, общину | heal, community, family, shelter |
| `exchange` | обмен, рынок, договор | market, guild, bank, logistics |

Профиль класса задаёт:

```json
{
  "class": "order",
  "default_theme": "civil",
  "need_themes": {"fear": "military", "health": "sanitary"},
  "base": {"heads": [], "adjectives": [], "dependents": [],
           "dependent_adjectives": [], "extensions": []},
  "themes": {"military": {"heads": [], "...": []}},
  "levels": {"1": {"heads": [], "adjectives": []}},
  "ontology": {"inputs": [], "outputs": [], "states": [],
               "handlers": [], "surrounding": []}
}
```

Ядро названия — **тема + уровень**. Тема выбирается по
`need_themes[need]` (или `default_theme`), уровень ограничивается диапазоном
`1..3+`. Голова берётся из тематического пула, чтобы потребность не
размывалась широкой базой; уровень добавляет прилагательные, зависимые
группы и фразы. Поэтому страх у `order` даёт военную/полицейскую лексику, а
голод у `provision` — урожай, склад и обоз. `base` остаётся разделяемым
слоем для расширений и редких fallback-слов.

### 3.1 Онтология класса

Онтология описывает не только имя, но и внутреннее устройство автомата:

* `inputs` — что автомат принимает (сырьё, сигнал, просьбу, вопрос);
* `outputs` — что отдаёт (благо, услугу, донесение, приказ);
* `states` — типовые фазы (закупка, тревога, обучение, выздоровление);
* `handlers` — обработчики: `nested_automaton` (вложенный автомат) или
  `scheme` (неавтоматная схема: регламент, маршрут, рецепт, триаж);
* `surrounding` — окружающие автоматы и среда, влияющие на поведение.

Каждый элемент содержит `label`, `kind` и `keywords`. Это декларативная
онтология для будущего контента, а не расширение схемы редактора.

## 4. Грамматика названия

Базовая формула:

```text
[прилагательные] существительное-голова [родительные группы] [готовая фраза]
```

Примеры:

```text
Карательный военный секретариат
Бригада столичного периметра
Госпиталь старческого здоровья
Союз услуги и сделки
Библиотека памяти в поисках истины
```

Ограничения:

* не больше **двух** прилагательных перед головой;
* не больше **двух** родительных групп, соединяемых `и`;
* одна готовая фраза-расширение;
* жёсткий потолок — **10 слов**;
* запрещены тавтологии с общим корнем (`резервный резерв`, `складской склад`);
* прилагательные согласуются с головой по роду, числу и одушевлённости;
* падежные формы строятся для всех шести падежей.

### 4.1 Распределение длины

Длина выбирается из усечённого дискретного логистического распределения
(`naming/distribution.py`):

* `MIN_WORDS = 1`, `MAX_WORDS = 10`;
* мода — **2 слова**;
* `P(≥ 6 слов) ≈ 0.0062`, то есть длинные названия редки, но возможны;
* всё, что вышло бы за 10 слов, перераспределяется внутри допустимого
  диапазона.

Распределение не «подгоняет» грамматику: генератор сначала выбирает точное
число слов, затем подбирает рецепт с таким же числом слотов. Если для редкой
длины не хватает слотов, берётся ближайший допустимый рецепт.

### 4.2 Морфология

`naming/morphology.py` поддерживает:

* существительные мужского, женского, среднего рода и pluralia tantum;
* одушевлённость (винительный падеж совпадает с родительным);
* прилагательные с твёрдой, мягкой, ударной, велярной и шипящей основой;
* явные исключения через `forms`;
* готовые фразы с собственными падежными формами.

Лексикон хранит только опорные формы. Например:

```json
"blagoy": {"kind": "adj", "nom": "благой"},
"gruppa": {"kind": "noun", "nom": "группа", "gen": "группы",
           "gender": "f"},
"po_pravu_silnogo": {"kind": "phrase", "nom": "по праву сильного",
                     "forms": {"gen": "по праву сильного"}}
```

## 5. Типы взаимодействий: пятёрка

Тип взаимодействия — семантический шаблон, а не пара классов. Его конфиг
содержит **пятёрку**:

1. `recipient_input` — что получатель воспринимает;
2. `sender_output` — что отправитель передаёт;
3. `handlers` — обработчики **обеих** сторон;
4. `states` — состояния **обеих** сторон;
5. `surrounding_influence` — влияние окружающих автоматов и среды.

Схема:

```json
{
  "type": "coercion",
  "label": "Принуждение",
  "quintuple": {
    "recipient_input": {"label": "сигнал требования", "kind": "signal",
                        "keywords": ["приказ", "угроза", "..."]},
    "sender_output": {"label": "принуждающее воздействие", "kind": "action",
                      "keywords": ["давление", "арест", "..."]},
    "handlers": {
      "sender": [
        {"label": "отряд принуждения", "kind": "nested_automaton",
         "keywords": ["приказ", "сила", "..."]},
        {"label": "схема санкций", "kind": "scheme",
         "keywords": ["норма", "мера", "..."]}
      ],
      "recipient": [
        {"label": "узел сопротивления", "kind": "nested_automaton",
         "keywords": ["баррикада", "воля", "..."]},
        {"label": "схема подчинения", "kind": "scheme",
         "keywords": ["приказ", "покорность", "..."]}
      ]
    },
    "states": {
      "sender": [{"label": "готовность", "kind": "state",
                  "keywords": ["сила", "решение", "..."]}],
      "recipient": [{"label": "сопротивление", "kind": "state",
                     "keywords": ["воля", "страх", "..."]}]
    },
    "surrounding_influence": {
      "label": "влияние окружающих автоматов",
      "sources": [
        {"label": "власть", "kind": "actor",
         "keywords": ["закон", "приказ", "..."]}
      ]
    }
  },
  "naming": {
    "heads": ["prinuzhdenie", "davlenie", "ultimatum"],
    "adjectives": ["zhestkiy", "preventivnyy"],
    "dependents": ["soprotivlenie", "pokornost"],
    "dependent_adjectives": ["zhestkiy", "surovy"],
    "extensions": ["po_pravu_silnogo"]
  }
}
```

Восемь готовых типов: `coercion`, `exchange`, `instruction`, `care`,
`ritual`, `recruitment`, `reconnaissance`, `negotiation`. Пул `naming`
строит имя типа по той же грамматике, что и имя автомата.

## 6. API

```python
from naming import NameGenerator, NamingCatalog

catalog = NamingCatalog.load()
generator = NameGenerator(catalog, seed=7)

result = generator.automaton_name("order", need="fear", level=3, seed=7)
print(result.text)          # имя в именительном падеже
print(result.gen)           # родительный падеж
print(result.render("dat")) # любой падеж
print(result.words, result.theme, result.parts)

interaction = generator.interaction_name("coercion", seed=7)
print(interaction.text)
```

`NameResult` содержит `text`, `forms`, `parts`, `seed`, `mode`, `need`,
`level`, `theme`. `parts` сохраняет выбранные `head`, прилагательные,
зависимые группы и фразу — это удобно для отладки и тестов.

Функции быстрого доступа:

```python
from naming import automaton_name, interaction_name

automaton_name("care", need="health", level=2, seed=3)
interaction_name("ritual", seed=3)
```

### 6.1 Детерминизм

Одинаковые `(mode, need, level, theme, seed)` дают одинаковое название.
`generate_many(..., count=N, seed=S)` использует один поток RNG, поэтому
выдаёт воспроизводимую последовательность без повторов.

`organizations.generator` по умолчанию вычисляет seed из самого разбора
(`analysis.to_dict()` без `assessments`, SHA-256). Это значит:

* один и тот же разбор всегда даёт одно и то же имя;
* разные организации с разными потребностями/масштабом получают разные имена;
* явный `seed=` переопределяет вычисленный seed, а `name=` — всё имя.

## 7. CLI

```bash
python3 -m naming --list
python3 -m naming --mode order --need fear --level 3 --count 5 --seed 7
python3 -m naming --interaction coercion --count 5 --seed 7
python3 -m naming --mode order --ontology
python3 -m naming --mode care --need health --level 2 --json
```

`--list` показывает классы и типы взаимодействий. `--ontology` печатает
онтологию класса в JSON. `--json` печатает массив `NameResult.as_dict()`.

## 8. Интеграция с организациями

`organizations.generator.build_automaton(analysis, name=None, seed=None)`:

* `name` задан — используется как есть;
* иначе имя строится по `analysis.top_mode`, `analysis.priority_need` и
  `analysis.level`;
* если конфиг названий недоступен или класс не найден, включается старый
  заголовок `<Ярлык> — <потребность>` как безопасный fallback.

CLI:

```bash
python3 -m organizations
python3 -m organizations --name-seed 7
python3 -m organizations --write --name-seed 7
```

`--name-seed` фиксирует имена для воспроизводимого вывода или тестов.

## 9. Как расширять

1. Добавьте слово в `configs/naming/lexicon.json` с опорными формами.
2. Добавьте ID в тему или уровень нужного класса (`base` — для общих
   расширений и fallback-слов).
3. Для нового класса создайте `configs/naming/classes/<id>.json` с
   `base`, `themes`, `levels` и полной `ontology`.
4. Для нового типа взаимодействия создайте
   `configs/naming/interactions/<id>.json` с полной пятёркой и `naming`.
5. Запустите `python3 -m naming --list` и `pytest -q tests/test_naming.py`.

Каталог валидирует ссылки на лексикон, типы слов, обязательные уровни,
полноту онтологии и пятёрки. Ошибка конфигурации — `NamingError` с указанием
ключа и слова.

## 10. Границы

* Это генератор **имён**, а не симуляция смысла. Он не проверяет, насколько
  выбранное прилагательное уместно для конкретной головы; тематические пулы
  снижают, но не устраняют странные сочетания.
* Лексикон ограничен и вручную выверен. Экзотические слова и нерегулярные
  формы нужно добавлять через `forms`.
* Названия не переводятся автоматически: это русскоязычный слой.
* Слой не импортирует pygame и не меняет `configs/classes/*.json`.

## 11. Тесты

```bash
pytest -q tests/test_naming.py
pytest -q tests/test_organizations.py
pytest -q
```

`tests/test_naming.py` проверяет распределение длины, полноту классов и
пятёрок, морфологию, детерминизм, падежные формы, CLI и отсутствие импорта
pygame. `tests/test_organizations.py` проверяет, что генератор организаций
использует естественные имена по умолчанию, поддерживает `name=`/`seed=` и
сохраняет валидность автоматов.
