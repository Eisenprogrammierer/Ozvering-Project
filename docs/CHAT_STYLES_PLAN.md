# План: игровой чат и стилевой слой общения

> **Статус:** рабочий план и фактический прогресс D5.1–D5.4, D3.2 и
> D6.2a.
> Разделы 1–4 сохранены как история первого подхода (строковые
> `frames`/`prefix`/`suffix`/`closer`), признанного недостаточным.
> Актуальная архитектура — регистровый профиль реализатора (§11)
> и автовыбор регистра (§12).
>
> **Связанные документы:** [`DIALOGUE_NLG.md`](DIALOGUE_NLG.md),
> [`DATA_DRIVEN_CORE_GAPS.md`](DATA_DRIVEN_CORE_GAPS.md).
>
> **Дата:** 2026-11-14.

## 1. Запрос пользователя

1. Добавить простой игровой чат: игрок выбирает автомат/фракцию и
   персонажа, с которым говорит, и пишет сообщения от лица своего
   игрового персонажа.
2. Проработать стилистическую составляющую общения: канцелярит
   (официальная переписка, доклад, приказ), дружеское, любовное общение
   и остальные регистры.

## 2. Жёсткие инварианты

- Диалог остаётся свободным русским текстом, без LLM, нейросетей,
  эмбеддингов и статистического ранжирования.
- Детерминизм: одинаковые мир, состояние диалога, стиль и ввод дают
  одинаковый ответ.
- Полная Data-Driven архитектура: стили, признаки, конструкции,
  обращения, маркеры и правила применения лежат в JSON. Python только
  интерпретирует данные.
- Стиль — только поверхностный слой. Он не выбирает факты, не меняет
  план ответа, не подменяет композиционный синтез и не превращается в
  выбор готовых ответов.
- Диалог read-only по отношению к кампании и BDI. Мост действий — только
  через намерения, как и раньше.
- Ровно 16 потребностей в `configs/characters/bdi.json` не трогать.
- Шаблоны `realization.json` остаются только аварийным fallback.
- По фундаментальным архитектурным вопросам спрашивать пользователя.

## 3. Архитектура стилевого слоя (первая версия, отвергнута)

### 3.1. Место в конвейере

Первая версия встраивала стилевой слой последним шагом:

```
Answer → StyleEngine.apply(answer, style_id, knowledge) → Answer
```

Причина отказа: строковые `frames`/`prefix`/`suffix`/`closer` — это
декоративная обёртка готового предложения, а не стиль речи.

### 3.2. Схема styles.json (первая версия, отвергнута)

```json
{
  "styles": {
    "official": {
      "frames": {"default": {"prefix": "Имею честь сообщить: "}},
      "closer": "С совершенным почтением, {speaker}.",
      "replacements": [{"find": "Да.", "replace": "Подтверждается."}]
    }
  }
}
```

## 4. Метаданные игрока и говорящего

`AgentKnowledge` дополняется полями:

- `speaker_post`, `faction_name`;
- `player_id`, `player_name`, `player_post`, `player_faction`,
  `player_side`, `player_gender`.

`build_knowledge()` заполняет эти поля, не меняя кампанию и BDI.

## 5. Игровой чат

`view/screens/dialogue_chat.py`, класс `DialogueChatScreen(BaseScreen)`.

Экран:

- левая панель — список фракций-автоматов и персонажей выбранной
  фракции;
- правая панель — история сообщений, заголовок собеседника, выбор
  стиля ответа;
- нижняя строка — поле ввода и кнопка «Отправить»;
- кнопка «Назад» / ESC — возврат на экран автоматов.

Сессии кэшируются по `(side, character_id)`, память общая через
`app.dialogue_session()`. История сообщений хранится в экране и
разделена по собеседникам.

## 6. Тесты

Обязательные проверки:

1. `lint_directory()` проходит и проверяет стили.
2. Нейтральный стиль не меняет текст существующих ответов.
3. Стиль сохраняет `kind`, `plan_id`, `proof`, `data`.
4. Одинаковый стиль + ввод → одинаковый текст.
5. Неизвестный стиль безопасно откатывается к стилю по умолчанию.
6. Подстановки `{player}`, `{speaker}`, `{address}` работают.
7. Новый стиль добавляется только правкой JSON и сразу работает.
8. Экран чата: выбор фракции/персонажа, выбор стиля, отправка.
9. Кнопка «СВЯЗЬ» на экране автоматов открывает чат.
10. Память диалога и сохранение не ломаются.

## 7. Команды проверки

```bash
venv/bin/python -m campaign.dialogue.lint
venv/bin/python -m campaign.content_lint
venv/bin/python -m pytest -q tests/test_d1_dialogue.py \
  tests/test_d1_5_synthesis.py tests/test_d2_state.py \
  tests/test_d3_comparison.py \
  tests/test_d5_discourse.py tests/test_d5_discourse_paragraph.py \
  tests/test_d5_registers.py tests/test_d4_social.py \
  tests/test_save_system.py
git diff --check
```

Полный прогон перед коммитом:

```bash
venv/bin/python -m pytest -q
```

## 8. Текущий прогресс

- [x] Изучены UI кампании, движок ответов, персоны, загрузчик, lint.
- [x] Зафиксирован план в этом файле.
- [x] `model.py`: `StyleSpec`, `StyleCatalog`, `FeatureSchema`,
  `DiscourseMove`, `DiscoursePattern`, `DiscourseCatalog`,
  `DiscourseAnaphora`, `StyleContextRule`, `StyleContextCatalog`,
  `ComparisonSpec`, `ComparisonCatalog`, `CounterfactualSpec`.
- [x] `loader.py`: `load_styles` (extends/features/selection),
  `load_features`, `load_discourse` (moves/patterns/connectives/
  anaphora), `load_style_context`, `load_comparison`,
  `load_counterfactual`.
- [x] `configs/dialogue/styles.json` (schema 4, 8 стилей).
- [x] `configs/dialogue/features.json`.
- [x] `configs/dialogue/style_context.json` (D5.2).
- [x] `configs/dialogue/discourse.json` (D5.1 + D5.3:
  `mode`, `topic`, `anaphora`).
- [x] `configs/dialogue/comparison.json` (D3.1).
- [x] `configs/dialogue/counterfactual.json` (D3.2).
- [x] `campaign/dialogue/style.py`: `StyleEngine`, `SELECTION_KEYS`,
  `features()`, `is_neutral()`, `resolve_for_context`,
  `profile_for_context`.
- [x] `campaign/dialogue/features.py`: `match_score`, `compatible`,
  `select_best`, `filter_compatible`.
- [x] `campaign/dialogue/coverage.py`: отчёт покрытия.
- [x] `campaign/dialogue/realize.py`: регистровый выбор, конструкции,
  вложенные клаузы, обращения, маркеры, антиповтор, `render_moves`
  с `mode: plain|clause`, анафора, тема-рема.
- [x] `campaign/dialogue/answers.py`: `_discourse`, `_build_moves`,
  `_ordered_moves`, `_answer_entities_for_anaphora`,
  `_fallback_entities`, `_answer_comparison`, `_answer_counterfactual`,
  `max_premises`.
- [x] `campaign/dialogue/counterfactual.py` (D3.2):
  `CounterfactualEngine.with_facts` / `compare` / `_differences`.
- [x] `campaign/dialogue/engine.py`: `DialogueSession(style_id=None)`
  = авто-режим; `set_style(None)` возвращает в авто.
- [x] `campaign/dialogue/lint.py`: `_style_problems`,
  `_style_context_problems`, `_discourse_problems`,
  `_anaphora_problems`, `_comparison_problems`,
  `_counterfactual_problems`.
- [x] `view/screens/dialogue_chat.py` (D1.5–D4).
- [x] Кнопка «СВЯЗЬ» в `automata_screen.py`.
- [x] Тесты `tests/test_d5_discourse.py` — 17 тестов.
- [x] Тесты `tests/test_d5_discourse_paragraph.py` — 16 тестов
  (D5.3 + D5.4).
- [x] Тесты `tests/test_d5_registers.py` — 19 тестов.
- [x] Тесты `tests/test_d3_comparison.py` — 16 тестов.
- [x] D5.4 — дискурсивная агрегация абзаца (4+ хода): механизм
  `topics` + линтер + тесты. Production-паттерна с `topics` нет.
- [x] D6.2a — отрицание в антецеденте: `NEG` в лексиконе, правила
  `np_neg_v_np*`, `negated: true`, обмен `remove`/`add`; покрыто
  `tests/test_d3_counterfactual.py`.
- [x] D6.2b–c — «то»-клауза и `predicate_relations`.
- [x] D6.3 — политика раскрытия и ложь.
- [x] D6.2d — условия, уступки, косвенная и прямая речь, beam,
  корпус парафраз; `tests/test_d6_grammar.py`,
  `tests/test_d6_parse_beam.py`, `tests/test_d6_paraphrases.py`.
- [x] D6.4 — цели разговора (`goals.json`), планировщик, мост к
  действиям, императивы и псевдонимы (`actions.json`);
  `tests/test_d6_planner.py`, `tests/test_d6_bridge.py`,
  `tests/test_d6_actions.py`.
- [ ] Аудит `lexicon.json` (сокращение дублей `aliases` ⊇ `forms`).
- [ ] D3.2: использование `differences` в тексте ответа; тесты D3.2.

## 9. Файловая карта

- `configs/dialogue/styles.json` — стили.
- `configs/dialogue/features.json` — схема измерений стиля.
- `configs/dialogue/style_context.json` — правила автовыбора.
- `configs/dialogue/discourse.json` — ходы, шаблоны, связки, анафора.
- `configs/dialogue/comparison.json` — таблица сравнений.
- `configs/dialogue/counterfactual.json` — правила контрфакта.
- `campaign/dialogue/style.py` — селектор регистра и автовыбор.
- `campaign/dialogue/features.py` — детерминированный выбор.
- `campaign/dialogue/coverage.py` — отчёт покрытия.
- `campaign/dialogue/realize.py` — синтез с учётом регистра,
  `render_moves` (plain/clause, анафора, тема-рема).
- `campaign/dialogue/answers.py` — план + синтез + дискурсивный слой
  + сравнения + контрфакты.
- `campaign/dialogue/counterfactual.py` — контрфакты.
- `campaign/dialogue/engine.py` — авто-режим стиля.
- `campaign/dialogue/lint.py` — валидация стилей, дискурса, анафоры,
  сравнений, контрфактов.
- `view/screens/dialogue_chat.py` — экран чата.
- `tests/test_d5_discourse.py` — D5.1.
- `tests/test_d5_discourse_paragraph.py` — D5.3 и D5.4.
- `tests/test_d5_registers.py` — D5.2.
- `tests/test_d3_comparison.py` — D3.1.
- `tests/test_d3_counterfactual.py` — D3.2 (не создан; см. `TODO.md`
  §2).

## 10. Что нельзя потерять

- Стиль не является выбором готового ответа.
- Стиль не меняет факты, план, доказательство и `data`.
- 16 потребностей не трогаем.
- Никаких LLM, эмбеддингов и статистики.
- Сквозной детерминизм и объяснимость.
- Нейтральный путь байт-в-байт (`StyleEngine.is_neutral` → fallback).

## 11. Актуальная архитектура: регистровый профиль реализатора

### 11.1. Диагноз

Строковые `frames`, `prefix`, `suffix` и `closer` — это не стиль речи,
а декоративная обёртка готового предложения. Отвергнуто.

### 11.2. Принцип

Стиль — это **регистровый профиль генерации**, а не постобработка
строки. Слои, ставшие данными:

1. **Лексические регистры.** У одного смысла может быть несколько
   лексем.
2. **Конструкции одного смысла.** Несколько конструкций, помеченных
   регистром, типом адресата и условиями.
3. **Рекурсивные конструкции.** Главное + придаточное.
4. **Обращения как именные группы.** Звательная/именительная форма,
   согласование по полу.
5. **Дискурсивный планировщик.** 1–3 хода: прямой ответ, обоснование,
   оговорка, заключение; 4+ — через `topics` (D5.4). Стиль выбирает
   форму и связки, но не добавляет факты.
6. **Детерминированный антиповтор.** Последние использованные
   конструкции хранятся в `DialogueMemory`.
7. **Анафора внутри ответа (D5.3).** Повтор имени первого хода
   заменяется на местоимение по роду/числу.
8. **Автовыбор регистра (D5.2).** Регистр определяется контекстом,
   если игрок не выбрал явно.

### 11.3. Схема данных

```json
{
  "schema": 4,
  "default": "neutral",
  "styles": {
    "official": {
      "id": "official",
      "label": "канцелярит",
      "extends": "neutral",
      "register": "official",
      "features": {
        "formality": "high",
        "distance": "far",
        "directness": "indirect",
        "nominalization": "high",
        "address_mode": "post"
      },
      "selection": {"avoid_recent": 0}
    }
  }
}
```

Признаки объявляются в `features.json` (`dimensions` со значениями и
умолчаниями). `extends` наследует признаки и `selection` родителя;
`register` — ключ профиля.

### 11.4. Что меняется в коде

- `style.py` — селектор регистра и профилей, `resolve_for_context`.
- `features.py` — детерминированное сопоставление.
- `realize.py` — выбор лексемы/конструкции по регистру, вложенные
  клаузы, обращения, маркеры, антиповтор, `render_moves` с
  `mode: plain|clause`, анафора, тема-рема.
- `answers.py` — передаёт стиль в реализатор, собирает `moves`,
  `data["discourse_trace"]`, обрабатывает контрфакты.
- `counterfactual.py` — подмена фактов и сравнение вывода.
- `engine.py` — авто-режим стиля.
- `coverage.py` — отчёт покрытия.

### 11.5. Что НЕ меняется

- Парсер, грамматика входа, вывод, доказательства.
- Read-only отношение к кампании и BDI.
- 16 потребностей.
- Память, сохранения, QUD и референты.
- Запрет на LLM, эмбеддинги и статистическое ранжирование.
- Композиционный синтез как основа; `realization.json` — fallback.
- Нейтральный путь байт-в-байт.

### 11.6. Решение по объёму переработки

Выбран **A. Полный регистровый реализатор**: лексические варианты,
несколько конструкций на смысл, вложенные клаузы, обращения,
дискурсивные маркеры и антиповтор.

## 12. D5.2: автовыбор регистра по контексту

### 12.1. Принцип

Если игрок не выбрал стиль явно (`style_id=None`), стиль определяется
правилами из `style_context.json`. Явный стиль игрока побеждает правила.

### 12.2. Схема данных

```json
{
  "schema": 1,
  "enabled": true,
  "rules": [
    {
      "id": "enemy_hostile",
      "style": "hostile",
      "priority": 100,
      "when": [
        {
          "kind": "fact",
          "rel": "at_war_with",
          "args": ["$speaker_faction", "$player_faction"]
        }
      ]
    },
    {
      "id": "same_faction_friendly",
      "style": "friendly",
      "priority": 55,
      "when": [
        {"kind": "field", "field": "player_side", "op": "eq",
         "value": "$side"}
      ]
    }
  ]
}
```

Типы условий:

- `fact` — наличие факта в `AgentKnowledge.facts_for(rel)` с
  подстановкой `$speaker_*`/`$player_*`/`$side`/`$faction_id`.
- `field` — сравнение поля `AgentKnowledge` (`player_id`, `player_side`,
  `side`, `faction_id`, `speaker_id` и т.д.) с константой или другим
  полем. Операторы: `eq`, `ne`, `in`, `not_in`, `exists`.

### 12.3. Порядок выбора

1. Явный `style_id` игрока.
2. `persona.default_style`.
3. Правила `style_context.json` по убыванию `priority`.
4. `styles.default` (обычно `neutral`).

### 12.4. Что НЕ делает автовыбор

- Не выбирает факты.
- Не меняет план.
- Не влияет на `kind`/`plan_id`/`proof`/`data`.
- Не отменяет read-only.

## 13. D5.3: агрегация, анафора и тема-рема

### 13.1. `mode: plain | clause`

- `plain` — связка разделяет два предложения: `A. При этом B.`
- `clause` — связка встраивается внутрь одного: `A, потому что B.`

Выбор — по `connectives[].mode`, с учётом регистра.

### 13.2. `topic` в паттерне

`topic` называет ход, который идёт первым (тема), остальные — ремы.
`explanation_basic` использует `topic: "justify"` — сначала
обоснование, потом ответ.

### 13.3. `anaphora`

```json
{
  "enabled": true,
  "types": ["faction", "character", "organ", "work"],
  "kinds": ["answer", "justify", "conclusion", "hedge"],
  "pronouns": {"f:sg": "она", "m:sg": "он", "n:sg": "оно"},
  "min_length": 3
}
```

Заменяет имя в ходе 2+ на местоимение, если оно уже было в ходе 1.
Регистронезависимое сравнение; сохранение регистра замены.

### 13.4. Что НЕ делает анафора

- Не работает в первом ходе (не на что ссылаться).
- Не работает между репликами (это D2 через `DialogueMemory`).
- Не заменяет имена в списочных ответах (`items` не участвуют).
- Не выходит за `types` и `kinds`.

## 14. D3.1: сравнения

### 14.1. Схема данных

```json
{
  "schema": 1,
  "comparisons": {
    "asset": {
      "relation": "asset",
      "subject_arg": 0,
      "key_arg": 1,
      "value_arg": 2,
      "key_prefix": "asset:",
      "greater": "comparison_greater",
      "less": "comparison_less",
      "equal": "comparison_equal",
      "unknown_left": "comparison_unknown_left",
      "unknown_right": "comparison_unknown_right",
      "both_unknown": "comparison_both_unknown"
    }
  }
}
```

### 14.2. Порядок

1. Значения читаются через `InferenceEngine.first(relation, ...)` с
   подстановкой `$value` в позицию значения (пустая строка не
   унифицируется с фактом).
2. `key_prefix` снимается с ключа перед унификацией (у `asset` ключ
   хранится без `asset:`).
3. Оператор (`==`, `>`, `<`) и конструкция исхода берутся из данных.
4. Нет данных → `unknown_*`/`both_unknown`.

### 14.3. Что НЕ делает сравнение

- Не добавляет факты.
- Не выходит за числовые отношения.
- Не работает через контрмодель (это D3.2).

## 15. D3.2: контрфакты

### 15.1. Схема данных

```json
{
  "schema": 1,
  "relations": ["belief", "asset", "at_war_with", "considers_outlaw"],
  "max_steps": 2,
  "outcomes": {
    "changed": "cf_changed",
    "unchanged": "cf_unchanged",
    "unknown": "cf_unknown"
  }
}
```

- `relations` — whitelist подменяемых отношений; вне списка `with_facts`
  игнорирует `remove`/`add`.
- `max_steps` — ограничение на число отличий в `differences`.
- `outcomes` — исход → конструкция синтеза в `synthesis.constructions`.

### 15.2. Движок

- `CounterfactualEngine.with_facts(remove, add)` собирает новый
  `AgentKnowledge` тем же конструктором, без мутаций и без изменений
  кампании.
- `compare(relation, args, remove, add)` доказывает цель в базе и в
  контрмодели.
- `_differences` обходит базу сверху вниз и возвращает **первый
  расходящийся шаг**; при `None` с одной стороны — голову доказанной
  ветки.

### 15.3. Что НЕ делает контрфакт

- Не подменяет правила вывода.
- Не меняет кампанию или BDI.
- Не добавляет новых фактов за пределами whitelist.
- Не объясняет «что именно» изменилось в тексте — это D6.2/D6.4.

### 15.4. Сквозное ограничение (2026-11-14)

`cf_explain` использует предикат разбора (`believe`/`fight`/`have`) как
имя отношения, а whitelist содержит `belief`/`asset`/`at_war_with`/
`considers_outlaw`. `cf_explain_yesno` удаляет `has_organ`,
которого нет в whitelist, поэтому удаление игнорируется. В production
типовой исход — `unknown`/`unchanged`; `cf_changed` практически
недостижим до D6.2c. Отдельного теста D3.2 нет.

## 16. Файловая карта (актуально)

- `configs/dialogue/styles.json`
- `configs/dialogue/features.json`
- `configs/dialogue/style_context.json`
- `configs/dialogue/discourse.json`
- `configs/dialogue/comparison.json`
- `configs/dialogue/counterfactual.json`
- `campaign/dialogue/style.py`
- `campaign/dialogue/features.py`
- `campaign/dialogue/coverage.py`
- `campaign/dialogue/model.py`
- `campaign/dialogue/loader.py`
- `campaign/dialogue/lint.py`
- `campaign/dialogue/realize.py`
- `campaign/dialogue/answers.py`
- `campaign/dialogue/counterfactual.py`
- `campaign/dialogue/engine.py`
- `campaign/dialogue/knowledge.py`
- `campaign/dialogue/state.py`
- `view/screens/dialogue_chat.py`
- `view/screens/automata_screen.py`
- `tests/test_d5_discourse.py`
- `tests/test_d5_discourse_paragraph.py`
- `tests/test_d5_registers.py`
- `tests/test_d3_comparison.py`
- `tests/test_d3_counterfactual.py` (не создан; D3.2 покрыт только
  линтером и ручными прогонами)