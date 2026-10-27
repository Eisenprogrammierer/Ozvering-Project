# `docs`

Справочник собран из docstrings и примечаний к переменным. Номера строк относятся к версии до очистки кода.

## `docs/history/simulation_v2_prototype.py`

### Модуль

Строка 1.

СТАТУС: АРХИТЕКТУРНО ОТВЕРГНУТЫЙ ПРОТОТИП (сохранён для истории идей).
Нейтральная онтология IDEA/CAPITAL/FORCE, переменные capital/resistance и
профили сущностей были отвергнуты автором проекта как избыточные: всё, что они
описывают, выводится из IPO-архитектуры и двух метрик (энергия/сила).
Каноническая модель — simulation.py (в корне репозитория). Не использовать как основу развития.

### function `calc_efficiency`

Строка 46.

```python
def calc_efficiency(work_amount, current_capital)
```

Закон убывающей отдачи.
Слишком большое усилие относительно базы дает меньший эффект.

### method `Entity.apply_influence`

Строка 84.

```python
def apply_influence(self, target, action_type, work_amount)
```

Передача воздействия.

### class `UtilityEntity`

Строка 123.

Детерминированный агент, maximizing Expected Value based on simple heuristics.

### class `RLEntity`

Строка 155.

Q-Learning Agent. State includes own energy, opponent's dominant resistance.
