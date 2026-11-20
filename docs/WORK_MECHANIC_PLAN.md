# Единая механика работы: статус и остаток

> **Статус:** фазы 1–5 закрыты для арены и кампании автоматов; открыт
> дневной мир (4b) и часть контентного хвоста. Полный план с фазами,
> флагами и миграционной таблицей — исторический документ
> [`history/WORK_MECHANIC_PLAN_FULL.md`](history/WORK_MECHANIC_PLAN_FULL.md).
> Исходный GAP-анализ — [`history/WORK_MECHANIC_GAP.md`](history/WORK_MECHANIC_GAP.md).

## 1. Действующий конвейер

```text
capability/interaction
  → campaign/work.py        (WorkPlan → core41.types.Work)
  → campaign/handlers.py    (правило получателя по form/when)
  → WorkReport              (stored/loss/entropy, trace)
  → campaign/effects.py     (apply_report — единственный вход)
```

- 65 работ и 17 взаимодействий идут одним путём.
- `core41.arena.resolve_work` вызывает `_receive_channel` и возвращает
  `WorkReport`; дублирующего приёма в `ArenaAgent` нет.
- `form` — канал, а не отдельная энергия.
- Правила получателя — JSON в `configs/campaigns/base/handlers/`.
- `perform()` и `perform_*` остались тонкими фасадами для старых вызовов.

## 2. Что осталось

- [ ] Дневной мир: перевести `WorldEngine.execute()` с отдельного
  конвейера `immediate/success/failure` на общий `Work`-путь.
- [ ] Реестр `PAYLOAD_KINDS`: открыть для данных вместо Python-списка.
- [ ] Квинтуплы `configs/naming/interactions`: подключить к обработчикам.
- [ ] Шанс работы: считать из контекста получателя, а не только из пары
  активов блока `chance`.
- [ ] Превью действий мира: перевести с `success_effects`/`failure_effects`
  на `Work`/`trace`.
- [ ] Калибровочные прогоны до/после для дневного мира.

## 3. Инварианты

- У работы нет встроенного эффекта; эффект вычисляет обработчик.
- Энергия одна; `stored + loss + entropy == amount`.
- Старые сейвы, UI и детерминизм не ломаются.
- 16 потребностей и лорный контент не меняются ради миграции.
