# TODO: что открыто и в каком порядке

> **Дата:** 2026-11-14. Основано на `DIALOGUE_NLG.md` §10,
> `CHAT_STYLES_PLAN.md` §8 и личном `SCALING_ANALYSIS.md`
> (не часть проекта).

## 0. Закрыто

### 0.1. D3.2 — контрфакты (закрыто 2026-11-14)

- **Грамматика.** `s_counterfactual` и `s_counterfactual_short` в
  `configs/dialogue/grammar.json`; лексемы `concept:if` (`COND`) и
  `part:would` (`PART`) в `lexicon.json`.
- **Движок.** `campaign/dialogue/counterfactual.py`
  (`CounterfactualEngine.with_facts` / `compare`). `_differences` —
  первый расходящийся шаг сверху вниз; при `None` с одной стороны —
  голова доказанной ветки.
- **Данные.** `configs/dialogue/counterfactual.json` (whitelist
  `belief`/`asset`/`at_war_with`/`considers_outlaw`, `max_steps: 2`),
  конструкции `cf_changed`/`cf_unchanged`/`cf_unknown` в
  `synthesis.json`.
- **Планы.** `cf_explain` (обобщённый: `relation`/`args`/`remove` из
  антецедента, `rel: "$rel"`) и `cf_explain_yesno` (`has_organ`) в
  `plans.json`.
- **Линтер.** `_counterfactual_problems`; `counterfactual` в
  `_ANSWER_TYPES` и `_DISCOURSE_KINDS`; `_plan_problems` пропускает
  `$`-значения в `remove`/`add`.

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

### 0.4. D6.2a — `не` в утверждениях и антецеденте (закрыто 2026-11-14)

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

## 1. Диалог: следующий шаг

### 1.1. D6.2c — `predicate_relations` (низкий риск, 1 день)

- В `world.json` добавить блок `predicate_relations`:
  `believe → considers_outlaw`, `fight → at_war_with`,
  `threaten → threatens`, `rule → leader`, `defend → protects`,
  `depend → depends_on`, `locate → located_at`, `begin → started_at`,
  `do → recent_work`, `know → …` (по факту).
- `_answer_counterfactual` резолвит `$rel` из `predicate_relations`,
  если ключ есть; иначе оставляет как есть.
- Линтер: `predicate_relations` ссылаются на существующие
  `world.relations`.
- Тесты: контрфакт по любому убеждению, не только
  `considers_outlaw`.

### 1.2. D6.2b — «то»-клауза контрфакта (низкий риск, 1 день)

- `s_counterfactual_consequent`: `[WH][COND][PART][S], [TO][S]` →
  `antecedent` + `consequent`.
- `CounterfactualEngine.compare` умеет проверять `consequent` как
  цель, если он задан.
- Лексема `concept:then` (`TO`) в `lexicon.json`.
- Тесты: «Что было бы, если бы Империя не издала эдикт, то
  Республика бы пала?».

### 1.3. D6.2d — условия, уступки, косвенная речь (высокий риск, 3–5 дней)

- +20–30 правил в `grammar.json`: `если … то`, `хотя …`, `несмотря
  на`, косвенная речь (`он сказал, что …`), цитаты.
- Детерминированный beam вместо «первого разбора».
- Корпус парафраз для проверки.
- Тесты: `tests/test_dialogue.py` (golden-разборы), новый
  `tests/test_d6_grammar.py`.

### 1.4. D6.3 — политика раскрытия и ложь (средний риск, 3 дня)

- `configs/dialogue/disclosure.json`: `honest/partial/evasive/lie`.
- `lie_probability` в `personas.json` как параметр персоны.
- Детерминированная ложь: при заданном seed и политике выбирается
  конкретная ложная пропозиция из допустимых.
- Трассировка помечает ложь.
- Тесты: `tests/test_d6_disclosure.py`.

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
  `added`. Полноценное «изменилось бы потому, что …» — D6.2/D6.4.
- **D3.2 whitelist.** 4 отношения; расширять по мере P8/P9.
- **D6.2a `s_counterfactual_neg`.** Дублирует `s_counterfactual`;
  удалить или оставить как документирующий алиас.

## 3. Документация

- [x] `DIALOGUE_NLG.md` — D3.1, D3.2, D5.1–D5.4 закрыты.
- [x] `CHAT_STYLES_PLAN.md` — вынесен обратно в отдельный файл.
- [x] `ONBOARDING.md` — §5.9, §6 обновлены.
- [x] `DATA_DRIVEN_CORE_GAPS.md` — G-20…G-23, G-19 D3.2.
- [x] `DATA_DRIVEN_CORE_PLAN.md` — P10: D3.2, D5.4 в закрытых.
- [x] `TODO.md` — этот файл.
- [ ] `SOURCE_OF_TRUTH.md` — добавить ссылку на `CHAT_STYLES_PLAN.md`
  как на отдельный документ.
- [ ] `SCALING_ANALYSIS.md` — личный документ, в проектную иерархию
  не входит.

## 4. Регрессии и полный прогон

- [x] Точечные прогоны D3.2/D5.1–D5.4/D6.2a зелёные.
- [ ] Запустить полный прогон (`venv/bin/python -m pytest -q`, ~15
  минут) после D6.2a. Если есть падения — чинить.
- [ ] Если полный прогон зелёный — коммит и пуш.
- [ ] После коммита — прогнать `venv/bin/python -m campaign.dialogue.lint`
  и `git diff --check`.

## 5. Приоритет на ближайшую неделю

1. **D6.2c** — `predicate_relations` (1 день).
2. **D6.2b** — «то»-клауза (1 день).
3. **D6.2d** — грамматика (3–5 дней).
4. **D6.3** — раскрытие и ложь (3 дня).
5. **D6.4** — цели разговора и действия (3–5 дней). **Здесь
   начинается текстовая RPG.**
6. **D7.0–D7.4** — текстовая RPG (5–7 дней после D6.4).