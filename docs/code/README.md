# Справочник по коду

> **Область действия.** Это карта текущего кода. Проектные решения и целевая
> модель — [`SOURCE_OF_TRUTH.md`](../SOURCE_OF_TRUTH.md) и
> [`WORLD_CORE_MODEL.md`](../WORLD_CORE_MODEL.md).

Документ собран из исходников до перехода к политике «код без комментариев и docstrings». Номера строк относятся к исходной версии. Актуальные изменения поведения описываются в тематических документах (`docs/CAMPAIGN_UI.md`, `docs/MODEL.md`, `docs/SUMMARY.md` и т.п.); этот справочник фиксирует назначение модулей и символов.

| Раздел | Файл |
|---|---|
| `agents`, `core41` | [AGENTS.md](../AGENTS.md) |
| `automata` | [automata.md](automata.md) |
| `campaign` | [campaign.md](campaign.md) |
| `docs` | [docs.md](docs.md) |
| `experiments` | [experiments.md](experiments.md) |
| `interaction` | [interaction.md](interaction.md) |
| `naming` | [naming.md](naming.md) |
| `organizations` | [organizations.md](organizations.md) |
| `root` | [root.md](root.md) |
| `systems` | [systems.md](systems.md) |
| `tests` | [tests.md](tests.md) |
| `ui` | [ui.md](ui.md) |
| `view` | [view.md](view.md) |

Inline-комментарии, перенесённые из кода, собраны в
[INLINE_NOTES.md](INLINE_NOTES.md).

## Состав

* модулей (`.py`): 220 — пересчитано при аудите документации;
* метрики docstrings/комментариев ниже заморожены по состоянию на момент
  генерации справочника и не пересчитывались (расходятся с текущим кодом):
  * docstrings определений: 1021;
  * строк-примечаний к переменным: 7;
  * inline-комментариев: 2115.

Карта анализа: [ANALYSIS.md](ANALYSIS.md) (разбор кода по модулям),
[DOCS_ANALYSIS.md](DOCS_ANALYSIS.md) (аудит документации).
