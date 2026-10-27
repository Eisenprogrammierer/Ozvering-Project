# Процесс разработки (кратко)

Документ отвечает на процессные вопросы ревью (пункт D5) и фиксирует уже
сложившуюся практику. Правки механики/архитектуры описываются в
[`docs/MODEL.md`](docs/MODEL.md), воспроизводимая базовая линия — в
[`docs/BASELINE.md`](docs/BASELINE.md).

## Язык и сообщения коммитов

* Сообщения коммитов — **на русском**. Англоязычные/стандартизованные (Conventional
  Commits) **не требуются**.
* Рекомендуемый вид первой строки: `<тип>: <краткая суть>`. Используемые типы (по
  фактической истории): `docs`, `refactor`, `measure`, `test`, `chore`, `fix`,
  `ci`, `arch`. Тип — ориентир, а не жёсткое правило.
* В теле коммита — что и зачем, ссылки на пункты ревью/`TODO.md`, и как проверено.

## `CHANGELOG`

* **Не ведётся** (проект пока рано вести журнал изменений). Роль журнала
  выполняют `git log`, [`docs/BASELINE.md`](docs/BASELINE.md) и раздел «Журнал
  правок» заметки ревью (до её переноса в `TODO.md`).

## Ветки и согласованность параллельных работ

Параллельные ветки (в т.ч. агентские `qwen-code…`, `review-…`) согласуются через
**единую точку правды и проверки**, а не через устные договорённости:

* **Канон — `simulation.py`.** Модель меняется только здесь; документация
  (`MODEL.md`, `BASELINE.md`, `README.md`) синхронна коду.
* **`game_engine.py` — отдельный слой наблюдения**, использует только публичное
  API `simulation.py` и модель не изменяет (см. `GAME_ENGINE_CHANGES.md`).
* **CI** ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) на каждый push/PR
  компилирует ядро/GUI/эксперименты и запускает `pytest`. Расхождения «доки ↔ код»
  ловит `tests/test_docs_sync.py`.
* **PR-чек-лист** ([`.github/pull_request_template.md`](.github/pull_request_template.md))
  фиксирует обязательные проверки (канон не изменился, синхронность констант,
  детерминизм, отражение в доках).
* Слияние — через PR с прогоном CI; канонический результат (`run_batch(10)` =
  RL 1 / UtilityAI 9 / без захвата 0) должен сохраняться либо изменение
  обосновывается и вносится в `BASELINE.md`.

## Код и документация

* В Python-файлах **нет комментариев и docstrings**. Исключение — исполняемый
  shebang в standalone-скриптах.
* Описание модулей, классов, функций и переменных переносится в
  [`docs/code/`](docs/code/README.md). Inline-заметки, удалённые из кода,
  попадают в [`docs/code/INLINE_NOTES.md`](docs/code/INLINE_NOTES.md).
* Новая механика, контракты и ограничения описываются в тематических
  документах (`MODEL.md`, `BASELINE.md`, `CAMPAIGN_UI.md` и т.п.), а не рядом
  с кодом.
* Форматирование — `black --line-length 79`; стиль — `pycodestyle` с
  настройками из `setup.cfg`. Исключения `E402`, `E203`, `W503` зафиксированы
  из-за bootstrap-импортов в экспериментах и совместимости с `black`.

## Перед отправкой PR

```bash
black --line-length 79 $(git ls-files '*.py')
python3 -m pycodestyle $(git ls-files '*.py')
python -m compileall -q simulation.py warfare.py game_engine.py main.py ui view automata interaction organizations experiments tests
pytest -q
```

Полный чек-лист — в `.github/pull_request_template.md`.
