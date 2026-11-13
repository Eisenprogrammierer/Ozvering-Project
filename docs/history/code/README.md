# Справочник по коду (исторический срез)

> **Область действия.** Историческая карта кода ранней версии. Номера строк,
> перечни модулей и символов относятся к той версии и с текущим деревом не
> сверяются. Проектные решения и целевая модель —
> [`SOURCE_OF_TRUTH.md`](../../SOURCE_OF_TRUTH.md) и
> [`WORLD_CORE_MODEL.md`](../../WORLD_CORE_MODEL.md).
>
> Актуальные описания поведения — в тематических документах `docs/`
> (`MODEL.md`, `CONTENT.md`, `SUMMARY.md`, `CAMPAIGN_UI.md` и т.п.).

Документ собран из исходников ранней версии; номера строк относятся к той
версии. Этот справочник фиксирует назначение модулей и символов на момент
составления.

| Раздел | Файл |
|---|---|
| `agents`, `core41` | [AGENTS.md](../../AGENTS.md) |
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

* модулей (`.py`): 269 — пересчитано по текущему дереву;
* docstrings определений: 536;
* inline-комментариев: 4 — только функциональные директивы
  (`noqa`, `pragma`), остальные заметки перенесены в
  [INLINE_NOTES.md](INLINE_NOTES.md).

Карта анализа: [ANALYSIS.md](ANALYSIS.md) (разбор кода по модулям),
[DOCS_ANALYSIS.md](DOCS_ANALYSIS.md) (аудит документации).
