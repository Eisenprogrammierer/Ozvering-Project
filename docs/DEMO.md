# Демо: запуск и готовность

> **Дата проверки:** 2026-11-28.
> Канон проекта — [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md), открытые
> задачи — [`TODO.md`](TODO.md).

## 1. Быстрый запуск

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-dev.txt
venv/bin/python main.py
```

Без флага открывается современный клиент `view/`: главное меню →
«Новая игра» → роль → сюжет → кампания/дневной мир. Самый короткий
путь к игре — «Быстрая кампания» в главном меню.

| Команда | Что открывает |
| --- | --- |
| `venv/bin/python main.py` | главное меню `view/` (режим по умолчанию) |
| `venv/bin/python main.py --campaign` | то же, явный флаг |
| `venv/bin/python main.py --automata` | редактор автоматов |
| `venv/bin/python main.py --arena` | дуэль-арена |
| `venv/bin/python main.py --classic` | легаси-меню `ui/` |
| `venv/bin/python main.py --list-checkpoints` | список чекпойнтов без окна |
| `venv/bin/python -m campaign.dialogue.lint` | проверка диалоговых данных |
| `venv/bin/python -m campaign.content_lint` | проверка контента |

Журнал пишется только по `--log`/`--log-file`; каждый запуск
перезаписывает файл.

## 2. Проверенный демо-путь

| Что проверено | Как | Результат |
| --- | --- | --- |
| Главное меню и живой цикл | `tests/test_gui_smoke.py` | кадры рисуются, меню живо |
| «Быстрая кампания» | `tests/test_demo_path.py`, ручной прогон | 8 действий, мир дошёл до 9-го дня |
| «Новая игра» → роль → сюжет | `tests/test_campaign.py`, `tests/test_view_world.py` | доходит до выбора должности и мира |
| Свободная жизнь (`free_citizen`) | ручной headless-прогон, `tests/test_free_mode.py` | мир открывается, 65 действий, день идёт, сейв пишется |
| Лорная кампания (`empire_leader`) | ручной headless-прогон | сводка → кампания автоматов → действие → ход |
| Дневной мир и действие | `tests/test_view_world.py`, `tests/test_world*.py` | действие исполняется, день двигается |
| Кампания автоматов | `tests/test_automata_campaign.py`, `tests/test_gui_smoke.py` | ходы, процессы, хроника |
| Чат «СВЯЗЬ» | `tests/test_view_dialogue_chat.py` | ответ агента, тон вычисляется |
| Арена | `main.py --arena`, `tests/test_gui_smoke.py` | открывается и возвращает в меню |
| Редактор автоматов | `main.py --automata` | открывается, цикл работает |
| Легаси-меню | `main.py --classic` | открывается |
| Сохранения и настройки | `tests/test_save_system.py`, `tests/test_view_settings.py` | сейв/загрузка, настройки переживают перезапуск |
| Headless-смоук | `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy venv/bin/python -m pytest -q tests/test_gui_smoke.py` | зелёный |

## 3. Ограничения демо

Это не блокеры, но честно перечислено:

- графика — процедурные плейсхолдеры (`configs/view/presentation.json`,
  `use_placeholders=true`); реальных портретов персонажей нет;
- музыка — 19 треков Kevin MacLeod без per-track лицензионных файлов;
- `pip install .` не ставит `assets/`, `configs/`, `music/`; демо
  запускается из дерева репозитория или PyInstaller-сборки;
- сейвы и настройки пишутся в `saves/` внутри дерева проекта, а не в
  пользовательский data-dir; схема сейва `SAVE_VERSION = 4` с миграциями
  1→2→3→4;
- при старте в консоль попадает безобидное предупреждение
  «Базовый военный мир не собран»: старый военный мир не нужен
  современным сюжетам и собирается только по запросу;
- легаси-слой (`ui/`, `simulation.py`, `game_engine.py`) ещё в
  репозитории: `--classic`, `--arena` и редактор автоматов опираются на
  него.

## 4. Что доделать после демо

Приоритеты и подробности — в [`TODO.md`](TODO.md). Коротко:

### 4.1. Легаси-слой (P0)

- вынести общие примитивы `ui/theme.py`, `ui/widgets.py`, `ui/scene.py`
  в активный слой (их использует редактор автоматов), затем удалить
  `ui/`, легаси-тесты и флаги `--classic`/`--ui`/`--interaction`;
- вынести из `simulation.py` нужные активному коду `Agent`,
  `UtilityAI`, `Environment` и константы в нейтральный модуль, перевести
  `warfare*.py`, `organizations/runtime.py`, `lod.py`, затем удалить
  `simulation.py` и легаси-дуэльные эксперименты;
- убрать fallback `--scene` без `--view`, каталоги `scenarios/` и
  верхнеуровневый `campaigns/`, если они не нужны активным слоям.

### 4.2. Играбельность и контент (P1)

- свести свободный режим к специфике общего сюжета кампании;
- убрать `_end_turn`/`end_turn` после отказа экранов;
- вакансии и перевод персонала, личные отношения персонажей;
- реальные портреты и лицензии на музыку.

### 4.3. Инфраструктура (P2)

- перенести логи и сейвы в XDG data-dir;
- поддерживать миграции схемы сейва при будущих изменениях (сейчас
  покрыт путь 1→4);
- Windows/macOS-сборка и CI-артефакт;
- разрезать оставшиеся крупные модули (`game_engine.py`,
  `view/support/world.py`) и разорвать
  `campaign → organizations.runtime → simulation`.

### 4.4. ИИ (P1, отдельным треком)

- W2a: eval-матрица и self-play политики NPC;
- покрытие языка и паритет диалога, затем снятие shadow;
- полный демонтаж legacy-модулей ИИ — только после этих проверок.
