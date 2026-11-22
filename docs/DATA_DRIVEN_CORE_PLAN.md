# Data-Driven ядро: открытый план

> **Статус:** активный план только по незакрытым фазам. P0 (схемы целых
> файлов, ссылки, golden-снимок) закрыт; ниже он оставлен как итог, чтобы
> было видно, что именно проверяется. Полный план P0–P10, история флагов
> и закрытые этапы — в
> [`history/DATA_DRIVEN_CORE_PLAN_FULL.md`](history/DATA_DRIVEN_CORE_PLAN_FULL.md).
> Открытые GAP-пункты — [`DATA_DRIVEN_CORE_GAPS.md`](DATA_DRIVEN_CORE_GAPS.md).

## 1. P0. Схемы целых файлов (закрыто)

Исполняемые блоки (`effects`, `conditions`, `requires`, `organ`,
`subfaction`, `automaton`) и целые файлы (`bdi`, `work`,
`lore_factions`, `automata_defaults`, `campaign_template`, `event`)
описаны JSON Schema в `configs/schemas/`. `campaign.content_schema`
валидирует файлы, `campaign.content_lint` добавляет семантику:

- [x] Строгие схемы без `additionalProperties`: опечатка в поле — ошибка.
- [x] Проверка ссылок `organ_id`, `target`, `requires.used_actions`,
  `essence`/`hints.intention_essence`, `subfaction_id`, `automaton_id`,
  категорий событий и `playwright.event_id`.
- [x] `configs/campaigns/*_campaign.json`, `configs/systems/events.json`
  и `playwright.json` входят в `DEFAULT_PATHS` линтера.
- [x] Golden-снимок кампании: `tests/test_campaign_golden.py` и
  `tests/fixtures/golden/empire_seed13.json`.
- [x] `jsonschema` остаётся необязательным: без него линтер работает,
  а схемы используются как whitelist ключей.

## 2. P4b. Работа в дневном мире

- [ ] Перевести `WorldEngine.execute()` на общий
  `campaign/work.py` → `handlers.py` → `WorkReport` → `apply_report`.
- [ ] Открыть реестр `payload` для данных.
- [ ] Подключить квинтуплы `configs/naming/interactions`.
- [ ] Считать шанс из контекста получателя, а не пары активов.

## 3. P6. Подсистемы и органы

Код закрыт: дерево `parent_id`, собственные `scales` органа, тик,
эффекты, условия, события и снимок. Контент кампании описывает 42 органа,
20 исполняемых автоматов (фракции, подфракции и все виды органов,
включая `organ.support`). Дальнейшее расширение — только данные:
новые органы и работы не требуют правок рантайма.

## 4. P9. Контент и калибровка

- [x] `belief_predicates` — 131 запись (ориентир 60–90).
- [x] `intention_essences` — 99 записей (ориентир 45–60), работы
  ссылаются на сути через `hints.essence`/`hints.intention_essence`.
- [x] Органы и работы: 42 органа и 65 работ, автоматы фракций,
  подфракций и ключевых органов, включая `organ.support`.
- [x] События: 97 записей в 12 категориях, включая шесть
  событий-порогов по активам (`legitimacy`, `supply`, `morale`, `myth`,
  `anxiety`, `is_compromised`). События по-прежнему ничего не меняют.
- [x] Калибровка: 72 хода × 4 шаблона × 3 seed (7, 13, 29). Ни одна
  фракция не теряет персонажа до 10-го хода и не застревает в
  равновесии: разброс оценок по ходам 0.03–0.22, финальный разрыв
  0.23–0.36. Скрипт:
  `experiments/calibrate_automata_outcomes.py`.

Критерии приёмки:

- линтер чистый, `pytest -q` зелёный;
- два прогона с одним seed дают идентичный снимок;
- нет ссылок на несуществующий орган, предикат или суть;
- у каждой фракции есть работа на каждую лорную подцель.

## 5. P10. Диалог

Открытые задачи — в [`TODO.md`](TODO.md), история фаз — в
[`history/DIALOGUE_NLG_PHASES.md`](history/DIALOGUE_NLG_PHASES.md).
Новые стили, связки, сравнения
и речевые акты добавляются данными, без ветвлений по id в Python.

## 6. Инварианты

- 16 потребностей, 15 делений, 12 черт не меняются.
- Событие ничего не производит и не порождает другое событие.
- Старые сейвы читаются аддитивно.
- Python знает контракты, но не содержание мира.
