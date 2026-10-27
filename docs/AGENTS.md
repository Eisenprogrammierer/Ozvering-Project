# Обучаемые агенты и RL-срез

**Статус:** текущая реализация. Это первый слой, а не полная миграция мира.
**Дата:** 2026-10-27
**Связанные документы:** [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md),
[`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md),
[`MODEL.md`](MODEL.md).

---

## 1. Что уже работает

В коде появились два независимых, но совместимых слоя.

### 1.1. `core41/` — дуэльный срез целевой модели

`core41` реализует минимальный вертикальный срез 4-2-1:

- `Work` — работа `{amount, form, payload, duration}`; `form` — канал, а не
  тип энергии;
- `Automaton` — `I/O/H/S/F/E/W` с одной универсальной энергией;
- `DuelWorld` — два автомата, обработчики, давление, окно входа,
  логистическая вероятность успеха;
- `DuelEnv` — Gym-подобный интерфейс `reset/step` для обучения;
- `Action`, `Observation`, `Transition` — общий контракт агентского слоя.

`core41` не является полным миром: в нём нет кампании, здоровья, смерти,
организаций, реального планировщика и конверсий между формами работы.

### 1.2. `agents/` — политики и адаптивный агент

- `BDIPolicy` — BDI-политика с убеждениями/желаниями/намерениями и линейной
  TD-оценкой; обновляется online;
- `QTablePolicy` — табличный baseline;
- `RandomPolicy` — baseline для сравнения;
- `PolicyAgent` — мост к текущему `simulation.Agent`; его использует арена;
- `agents.train` — CLI обучения на `DuelEnv`.

`PolicyAgent` сохраняет API `simulation.Agent` (`force`, `energy_pool`,
`sense`, `form_intention`, `rest_if_starving` и т.д.), поэтому UI и
`game_engine.py` не пришлось переписывать целиком.

---

## 2. Что изменилось в игре

Активный противник в `game_engine.py` и `ui/battlefield.py` — `PolicyAgent`.
`UtilityAI` больше не создаётся в игровом потоке; он остаётся в
`simulation.py` как baseline и используется историческими экспериментами и
`tests/test_canon.py`.

`simulation.check_capture` получил необязательные метки победителя
(`winner_rl`, `winner_ai`). Значения по умолчанию сохранены для легаси-тестов;
арена передаёт `winner_ai="AI"`.

Обучение в игре:

- `MatchEngine` вызывает `PolicyAgent.observe_reward(...)` после такта;
- `BattlefieldModel` делает то же после дуэли;
- награда — изменение силы и энергии, а не внешняя команда.

Это online-обучение на коротких партиях. Оно не заменяет офлайн-тренировку и
не гарантирует сильную политику.

---

## 3. Как обучить политику

Из корня репозитория:

```bash
venv/bin/python -m agents.train --episodes 500 --seed 0
```

С сохранением весов:

```bash
venv/bin/python -m agents.train --episodes 2000 --seed 0 --out saves/bdi.json
```

CLI печатает JSON со статистикой (`wins`, `losses`, `draws`, `win_rate`).
`BDIPolicy` и `QTablePolicy` умеют `save/load` через `state_dict()`.

Загрузить веса в агента можно так:

```python
from agents import BDIPolicy, PolicyAgent

agent = PolicyAgent()
agent.policy = BDIPolicy()
agent.load_policy("saves/bdi.json")
```

Автоматическая загрузка чекпойнта в игру пока не включена: это следующий шаг,
после появления стабильного формата и оценки качества.

---

## 4. Контракт наблюдения и действия

```text
Observation: F/E свои и противника, давление, окно входа, время, формы
Action:      REST | WORK(form, fraction)
Transition:  observation, action, reward, next_observation, done, next_actions
```

`Policy`-объект должен уметь:

- `act(observation, actions, explore=True) -> Action`;
- `observe(transition) -> None`;
- `state_dict()/load_state_dict()` для сохранения.

Этого достаточно для подключения будущей нейросетевой политики без изменения
игрового цикла.

---

## 5. Ограничения и следующий шаг

- `simulation.py` всё ещё использует контекстные фазы `WATER/FIRE/EARTH`;
  `PolicyAgent` работает поверх этого легаси-моста.
- `core41` — дуэль, а не мир; `campaign/world.py` не мигрирован.
- Нет здоровья, смерти, распада организации, реального времени и
  production-планировщика.
- Коэффициенты логистики и единицы `F/E/W` остаются открытыми.
- Нет PyTorch-зависимости; текущие политики линейные/табличные.
- `UtilityAI` не удалён: он нужен как воспроизводимый baseline.

Следующий инженерный шаг — сделать `core41` runtime-ом кампании, затем
подключить `PolicyAgent` к её циклам и только после этого обучать
production-модель.
