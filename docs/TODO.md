# TODO: только открытые задачи

> **Дата:** 2026-11-24. Закрытые пункты удалены из трекера; их история
> остаётся в git и в [`history/`](history/). Канон и границы — в
> [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md).

## 1. Кампания, время и работа

- [ ] Удалить legacy-помощники `_end_turn`/`end_turn` после отказа экранов
  от старых вызовов.
- [ ] Добавить вакансии и перевод персонала между органами длительным
  действием.
- [ ] Дать персонажам личные отношения друг с другом (покровитель,
  соперник, долг), чтобы цели влияли на состав исполнителей.
- [ ] Наполнить `assets/images/characters/` реальными портретами; пока это
  плейсхолдеры.

## 1.1. Сюжет как проекция симуляции

Канон — в [`NARRATIVE_INVARIANT.md`](NARRATIVE_INVARIANT.md), схема и
фазы — в [`LORE_IMPLEMENTATION_PLAN.md`](LORE_IMPLEMENTATION_PLAN.md).
Сюжет не задаётся сценами, выборами или финалами в данных: он собирается
из `AutomataCampaign.narrative` в `campaign/chronicle.py`.

Открытых пунктов нет: причинные связи, курс подфракции, free-life
«Агора», литературный слой и фразы-маркеры закрыты. Шаблоны хроники
проверяются `campaign.content_lint` (категории, обязательные
плейсхолдеры, неизвестные поля), а файловый журнал включается только
флагом `--log`.

## 2. Диалог

- [ ] `avoid_recent` (D5.1): проверить, что ограничение по ходам не даёт
  выбрать неожиданный регистр в длинном разговоре.
- [ ] D3.2: контрфакты не используют `differences`/`removed`/`added`.
  Полноценное «изменилось бы потому, что …» — отдельная задача.
- [ ] D3.2: расширить whitelist из 5 отношений по мере P8/P9.
- [ ] D6.2a: `s_counterfactual_neg` дублирует `s_counterfactual` — удалить
  или оставить как документирующий алиас.
- [ ] `fallback.json`: пополнять лексику по реальным фразам игроков и
  проверять battery-тестом на естественных вопросах.
- [ ] Ротация связок для длинного абзаца (3+ стыка), если понадобится.
- [ ] Проверить интеграционным тестом, что изменения отношений и убеждений
  сразу видны в следующем ответе.

## 3. Приоритет на ближайшую неделю

1. Корпус парафраз и доменных псевдонимов — по мере роста грамматики.
2. Корпус фраз-маркеров режимов разговора: тон уже меняется, содержание
   ответа — не всегда.
3. Факты здравого смысла: расширять курированный слой и покрытие
   runtime-хука стиля.

## 4. Архитектура (следующие шаги)

- [x] `WorldEngine` (`campaign/world.py`, 237 методов) разрезан по швам на
  миксины: `world_core.py`, `world_entities.py`, `world_relations.py`,
  `world_career.py`, `world_actions.py`, `world_day.py`,
  `world_snapshot.py`; общие примитивы — `world_support.py`. Публичный API
  и формат снимка сохранены (AST-сверка 230/230 имён, полный прогон).
- [x] `AutomataCampaign` (`campaign/automata.py`, 190 методов) разрезана
  тем же протоколом: `automata_core.py`, `automata_actions.py`,
  `automata_processes.py`, `automata_ai.py`, `automata_characters.py`,
  `automata_orders.py`, `automata_reports.py`, `automata_snapshot.py`;
  общие примитивы — `automata_support.py`. Алиасы
  `interact_organ`/`interact_automaton`/`interact_character` и
  `to_dict` сохранены; публичный API и формат снимка проверены AST-сверкой.
- [x] Убрать прямые импорты `warfare`/`simulation` из `campaign/` на
  верхнем уровне: `automata_support._character_from_record` и
  `preset._make_character` создают `warfare.Character` лениво; граница
  зафиксирована `tests/test_architecture_boundaries.py` и описана в
  `SOURCE_OF_TRUTH.md` §4.
- [x] View-слой разрезан по тому же протоколу:
  `view/app.py` — фасад `App` + `app_{core,storyline,scenes,flow,dialogue,saves,menu,support}.py`;
  `world_screen.py` + `world_screen_{core,events,draw,detail,personality,support}.py`;
  `rts_screen.py` + `rts_screen_{core,commands,update,events,draw,support}.py`;
  `automata_network.py` +
  `automata_network_{core,selection,actions,events,draw,support}.py`.
  Публичные имена, атрибуты классов и `__init__` сохранены; MRO ставит
  миксины до `BaseScreen`, иначе базовые заглушки перекрывали бы экран.
- [ ] Следующие крупные модули вне экранов: `game_engine.py` (`GameApp`,
  легаси-арена) и `view/support/world.py` (`CampaignEngine`,
  `CampaignState`); это не «божественные объекты» одного класса, но
  кандидаты на такие же швы.
- [ ] Остаётся транзитивная зависимость `campaign → organizations.runtime →
  simulation`: `OrganizationRuntime` наследует `simulation.Environment`.
  Полный разрыв — вынести `Agent`/`Environment` в нейтральный модуль
  (отдельная миграция, менять поведение легаси нельзя).
- [ ] Перенести логи и сейвы из дерева репозитория в пользовательский
  data-dir (XDG), оставив флаг для локальной отладки.

## 5. Перед коммитом

```bash
venv/bin/python -m pytest -q
venv/bin/python -m campaign.content_lint
venv/bin/python -m campaign.dialogue.lint
venv/bin/python -m compileall -q campaign warfare.py view tests
git diff --check
```
