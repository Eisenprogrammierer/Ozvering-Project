# Обучаемые агенты и RL-срез

**Статус:** текущая реализация. Это первый слой, а не полная миграция мира.
**Дата:** 2026-10-28
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
- `arena.py` — runtime активной арены: `ArenaAgent`, `ArenaMatch`,
  `run_duel_tick`, `check_capture`, формы `force`/`info` и UI-совместимый
  фасад (`force`, `energy_pool`, `defense`, `w_adopt`, `Q`, истории);
- `Action`, `Observation`, `Transition` — общий контракт агентского слоя.

`core41` не является полным миром: в нём нет кампании, здоровья, смерти,
организаций, реального планировщика и конверсий между формами работы.

### 1.2. `agents/` — политики и адаптивный агент

- `BDIPolicy` — BDI-политика с убеждениями/желаниями/намерениями и линейной
  TD-оценкой; обновляется online;
- `QTablePolicy` — табличный baseline;
- `RandomPolicy` — baseline для сравнения;
- `PolicyAgent` — совместимый мост к `simulation.Agent` для легаси-тестов и
  экспериментов; активные сцены его больше не создают;
- `agents.train` — CLI обучения на `DuelEnv`.

`PolicyAgent` сохраняет API `simulation.Agent` (`force`, `energy_pool`,
`sense`, `form_intention`, `rest_if_starving` и т.д.), поэтому старые тесты и
эксперименты можно запускать без переписывания. Активная арена использует
`ArenaAgent` и одну универсальную энергию.

---

## 2. Что изменилось в игре

Обе активные сцены работают на `core41`:

- `game_engine.MatchEngine` создаёт `ArenaMatch`; RL-сторона — `QTablePolicy`
  (Q-learning), BDI-сторона — `BDIPolicy`. `PolicyAgent`, `RLAgent` и
  типизированная энергия в игровой поток не входят;
- `ui/battlefield.Commander` создаёт `ArenaAgent`; человек управляет своей
  стороной, противник использует `BDIPolicy`;
- дуэль на тактическом поле идёт через `core41.run_duel_tick`, захват — через
  `core41.check_capture`;
- `UtilityAI` больше не создаётся в игровом потоке; он остаётся в
  `simulation.py` как baseline для `tests/test_canon.py` и исторических
  экспериментов.

`simulation.check_capture` сохраняет необязательные метки победителя
(`winner_rl`, `winner_ai`) для легаси-тестов. Активные сцены используют
`core41.check_capture`, а `simulation.py` не импортируется из `game_engine.py`
и `ui/battlefield.py`.

Обучение в игре:

- `ArenaMatch` обновляет обе политики после каждого такта;
- `BattlefieldModel` обновляет BDI-политику противника после дуэли;
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
`BDIPolicy` умеет `save/load`; обе политики — `state_dict/load_state_dict`.
`agents.load_policy(path)` читает `kind` из файла и возвращает `BDIPolicy`
или `QTablePolicy`.

Загрузить чекпойнт в активную сцену можно явно:

```bash
python3 main.py --checkpoint saves/bdi.json
python3 main.py --arena --checkpoint saves/bdi.json
python3 main.py --scene battlefield --checkpoint saves/bdi.json
```

```python
from agents import load_policy
from core41 import ArenaAgent

policy = load_policy("saves/bdi.json", seed=0)
agent = ArenaAgent("player", policy=policy, seed=0)
```

Старый `PolicyAgent` по-прежнему умеет `load_policy("saves/bdi.json")` для
легаси-моста. Автопоиска чекпойнта нет: путь передаётся явно. Оценка качества
загруженной политики и production-выбор чекпойнта — следующий шаг.

---

## 4. Контракт наблюдения и действия

```text
Observation: F/E свои и противника, давление, окно входа, время, формы
Action:      REST | WORK(form, fraction), form = force | info
Transition:  observation, action, reward, next_observation, done, next_actions
```

`ArenaAgent` — это автомат плюс политика. Он не хранит типизированную
энергию: `energy_pool` — проекция единственного `E`, а `form` выбирает канал
работы. `Policy`-объект должен уметь:

- `act(observation, actions, explore=True) -> Action`;
- `observe(transition) -> None`;
- `state_dict()/load_state_dict()` для сохранения.

Этого достаточно для подключения будущей нейросетевой политики без изменения
игрового цикла.

---

## 5. Ограничения и следующий шаг

- `simulation.py` всё ещё использует контекстные фазы `WATER/FIRE/EARTH`;
  это легаси-канон и baseline, но не активный игровой поток.
- `core41.arena` — дуэль/арена, а не мир; `campaign/world.py` не мигрирован.
- Нет здоровья, смерти, распада организации, реального времени и
  production-планировщика.
- Нет отдельного актора среды в новом runtime; флаг `with_env` сохранён в
  фасаде, но `env=None`.
- Коэффициенты логистики и единицы `F/E/W` остаются открытыми.
- Нет PyTorch-зависимости; текущие политики линейные/табличные.
- Нет автоматической загрузки production-чекпойнта в игру: путь передаётся
  явно через `--checkpoint`, автопоиска и оценки качества нет.
- `UtilityAI` не удалён: он нужен как воспроизводимый baseline.

Следующий инженерный шаг — перенести `core41` в кампанийный runtime, закрыть
здоровье/смерть и реальное время, затем подключить production-чекпойнт BDI к
активным сценам.
