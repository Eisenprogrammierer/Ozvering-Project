# CAMPAIGN_UI.md — кампанийный интерфейс `view/`

Документ описывает **перенесённый UI-каркас** из локального легаси-проекта:
экраны командного пункта, карты, приказов, документов и нарратива. Это именно
оболочка: источником игрового состояния служит [`warfare.py`](../warfare.py), а
каноническое ядро [`simulation.py`](../simulation.py) не изменяется.

## Запуск

```bash
python3 main.py --view             # кампанийный интерфейс
python3 main.py --view -f          # он же в полноэкранном режиме
python3 -m view                    # альтернативная точка входа
```

Старый сценный слой `ui/` остаётся по умолчанию:

```bash
python3 main.py                    # ui: меню -> нарратив -> партия
python3 main.py --arena            # арена game_engine
```

## Что перенесено

| Блок | Модули | Назначение |
|------|--------|-----------|
| Приложение | `view/app.py` | окно, шрифты, музыка, стек экранов, сюжет |
| Экраны | `view/screens/` | меню, настройки, сохранения, выбор сюжета, создание персонажа, новелла, документы, диалог, КП, карта, приказы, последствия, обязательные сцены |
| Виджеты | `view/ui/` | `ScreenManager`, кнопки/панели, загрузчик ассетов, музыка, HUD времени, оверлеи |
| Контент | `configs/` | приказы, документы, блокнот, диалоги, сюжеты |
| Карты | `scenarios/` | `.npz`-карты высот/биомов |
| Ассеты | `assets/` | изображения, шрифты |
| Музыка | `music/` | фоновые треки |

Бинарные материалы скопированы целиком: `assets/` — около 18 МБ, `music/` —
около 120 МБ.

## Архитектура адаптера

```
view/
  app.py                 # App: окно, музыка, роутинг, сюжетные сцены
  screens/               # экраны (перенесены из легаси)
  ui/                    # менеджер экранов, виджеты, ассеты, HUD, оверлеи
  support/
    world.py             # CampaignState + CampaignEngine поверх warfare.py
    scenario.py          # build_world(), load_map()
    time_system.py       # часы кампании и действия игрока
    save_system.py       # слоты saves/campaign/*.json
    content.py           # JSON-контент configs/content
    storyline.py         # декларативные сюжеты
    effects.py           # effect → приказ/сегмент/напряжение
    rules.py             # совместимый no-op для решений
    traits.py            # модификатор шума разведки
    log_journal.py       # operation_ozverin.log
```

### Состояние

`CampaignState` — тонкий презентер над `warfare.WarfareSimulation`:

* `units` / `count` / `factions` / `entity_ids` — активные и выбывшие отделения;
* `coords` — позиции отделений, растянутые на карту 256×256;
* `read_segment()` — сегменты `condition`, `order`, `size`, `morale`,
  `discipline`, `supply`, `fatigue`, `cohesion`, `initiative`, `health`;
* `read_voltage()` — `U_manpower`, `U_casualties`, `U_supply` и совместимые
  каналы техники;
* `read_voltage("U_manpower")` = `force * 500`, поэтому численность выглядит
  как штатная численность подразделения, а не как абстрактная сила.

`CampaignEngine` переводит действия интерфейса в пассивные приказы
`warfare.Order` (`aggressive_attack`, `attack`, `holding_defense`, `rest`,
`withdrawal`, …), двигает отделения к точке стрелки и раз в 30 игровых минут
вызывает `WarfareSimulation.tick()`. Это тот же войсковой слой, что и в
`warfare.py`; отдельной боевой математики в `view/` нет.

### Время и обязательные сцены

`CampaignTimeSystem` читает `configs/content/time_settings.json` и
`time_actions.json`. Действия «подождать» продвигают часы; каждые 30 минут
происходит один войсковой такт. При переходе через вечернюю границу
выставляется `pending_mandatory_scene`, который `App.run()` превращает в экран
обязательной сцены. Сюжетные условия победы/поражения проверяются в
`App.check_storyline_end_of_day()`.

### Сохранения

Слоты лежат в `saves/campaign/` (каталог в `.gitignore`) и не пересекаются с
автосейвами `ui/`:

```json
{
  "version": 1,
  "updated": "2026-10-25 19:00:00",
  "scenario_path": "scenarios/mvp.json",
  "campaign": { "seed": 7, "turn": 12, "detachments": [] },
  "time_system": { "day": 1, "seconds_of_day": 27000 },
  "storyline": { "scene_index": 12, "variables": {} }
}
```

При загрузке мир пересобирается из `seed`, доигрывается до сохранённого такта
и получает сохранённые силы/позиции/приказы. Сюжетные переменные
восстанавливаются через `StorylineInterpreter.load_from_snapshot()`.

## Музыка и атрибуция

Треки берутся из `music/{overture,ambient,victorious,tragic}`. В правом нижнем
углу главного меню мелким приглушённым шрифтом выведено
**Music by Kevin MacLeod**.

## Ограничения переноса

* Это UI-каркас: сложная кампанийная экономика, метаморфозы и легаси-`TickEngine`
  не переносились.
* Расчёты боя, морали, паники, заградотрядов и подкреплений остаются в
  `warfare.py`.
* Сюжетные JSON-файлы используются как декларативный контент; их поле
  `scenario_path` совместимо, но состояние всё равно строится из
  `warfare.build_demo_scenario()`.
* Не-GUI тесты: `tests/test_view.py` (адаптер `warfare`, приказ/такт,
  движение, эффекты, слоты; без pygame).
* Графические проверки выполняются headless:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python3 -m view
```
