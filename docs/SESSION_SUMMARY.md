# Саммари сессии: аудит Data-Driven ядра и контент-план по лору

> **Назначение.** Точка входа для следующих сессий. Фиксирует, что
> прочитано, что найдено, какие решения приняты и что делать дальше.
> Документ — не канон; канон в [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md).
>
> **Дата:** 2026-11-12 (обновлено после P5/P6).
> **Ветка/дерево:** `main`; P0–P6 закоммичены, дальше P7 (ИИ) и P8
> (отношения).

---

## 1. Задача

1. Разобрать лор из [`docs/лор.pdf`](лор.pdf) (22 стр.) и превратить его
   в подробный план наполнения игры.
2. Контент должен добавляться **только правкой JSON**; любое требование
   правки Python — архитектурная проблема, которую надо описать.
3. Перед правкой кода/конфигов — зафиксировать, **что именно не так с
   кодом**, и составить план исправления до полноценного Data-Driven ядра.
4. Не менять количество потребностей: ровно 16.
5. Золотое правило контента: «больше — лучше».
6. При переполнении контекста — писать саммари в документ (этот файл).

---

## 2. Что прочитано

### Документы

* `docs/ONBOARDING.md` — карта проекта, маршруты, инварианты.
* `docs/SOURCE_OF_TRUTH.md` — онтология, приоритеты, канон.
* `docs/CONTENT.md` — карта JSON-контента и загрузчиков.
* `docs/CONTENT_BDI_DIVISIONS_EVENTS.md` — триплеты/дуплеты, деления,
  события, производные активы.
* `docs/AUTOMATA_CAMPAIGN.md` — текущее поведение автоматов кампании.
* `docs/AUTOMATA.md` — формат автоматов редактора (только отображение).
* `docs/AGENTS.md`, `docs/WORLD_CORE_MODEL.md` (§7.0) — целевая модель
  4-2-1 и открытые пункты.

### Лор

Извлечён в `/tmp/opencode/lore.txt` (951 строка) командой:

```bash
pdftotext -layout docs/лор.pdf /tmp/opencode/lore.txt
```

Ключевое из лора:

* Мир: две империи из одной федерации, 200 лет войны; конфликт —
  **конфликт легитимности**, а не ценностей.
* Империя: порядок, миф о непобедимости, уязвима к публичному поражению.
* Республика: свобода, процедура, уязвима к потере лица и канала.
* Культ Земли: паразит на обиде, работает на обработчик, зависит от
  нарратива и лидера.
* Торговая планета: медиатор без репутации, канал, автономия.
* В Империи и Республике по три внутренних фракции: ортодоксы, модераты,
  ревизионисты.
* Списки органов: Империя ~35, Республика ~38, культ 9, планета 10.

### Код

* `bdi.py` — `Belief`, `Intention`, `BDIConfig`, `BDIState`,
  `choose_intention`, `tick`.
* `warfare.py` — `Character`, `deliberate`, `tick_needs`,
  `ESSENCE_FOR_KIND`, сеттеры beliefs/intentions.
* `campaign/preset.py` — `_make_character`, `_build_faction_automaton`,
  `_build_organ_automaton`, `_build_faction_record`.
* `campaign/automata.py` — `_character_from_record`, `_build_factions`,
  `_story_context`, `_apply_story_effects`, `_apply_branch`, `auto_action`,
  `_tick_faction_characters`, снимок/загрузка.
* `campaign/faction_state.py` — `character_metric`, `faction_metric`,
  `asset_keys`, `derived_asset`, драйверы.
* `campaign/fractal.py` — `OrganRuntime`, `tick_organs`.
* `systems/events.py` — условия, включая `belief`.
* `campaign/relations.py`, `campaign/planner.py` — не подключены к
  кампании.

---

## 3. Главные выводы

### 3.1. Data-Driven ядро готово примерно на две трети

**Работает из JSON:** 16 потребностей и их числа, черты, архетипы,
15 делений, личность героя, роли, сюжеты, шаблоны кампаний, органы
(пассивно), работы (частично), активы фракций (полностью, с формулами),
события (частично), сохранения beliefs/intentions.

**Не работает:**

1. **Убеждения не загружаются и не сеются.** `preset.py:430-496` не
   читает `beliefs`; `automata.py:141-182` тоже. Предикаты мертвы.
2. **Намерения не контентные.** `warfare.py:485-500` всегда ставит
   объектом потребность (`bdi.py:673-676`). Сути не связаны с работами.
3. **Эффекты работ закрыты.** `automata.py:1969-1987` умеет только
   активы и потребности. Убеждения, намерения, органы, флаги, отношения —
   невозможно.
4. **Автоматы — Python, не данные.** `preset.py:499-535` и `604+` —
   фиксированные пятифазные циклы; `configs/automata/` был пуст до P5; состояния не
   исполняются.
5. **Условия — только активы.** `automata.py:1166-1260`.
6. **ИИ игнорирует BDI.** `automata.py:2168-2198` — только
   `ai_priority` × защита цели.
7. **Слой отражения видит только лидера** и `force/energy/needs/
   conditions` (`automata.py:980-1100`). События обязаны ничего не менять
   (см. §4), но и отражать они умеют лишь узкий срез мира.
8. **Модель веры — голый триплет.** `bdi.py:91-135`; свойства требуют
   фиктивного объекта (`bdi.py:108`).
9. **Орган — один скаляр** `integrity`; `parent_id`/`automaton_id` не
   используются (`fractal.py:315-500`).
10. **Отношения не подключены** (`campaign/relations.py`).
11. **Нет валидации контента** — неизвестные ключи молча игнорируются.

Подробности и file:line — в
[`DATA_DRIVEN_CORE_GAPS.md`](DATA_DRIVEN_CORE_GAPS.md).

### 3.2. Что это значит для контента

Пока не закрыты пункты 1–4, любая лорная механика «миф», «легитимность»,
«обработчик», «подрыв», «канал» останется текстом. Работы смогут менять
только ±активы и ±потребности — то есть ~30% лорного смысла.

---

## 4. Принятые решения

| Решение | Обоснование |
|---|---|
| Не менять 16 потребностей | Контракт `bdi.NEEDS`, тест `test_bdi.py` |
| Богатство поведения — через предикаты, сути, автоматы, события | Не добавляет потребностей |
| Сначала документы, потом код | Требование пользователя |
| Порядок работ: P0 (диагностика) → P1 (BDI-вход) → P2 (вера v2) → P3/P4 (движки эффектов/условий) → P5/P6 (автоматы/подсистемы) → P7 (ИИ) → P8 (отношения) → P9 (контент) | Дешёвые изменения с максимальным эффектом первыми |
| Единый движок эффектов и условий | Иначе каждый слой контента требует Python-ветки |
| Автоматы — отдельные JSON-файлы с индексом | Масштаб: 100+ органов |
| Лорный список автоматов — нижняя граница | PDF неполный и поверхностный |
| Контент писать по доктринам, не по файлам | Легче держать баланс |
| **События — ролевой слой, не ядро** | Они ничего не производят и не порождаются другими событиями; только отражают текущие процессы. Состояние меняют работы, переходы автоматов и действия игрока |

### 4.1. Контракт событий

* Событие **читает** состояние через `conditions` и **ничего не пишет**.
* У события нет `effects`, `apply` и `emit`. Никакой эффект не порождает
  событие: очередь событий не является причиной состояния.
* Событие не порождает другое событие.
* Текст, видимость, вес и тон — единственные «выходы» события.
* В кампании `_advance_story_events` больше не вызывает применение
  эффектов; запись события хранит `effects: {}`.
* Линтер (`campaign/content_lint.py`) отклоняет событие с `effects` или
  `emit`.
* Следствие для контента: событие описывает уже случившееся — удар по
  мифу, казнь, закрытие канала, — но причиной этих изменений является
  работа или переход автомата.

---

## 5. Что создано в этой сессии

| Файл | Содержание |
|---|---|
| [`DATA_DRIVEN_CORE_GAPS.md`](DATA_DRIVEN_CORE_GAPS.md) | Аудит: 16 находок G-01…G-16, severity, file:line, критерии готовности |
| [`DATA_DRIVEN_CORE_PLAN.md`](DATA_DRIVEN_CORE_PLAN.md) | План P0…P9, схемы JSON, изменения по файлам, тесты, риски |
| [`CONTENT_PLAN_LORE.md`](CONTENT_PLAN_LORE.md) | Канон, ~100 предикатов, ~60 сутей, 126 работ, автоматы, активы, персонажи, события, сюжеты, объём, приёмка |
| `docs/SESSION_SUMMARY.md` | Этот файл |

### 5.1. Реализовано (P0 + P1)

* `campaign/content_lint.py` — линтер контента: 16 потребностей,
  предикаты, сути, ссылки органов, эффекты, события, подписи активов.
* `bdi.BDIState.seed()` — засев убеждений и намерений из контента без
  замены нескольких объектов одного предиката.
* `Character.deliberate(target=...)` и `Character.deliberate_target` —
  объект намерения больше не подменяется потребностью.
* `campaign/preset.py` — читает `character_defaults` и `posts[].beliefs/
  intentions`; записывает их в пресет вместе с `deliberate_target`.
* `campaign/automata.py` — восстанавливает убеждения/намерения из записи;
  **события больше не применяют эффекты** (ролевой слой).
* `configs/characters/bdi.json` — 9 новых предикатов-отношений и 8 сутей.
* `configs/campaigns/base/lore_factions.json` — `character_defaults` у всех
  четырёх фракций.
* Тесты: `tests/test_content_lint.py`, дополнения в `tests/test_bdi.py` и
  `tests/test_automata_campaign.py`.

### 5.2. Реализовано (P2)

* `bdi.Belief` получил `value`, `confidence`, `source`, `ttl`; объект у
  предиката-свойства теперь пуст, а не фиктивен.
* `BDIConfig.predicate_object_rule()` читает `object:
  required|forbidden`; правило по умолчанию выводится из `kind`.
* `BDIState.believe()` и `seed()` переносят силу, уверенность, источник и
  срок; `belief_value()` умножает вес на `value × confidence`.
* `BDIState.decay_beliefs()` старит убеждения и забывает истёкшие; ядро
  его автоматически не вызывает — темп задаёт контент/работа.
* `configs/characters/bdi.json`: у всех 30 предикатов явное правило
  объекта; добавлены свойства `is_legitimate` и `believes_in_own_myth`.
* Стартовые верования Империи и Республики переведены на свойства
  (`is_legitimate`, `believes_in_own_myth`) без фиктивного объекта.
* Линтер проверяет правило объекта: отношение без объекта и свойство с
  объектом — ошибки.

### 5.3. Реализовано (P3 + P4)

* `campaign/effects.py` — единственная точка записи. Понимает старый
  плоский формат и новый (`assets`, `needs`, `traits`, `conditions`,
  `beliefs.add/remove`, `intentions.push/clear`, `organs`, `flags`).
  `relations` отложена до P8 и попадает в `ignored`, а не в активы.
* `campaign/automata.py` — `_apply_branch` стал тонкой обёрткой;
  `FactionRuntime.flags` входит в снимок и сохраняется.
* `campaign/conditions.py` — `asset_reason` (старый формат) и
  `check_conditions` (типизированные клаузы: активы, потребности, черты,
  состояния, убеждения, намерения, органы, флаги, цикл, история; группы
  `all`/`any`/`not`).
* `requires.when` работает в `_action_requirement_reason`; линтер
  проверяет виды клауз и отвергает неизвестные.
* Тесты: `tests/test_effects.py`, `tests/test_conditions.py`; обновлены
  `test_content_lint.py` и `test_events_runtime.py` (события без эффектов).

События в `systems/events.json` больше не содержат `effects`: исторические
блоки удалены, а `test_production_runtime_events_are_data_driven` теперь
проверяет их отсутствие. `EventDefinition.effects` и `EventEngine.effects()`
остаются в `systems/events.py` только как легаси-API для старых тестов;
кампания их не вызывает. Линтер отклоняет `effects`/`apply`/`emit` в
событиях.

### 5.4. Реализовано (P5)

* `campaign/state_machine.py` — `StateMachineDefinition`, `StateSpec`,
  `TransitionSpec`, `StateMachine`, `StateMachineCatalog`; загрузка
  `configs/campaigns/base/automata/*.json`, приоритеты переходов, `on_enter`/`on_tick`,
  обработчики событий, снимок состояния и истории.
* `configs/campaigns/base/automata/faction_default.json` и `organ_default.json` — схема 2,
  пять состояний жизненного цикла, условия на активы и цикл, флаги на
  входах в ключевые состояния.
* `campaign/preset.py` — фракционные и органные автоматы собираются из
  JSON; Python-циклы остались fallback'ом, если файлов нет.
* `campaign/automata.py` — `_build_machines()` создаёт машины для каждой
  фракции и каждого органа; `_tick_machines()` вызывается из
  `_tick_organizations()`; состояния и история сохраняются в снимке под
  ключом `machines` и восстанавливаются.
* `campaign/content_lint.py` — проверяет `configs/campaigns/base/automata/*.json`:
  схема 2, `kind`, начальное состояние, цели переходов, эффекты и условия.
* Тесты: `tests/test_state_machine.py` (условия, приоритеты, эффекты,
  обработчик, стабильное состояние, снимок, дефолтный каталог, кампания);
  `tests/test_content_lint.py` дополнен проверками автоматов.

Автоматы пока не меняют баланс: у дефолтных состояний нет эффектов на
активы, только флаги. Это оставляет место для P9, где контент задаст
лорные эффекты переходов.

### 5.5. Реализовано (P6, основа)

* `SubfactionRuntime` во фракции: `id`, `label`, `share`, собственные
  `assets`, `organ_ids`, `machine_id`; `FactionRuntime.subfaction()`.
* `campaign/automata.py` — `_build_subfactions()` читает JSON, связывает
  вложенные органы через `subfaction_id`, создаёт автоматы подфракций,
  тикает их и сохраняет активы/состояния в снимке.
* `campaign/effects.py` — область `subfactions`:
  `{id: {"assets": {...}, "share": delta}}`; неизвестная подфракция
  попадает в `ignored`, а не в активы.
* `campaign/conditions.py` — `kind: subfaction` читает `asset` и `id`
  (или контекстную подфракцию).
* `campaign/faction_state.py` — метрики `subfactions.<id>.<asset>` и
  агрегаты `subfactions.mean|max|min:<asset>`.
* `campaign/preset.py` — `_subfaction_records()`, вложенные органы
  подфракций попадают в общий `organs` с `subfaction_id`; работы видят их
  подписи.
* `configs/campaigns/base/automata/subfaction_default.json` — лояльная →
  правящая / оттеснённая → ревизия.
* `campaign/content_lint.py` — id/share/assets/ссылки подфракций и
  вложенных органов.
* Тесты: `tests/test_subfactions.py` (сборка, эффекты, условия, метрики,
  автомат, снимок, линтер).

Осталось по P6: дерево «орган внутри органа» по `parent_id`, собственные
шкалы органа и петля «лидер → доктрина → работы» (G-14).

---

## 6. Следующие шаги

1. ~~**P0.** `campaign/content_lint.py`, проверка ссылок и эффектов.~~
   Сделано; осталось `configs/schemas/` и `schema_version` снимка.
2. ~~**P1.** Загрузить `beliefs`/`intentions` из
   `lore_factions.character_defaults` и `posts`; передать `target` в
   `deliberate`.~~ Сделано.
3. ~~**P2.** Расширить `Belief` (`value`, `confidence`, `source`, `ttl`) и
   `belief_predicates` (`object: required/forbidden`), затем перенести
   стартовые убеждения на свойства.~~ Сделано: свойства без объекта,
   `BDIState.decay_beliefs()`, лinter проверяет правило объекта.
4. ~~**P3/P4.** `campaign/effects.py` и `campaign/conditions.py`; перевести
   `_apply_branch` и `_asset_requirement_reason`.~~ Сделано; `relations`
   отложена до P8, `when` доступен работам.
5. ~~**P5.** `campaign/state_machine.py`; вынести автоматы из
   `preset.py`.~~ Сделано: JSON-каталог, тик и снимок автоматов фракций и
   органов.
6. ~~**P6.** Подсистемы и вложенные органы.~~ Основа сделана:
   `subfactions`, активы/эффекты/условия/метрики, автоматы и снимок;
   осталось дерево «орган внутри органа» и петля G-14.
7. **P7.** ИИ из данных.
8. **P8.** Отношения.
9. **P9.** Наполнение по `CONTENT_PLAN_LORE.md`, начиная с предикатов,
   активов, органов и работ Империи.

---

## 7. Инварианты и запреты (не забыть)

* Ровно 16 потребностей; имена из `bdi.NEEDS`.
* `simulation.py` — легаси-baseline, не менять без `BASELINE.md`.
* `core41/` — целевое ядро арены; не путать с кампанией.
* `configs/` — данные; новый контент не должен требовать правки Python,
  если загрузчик уже есть.
* Детерминизм по seed — часть контракта.
* Сохранения версионируются; изменение снимка — миграция + тест.
* PDF в `.gitignore` — не удалять правило.
* `yet_another_project/` — чужой каталог, не трогать.

---

## 8. Быстрые команды

```bash
# Лор
pdftotext -layout docs/лор.pdf /tmp/opencode/lore.txt

# Тесты
venv/bin/python -m pytest -q
venv/bin/python -m pytest -q tests/test_bdi.py
venv/bin/python -m pytest -q tests/test_content_pipeline.py
venv/bin/python -m pytest -q tests/test_automata_campaign.py
venv/bin/python -m pytest -q tests/test_state_machine.py tests/test_subfactions.py
```

---

## 9. Ключевые file:line (шпаргалка)

| Что | Где |
|---|---|
| 16 потребностей | `bdi.py:NEEDS`, `bdi.json:needs` |
| Триплет | `bdi.py:91-135` |
| Дуплет | `bdi.py:137-196` |
| Выбор намерения | `bdi.py:621-676` |
| `deliberate` | `warfare.py:464-500` |
| `ESSENCE_FOR_KIND` | `warfare.py:135` |
| Генерация персонажа | `campaign/preset.py:430-496` |
| Автоматы (данные) | `configs/campaigns/base/automata/*.json` |
| Рантайм автоматов | `campaign/state_machine.py` |
| Сборка графа пресета | `campaign/preset.py` (`_automaton_from_definition`) |
| Тик/снимок автоматов | `campaign/automata.py` (`_tick_machines`, `_machines_snapshot`) |
| Подфракции | `campaign/automata.py` (`SubfactionRuntime`, `_build_subfactions`) |
| Запись персонажа | `campaign/automata.py:141-182` |
| Сборка фракций | `campaign/automata.py:588-755` |
| Контекст сюжета | `campaign/automata.py:980-1031` |
| Требования работ | `campaign/automata.py:1166-1260` |
| Эффекты работ | `campaign/automata.py:1969-1987` |
| ИИ | `campaign/automata.py:2168-2198` |
| Тик персонажей | `campaign/automata.py:2300-2340` |
| Активы из JSON | `campaign/faction_state.py:243-295` |
| Орган | `campaign/fractal.py:315-405` |
| Тик органов | `campaign/fractal.py:465-500` |
| Belief-условие | `systems/events.py:192-208` |
| Отношения (не подключены) | `campaign/relations.py` |
