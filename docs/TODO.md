# TODO: что открыто и в каком порядке

> **Дата:** 2026-11-14. Основано на `DIALOGUE_NLG.md` §10,
> `CHAT_STYLES_PLAN.md` §8 и личном `SCALING_ANALYSIS.md`
> (не часть проекта).

## 0. Закрыто

### 0.1. D3.2 — контрфакты (механизм и сквозной сценарий закрыты 2026-11-14)

- **Грамматика.** `s_counterfactual`, `s_counterfactual_short`,
  `s_counterfactual_neg`, `s_counterfactual_consequent[_would]`,
  `s_counterfactual_past[_consequent]` и `s_assert_np_part_v*` в
  `configs/dialogue/grammar.json`. Разбираются «Что если …?»,
  «Что, если бы …?», «Что было бы, если бы …?» и «…, то …».
- **Лексемы.** `concept:if` (`COND`), `part:would` (`PART`),
  `concept:then` (`TO`), `verb:issue`, `verb:fall`.
- **Движок.** `campaign/dialogue/counterfactual.py`
  (`CounterfactualEngine.with_facts` / `compare`). `_differences` —
  первый расходящийся шаг сверху вниз; при `None` с одной стороны —
  голова доказанной ветки.
- **Данные.** `configs/dialogue/counterfactual.json` (whitelist
  `belief`/`asset`/`at_war_with`/`considers_outlaw`/`has_organ`,
  `max_steps: 2`), `world.json: predicate_relations`, конструкции
  `cf_changed`/`cf_unchanged`/`cf_unknown` в `synthesis.json`.
- **Планы.** `cf_explain` (прямой NP-объект), `cf_explain_with`
  (PP-объект: «воюет с …»), `cf_explain_yesno` (`have → has_organ`).
- **D6.2c.** Предикат разбора резолвится в отношение мира через
  `world.predicate_relations`. Для производных отношений (`believe →
  considers_outlaw`) удаляется исходный факт (`belief`) через
  `remove`, а не сам derived-атом.
- **D6.2b.** `consequent` («…, то …») становится целью сравнения;
  антецедент остаётся подменой фактов.
- **D6.2a.** `negated: true` меняет `remove`/`add` местами; разбор
  `NEG` закреплён тестом.
- **Линтер.** `_counterfactual_problems`; `_world_problems` проверяет
  `predicate_relations` (строка/объект, `relation`, `remove`);
  `counterfactual` в `_ANSWER_TYPES` и `_DISCOURSE_KINDS`;
  `_plan_problems` пропускает `$`-значения в `remove`/`add`.
- **Тесты.** `tests/test_d3_counterfactual.py` (17 тестов): исходы,
  whitelist, read-only, `predicate_relations`, отрицание, consequent,
  битая ссылка в линтере.

**Долг, вынесенный из D3.2 в D6.2:**

- **Обобщение через `world.belief_predicates`.** Сейчас `cf_explain`
  использует `predicate` парсера (`believe`/`fight`) как имя
  отношения. Если отношения с таким именем нет в `world.relations`,
  доказательство пустое, исход `unknown`. Нужно: маппинг
  `predicate → relation` через `world.belief_predicates` (для
  `belief`) и таблицу `predicate → relation` для остальных.
- **`cf_*` конструкции не используют `differences`/`removed`/`added`.**
  Сейчас текст — «Если бы это было иначе, X изменилось бы», без
  указания, что именно. Полноценное «изменилось бы потому, что …» —
  D6.2 или D6.4.
- **«то»-клауза (consequent).** Сейчас поддерживается только
  антецедент. «…, то Республика бы пала?» — D6.2.
- **Whitelist `counterfactual.json`** — 4 отношения. Расширять по
  мере роста лора (P8/P9), осознанно, не «на всякий случай».

### 0.2. D5.3 — агрегация, анафора, тема-рема (закрыто 2026-11-14)

- `discourse.connectives[].mode: plain|clause`, `patterns[].topic`,
  `discourse.anaphora` — данные в `discourse.json`.
- `Realizer.render_moves` (склейка по `mode`, `topic`, анафора).
- `_discourse`, `_build_moves`, `_ordered_moves`,
  `_answer_entities_for_anaphora` в `answers.py`.
- Линтер `_discourse_problems`, `_anaphora_problems`.
- Тесты `tests/test_d5_discourse_paragraph.py`.

### 0.3. D5.4 — абзац 4+ хода (закрыто 2026-11-14)

- `DiscoursePattern.topics: Tuple[str, ...]`.
- `_ordered_moves`: `topics` → `topic` → `moves`, дедупликация,
  защита от опечаток.
- `_discourse_problems`: `topics ⊆ moves`, без дублей.
- Механизм есть; `explanation_detailed` **не** в production —
  иначе ломался бы `test_missing_pattern_skips_discourse`.
- Тесты `tests/test_d5_discourse_paragraph.py` (D5.4-часть).

### 0.4. D6.2a — `не` в утверждениях и антецеденте (механизм закрыт 2026-11-14)

- `lexicon.json`: `part:not` переехал из `PART` в `NEG`,
  `semantic: {"kind": "neg", "id": "not"}`.
- `grammar.json`: `s_yesno_*` матчат `PART` с
  `features: {"lemma": "ли"}`; новые правила `np_neg_v_np`,
  `np_neg_v_np_adj`, `np_neg_v_pp` дают `negated: true`.
- `semantics.py`: `flatten` обрабатывает `kind: "neg"` → `True`.
- `answers.py`: `_plan` кладёт `$sem` для `counterfactual`;
  `_answer_counterfactual` берёт `negated` из
  `$sem.antecedent.negated` и меняет `remove`/`add` местами.
- `plans.json`, `lint.py`, `model.py`, `loader.py`, `parser.py` —
  не тронуты.
- **Сквозной сценарий.** После D6.2c отрицательный контрфакт
  резолвит предикат в отношение мира, поэтому `remove`/`add` больше
  не теряются на несогласованном имени.
- **Тесты.** `tests/test_d3_counterfactual.py`: разбор `NEG`,
  `negated: true` и перестановка `remove`/`add`.

## 1. Диалог: следующий шаг

### 1.1. D6.2c — `predicate_relations` (закрыто 2026-11-14)

- `world.json` содержит `predicate_relations` для `believe`, `befriend`,
  `fight`, `have`, `threaten`, `defend`, `depend`, `rule`, `locate`,
  `begin`, `do`.
- `_answer_counterfactual` резолвит `$rel` через таблицу; для
  производных отношений использует исходный факт из `remove`.
- Линтер проверяет `relation` и `remove` в `predicate_relations`.
- Сквозной сценарий проверен: «Империя считает Республику незаконной» →
  `considers_outlaw`, `changed`; «Империя имеет Абвер» → `has_organ`,
  `changed`; «Империя воюет с Республикой» → `at_war_with`, `changed`.

### 1.2. D6.2b — «то»-клауза контрфакта (закрыто 2026-11-14)

- `s_counterfactual_consequent[_would]`,
  `s_counterfactual_past[_consequent]` и `concept:then` (`TO`).
- `consequent` становится целью сравнения; антецедент остаётся
  подменой фактов.
- Тесты: разбор «Что было бы, если бы Империя не издала эдикт, то
  Республика бы пала?» и проверка consequent как цели.

### 1.3. D6.2d — условия, уступки, косвенная речь (высокий риск, 3–5 дней) — сделано

- +20–30 правил в `grammar.json`: `если … то`, `хотя …`, `несмотря
  на`, косвенная речь (`он сказал, что …`), цитаты.
- Детерминированный beam вместо «первого разбора».
- Корпус парафраз для проверки.
- Тесты: `tests/test_dialogue.py` (golden-разборы), новый
  `tests/test_d6_grammar.py`.

**Сделано 2026-11-14:** `s_conditional` (`если … то …`),
`s_concessive` (`хотя …`, «несмотря на»), `s_indirect_speech`
(`NP сказал, что S`) и `s_direct_speech` (цитата в «…»); лексемы
`concept:although` (`SCONJ`), `concept:despite` (`SCONJ`),
`concept:that` (`COMP`), `quote:open`/`quote:close` (`QUOTE`/
`QUOTE_END`), `verb:say`. Семантика: `conditional` / `concessive` /
`report` с `mode: direct|indirect`. Токенизатор сохраняет кавычки.
Детерминированный beam — `configs/dialogue/parsing.json`
(`beam_width`, `kind_priority`, `prefer_depth`), `parse_beam` /
`parse_best`; при равном виде сохраняется канонический порядок.
Тесты — `tests/test_d6_grammar.py` (16),
`tests/test_d6_parse_beam.py` (11) и
`tests/test_d6_paraphrases.py` (32; корпус 26 фраз из
`configs/dialogue/paraphrases.json`). D6.2d закрыт полностью.

### 1.4. D6.3 — политика раскрытия и ложь (средний риск, 3 дня) — сделано

- `configs/dialogue/disclosure.json`: политики `honest`, `partial`,
  `withhold`, `evasive`, `lie` с исходами и текстами.
- `lie_probability` и `disclosure`/`on_topic` в персонах.
- Детерминированная ложь: SHA-256 от seed/хода/темы/аргументов;
  ложь только при `score < lie_probability`.
- Трассировка: `disclosure`, `disclosure_topic`, `lied`,
  `lie_score`, `truth_text`/`truth_kind`/`truth_args`.
- Линтер `_disclosure_problems`; тесты —
  `tests/test_d6_disclosure.py` (19 тестов).

### 1.5. D6.4 — цели разговора и действия (средний риск, 3–5 дней)

**Переопределено 2026-11-14.** Раньше D6.4 был «цели разговора,
иерархический планировщик» — про диалог. Теперь — **общий механизм
для диалога и действий**, шаг к текстовой RPG.

- `campaign/dialogue/planner.py`: HTN-подобный планировщик.
  Вход — цель (`explain(X)`, `convince(Y, Z)`, `move_to(N)`,
  `perform(work)`), выход — дерево подцелей с проверкой выполнения.
- `campaign/dialogue/bridge.py`: мост «фраза → намерение →
  действие». `DialogueSession` получает флаг `allow_actions`; при
  `False` (RTS) мост не вызывается, диалог остаётся read-only. При
  `True` (текстовая RPG) фраза разбирается в намерение, проходит
  через `conditions.py`, отправляется в `AutomataCampaign.perform`.
- Планировщик работает и для диалога (вести разговор к цели), и для
  действий (выполнить цель в мире).
- Тесты: `tests/test_d6_planner.py`, `tests/test_d6_bridge.py`.

### 1.6. D7 — текстовая ролевая игра (5–7 дней после D6.4)

**Новый раздел 2026-11-14.** Текстовая RPG — не новый домен, а
второй **проектор** существующего мира. Тест архитектуры на
универсальность: если `bridge.py` + `Narrator` получаются тонкими
(сотни строк), и ядро не трогается — принцип «универсальность через
домены» работает.

- **D7.0. Мост «фраза → намерение».** Уже покрыт D6.4
  (`bridge.py`). Здесь — обвязка: текстовый UI, история команд,
  откат, подсказки.
- **D7.1. Речевые действия как действия.** `social.json` уже
  разбирает «приказываю», «обещаю», «угрожаю». В RTS они read-only;
  в текстовой RPG через `bridge.py` становятся намерениями и уходят
  в конвейер работ. Проверка: `has_authority`, `trusts`,
  `has_leverage` уже есть в `knowledge.py`; надо использовать их
  в `conditions.py` для гейтов.
- **D7.2. Пространство и перемещение через текст.** «Иду к Абверу»,
  «Отправляюсь в столицу» — `located_at` + `geometry` (P6.5, этап
  B: метрический граф без координат). Для текстовой RPG
  достаточно «рядом», «далеко», «путь через X».
- **D7.3. Время и ходы через текст.** «Жду», «Жду до утра»,
  «Ускоряю» — управление `AutomataCampaign.tick`. Механизм
  ускорения в UI уже есть; нужен текстовый эквивалент.
- **D7.4. Нарративный слой.** `systems/events.py` уже read-only и
  отражает процессы. Для текстовой RPG события становятся
  **основным** источником текста: «что игрок видит». Нужен
  `Narrator`, который превращает события в описание, но **не**
  меняет мир (контракт G-08 сохраняется).
- **Архитектурный инвариант.** `bridge.py` + `Narrator` —
  тонкие. `automata.py`, `faction_state.py`, `fractal.py`,
  `state_machine.py` — не трогаются. Если придётся переписать ядро
  под действия через текст — фиксируем разрыв в
  `DATA_DRIVEN_CORE_GAPS.md` и пересматриваем принцип.

## 2. Диалог: технический долг

- **G-20 (UX).** Правила автовыбора не показываются игроку. В D6:
  панель «почему такой регистр» в чате.
- **G-21 (ordinal).** Сравнение нечисловых сущностей (сила
  убеждения, репутация).
- **G-23 (because).** Валидация формы `reason` для `mode: clause`.
- **D5.1 антиповтор.** `avoid_recent` ограничен N ходами; проверить,
  что он не даёт выбрать неожиданный регистр в длинном диалоге.
- **D3.2 cf-конструкции.** Не используют `differences`/`removed`/
  `added`. Полноценное «изменилось бы потому, что …» — D6.4.
- **D3.2 whitelist.** 5 отношений; расширять по мере P8/P9.
- **D6.2a `s_counterfactual_neg`.** Дублирует `s_counterfactual`;
  удалить или оставить как документирующий алиас.
- **Тесты D3.2.** `tests/test_d3_counterfactual.py` покрывает исходы
  changed/unchanged/unknown, whitelist, read-only, `predicate_relations`,
  отрицание и consequent.
- **Тесты D6.2a.** Разбор `NEG`, `negated: true` и обмен
  `remove`/`add` покрыты там же.
- **Тесты `DialogueChatScreen`.** Нет headless-теста экрана чата:
  выбор фракции/персонажа, ручной стиль, отправка, память.
- **Автостиль в чате.** `DialogueChatScreen` всегда передаёт
  выбранный вручную стиль; авто-режим есть только в
  `DialogueSession(style_id=None)`. Нужен переключатель «авто».
- **Production `topics`.** Механизм D5.4 покрыт тестами, но паттерна
  с `topics` в `configs/dialogue/discourse.json` нет. Решить, когда
  включать `explanation_detailed`, не ломая
  `test_missing_pattern_skips_discourse`.

## 3. Документация

- [x] `DIALOGUE_NLG.md` — D0–D5.4, D3.2, D6.2a–d и D6.3 отражены;
  границы сквозных контрфактов сняты.
- [x] `CHAT_STYLES_PLAN.md` — вынесен обратно в отдельный файл.
- [x] `ONBOARDING.md` — §3, §4, §5.9, §5.10, §6 обновлены.
- [x] `SOURCE_OF_TRUTH.md` — диалог добавлен в навигатор, карты
  пакетов/конфигов/тестов и §4/§9; ссылка на
  `CHAT_STYLES_PLAN.md` добавлена.
- [x] `DATA_DRIVEN_CORE_GAPS.md` — G-20…G-23, G-19 D3.2; статусы
  D3.2/D5.4/D6.2a–d/D6.3 выровнены с кодом.
- [x] `DATA_DRIVEN_CORE_PLAN.md` — P10: D3.2, D5.4, D6.2a–d, D6.3;
  открыт D6.4.
- [x] `TODO.md` — этот файл.
- [ ] `SCALING_ANALYSIS.md` — личный документ, в проектную иерархию
  не входит.

## 4. Регрессии и полный прогон

- [x] Точечные прогоны D0–D5.4 зелёные (`test_dialogue.py`,
  `test_d1_dialogue.py`, `test_d1_5_synthesis.py`, `test_d2_state.py`,
  `test_d3_comparison.py`, `test_d4_social.py`, `test_d5_discourse.py`,
  `test_d5_registers.py`, `test_d5_discourse_paragraph.py`).
- [x] `tests/test_d3_counterfactual.py` — 17 тестов, зелёные.
- [x] `tests/test_d6_grammar.py` — 16 тестов (условия, уступки,
  косвенная/прямая речь), зелёные.
- [x] `tests/test_d6_parse_beam.py` — 11 тестов (приоритет видов,
  ширина beam, детерминизм, канонический порядок), зелёные.
- [x] `tests/test_d6_paraphrases.py` — 32 теста (26 фраз корпуса),
  зелёные.
- [x] `tests/test_d6_disclosure.py` — 19 тестов, зелёные.
- [x] Диалоговый поднабор с новыми файлами: **279 тестов**, зелёный.
- [x] Полный прогон после корпуса парафраз: **1347 тестов**,
  зелёный (10:25).
- [ ] Коммит и пуш после ревизии документации.
- [ ] После коммита — прогнать `venv/bin/python -m campaign.dialogue.lint`
  и `git diff --check`.

## 5. Приоритет на ближайшую неделю

1. **D6.4** — цели разговора и действия (3–5 дней). **Здесь
   начинается текстовая RPG.**
2. **D7.0–D7.4** — текстовая RPG (5–7 дней после D6.4).
3. **D6.1** — аудит `lexicon.json`; расширение корпуса парафраз по мере
   роста грамматики.