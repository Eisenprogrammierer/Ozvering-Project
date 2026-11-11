# Как играть, обучать и контрибьютить

Практическое руководство по текущему состоянию проекта. Канон онтологии и
границы реализации — в [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md); формулы и
константы — в [`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md) и
[`ALGORITHMS.md`](ALGORITHMS.md). Если вы только входите в проект и ищете
«что, где, как, зачем» по конкретной потребности, начните с
[`ONBOARDING.md`](ONBOARDING.md).

---

## 1. Как играть

### 1.1. Установка и запуск

Нужен Python 3 и виртуальное окружение из корня репозитория:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pytest, pycodestyle
```

Основная точка входа — `main.py`. Без флага открывается современный
кампанийный клиент `view/`:

```bash
python3 main.py                  # кампания (современный клиент)
python3 main.py --classic        # легаси-слой ui/
python3 main.py --arena          # только арена
python3 main.py --automata       # редактор автоматов
python3 main.py --fullscreen     # полноэкранный режим
```

Полезные флаги: `--checkpoint PATH` (загрузить политику),
`--list-checkpoints` (показать найденные чекпойнты без окна),
`--speed 1|2|4|8|16` и `--no-auto-pause` (арена), `--sickness 0..1`
(начальная болезнь), `--health-factors aging=1.5,illness=2`
(множители здоровья).

`-m` принимает имя модуля через точку, а не путь. Команды
`python3 -m campaign/world` и `python3 -m core41/arena` завершаются ошибкой
`No module named ...`: слэш — разделитель каталогов, а не пакетов.
`campaign/world.py` и `core41/arena.py` — библиотеки, поэтому корректные
`python3 -m campaign.world` и `python3 -m core41.arena` печатают подсказку.
Запуск: `python3 main.py --view` (мир) и `python3 main.py --arena` (арена);
справка и демо ядра — `python3 -m core41` и `python3 -m core41 --demo`.

### 1.2. Первые шаги в кампании

1. В меню создайте героя по биографии или выберите готового.
2. Выберите структуру и должность. Доступные действия видны все; у
   недоступных показана причина (нет полномочий, ресурса, уровня или
   подходящей цели).
3. Каждый день у героя есть бюджет действий (`actions_left`). Действие
   тратит энергию и ресурсы; кнопка «Завершить день» переводит сутки.
4. Мир живёт сам: узлы и персонажи действуют по своим интересам, а
   отложенные намерения исполняются по слотам внутри дня.
5. Следите за `standing` (репутация), легитимностью структуры, здоровьем
   `H`, болезнью и силой `F`. Низкая репутация или легитимность приводит к
   смене роли, а не к мгновенному поражению; смерть наступает при
   `force <= 0`, а здоровье и болезнь — условия, которые ведут к падению
   силы.
6. Легитимность — опора организации: ниже порога смены роли она эродирует
   связность, глубже — силу; пустая казна ускоряет эрозию. Здоровая
   легитимность и казна постепенно возвращают шкалы, поэтому запущенный
   кризис можно остановить, но не игнорировать.

Карьера включает повышение, перевод, увольнение и уход по собственному
желанию. Потеря должности без замены в `CampaignEnv` считается нейтральным
финалом, а не поражением.

### 1.3. Время, фон и сохранения

- В активном окне дни идут по кнопке «Завершить день».
- В фоне реальные секунды копятся в `CampaignClock`
  (`SECONDS_PER_DAY = 120`) и переводятся в ограниченный догон
  (`MAX_CATCHUP_DAYS = 7`). Внутри суток часы открывают слоты
  `0..SLOTS_MAX`, поэтому отложенные намерения и ходы автономных узлов
  срабатывают не только на границе дня.
- Авто-пауза включается при смерти, критическом здоровье/болезни,
  завершённом сюжете и отсутствии должности.
- После загрузки оффлайн-догон ограничен `saved_at` и `max_offline_days`.
- Сохранения лежат в `saves/`. Этот каталог не коммитится.
- Формат сохранения версионирован (`SAVE_VERSION = 2`). Старые снимки
  мигрируют аддитивно: получают контейнеры `node_strategy_state` и
  `environment_plan`, не теряя остальных полей. Файл будущей версии
  загружается как есть с предупреждением в логе, поэтому откат сборки не
  уничтожает сейв.

### 1.4. Арена и чекпойнты

Арена запускается отдельно (`python3 main.py --arena`) или из кампанийного
клиента. Политики загружаются из `checkpoints/` автоматически: сначала
`best.json`, затем `latest.json`, затем самый свежий `*.json`. Явный
`--checkpoint` важнее автопоиска, `--no-auto-checkpoint` отключает его.

Если файл повреждён или имеет неподдерживаемую версию, он пропускается;
игра не падает. Проверить кандидатов можно командой:

```bash
python3 main.py --list-checkpoints
```

---

## 2. Как обучить политику

### 2.1. Базовый цикл

Обучение запускается модулем `agents.train` из корня репозитория:

```bash
venv/bin/python -m agents.train --episodes 500 --seed 0
```

По умолчанию используется `ArenaEnv` — та же среда, что активная арена
(`force`/`info`, `TREAT`, захват). Горизонт арены — 2000 шагов. Для раннего
дуэльного среза:

```bash
venv/bin/python -m agents.train --episodes 500 --seed 0 --env duel
```

Для дневной кампании (один агент, без оппонента и self-play):

```bash
venv/bin/python -m agents.train --episodes 100 --seed 0 --env campaign \
    --policy bdi \
    --world tests/fixtures/content/configs/worlds/agora_world.json
```

Флаг `--world` указывает JSON-мир. В поставке `configs/worlds/` пуст,
поэтому без флага среда поднимает `WorldError`; тестовый мир на 43 узла
лежит в `tests/fixtures/content/`.

Кампанейские действия — `CampaignAction` (`END_DAY`, `TREAT_SELF` и обычные
ходы `WorldEngine` по всем доступным адресатам). Награда — `campaign_reward()`
из дельт положения, организации, здоровья и болезни плюс терминальный бонус
исхода. Горизонт 30 дней — усечение обучения, а не поражение.

### 2.2. Полезные флаги

| Флаг | Назначение |
|---|---|
| `--policy bdi\|qtable\|mlp\|random` | выбрать обучаемую политику |
| `--env arena\|duel\|campaign` | среда обучения |
| `--episodes N`, `--seed N` | длина и воспроизводимость прогона |
| `--campaign-career` | открыть `seek_promotion`/`request_transfer`/`resign` |
| `--drift-scale X` | множитель темпа организационного дрейфа (1.0 — канон) |
| `--deadline N` | сюжетный дедлайн главы (не путать с `--days`) |
| `--dismissal-standing X` | порог репутации для смены роли |
| `--dismissal-legitimacy X` | порог легитимности структуры |
| `--collapse-grace N` | дней подряд ниже порога до распада |
| `--reward-profile legacy\|advantage\|advantage_cost` | формула награды арены |
| `--resume PATH` | продолжить обучение с чекпойнта |
| `--out PATH` | сохранить веса |
| `--eval-episodes N` | held-out матрица силы (0 — выключить) |
| `--eval-checkpoint NAME=PATH` | явный baseline для матрицы |
| `--domain-randomize` | доменная рандомизация перед эпизодом |
| `--save-best PATH`, `--best-every N` | сохранять лучший held-out чекпойнт |

Пример полного прогона с сохранением и оценкой:

```bash
venv/bin/python -m agents.train --episodes 2000 --seed 0 \
    --eval-episodes 50 --eval-seed 100000 \
    --eval-opponents bdi,qtable,random,mlp \
    --out saves/bdi.json --eval-out saves/eval.json
```

Обучение по умолчанию идёт в self-play: обе стороны обновляют свои политики.
`--no-self-play` оставляет противника фиксированным спарринг-партнёром.
Оценка никогда не вызывает `observe()` и не меняет веса.

### 2.3. Воспроизводимость и артефакты

- Сид задаёт и обучение, и жеребьёвку домена; один и тот же запуск
  воспроизводим.
- Held-out оценка по умолчанию идёт на каноническом домене. Явный
  `--eval-domain-randomize` усредняет её по распределению доменов.
- Production-чекпойнт арены — `checkpoints/duel_mlp_production.json`
  (`duel-mlp`, `v5/30`, `advantage_cost`). Матрица N=50 и известные
  ограничения — `ALGORITHMS.md` §6.7 и §8.6.
- Калибровка кампании:

```bash
venv/bin/python experiments/exp_campaign_calibration.py \
    --seeds 20 --days 30 --policies bdi,qtable-campaign,mlp \
    --world tests/fixtures/content/configs/worlds/agora_world.json
```

`--world` обязателен при пустом `configs/worlds/`: без него скрипт не найдёт
мир. Плечи для тонкой калибровки:

```bash
# жёсткий/мягкий дрейф и другой дедлайн
venv/bin/python experiments/exp_campaign_calibration.py \
    --seeds 20 --days 30 --policies bdi,qtable-campaign,mlp \
    --world tests/fixtures/content/configs/worlds/agora_world.json \
    --drift-scale 0.5 --deadline 20
# смена порогов карьеры/распада
venv/bin/python experiments/exp_campaign_calibration.py \
    --seeds 20 --days 30 --policies bdi,qtable-campaign,mlp \
    --world tests/fixtures/content/configs/worlds/agora_world.json \
    --dismissal-standing 0.02 --dismissal-legitimacy 0.04 \
    --collapse-grace 3
```

Скрипт ничего не меняет в коде: политики прогреваются на отдельном потоке
seed'ов, а метрики (победы, поражения, `neutral`, усечения, смены роли,
распады) печатаются в JSON и таблицу. Актуальные числа и трактовка
плеч — в `WORLD_CORE_MODEL.md` §2.3.4–2.3.6 и `TODO.md`.

### 2.4. Интерпретация результатов

- `truncated` — horizon обучения, а не победа и не поражение.
- `neutral` — нейтральный финал главы: дедлайн без взятия порога или потеря
  должности без замены.
- `dismissal` — смена роли, событие карьеры, а не поражение.
- `collapse` — распад организации (`power`/`cohesion` ниже порога
  `COLLAPSE_GRACE_DAYS` дней подряд).
- Сравнивайте матрицы только при одинаковом профиле награды, сиде и
  горизонте: `qtable` прогревается на том же профиле, что и основная
  политика.

---

## 3. Как контрибьютить

### 3.1. Перед началом

1. Прочитайте [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) — при расхождении
   документов приоритет у него.
2. Сверьтесь с [`TODO.md`](TODO.md) и [`RELEASE_READINESS.md`](RELEASE_READINESS.md):
   возможно, задача уже закрыта или имеет принятое решение.
3. Не меняйте канон 4-2-1 и легаси `simulation.py` без явного обоснования:
   это воспроизводимый baseline, а не активный игровой поток.

### 3.2. Правила кода

- PEP-8, длина строки **79** (`setup.cfg`, `pycodestyle`).
- Публичные модули, классы и функции — с docstrings; причины решений
  описываются в docstrings и тематических документах, а не в inline-комментариях.
- Новое поведение сопровождается тестом в `tests/`.
- Документация синхронна коду: константы, пороги и команды обновляются в
  `WORLD_CORE_MODEL.md`, `ALGORITHMS.md`, `AGENTS.md` и `TODO.md`.
- Не коммитьте `saves/`, `yet_another_project/`, артефакты экспериментов и
  временные файлы.

### 3.3. Проверки перед коммитом

```bash
venv/bin/python -m pytest -q
venv/bin/python -m pycodestyle $(git ls-files '*.py')
git diff --check
```

Полный прогон занимает несколько минут. Для точечной проверки можно
запускать отдельные файлы, но перед push нужен полный набор. CI
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) компилирует
ядро/GUI/эксперименты и запускает `pytest`; `tests/test_docs_sync.py`
ловит расхождения «доки ↔ код».

### 3.4. Коммиты и ветки

- Сообщения коммитов — на русском. Рекомендуемый вид первой строки:
  `<тип>: <краткая суть>` (`docs`, `fix`, `test`, `refactor`, `measure`,
  `chore`, `ci`, `arch`).
- В теле — что и зачем, ссылки на пункты `TODO.md`/ревью и способ проверки.
- Работа идёт в тематической ветке; слияние — через PR с зелёным CI.
- `CHANGELOG` не ведётся: его роль выполняют `git log`, `BASELINE.md` и
  `TODO.md`.

### 3.5. Куда добавить новый контент

- Новый мир, роль или сюжет — `configs/` и `campaign/`, без правки движка,
  если хватает существующих полей. Каталоги контента пусты: сюжет
  добавляется файлом `configs/storylines/<id>.json` вместе с
  `*_char.json`/`*_scenes.json`, мир — `configs/worlds/<name>.json`,
  роль — `configs/roles/<name>.json`.
- **Стратегии узлов** — `strategies` прямо в мире или отдельный
  `*_strategies.json`. Достаточно id, селекторов узлов/целей,
  `horizon_days`, `goal` и весов `actions`; код не меняется.
- **План среды** — JSON вида `configs/environments/<name>.json`
  (`goals` с `ratio`/`horizon`/`label`); подключается через
  `ArenaEnvironment(plan_path=...)` или `ArenaMatch(env_plan=...)`.
- **Рынок труда** — блок `labor_market` в мире: `rivals`,
  `refresh_days`, `structure_quota`, `quota`, `weights`. Новые поля
  сохраняются в конфиге, поэтому расширение не ломает старые миры.
- Новая механика — сначала тест и раздел в `WORLD_CORE_MODEL.md`, затем код.
- Новый эксперимент — `experiments/`, с детерминированным сидом и печатью
  JSON; результаты не коммитятся, если это не эталонная матрица.
- Новый агент/политика — `agents/`, с `state_dict()`/`load_state_dict()`,
  версией чекпойнта и записью в `AGENTS.md` §4.

### 3.6. Data-Driven чек-лист

1. Добавьте/измените JSON в `configs/`.
2. Проверьте загрузку точечным тестом (`load_world`, `load_storyline`,
   `load_environment_plan`) и отсутствие «висячих» id.
3. Для новой механики добавьте поле в валидатор и docstring, а не только
   в контент.
4. Обновите `docs/CONTENT.md` (карта папок) и `docs/WORLD_CORE_MODEL.md`
   (формулы/пороги), если поведение стало новым.
5. Прогоните `pytest`, `pycodestyle` и `git diff --check`; сохранения
   проверяйте на старом сейве и на текущем.

---

## 4. Частые проблемы

| Симптом | Что проверить |
|---|---|
| `ModuleNotFoundError: pygame` | установите `requirements.txt` и используйте `venv` |
| Игра не находит чекпойнт | `--list-checkpoints`, версия файла, `--checkpoint PATH` |
| Политика всегда выбирает `END_DAY` | для кампании нужен `campaign_features()`/`campaign_weights`; аренный чекпойнт не читает `CampaignObservation` |
| Матрица силы не сравнима с прошлой | другой профиль награды, сид, горизонт или прогрев baseline |
| Кампания «зависла» без действий | нет должности (`attached=False`) или завершён сюжет; часы стоят на паузе |
| Тест падает только в CI | проверьте длину строки 79 и `git diff --check`, затем полный `pytest` |
