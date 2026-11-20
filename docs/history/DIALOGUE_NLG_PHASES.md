# Диалог: история фаз D0–D7

> **Статус:** исторический снимок. Полный поэтапный план и
> фактический прогресс закрытых фаз. Актуальная архитектура —
> [`../DIALOGUE_NLG.md`](../DIALOGUE_NLG.md).

## Поэтапный план и фактический прогресс

### D0. Контракты и лексикон — выполнен

Онтология, лексикон, грамматика, линтер, тесты на разбор.

### D1. Вопросы о мире (read-only) — ядро выполнено

`AgentKnowledge`, `InferenceEngine`, `Realizer`, `AnswerPlanner`,
`DialogueSession`, `Repl`. Вопросы о фактах, доказательства, незнание,
детерминизм, read-only.

### D1.5. Композиционный синтез — выполнен

Конструкции, морфология, fallback через `realization.json`.

### D2. Диалоговое состояние — выполнен для QUD, референтов, общего фонда, местоимений, эллипсиса и памяти партии

`ConversationState`, `DialogueMemory`, `DialogueMemoryStore`.
Сейв версии 3 хранит память по агентам.

### D3. Объяснения и контрфакты — закрыто

#### D3.1. Сравнения и расширенное «почему» — закрыто

- `configs/dialogue/comparison.json` — таблица сравнений.
- `_answer_comparison` — обработчик без `if a > b`: оператор и
  конструкция исхода берутся из данных.
- `max_premises` в `plans.json` — расширенное «почему» до N ближайших
  посылок (по умолчанию 1).
- `ComparisonSpec`/`ComparisonCatalog` в `model.py`.
- Линтер `_comparison_problems`.
- Тесты `tests/test_d3_comparison.py` — 16 тестов.

#### D3.2. Контрфакты — механизм и сквозной сценарий закрыты (2026-11-14)

- `campaign/dialogue/counterfactual.py`: `CounterfactualEngine`,
  `CounterfactualResult`, `Difference`.
- `CounterfactualSpec` + поле `counterfactual` в `DialogueCatalog`.
- `configs/dialogue/counterfactual.json` — whitelist
  `belief`/`asset`/`at_war_with`/`considers_outlaw`/`has_organ`,
  `max_steps: 2`, `outcomes` → `cf_changed`/`cf_unchanged`/`cf_unknown`.
- `_answer_counterfactual`, `_fact_from` в `answers.py`.
- Планы `cf_explain` (прямой NP-объект), `cf_explain_with`
  (PP-объект) и `cf_explain_yesno` (`have → has_organ`).
- `_counterfactual_problems` в `lint.py`; `_world_problems` проверяет
  `predicate_relations`; `_plan_problems` пропускает `$`-значения в
  `remove`/`add`; `counterfactual` в `_ANSWER_TYPES` и
  `_DISCOURSE_KINDS`.
- Грамматика `s_counterfactual`, `s_counterfactual_short`,
  `s_counterfactual_neg`, `s_counterfactual_consequent[_would]`,
  `s_counterfactual_past[_consequent]`; лексемы `concept:if` (`COND`),
  `part:would` (`PART`), `concept:then` (`TO`), `verb:issue`, `verb:fall`.
- Конструкции `cf_changed`/`cf_unchanged`/`cf_unknown` в
  `synthesis.json`.
- D6.2a: `negated: true` меняет `remove`/`add` местами.
- D6.2b: `consequent` («…, то …») становится целью сравнения.
- D6.2c: `world.predicate_relations` резолвит предикат в отношение;
  для `believe` удаляется исходный факт `belief`, а не derived
  `considers_outlaw`.
- Тесты `tests/test_d3_counterfactual.py` — 17 тестов: исходы,
  whitelist, read-only, `predicate_relations`, отрицание, consequent,
  битая ссылка в линтере.

**Вне объёма D3.2:** использование `differences` в тексте ответа
(«изменилось бы потому, что …») — открытый хвост D6.2; расширение
whitelist по P8/P9.

### D4. Речевые действия — закрыто

Акты, реакции, условия, эффекты, `commitments`, JSON-only расширение.
Тесты `tests/test_d4_social.py`.

### D5. Продвинутый синтез — D5.1, D5.2, D5.3, D5.4 закрыты

#### D5.1. Дискурсивный планировщик (1–3 хода) — закрыто

- `configs/dialogue/discourse.json` — `moves`, `patterns`,
  `connectives`.
- `DiscourseMove`, `DiscoursePattern`, `DiscourseCatalog` в `model.py`.
- `_discourse` в `answers.py`.
- `render_moves` в `realize.py`.
- Линтер `_discourse_problems`.
- Тесты `tests/test_d5_discourse.py` — 17 тестов.

#### D5.2. Автовыбор регистра по контексту — закрыто

- `configs/dialogue/style_context.json` — `enabled`, `hint_priority`,
  `hint_min_weight`, `rules`.
- `StyleEngine.resolve_for_context` — явный стиль → `persona.default_style`
  → правила по контексту и подсказка `style_hints` по убыванию
  `priority` → `styles.default`.
- Подсказка режима: `DialogueSession(senses=...)` читает факты
  здравого смысла, `Reading.weights`/`mode_weight` дают уверенность,
  а `hint_priority` (`40`) ставит подсказку между
  `default_official` (`10`) и отношениями (`50+`). Явный стиль и
  правила с большим приоритетом её перебивают; без базы фактов или
  при весе ниже `hint_min_weight` подсказка не применяется.
  Подсказка считается до разбора, поэтому неразобранная реплика
  («Ты дурак.») тоже выбирает тон уточнения, не меняя его содержания.
- `DialogueSession(style_id=None)` — авто-режим.
- Линтер `_style_context_problems`.
- Тесты `tests/test_d5_registers.py` — 19 тестов.
- Тесты `tests/test_d5_style_hints.py` — 31 тест.

#### D5.3. Агрегация, анафора и тема-рема — закрыто

- `discourse.connectives[].mode: "plain" | "clause"`.
- `discourse.connectives[].lowercase_glue` — для `clause` связка
  встраивается со строчной буквы: «…, потому что …».
- `discourse.patterns[].topic`.
- `Answer.data.reason_in_text` — причина уже в тексте ответа, ход
  `justify` пропускается (иначе она дублировалась).
- `discourse.anaphora` — `enabled`, `types`, `kinds`, `pronouns`,
  `min_length`.
- `_apply_anaphora` в `realize.py`.
- `_answer_entities_for_anaphora`/`_fallback_entities` в `answers.py`.
- Линтер `_anaphora_problems`.
- Тесты `tests/test_d5_discourse_paragraph.py` — 18 тестов (D5.3 и D5.4).

#### D5.4. Дискурсивная агрегация абзаца (4+ хода) — закрыто

Решение: **эволюционно**, без отдельного `paragraph_planner`.
`DiscoursePattern.topics: [...]` задаёт порядок абзаца; `_ordered_moves`
идёт `topics → topic → moves`, отбрасывает дубли и неизвестные темы;
линтер `_discourse_problems` проверяет, что тема входит в `moves`, и
ловит дубли.

Production-паттерн `explanation_detailed` помечен `detail: true` и
выбирается только по явной просьбе: «Подробнее» или «Почему?» как
уточнение к прошлому ответу. Обычный вопрос берёт
`explanation_basic`, поэтому `pattern_for("explanation", "")` не
подхватывает длинный паттерн и семантика «нет паттерна — нет
дискурса» сохраняется. Абзац объявляет `connectives: false`: ходы
идут друг за другом через точку, без повтора одной связки.

Ход `statement` берёт утверждение из `Answer.data`, `hedge_detail` и
`conclusion` — данные `synthesis.json` с регистровыми маркерами.
Повтор одинакового текста отбрасывается в `_build_moves`. Риски
отдельного planner зафиксированы в `TODO.md`.

### D6. Расширение и калибровка — частично закрыто

#### D6.2a. Отрицание в антецеденте — закрыто

- `part:not` в категории `NEG` (не `PART`), семантика `kind: neg`.
- Правила `np_neg_v_np`, `np_neg_v_np_adj`, `np_neg_v_pp` ставят
  `negated: true`; `semantics.flatten` читает `neg`.
- `_answer_counterfactual` при `antecedent.negated` меняет местами
  `remove` и `add` плана.
- Сквозной сценарий работает после D6.2c: предикат резолвится в
  отношение мира, поэтому отрицательный контрфакт не теряет подмену.
- Тесты — в `tests/test_d3_counterfactual.py`.

#### D6.2b. «То»-клауза — закрыто

- `concept:then` (`TO`); `s_counterfactual_consequent[_would]` и
  `s_counterfactual_past[_consequent]`; `s_assert_np_part_v*` для
  «Республика бы пала».
- `_answer_counterfactual` берёт `consequent` как цель сравнения;
  антецедент остаётся подменой фактов.
- Тесты: разбор и проверка consequent как цели.

#### D6.2c. `predicate_relations` — закрыто

- `world.json: predicate_relations` для `believe`, `befriend`, `fight`,
  `have`, `threaten`, `defend`, `depend`, `rule`, `locate`, `begin`,
  `do`. Значение — строка или объект `{relation, remove}`.
- `_predicate_mapping`, `_predicate_relation`, `_assertion_target`,
  `_nested_entity` в `answers.py`.
- Для derived-отношений (`believe → considers_outlaw`) `remove`
  указывает исходный факт `belief(...)`; иначе удаление derived-атома
  ничего не меняет.
- Линтер `_world_problems` проверяет `relation` и `remove`.
- Сквозные сценарии: `believe`, `have`, `fight` дают `changed`.

#### D6.2d. Условия, уступки, речь и beam — закрыто

- Лексикон: `concept:although` (`SCONJ`, «хотя/хоть»),
  `concept:despite` (`SCONJ`, «несмотря на/невзирая на»),
  `concept:that` (`COMP`, «что»), `quote:open`/`quote:close`
  (`QUOTE`/`QUOTE_END`), `verb:say` (`V`, «сказать»).
- `s_conditional`: `COND S TO S` → `kind: conditional` с
  `antecedent` и `consequent`.
- `s_concessive`: `SCONJ S S` → `kind: concessive` с `concession`
  и `clause`.
- `s_indirect_speech`: `NP V COMP S` → `kind: report`, `mode:
  indirect`, поля `speaker`, `predicate`, `body`.
- `s_direct_speech`: `NP V QUOTE S QUOTE_END` → `kind: report`,
  `mode: direct`; токенизатор сохраняет «…»/`"…"`, поэтому цитата
  не смешивается с косвенной речью.
- `configs/dialogue/parsing.json`: `beam_width`, `kind_priority`
  (порядок видов), `prefer_depth`. `ChartParser.parse_beam` сортирует
  разборы по этим данным, `parse_best` берёт первый; при равном виде
  сохраняется канонический порядок чарта, вероятностей нет.
  `DialogueSession._interpret` использует `parse_best`.
- `configs/dialogue/paraphrases.json`: корпус из 63 фраз
  (приветствие/прощание, запрос, yes/no, wh, утверждение с отрицанием,
  контрфакт, условие, уступка, косвенная/прямая речь) с ожидаемым видом
  и полями семантики. 11 записей происходят из базы фактов здравого
  смысла и помечены `"source": "commonsense"`; тест сверяет, что их
  текст есть в `speech_acts.jsonl` как `IsA`-факт.
- Тесты: `tests/test_d6_grammar.py` (16 тестов),
  `tests/test_d6_parse_beam.py` (11 тестов) и
  `tests/test_d6_paraphrases.py` (69 тестов), включая JSON-only
  расширение, детерминизм, приоритет видов, ширину beam, проверку
  корпуса и регрессию старого yes/no-разбора.
- D6.2d закрыт полностью; корпус можно расширять вместе с грамматикой.

#### D6.3. Политика раскрытия и ложь — закрыто

- `configs/dialogue/disclosure.json`: политики `honest`, `partial`,
  `withhold`, `evasive`, `lie`; исход политики — поле `outcome`,
  тексты — поля `prefix`/`text`/`yes`/`no`/`other`.
- `personas.json`: `disclosure.default`, `disclosure.on_topic` и
  `lie_probability ∈ [0, 1]`. Тема — отношение ответа (`relation` /
  `predicate` / `topic`) или план-источник.
- `AnswerPlanner._disclose` применяет политику только к информативным
  ответам (`yes/no/explanation/value/list/description/summary/located/
  started/last_works/entity`), не к социальным репликам.
- Ложь включается только при `lie_score < lie_probability`. Бросок —
  SHA-256 от `salt`, `run_id`, `speaker_id`, номера хода, темы и
  аргументов: одинаковые данные дают один и тот же результат, без
  статистики и скрытых эвристик.
- `Answer.data` хранит `disclosure`, `disclosure_topic`, `lied`,
  `lie_score`, `lie_probability`; для лжи/утаивания/уклонения также
  `truth_text`, `truth_kind`, `truth_relation`, `truth_args`.
  Читатель всегда может восстановить истину.
- Линтер `_disclosure_problems` проверяет исходы, тексты, ссылки
  персон на политики и диапазон `lie_probability`.

#### D6.4. Цели разговора и мост к действиям — сделано

- `configs/dialogue/goals.json` задаёт цели (`answer`, `social`,
  `action`), условие выбора `when` и шаги `answer`/`social`/`action`/
  `check`. `GoalPlanner` выбирает первую подходящую цель, шаги идут в
  объявленном порядке; проверки получают `done`/`blocked` только из
  явного словаря `checks`.
- `Intent` извлекается из готовой логической формы: вид, речевой акт,
  цель и явный `action_id`. Никаких вероятностей и скрытого выбора
  действия.
- `campaign/dialogue/bridge.py`: `ActionBridge` и `ActionResult`.
  `allow_actions=False` по умолчанию; при включении действие проходит
  публичный `available_actions` и уходит в
  `AutomataCampaign.perform` с целью из разбора.
- `DialogueSession(allow_actions=False, campaign=None)` добавляет
  `intent`, `plan_goal` и `act`. `ask`/`respond` остаются read-only
  независимо от флага: действие выполняется только явным `act`.
- `configs/dialogue/actions.json` — доменные псевдонимы действий;
  `ActionBridge.resolve` приводит псевдоним к id кампании, линтер
  `_action_problems` проверяет уникальность и наличие в лексиконе.
- Императивная грамматика: `s_imperative_v_np` и
  `s_imperative_v_np_pp` (`mood=imperative`); «Покажи силу», «Укрепи
  гарнизон», «Согласуй план», «Опубликуй эдикт», цель через PP
  («Покажи силу против Республики»). Синонимы императивов —
  «Продемонстрируй силу», «Усиль гарнизон», «Утверди план», «Издай
  эдикт».
- Данными добавлены императивы имперских действий: «Назначь врага»
  (`enemy_of_state`), «Созови собор» (`imperial_church`), «Разверни
  госпитали» (`field_medicine`), «Защити шифры» (`cipher_protection`),
  «Проведи парад» (`guard_parade`), «Очисти корпус» (`officer_purge`),
  «Устрой диверсию» (`abwehr_sabotage`), «Вскрой сеть» (`cyber_osint`),
  «Открой больницы» (`church_hospitals`).
- Тесты: `tests/test_d6_planner.py` (13), `tests/test_d6_bridge.py`
  (12) и `tests/test_d6_actions.py` (13) — данные целей, проверки,
  запрет по умолчанию, реальное действие, цель, бюджет, read-only
  `ask`, псевдонимы, императивы и разбор каждой объявленной фразы.
- Открыто: дальнейшее расширение доменных псевдонимов по мере роста
  контента; текстовый UI — D7.0–D7.4 (сделано).

**D6.1. Аудит лексикона.** На момент аудита проверены 367 лексем
(после расширения корпуса — 388): единственный псевдоним,
дублировавший собственную форму, — `дела` у `concept:affairs` (уже
есть в `gen`/`nom_pl`/`acc_pl`); он удалён.
Полезные псевдонимы вроде `имперцы` у `faction:red` сохранены. В
`lint_catalog` добавлена проверка «псевдоним дублирует форму», так что
данные с таким дублем больше не проходят линтер. Тесты —
`tests/test_d6_lexicon.py` (4).

### D7. Текстовая RPG — D7.0–D7.4 сделано

- `campaign/dialogue/console.py`: `TextGame` и `ConsoleEntry`.
  Реплика либо уходит в `DialogueSession.act`, если у намерения есть
  `action_id` или это речевое действие при `allow_actions=True`, либо
  в read-only `respond`.
- История реплик и откат: снимок `ConversationState` (вместе с
  памятью) и `AutomataCampaign.save_snapshot`/`load_snapshot`; откат
  возвращает и диалог, и кампанию, включая состояние ГСЧ.
- Подсказки детерминированы: фразы из `actions.json`, отфильтрованные
  публичным `available_actions`; порядок — порядок данных.
- `configs/dialogue/console.json`: команды (`help`, `history`, `undo`,
  `hint`, `sense`, `style`, `look`, `quit`), сообщения, псевдонимы
  команд (включая `/смысл → sense`, `/стиль` и `/регистр → style`) и
  `history_limit`. Линтер `_console_problems` проверяет обязательные
  ключи и ссылки.
- `/смысл <фраза>` (`/sense`) — read-only подсказка по базе фактов
  здравого смысла: акты, режимы и стиль из `schema.json.style_hints`.
  Пустая фраза, недоступная база и нераспознанный текст дают отдельные
  сообщения; мир, откат и история не меняются.
- `/style` (`/стиль`, `/регистр`) — текущий регистр, режим
  авто/вручную и причина выбора из `StyleDecision`; мир не меняется.
- CLI: `python -m campaign.dialogue.textgame --allow-actions`.
- Тесты: `tests/test_d7_console.py` (24) — история, откат состояния и
  кампании, подсказки, команды, `/смысл`, `/style`, лимит истории,
  детерминизм, линтер.
- **D7.1. Речевые действия как действия.** `social.json` получил
  поле `interaction`: `command → social_command`,
  `promise → social_promise`, `threat → social_threat`,
  `offer → social_offer`, `apology → social_apology`. Сами
  взаимодействия — данные `character_interactions` в
  `configs/campaigns/base/automata_defaults.json` и
  `lore_factions.json`. `SocialEngine` проверяет `has_authority`
  (приказ), `trusts` (обещание/предложение) и `has_leverage` (шантаж);
  отказ по гейту не трогает мир. `ActionBridge.perform_social`
  вызывает публичный `perform_character_interaction` только при
  `allow_actions=True`, `DialogueSession.act` пишет эффект реакции в
  `ConversationState`. `has_leverage` выводится из открытых
  обязательств (`creditor=player`, `debtor=собеседник`), виды рычага
  заданы в `world.json.leverage.kinds`, а акт `blackmail`
  переиспользует interaction `social_threat`.
- Тесты: `tests/test_d7_social.py` (25) — пять interactions, гейты
  authority/trusts/leverage, отказ без кампании и при выключенных
  действиях, TextGame-маршрутизация, откат, линтер.
- **P5. Проекция действий, лексикон и новые речевые акты.**
  `campaign/dialogue/projection.py` собирает реестр `actions.json` из
  любого каталога `ActionSpec` (`id`, `label`, `aliases`, явные
  `phrases`); ручные записи остаются override, дубликат фразы не
  перехватывается. Проекция opt-in и не меняет `load_dialogue` по
  умолчанию. Мирские действия Агоры получили псевдонимы и императивы
  («Обними его», «Поцелуй меня», «Научи меня», «Утешь его»,
  «Попроси его», «Принеси жертву», «Прими закон», «Сыграй на улице»,
  «Успокой улицу», «Сошлись на норму»). Лексикон получил местоимение
  «я», существительные места/закона/жертвы/песни и глаголы контакта,
  обряда, права, искусства и обучения; грамматика — правило
  `s_imperative_v_pp`. `social.json` расширен до 13 актов: `flirt`,
  `confess`, `console`, `bless`, `oath`, `beg_pardon`, `propose`,
  `insult`.
  Для всех 13 актов есть планы ответа, поэтому read-only `respond`
  («Признаюсь в любви», «Ты дурак») даёт `kind: social` и реакцию, а не
  «не знаю». Текст ответа берётся из конструкции выбранной реакции
  (`social_resent`, `social_reject`, …), а не из первого попавшегося
  `social_*`; `insult` — разговорный акт без interaction и не меняет
  мир. Линтер `_verb_path_problems` требует путь в реестре для каждого
  глагола `act_*` и правило грамматики для каждого речевого акта.
  Тесты: `tests/test_dialogue_projection.py` (10),
  `tests/test_d7_social_acts.py` (21) и
  `tests/test_d6_flexible_grammar.py` (12).
- **P5. Реестр типов ответа.** `configs/dialogue/answer_kinds.json`
  связывает `plan.answer.type` с обработчиком. `AnswerPlanner` берёт
  имя метода из реестра (`answer_handler_name`), поэтому новый тип
  может ссылаться на generic `entity`/`relation`/`value`/`list`/
  `explain`/`summary` без нового Python-метода. Линтер
  `_answer_kind_problems` проверяет, что каждый тип плана
  зарегистрирован, а каждый handler реализован. Тесты:
  `tests/test_answer_registry.py` (9).
- **P5. Адаптеры мира.** `campaign/perception.py` расширен протоколом
  `WorldView` (`entities`, `relations`, `perceived`, `believed`,
  `recent_work`, `unknown`) и тремя мостами: `AutomataCampaignAdapter`,
  `WorldEngineAdapter`, `SceneAdapter`; `adapter_for` выбирает мост по
  форме источника. `configs/dialogue/world.json.adapters` объявляет
  реализации, а `factions` остаётся необязательным override. Тесты:
  `tests/test_world_adapters.py` (11).
- **P5. Живой мост действий.** При `allow_actions=True`
  `ActionBridge` проходит путь `Intent → ActionSpec → validate → Work`.
  Объявленное действие (`source: declared`) выполняется через
  `AutomataCampaign.perform` или `WorldEngine.execute`, а его работа
  собирается `build_spec_work`. Свободное действие (`source:
  improvised`) собирается `improvised_work` только при явном
  `allow_improvised=True` и требует существующую форму и совместимый
  адресат. `ActionResult` хранит `work` и `trace` (глагол, акт, форма,
  адресат, источник). `allow_actions=False` остаётся умолчанием.
  Тесты: `tests/test_d6_bridge.py` (18).
- **D7.2. Пространство и перемещение.** `configs/dialogue/movement.json`
  задаёт стартовый узел для каждой стороны, явные места
  `organ:<side>:<node>` и `noun:capital`, пороги
  `near/middle/far` и сообщения. `campaign/dialogue/movement.py`
  (`MovementGuide`, `MoveResult`) строит маршрут по `MetricGraph`
  **стороны игрока**: разговор с синим не переносит красного игрока в
  чужую геометрию. Путь и расстояние не хранятся в данных — их
  считает P6.5; текст показывает «рядом/далеко» и весь маршрут.
  `DialogueSession.travel` меняет только `ConversationState.location`
  и лишь при `allow_actions=True`; read-only возвращает план с
  `actions_disabled`. Фразы «Иду к Абверу», «Отправляюсь в столицу»
  дают `kind: move` (правила `s_move_*`), `TextGame` отдаёт
  `ConsoleEntry(kind="move")`, откат восстанавливает локацию.
- Тесты: `tests/test_d7_movement.py` (17) — данные и линтер,
  разбор, маршрут и band, сторона игрока, read-only, перемещение,
  `already`/unknown/no geometry/no path/no start, TextGame и откат.
- **D7.3. Время и ходы.** `configs/dialogue/time.json` задаёт
  `wait_seconds` (один ход), `cycle_seconds`, фазы
  `noun:morning/evening/night`, направления `up/down/reset` и
  сообщения. `campaign/dialogue/timeflow.py` (`TimeGuide`,
  `TimeResult`) двигает `AutomataCampaign.advance_time` только при
  `allow_actions=True`: «Жду» — фиксированное игровое время,
  «Жду до утра/вечера/ночи» — ближайшая фаза (при том же темпе
  пересчитывается реальная длительность), «Ускоряю/Замедляю/
  Сбрасываю» — `speed_up/slow_down/reset_speed`. Read-only
  возвращает план и не трогает кампанию; завершение кампании во
  время ожидания отмечается `finished_during`. `TextGame` отдаёт
  `ConsoleEntry(kind="wait"/"speed")`; откат восстанавливает время
  и темп.
- Тесты: `tests/test_d7_time.py` (20) — данные и линтер, разбор,
  read-only, `advance_time` и множитель темпа, фазы и следующий
  цикл, лимиты темпа, TextGame и откат.
- **D7.4. Нарративный слой.** `configs/dialogue/narrator.json`
  задаёт `limit`/`max_limit`, `visible_only`, `line_prefix`, полосы
  `severity_bands`, подписи `forms`/`outcomes`, шаблоны `kinds`
  (`story/work/organ/automaton/character`), `fallback` и сообщения.
  `campaign/dialogue/narrator.py` (`Narrator`, `Narration`,
  `NarrationEntry`) читает только `story_events`,
  `log` и `events`: видимые story-события, работы из богатого `log`
  (work-события из `events` пропускаются как дубль), прочие события
  по видам; неизвестный вид уходит в `fallback`. Сортировка —
  `(turn, source_priority, index)`, лимит оставляет последние
  события, лимит зажимается `max_limit`. `DialogueSession.narrate`
  и `TextGame.look` read-only; команды `/look`, `/l` и
  `/осмотреться` в `console.json`. Кампания, BDI и ГСЧ не меняются.
- Тесты: `tests/test_d7_narrator.py` (18) — данные и линтер,
  видимость, работы из `log` без дубля, виды событий, fallback,
  важность/формы/исходы, лимит и хронология, пустота/no campaign,
  read-only, `/look` и откат.
- D7.1 закрыт полностью: `has_leverage` выводится из открытых
  обязательств, акт `blackmail` проходит гейт и переиспользует
  `social_threat`.

Остальное открыто:

* Больше конструкций; расширение корпуса парафраз.
* Больше типов вопросов и тем.
* Замер покрытия и устранение провалов разбора.
* Производительность и лимиты.
* Использование `differences` в тексте контрфакта («изменилось бы
  потому, что …»).
* Императивные фразы и псевдонимы действий расширяются данными;
  текстовая RPG D7.0–D7.4 закрыта.

---
