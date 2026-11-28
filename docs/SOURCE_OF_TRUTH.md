# Источник истины по проекту

**Статус:** главный проектный документ и навигационная карта. Решения ниже
согласованы с автором проекта. Реализация целевой модели начата: есть
вертикальный срез `core41`, runtime активной арены, слой обучаемых агентов
`agents` и диалоговый слой `campaign/dialogue/`; полная миграция мира ещё не
завершена.

**Дата:** 2026-11-19.

**Формулы:** точные формулы, единицы, примеры и ссылки на код собраны в
[`FORMULAS.md`](FORMULAS.md). Этот документ даёт только сводку и маршрут к
ним.

**Роль документа.** Это верхний уровень истины для целей, онтологии и границ
проекта. Если документы расходятся, действует следующий порядок:

1. **Проектные решения и целевая онтология** — этот документ.
2. **Детализация целевой модели мира** — [`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md),
   если она не противоречит этому документу.
3. **Текущее поведение легаси-кода** —
   [`history/MODEL.md`](history/MODEL.md),
   [`history/BASELINE.md`](history/BASELINE.md) и тесты, пока код не
   переведён на целевую модель.
4. **Текущий кампанийный поток** — [`WORLD.md`](WORLD.md); это описание
   текущей реализации, а не целевой мир.
5. **История и обзоры** — [`history/`](history/); они фиксируют прошлое и
   не являются каноном.

Нельзя молча менять код под документ или документ под код. Изменение канона —
это отдельное изменение: сначала этот документ и/или
[`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md), затем код, тесты и остальные
документы.

---

## 0. Навигатор: потребность → маршрут

Этот раздел нужен, чтобы по одной потребности сразу понять, **какой слой
читать, где менять код, где данные и чем проверить**. Формат строки:
`потребность` → `слой` → `код` · `конфиги` · `тесты` · `документ`.

### 0.1. Понять проект и его границы

| Потребность | Куда идти |
|---|---|
| Понять, что за проект и какая у него онтология | §1–§3 этого документа; [`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md) |
| Понять, где текущая реализация, где цель, а где легаси | §4 и таблица статусов в §6 |
| Понять, как считаются формулы | [`FORMULAS.md`](FORMULAS.md); [`ALGORITHMS.md`](ALGORITHMS.md) |
| Понять, что уже сделано и что открыто | §7 (только открытые пункты), §9; [`TODO.md`](TODO.md) |
| Увидеть историю решений, не канон | [`history/`](history/) |

### 0.2. Запустить и увидеть игру

| Потребность | Слой | Код · конфиги · тесты · документ |
|---|---|---|
| Поставить окружение и запустить | вход | `main.py`, `view/`, `ui/` · — · `test_gui_smoke.py` · [`ONBOARDING.md`](ONBOARDING.md), [`HOWTO.md`](HOWTO.md), `README.md` |
| Запустить конкретный режим | вход | `main.py --arena/--scene/--view/--classic/--automata` · — · `test_ui.py`, `test_view.py` · [`ONBOARDING.md`](ONBOARDING.md) §1.4 |
| Включить файловый журнал | вход | `main.py --log` / `--log-file PATH`, `view/support/log_journal.py` · — · `test_logging_setup.py` · [`ONBOARDING.md`](ONBOARDING.md) §5.8 |
| Играть в кампанию автоматов | кампания | `campaign/automata.py`, `campaign/fractal.py`, `campaign/faction_state.py`, `campaign/preset.py` · `configs/campaigns/`, `configs/characters/` · `test_automata_campaign.py`, `test_automata_network.py` · [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) |
| Играть в дневной мир должностного лица | мир | `campaign/world.py`, `view/screens/world_screen.py` · `configs/roles/`, `configs/storylines/`, `configs/worlds/agora_world.json` · `test_campaign.py`, `test_world.py`, `test_view_world.py` · [`WORLD.md`](WORLD.md) |
| Играть свободным жителем без мандата | мир | `configs/roles/roles.json` (`free_citizen`), `configs/storylines/free_life*.json`, `configs/characters/archetypes.json`, `view/screens/archetype_select.py` · `campaign/world.py` (`profile_from_identity`), `view/app.py` (`_free_start_entry`, `_save_world_game`) · `test_free_mode.py`, `test_archetypes.py`, `test_player_avatar.py` · [`WORLD.md`](WORLD.md) §1 |
| Играть на арене | арена | `game_engine.py`, `core41/arena.py` · `configs/content/` · `test_health.py`, `test_core41.py` · [`AGENTS.md`](AGENTS.md), [`ALGORITHMS.md`](ALGORITHMS.md) |
| Говорить с агентом в чате | диалог | `view/screens/dialogue_chat.py`, `campaign/dialogue/` · `configs/dialogue/` · `test_dialogue.py`, `test_d1_dialogue.py`, `test_d5_registers.py`, `test_d5_style_hints.py`, `test_view_dialogue_chat.py` · [`DIALOGUE_NLG.md`](DIALOGUE_NLG.md), [`CHAT_STYLES_PLAN.md`](CHAT_STYLES_PLAN.md) |

`-m` принимает имя модуля через точку, а не путь. `python3 -m campaign`
запускает CLI ролей/пресетов, `python3 -m core41` показывает справку и демо
ядра. Записи `python3 -m campaign/world` и `python3 -m core41/arena`
синтаксически неверны; `campaign/world.py` и `core41/arena.py` — библиотеки,
поэтому `python3 -m campaign.world`/`-m core41.arena` только печатают
подсказку. Игра — `python3 main.py --view` или `python3 main.py --arena`.

### 0.3. Изменить бой, здоровье и арену

| Потребность | Слой | Код · конфиги · тесты · документ |
|---|---|---|
| Урон, здоровье, смерть | ядро | `core41/model.py` (`HEALTH_*`, `apply_force_damage`, `tick_health`) · — · `test_health.py` · [`FORMULAS.md`](FORMULAS.md) §3 |
| Болезнь, рана, заражение | ядро | `core41/model.py` (`SICKNESS_*`, `WOUND_*`, `transmit_sickness`) · — · `test_sickness.py` · [`FORMULAS.md`](FORMULAS.md) §3 |
| Вероятность успеха | ядро | `core41/model.py`, `success_probability()` · коэффициенты действия в контенте · `test_math_model.py` · [`FORMULAS.md`](FORMULAS.md) §2 |
| Действия, подготовка, давление | арена | `core41/arena.py` (`CORE_ACTIONS`, `work_amount`, `resolve_pair`) · — · `test_core41.py` · [`ALGORITHMS.md`](ALGORITHMS.md) §4 |
| Захват и исход партии | арена | `core41/arena.py`, `check_capture()` · — · `test_core41.py` · [`FORMULAS.md`](FORMULAS.md) §4 |
| Награда арены и профили | обучение | `core41/arena.py`, `reward_delta()` · — · `test_core41.py` · [`FORMULAS.md`](FORMULAS.md) §5 |
| Среда арены, сезоны, окна | арена | `core41/environment.py` · `configs/environments/` (пуст) · `test_environment.py` · [`ALGORITHMS.md`](ALGORITHMS.md) §2.4 |
| Типизированная нагрузка работы | ядро | `core41/payload.py`, `core41/types.py` · — · `test_payload.py` · [`ALGORITHMS.md`](ALGORITHMS.md) |
| Составной автомат | ядро | `core41/composite.py` · — · `test_composite.py` · [`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md) |

### 0.4. Обучить, оценить и подключить политику

| Потребность | Слой | Код · конфиги · тесты · документ |
|---|---|---|
| Обучить политику арены | обучение | `agents/train.py`, `agents/policies.py`, `core41/env.py` · — · `test_train_cli.py` · [`AGENTS.md`](AGENTS.md) §3 |
| Обучить политику кампании | обучение | `agents/train.py --env campaign --world PATH`, `campaign/env.py` · `configs/worlds/agora_world.json` (production) · `test_campaign_env.py` · [`AGENTS.md`](AGENTS.md) §3 |
| Добавить новый тип политики | обучение | `agents/policies.py`, `agents/__init__.py` · — · `test_core41.py`, `test_train_cli.py` · [`AGENTS.md`](AGENTS.md) §4 |
| Загрузить/найти чекпойнт | обучение | `agents/checkpoints.py`, `agents/__init__.py` · `checkpoints/` · `test_checkpoints.py` · [`AGENTS.md`](AGENTS.md) §3 |
| Понять признаки и версии чекпойнтов | обучение | `agents/policies.py`, `core41/env.py` · — · `test_core41.py` · [`ALGORITHMS.md`](ALGORITHMS.md) §5–6 |
| Доменная рандомизация и held-out | обучение | `agents/train.py` · `configs/content/combat_defaults.json` · `test_train_cli.py` · [`AGENTS.md`](AGENTS.md) §3 |

### 0.5. Изменить кампанию автоматов

| Потребность | Слой | Код · конфиги · тесты · документ |
|---|---|---|
| Фракции, органы, работы | кампания | `campaign/automata.py`, `campaign/preset.py` · `configs/campaigns/*.json`, `configs/campaigns/base/lore_factions.json` · `test_automata_campaign.py` · [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) |
| Работа: capability → `Work` → обработчик | кампания | `campaign/work.py`, `campaign/handlers.py`, `campaign/work_trace.py`, `campaign/effects.py` · `configs/campaigns/base/handlers/*.json` · `test_automata_campaign.py` · [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) §3 |
| Сеть органов и взаимодействия | кампания | `campaign/fractal.py` · поле `links` в `configs/campaigns/base/lore_factions.json` · `test_automata_campaign.py`, `test_automata_network.py` · [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) §3.2 |
| Производные активы фракции | кампания | `campaign/faction_state.py` · `faction_state` в `configs/campaigns/base/automata_defaults.json` · `test_automata_campaign.py` · [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md) §3 |
| BDI персонажей | кампания | `bdi.py`, `warfare.py` (`Character`), `campaign/actor.py`, `campaign/character.py`, `campaign/routine.py` · `configs/characters/bdi.json`, `bdi_routine` в мире · `test_bdi.py`, `test_automata_campaign.py`, `test_world_needs.py` · [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md) §1 |
| Политика NPC поверх BDI | кампания | `campaign/npc_policy.py`, `campaign/automata_ai.py` (`npc_outcome_report`), `campaign/npc_decisions.py` (`NpcDecisionMonitor`, `job_diversity`) · `ai_model.npc_policy` (`backend`, `backends`, `timeout_ms`, `tick_timeout_ms`) в `configs/campaigns/base/automata_defaults.json` · `test_npc_policy.py`, `test_npc_decisions.py` · — |
| 16 потребностей и 15 делений | кампания | `organizations/needs.py`, `campaign/divisions.py`, `character_traits.py` · `configs/characters/bdi.json`, `configs/characters/divisions.json`, `configs/characters/traits.json` · `test_organizations.py`, `test_divisions.py`, `test_people.py` · [`ORGANIZATIONS.md`](ORGANIZATIONS.md), [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md) §1–§2 |
| События и их условия | кампания | `systems/events.py` · `configs/systems/events.json` · `test_events_runtime.py`, `test_automata_campaign.py` · [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md) §4 |
| Темп, действия, скорости | кампания | `campaign/defaults.py` · `configs/campaigns/base/automata_defaults.json` · `test_automata_campaign.py` · [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) |
| Исходы, поражение, распад | кампания | `campaign/automata.py` · шаблон кампании · `test_automata_campaign.py` · [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) |
| ИИ кампании и приоритеты | кампания | `campaign/automata.py` · шаблон кампании · `test_automata_campaign.py` · [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) |

### 0.6. Изменить дневной мир `world_actor`

| Потребность | Слой | Код · конфиги · тесты · документ |
|---|---|---|
| Узлы, должности, действия мира | мир | `campaign/world.py`, `campaign/actions.py` · `configs/worlds/agora_world.json`, `configs/worlds/actions/*.json`, `configs/campaigns/forms.json`, `configs/worlds/agora_strategies.json`, фикстуры · `test_world.py`, `test_action_catalog.py`, `test_world_primitives.py`, `test_items.py`, `test_free_mode.py` · [`WORLD.md`](WORLD.md), [`CONTENT.md`](CONTENT.md) |
| Персонаж `E/F/H`, BDI и бюджет действий | мир | `campaign/actor.py`, `campaign/character.py`, `campaign/routine.py`, `campaign/projections.py` · `bdi_routine` в `configs/worlds/agora_world.json` · `test_projections.py`, `test_campaign_energy.py`, `test_world_needs.py` · [`WORLD.md`](WORLD.md) |
| Отношения и обязательства | мир | `campaign/relations.py`, `campaign/obligations.py` · — · `test_campaign_relations.py` · [`FORMULAS.md`](FORMULAS.md) §2.3 |
| Ценности и коалиции | мир | `campaign/values.py`, `campaign/coalitions.py` · блоки `values`/`coalitions` мира · `test_campaign_values.py`, `test_campaign_coalitions.py` · [`FORMULAS.md`](FORMULAS.md) §8 |
| Экономика, бедность, кредит | мир | `campaign/economy.py` · блок `economy` мира · `test_campaign_economy.py` · [`FORMULAS.md`](FORMULAS.md) §7 |
| Планировщик и автономия | мир | `campaign/planner.py`, `campaign/control.py` · — · `test_campaign_planner.py`, `test_campaign_control.py` · [`WORLD.md`](WORLD.md) |
| Журнал и LOD | мир | `campaign/logbook.py`, `campaign/lod.py` · блоки `logging`/`lod` · `test_campaign_logbook.py` · [`WORLD.md`](WORLD.md) |
| Дрейф, распад, смена роли | мир | `campaign/world.py` (`_apply_organizational_drift`, `_check_dismissal`) · пороги мира · `test_campaign.py`, `test_campaign_clock.py` · [`FORMULAS.md`](FORMULAS.md) §6 |
| Фон и оффлайн-догон | мир | `campaign/clock.py` · — · `test_campaign_clock.py` · [`WORLD.md`](WORLD.md) |
| Сюжетная глава и финал | мир | `campaign/world.py` (`_check_storyline`) · блок `storyline` · `test_story_arcs.py` · [`WORLD.md`](WORLD.md) |
| Карьера и рынок труда | мир | `campaign/world.py` (`office_options`) · блок `labor_market` · `test_campaign.py` · [`WORLD.md`](WORLD.md) |
| Стратегии узлов | мир | `campaign/node_strategy.py` · `configs/worlds/*_strategies.json` · `test_node_strategy.py` · [`CONTENT.md`](CONTENT.md) |

### 0.7. Изменить контент без кода

| Потребность | Куда идти |
|---|---|
| Общая карта JSON и загрузчиков | [`CONTENT.md`](CONTENT.md) |
| Роли игрока | `configs/roles/roles.json`, `configs/characters/archetypes.json`, `campaign/roles.py`, `campaign/identity.py`; тесты `test_campaign.py`, `test_archetypes.py` |
| Управляемый персонаж (аватар) | `campaign/avatar.py`, `campaign/preset.py` (`select_player_character`), `campaign/automata.py` (`avatar_character`, снимок `avatar`), `view/screens/character_select.py`; тест `test_player_avatar.py` |
| Сюжеты и сцены | `configs/storylines/` (`storyline_tags`, метаданные и `gameplay`), `configs/worlds/scenes/`; `view/support/storyline.py`, `campaign/scenes.py`; сюжет automata-кампании — `campaign/chronicle.py` и `AutomataCampaign.narrative`; тесты `test_view_world.py`, `test_storyline_flex.py`, `test_narrative_emergence.py`, `test_scene.py` |
| Миры кампании | `configs/worlds/agora_world.json` (production), `configs/worlds/agora_strategies.json`; `campaign/world.py::load_world`; блок `bdi_routine` включает суточные потребности |
| Биография и личность героя | `configs/worlds/biography.json`, `configs/characters/identity.json`, `configs/characters/archetypes.json`; `campaign/identity.py`, `campaign/world.py::profile_from_identity`, `test_identity.py`, `test_archetypes.py` |
| Черты персонажей | `configs/characters/traits.json`; `character_traits.py`; `test_people.py` |
| BDI персонажей | `configs/characters/bdi.json`; `bdi.py`, `warfare.py` (`Character`), `campaign/actor.py`, `campaign/character.py`, `campaign/routine.py`; `test_bdi.py`, `test_automata_campaign.py`, `test_world_needs.py`; [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md) §1 |
| 15 делений | `configs/characters/divisions.json`; `campaign/divisions.py`; `test_divisions.py`; [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md) §2 |
| Формулы активов фракции | `configs/campaigns/base/automata_defaults.json` → `faction_state`; `campaign/faction_state.py`; `test_automata_campaign.py` |
| Среда, события, драматург | `configs/systems/`; `systems/`; `test_systems.py`, `test_events_runtime.py` |
| Имена и политики имён | `configs/naming/`; `naming/`; `test_naming.py`, `test_people.py`; [`NAMING.md`](NAMING.md) |
| Приказы, документы, диалоги, время | `configs/content/`; `view/support/content.py`; `test_content_pipeline.py` |
| Диалог: лексикон, грамматика, планы, стили, дискурс, контрфакты | `configs/dialogue/`; `campaign/dialogue/loader.py`; `test_dialogue.py`, `test_d5_registers.py`; [`DIALOGUE_NLG.md`](DIALOGUE_NLG.md) |
| Реестр действий диалога | ручной `configs/dialogue/actions.json` (включая `markers` для приказов, угроз и обещаний) + проекция `campaign/dialogue/projection.py`; `test_d6_actions.py`, `test_dialogue_projection.py` |
| Речевые акты | `configs/dialogue/social.json`, `grammar.json`, `lexicon.json`; `test_d4_social.py`, `test_d7_social.py`, `test_d7_social_acts.py` |
| Типы ответа диалога | `configs/dialogue/answer_kinds.json`; `campaign/dialogue/answers.py` (`answer_handler_name`); `test_answer_registry.py` |
| Адаптеры мира | `campaign/perception.py` (`WorldView`, `AutomataCampaignAdapter`, `WorldEngineAdapter`, `SceneAdapter`); `configs/dialogue/world.json.adapters`; `test_world_adapters.py` |
| Отношения и эмоциональные оси | `campaign/relations.py`; блоки `relation_axes`/`relation_effect_weights`/`relation_effect_limit` мира; эффекты `target`/`relation_axes` в `configs/worlds/actions/`; `test_relation_axes_config.py` |
| Факты здравого смысла | `configs/knowledge/commonsense/` (`schema.json` с `style_hints`, `speech_acts.jsonl`, `mode_markers.jsonl`, `social_causes.jsonl`, `entities.jsonl`; `raw/` — исходные LLM-выгрузки); `campaign/commonsense.py`; `python -m campaign.commonsense --check`; команда консоли `/смысл`; runtime-хук стиля в `DialogueSession`; корпус парафраз с `"source": "commonsense"`; `test_commonsense.py`, `test_d5_style_hints.py`, `test_d7_console.py` |
| Живой мост действий | `campaign/dialogue/bridge.py` (`ActionBridge`, `ActionResult.work`/`.trace`); `campaign/actions.py` (`build_spec_work`, `improvised_work`); `test_d6_bridge.py` |
| Когнитивный фасад и миграция ИИ | `campaign/cognition/` (`understand`, `decide`, `UtteranceFrame`, `soar_bridge.v1`, `GoldenCorpus`, parity, `rive_compiler` с `grammar_patterns`, `RiveNlu` с `report`, macros, `nlu_lint`, `corpus_builder`, `soar_compiler`, `intention_compiler`, `faction_compiler`, `reaction_compiler`, `pragmatics_compiler`, `inference_compiler`, `SoarNpcPolicy`, `SoarIntention`/`IntentionMonitor`/`SoarIntentionPool`, `SoarFactionPolicy`/`FactionDecisionMonitor`, `SoarReactionPolicy`/`ReactionDecisionMonitor`, `SoarAgent` с `soar_snapshot.v1`/`soar_snapshots.v1`, `soar_npc` (`bdi_memory`, `SoarNpcAgent`, `SoarNpcPool`), `SoarInference`, `NluBackend`, `InferenceBackend.for_knowledge` для контрфактов), `campaign/dialogue/state.py` (`ConversationState.to_dict/restore`) и `campaign/dialogue/stores.py` (`DialogueMemoryStore`, `DialogueStateStore`), `campaign/npc_decisions.py` (`NpcDecisionMonitor`), `mass_npc_report`/`intention_report` в `automata_characters.py`; `configs/cognition/backends.json` (включая `fallback_rate_max`) и `golden_corpus.json`; сгенерированные `configs/rive/` и `configs/soar/`; флаги `ai_backend`/`nlu_backend`/`dialogue_backend`/`inference_backend` и `npc_policy.backend`/`backends`/`agent_pool`, `character_agency.tick_budget_ms`, `faction_policy.backend`/`backends`, `reaction_policy.backend`/`backends`; `test_cognition_*.py`, `test_soar_full_runs.py`, `test_d2_state.py`, `test_soar_snapshot.py`, `test_d6_pragmatics.py`, `test_d6_inference.py`, `test_nlu_backend.py`, `test_npc_decisions.py`, `test_soar_bridge.py`; [`SOAR_RIVESCRIPT_MIGRATION.md`](SOAR_RIVESCRIPT_MIGRATION.md) |
| Автоматы редактора | `configs/automata/*.json` (каталог пуст); `automata/storage.py`; `test_automata.py` |

### 0.8. Изменить имена и политики имён

Кратко: Империя — только европейские имена, германские вероятнее остальных
европейских; Республика — преимущественно обычные имена без прозвищ и
эпитетов, с редкой фэнтези-темой; Торговая планета — любые имена без
прозвищ и эпитетов; Культ — только религиозные прозвища. Мужскому персонажу — только
мужские имена, женскому — только женские. Полная спецификация и таблица
алиасов — [`NAMING.md`](NAMING.md); код — `naming/people.py`,
`configs/naming/policies.json`; тесты — `test_naming.py`, `test_people.py`,
`test_lore_characters.py`.

### 0.9. Изменить UI

| Потребность | Куда идти |
|---|---|
| Кампанийный UI `view/` | `view/app.py`, `view/screens/`, `view/ui/`; [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md); тесты `test_view.py`, `test_view_world.py` |
| Сценный UI `ui/` | `ui/app.py`, `ui/scenes/`, `ui/battlefield.py`; [`history/UI.md`](history/UI.md); тесты `test_ui.py`, `test_battlefield.py` |
| Экран взаимодействий | `ui/scenes/interaction.py`, `interaction/`; [`INTERACTION.md`](INTERACTION.md); `test_interaction.py` |
| Редактор автоматов | `automata/`; [`AUTOMATA.md`](AUTOMATA.md); `test_automata_ui.py` |
| Ассеты и плейсхолдеры | `assets/`, `configs/view/presentation.json` (нет в поставке); `test_gui_smoke.py` |

### 0.10. Сохранения, снимки, совместимость

| Потребность | Куда идти |
|---|---|
| Сейвы `view/` | `view/app.py`, `ui/save.py`; `SAVE_VERSION`; тест `test_save_system.py` |
| Снимок мира и кампании автоматов | `SCHEMA_VERSION = 3` (аватар, `entity_ref`/обязательства, сцена, окно исхода); `migrate_snapshot()`; `WorldEngine.to_dict()/load_snapshot()`; `test_projections.py`, `test_migrations.py` |
| Контент без Python | `test_content_without_python.py`; `configs/schemas/` и `campaign/content_schema.py`; `content_lint`; `test_content_lint.py`, `test_content_schema.py` |
| Стабильность кампании | `test_campaign_golden.py`; `tests/fixtures/golden/empire_seed13.json` |
| Восприятие и провенанс | `campaign/perception.py`; `build_knowledge(view=...)`; `configs/dialogue/world.json` блок `perception`; `test_perception.py`, `test_provenance.py` |
| Перенос `health/sickness/wound` | `core41/model.py` (`condition_state`, `load_condition`); `test_health.py`, `test_sickness.py` |
| Версии чекпойнтов | `agents/policies.py`, `agents/checkpoints.py`; `test_checkpoints.py`; [`AGENTS.md`](AGENTS.md) §4 |

### 0.11. Собрать, упаковать, проверить

| Потребность | Куда идти |
|---|---|
| Упаковка | `packaging/`, `packaging/README.md` |
| Все тесты | `venv/bin/python -m pytest -q`; карта ниже в §0.14 |
| Стиль | `venv/bin/python -m pycodestyle`; `setup.cfg` (`max-line-length = 79`) |
| Проверка компиляции | `venv/bin/python -m compileall core41 agents campaign automata naming systems organizations interaction view ui` |
| Согласованность документации | `tests/test_docs_sync.py`, `tests/test_docs_core41.py` |

### 0.12. Карта пакетов

| Пакет/файл | Роль | Статус |
|---|---|---|
| `main.py` | единая точка входа | активный |
| `core41/` | ядро 4-2-1: `Work`, `Automaton`, арена, среда, клок, payload | активный срез |
| `agents/` | политики, обучение, чекпойнты | активный |
| `campaign/` | кампании автоматов (работа: `work.py` → `handlers.py` → `work_trace.py`, проекции `effects.py`, открытые формы/действия `actions.py`, доклады источников `dispatch.py` + `dispatch_*.py`, движок `automata.py` + `automata_*.py`), дневной мир `world_actor` (`world.py` — фасад, реализация в `world_*.py`), локальные сцены `scenes.py`, суточная рутина `routine.py`, качественные уровни `qualitative.py`, аудит `audit.py`, восприятие `perception.py`, предметы-автоматы `item_automaton.py`, свободные часы `free_clock.py` | активный |
| `campaign/dialogue/` | детерминированный диалог: парсер, вывод, планы, синтез, стили, дискурс, сравнения, контрфакты, речевые действия | активный |
| `campaign/cognition/` | когнитивный фасад: `understand`/`decide`, `UtteranceFrame`, `soar_bridge.v1`, золотой корпус, parity; единственное место для будущих импортов Soar/RiveScript | активный фундамент |
| `automata/` | редактор автоматов | активный инструмент |
| `naming/` | имена и названия | активный инструмент |
| `systems/` | среда/события/драматург | активный инструмент |
| `organizations/` | организации-суперсистемы, 16 потребностей | активный инструмент |
| `interaction/` | доменно-нейтральные взаимодействия | активный инструмент |
| `view/` | кампанийный UI | активный |
| `ui/` | сценный UI и тактическое поле | активный + легаси-сцены |
| `game_engine.py` | арена + HUD на `core41` (легаси-клиент, к удалению) | активный |
| `simulation.py` | легаси-канон дуэлей | легаси/baseline |
| `warfare.py` | войсковые автоматы (фасад; персонаж — `warfare_character.py`, константы — `warfare_core.py`) | отдельный слой |
| `observability.py`, `lod.py`, `information.py` | наблюдаемость, LOD, энтропия | текущий код |

### 0.13. Карта конфигов

| Каталог | Что лежит в поставке | Загрузчик |
|---|---|---|
| `configs/roles/` | `roles.json` — 5 ролей (4 лидера + `free_citizen`) | `campaign/roles.py` |
| `configs/storylines/` | 5 сюжетов + сцены (4 лорных + `free_life`), у каждого `storyline_tags`; у 4 лорных — только метаданные и сцена `gameplay`, сюжет собирается из `AutomataCampaign.narrative`; у `free_life` — `world_briefing` + `world`, без главы и `days` | `view/support/storyline.py`, `campaign/chronicle.py` |
| `configs/campaigns/` | 4 шаблона + `base/`; `base/handlers/*.json` — правила получателя по формам работы; `forms.json` — манифест 19 форм; `base/chronicle_phrases.json` — языковые шаблоны хроники | `campaign/preset.py`, `campaign/defaults.py`, `campaign/handlers.py`, `campaign/actions.py`, `campaign/chronicle.py` |
| `configs/content/` | приказы, документы, диалоги, время, LOD | `view/support/content.py` |
| `configs/characters/` | `traits.json` (12 черт), `bdi.json` (16 желаний), `divisions.json` (15 делений), `identity.json`, `archetypes.json` | `character_traits.py`, `bdi.py`, `campaign/divisions.py`, `campaign/identity.py` |
| `configs/systems/` | `environment.json`, `events.json`, `playwright.json` | `systems/` |
| `configs/dialogue/` | онтология, лексикон, грамматика, правила, факты, планы, синтез, стили, `style_context`, дискурс, сравнения, контрфакты, цели и шаги, псевдонимы действий, текстовый интерфейс, мост к миру | `campaign.dialogue.loader` |
| `configs/cognition/` | `backends.json` — флаги `ai_backend`/`nlu_backend`/`dialogue_backend`/`inference_backend`, режимы, пороги и таймауты; `golden_corpus.json` — 144 зафиксированных кадра диалога | `campaign.cognition.load_flags()`, `python -m campaign.cognition.corpus_builder --check` |
| `configs/rive/` | сгенерированные `dialogue.rive` и `manifest.json` (не редактировать вручную) | `python -m campaign.cognition.rive_compiler --write` |
| `configs/soar/` | `decision.json` — формула, пороги и настройки выбора NPC; `intention.json` — выбор BDI-намерения; `faction.json` — выбор действия/приказа фракции; `reaction.json` — реакция на доклад/угрозу; `rl.json` — RL-предпочтения и пороги сравнения; `pragmatics.json` — план/раскрытие; `inference.json` — runtime логического вывода; `*.soar` генерируются и не редактируются вручную | `python -m campaign.cognition.soar_compiler --write`, `python -m campaign.cognition.intention_compiler --write`, `python -m campaign.cognition.faction_compiler --write`, `python -m campaign.cognition.reaction_compiler --write`, `python -m campaign.cognition.rl_compiler --write`, `python -m campaign.cognition.pragmatics_compiler --write`, `python -m campaign.cognition.inference_compiler --write` |
| `configs/naming/` | лексикон, классы, взаимодействия, люди, политики | `naming/` |
| `configs/worlds/` | production: `agora_world.json` (44 узла, 72 должности, 65 действий после слияния каталогов, 8 предметов, 6 сцен, `norms`, `sandbox`/`realtime`/`time_speeds`; без `days` и главы), `actions/*.json`, `scenes/*.json`, `agora_strategies.json`, `biography.json` | `campaign/world.py`, `campaign/actions.py`, `campaign/scenes.py`, `campaign/node_strategy.py` |
| `configs/knowledge/commonsense/` | курированные факты «субъект — отношение — объект»: речевые акты, режимы, причины эмоций, свойства предметов; `style_hints` связывают режим со стилем ответа; `raw/` — исходные LLM-выгрузки только для провенанса. Используется подсказкой `/смысл` и корпусом парафраз | `campaign/commonsense.py` |
| `configs/strategy/` | **пуст** | `campaign/strategy.py` |
| `configs/automata/` | **пуст** | `automata/storage.py` |
| `configs/environments/` | **пуст** | `core41/environment.py` |
| `configs/presets/`, `configs/classes/`, `configs/view/` | **пусты** | соответствующие слои |
| `checkpoints/` | production-чекпойнты | `agents/checkpoints.py` |
| `tests/fixtures/content/` | тестовый контент, включая мир | тесты |

### 0.14. Карта тестов

| Область | Тесты |
|---|---|
| Ядро и арена | `test_core41.py`, `test_health.py`, `test_sickness.py`, `test_payload.py`, `test_composite.py`, `test_environment.py`, `test_clock.py`, `test_math_model.py` |
| Агенты | `test_train_cli.py`, `test_checkpoints.py`, `test_core41.py` |
| Кампания автоматов | `test_automata_campaign.py`, `test_automata_network.py`, `test_campaign_golden.py`, `test_bdi.py`, `test_divisions.py`, `test_events_runtime.py` |
| Доклады источников | `test_campaign_dispatch.py`, `test_campaign_reports_overlay.py`, `test_campaign_overlays.py`, `test_perception.py`, `test_provenance.py` |
| Дневной мир | `test_campaign.py`, `test_world.py`, `test_world_primitives.py`, `test_world_work.py`, `test_scene.py`, `test_free_clock.py`, `test_campaign_energy.py`, `test_campaign_economy.py`, `test_campaign_relations.py`, `test_campaign_values.py`, `test_campaign_coalitions.py`, `test_campaign_planner.py`, `test_campaign_control.py`, `test_campaign_clock.py`, `test_campaign_logbook.py`, `test_campaign_routine.py`, `test_campaign_stats.py`, `test_campaign_success.py`, `test_projections.py`, `test_node_strategy.py` |
| Контент и документы | `test_content_pipeline.py`, `test_content_lint.py`, `test_content_schema.py`, `test_action_processes.py`, `test_docs_sync.py`, `test_docs_core41.py`, `test_identity.py`, `test_archetypes.py`, `test_player_avatar.py`, `test_story_arcs.py`, `test_narrative_emergence.py`, `test_storyline_flex.py`, `test_lore_characters.py`, `test_commonsense.py`, `test_items.py` |
| Когнитивный фасад | `test_cognition_frame.py`, `test_cognition_backends.py`, `test_cognition_nlu.py`, `test_cognition_corpus.py`, `test_cognition_corpus_builder.py`, `test_cognition_parity.py`, `test_cognition_rive.py`, `test_cognition_macros.py`, `test_cognition_lint.py`, `test_cognition_soar.py`, `test_cognition_boundaries.py`, `test_npc_decisions.py`, `test_soar_bridge.py` |
| Диалог | `test_dialogue.py`, `test_d1_dialogue.py`, `test_d1_5_synthesis.py`, `test_d2_state.py`, `test_d3_comparison.py`, `test_d4_social.py`, `test_d5_discourse.py`, `test_d5_discourse_paragraph.py`, `test_d5_registers.py`, `test_d5_style_hints.py`, `test_dialogue_fallback.py`, `test_d6_pragmatics.py`, `test_d6_inference.py`, `test_view_dialogue_chat.py` |
| Инструменты | `test_automata.py`, `test_automata_ui.py`, `test_naming.py`, `test_people.py`, `test_systems.py`, `test_organizations.py`, `test_organization_runtime.py`, `test_interaction.py` |
| UI и сейвы | `test_ui.py`, `test_view.py`, `test_view_world.py`, `test_view_rts.py`, `test_view_strategy.py`, `test_battlefield.py`, `test_gui_smoke.py`, `test_save_system.py`, `test_world_text.py`, `test_logging_setup.py` |
| Легаси и прочее | `test_canon.py`, `test_strategy.py`, `test_warfare.py`, `test_advanced.py`, `test_breakthrough_balance.py`, `test_soak.py`, `test_checks.py`, `test_domain_audit.py` |

### 0.15. Быстрые команды

```bash
venv/bin/python -m pytest -q                       # все тесты
venv/bin/python -m pycodestyle                     # стиль
venv/bin/python -m agents.train --episodes 500 --seed 0
venv/bin/python -m campaign.dialogue.lint         # проверка диалоговых данных
python3 main.py                                    # клиент view/
python3 main.py --arena                            # арена
python3 main.py --automata                         # редактор автоматов
python3 main.py --log                              # файловый журнал (перезапись)
python3 main.py --log-file /tmp/game.log           # свой путь журнала
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy venv/bin/python -m pytest -q tests/test_gui_smoke.py
```

---

## 1. Что за проект

`Ozvering-Project` — проект симуляции мира, а не только общества. Целевой мир
включает природу, персонажей, организации, предметы и социальные структуры.
Все они описываются одной онтологией **4-2-1**, а не набором несвязанных
симуляторов.

В репозитории одновременно существуют:

- **текущий код** — `simulation.py` (легаси-канон дуэлей), `campaign/world.py`
  (кампания с дневным ходом), `warfare.py`, UI и инструменты;
- **целевая модель мира** — 4-2-1, одна универсальная энергия, BDI/не-BDI,
  реальное время, бесконечная RTS;
- **переходный период** — целевая модель описана; `core41` и `agents` уже
  работают в активных сценах арены и тактического поля, но кампания и
  остальной мир ещё не мигрированы.

Текущий `WorldEngine` — **не ядро** будущего мира. Это узкий частный случай
для должностей и организаций. Его нужно рассматривать как легаси-слой; вопрос,
выводить ли его из общей модели или оставлять совместимым слоем, относится к
миграции.

---

## 2. Ядро 4-2-1

Каждая сущность мира — конечный автомат или часть автомата:

```text
A_i = (I_i, O_i, H_i, S_i; F_i, E_i; W_i)
```

| Элемент | Смысл |
|---|---|
| `I` | входы: какие воздействия автомат способен принять |
| `O` | выходы: какие воздействия он способен отправить |
| `H` | обработчики: правила преобразования входов в выходы/работу |
| `S` | состояния: внутренняя конфигурация, память, здоровье, отношения |
| `F` | сила: способность оказывать/выдерживать работу и сопротивляться |
| `E` | универсальная энергия: способность совершать работу |
| `W` | работа: процесс/поток взаимодействия |

### 2.1. Взаимодействие

Всё взаимодействие — отправка работы. У работы **нет встроенного эффекта**:
результат определяется контекстом:

- выходом адресанта;
- входом адресата;
- обработчиками обеих сторон;
- состояниями;
- силой и энергией;
- участием третьих автоматов.

Один и тот же хлеб может накормить, стать товаром, подарком, взяткой или
уликой. Это не разные виды энергии, а разные контексты одной работы.

### 2.2. Принятая семантика `F`, `E`, `W`

Принято:

- `E` — неотрицательный скаляр универсальной энергии. Работа тратит `E`;
  входы могут пополнять или конвертировать `E` через обработчик; потери
  уходят в энтропию/отходы.
- `F` — неотрицательный скаляр силы/пропускной способности/сопротивления.
  `F` не является энергией; она ограничивает максимальную работу за интервал
  и защищает от входной работы; её можно повредить и восстановить.
- `W` — поток работы:

```text
W = {amount, form, payload, duration}
```

`amount` измеряется в единицах энергии. `form` — канал/форма воздействия
(физическая, информационная, денежная, принудительная), но **не отдельный тип
энергии**. `payload` — полезная нагрузка. `duration` — длительность.

Энергетический баланс:

```text
E_i -= amount
E_j += amount * efficiency(context)
loss  = amount * (1 - efficiency(context))
```

Это только баланс. Направление эффекта — лечение, урон, убеждение,
обогащение, заражение — определяет обработчик получателя `H_j`. Работа может
как добавлять энергию, так и отнимать её или повреждать `F`.

---

## 3. Принятые решения

| Вопрос | Решение |
|---|---|
| Онтология | 4-2-1: входы, выходы, обработчики, состояния; сила и энергия; работа |
| Энергия | одна универсальная; типизированной энергии нет |
| Конверсия | через контекст и обработчики; с потерями, энтропией и lossy-агрегацией |
| Успех | логистическая формула от навыков, полномочий и сопротивления |
| Отношения | асимметричные; `R_ij ≠ R_ji` |
| Разумность | BDI / не-BDI; без деления на три типа |
| BDI-сущности | все сущности с индивидуальным или коллективным сознанием |
| Игрок | BDI-автомат под управлением человека |
| Предметы | сознания не имеют, BDI у них нет; могут действовать автономно через обработчики |
| Время | бесконечная RTS; при `1x` одна реальная секунда равна одной игровой |
| Скорости | явные множители `≥ 1x`; пауза, замедление ниже `1x` и rewind запрещены |
| Ускорение | автоматически прерывается на критических событиях |
| Фон | первый срез: ограниченный фоновый догон при неактивном окне и оффлайн-догон после загрузки (`saved_at`, `MAX_CATCHUP_DAYS`) |
| Победа | объективной победы нет; условие «дожил до 31 дня» убрано |
| Поражение | смерть персонажа при `force <= 0` (здоровье/болезнь — состояния BDI); распад организации |
| Распад организации | первый срез: `power`/`cohesion <= 0.05` в течение 2 дней подряд (полный ноль — сразу) |
| Увольнение | смена роли: другая должность в той же структуре или выбор роли вне службы; не поражение |
| Старые шкалы | проекции ядра, не независимые ресурсы |
| Слои | навыки растут, персонажи действуют сами, предметы — автоматы |
| Текущий `WorldEngine` | не ядро, а легаси-частный случай |
| Реализация | начата: срез `core41` и обучаемые агенты |

### 3.1. Логистический успех

Минимальная форма:

```text
p = sigmoid(
    β0
  + β_skill * skill
  + β_authority * authority
  - β_resistance * resistance
  + β_context * context
)
```

`resistance` — не только сила цели, но и её обработчик, состояние и вход.
Один и тот же акт может быть принят, отторгнут, переработан или усилен.
Точный список предикторов, коэффициенты и бинарность/маржа успеха ещё
открыты.

### 3.2. BDI и не-BDI

Есть два режима:

- **BDI-автоматы** — убеждения (beliefs), желания (desires), намерения
  (intentions). Они выбирают работу на основе ожиданий, памяти, целей и
  отношений. BDI имеют персонажи, организации и все сущности с
  индивидуальным или коллективным сознанием.
- **Не-BDI автоматы** — фиксированные обработчики, пороги, рефлексы. Танк,
  автомобиль, инструмент, река, погода. Предметы сознания не имеют, поэтому
  BDI у них нет.

BDI — не третий тип и не отдельная онтология. Это свойство обработчика и
состояния. BDI-автомат всё равно имеет `I/O/H/S/F/E/W` и отправляет работу.

**Граница текущей реализации.** `BDIState` с 16 желаниями есть у
`warfare.Character` — это персонажи арены, automata-кампаний и отрядов
RTS-мира. Персонажи дневного мира (`campaign/character.py`,
`CampaignCharacter`) и игрок мира (`campaign/actor.py`, `CampaignActor`) —
упрощённые `Automaton`-обёртки без BDI; их отношения, доверие, здоровье и
болезнь живут отдельными полями. То есть тезис «BDI у всех персонажей» —
целевая модель, а не текущее покрытие.

Игрок — BDI-автомат под управлением человека. Человек принимает решения, но
сам автомат имеет состояние, потребности, отношения и ограничения. Граница
между человеческим управлением и автономией BDI пока открыта.

### 3.3. Одна универсальная энергия

Типизированной энергии нет. Это означает:

- хлеб может превратиться в деньги через торговлю;
- конверсия идёт через обработчик рынка/торговли, требует подходящего входа
  и состояния и происходит с потерей;
- без рынка, покупателя или обработчика хлеб не станет деньгами;
- одна и та же энергия в разных контекстах даёт разные эффекты;
- прямое «хлеб → политическая кампания» без цепочки обменов и потерь
  невозможно;
- сила не превращается в энергию автоматически; нужен обработчик
  (разрушение, сжигание, продажа имущества) с потерей.

Одна энергия не означает одинаковый эффект. Контекст — вход, выход,
обработчик, состояние и третьи автоматы — решает, что произойдёт.

### 3.4. Поражение и рамка

Убираются:

- объективная победа;
- условие «дожил до 31 дня — победил»;
- финальный `win` как цель.

Остаются только поражения:

- смерть персонажа при `force <= 0`; пренебрежение здоровьем и болезнь —
  условия BDI, которые ведут к падению силы;
- распад организации.

Для старта распад организации считается потерей силы: `power` или
`cohesion` узла героя не выше `0.05` в течение `COLLAPSE_GRACE_DAYS = 2`
дней подряд (полный ноль обеих шкал — сразу). Легитимность ниже `0.02` пока
только усиливает сигнал хрупкости от `organization_status()`, а не завершает
игру сама. Более глубокий критерий (легитимность, обработчики, коалиции,
энергия) остаётся открытым.

Увольнение — не поражение, а переход в другую роль. При `standing <= 0.05`
или легитимности структуры `<= 0.08` герой теряет должность и получает
другую доступную роль в той же структуре; если роли нет, остаётся вне
службы и выбирает её через UI. Добровольная отставка (`resign`) использует
тот же путь. Игрок может продолжать после потери должности; после смерти —
нет. Рынок труда, очередь кандидатов и переговоры с соперником реализованы;
открыты автоматическая карьера политики и полная экономика распада
коалиций.

Бесконечная рамка: `WorldEngine.infinite = True` по умолчанию, прохождение
`days` только помечает `horizon_passed`; нарративный финал задаётся
`end_storyline()`/`effects["ending"]` (`win`, `lose`, `neutral`), причём
`neutral` не даёт объективной победы и терминального бонуса. Блок
`storyline` в конфиге мира добавляет главу: `deadline_day` и пороги
`win.standing_at_least` / `lose.standing_at_most` + `lose.days`; без блока
мир остаётся бесконечным. В свободном режиме `sandbox: true` отключает
главу и горизонт, production-мир `agora_world.json` не задаёт `days`, а
`realtime: true` включает `FreeClock`; скорость не опускается ниже `1x`,
rewind отсутствует.

### 3.5. Старые шкалы — проекции

Ядро хранит `F`, `E`, `S`, отношения и автоматы. Старые шкалы вычисляются из
ядра:

| Старое | В 4-2-1 |
|---|---|
| `wealth` | денежная форма `E` |
| `power` | проекция `F` + полномочия + отношения |
| `legitimacy` | состояние `S` |
| `cohesion` | состояние `S` |
| `reach` | ограничение выхода `O`/канала |
| `capacity` | ограничение обработчика `H` |
| `standing` | состояние/репутация; условие сюжетного финала при заданном `storyline` |
| `influence`, `favor`, `evidence` | состояния, права или обязательства |
| `health` | новое состояние/потребность |

Нельзя держать две независимые модели. При миграции проекции можно временно
вычислять для UI и старого контента, но источником остаётся ядро.

### 3.6. Сводка формул

Полный разбор с обозначениями, единицами, примерами и таблицами констант —
в [`FORMULAS.md`](FORMULAS.md). Здесь только карта:

| Блок | Главная формула | Где смотреть |
|---|---|---|
| Конверсия работы | `loss + entropy + stored = amount` | [`FORMULAS.md`](FORMULAS.md) §1 |
| Успех ядра | `p = sigmoid(intercept + skill·S·… − resistance·R + …)` | §2 |
| Кампанийный шанс | `clamp(base + 0.30·(core−0.5), 0.05, 0.95)` | §2.2 |
| Отношения | `shift = Σ weight·axis`, предел `±0.20` | §2.3 |
| Урон | `health_damage = overflow · 0.25 · множители` | §3.1 |
| Болезнь | `sickness += 0.004·decay` без отдыха, `H −= 1.5·sickness` | §3.3 |
| Рана | `H −= 0.60·wound`, заживает отдыхом и `TREAT` | §3.4 |
| Захват | `dom ≥ 36` при `E ≥ 1.5·E_opp` и `F > F_opp` | §4.2 |
| Награда арены | потери сторон + цена `E` + терминальный `±1` | §5 |
| Дрейф организации | `d_cohesion/d_power` от легитимности и казны | §6.2 |
| Распад | `power`/`cohesion ≤ 0.05` два дня подряд | §6.4 |
| Экономика | `price = effect/efficiency`; обмен денег с потерей | §7 |
| Коалиции | `0.5·(avg(R_a→b)+avg(R_b→a)) + 0.06·min(oblig, 3)` | §8.1 |
| Награда кампании | нормированные дельты `standing/power/cohesion/H` + исход | §9 |
| Время | арена `1 с/такт`; кампания `1:1`, цикл `86400 с`, действие `21600 с` | §10 |
| Легаси | `p = P_BASE/(1+e^(−K_MASS·ln(mass)+penalty))` | §11 |

**Правило чтения.** Формулы ядра и их константы живут в коде ядра
(`core41/model.py`, `core41/arena.py`); данные мира (темп, цены, пороги
контента) — в `configs/`. Если число нужно и коду, и контенту, оно должно
иметь явное переопределение, а не две независимые копии.

---

## 4. Текущее состояние и цель

| Область | Сейчас | Цель |
|---|---|---|
| `simulation.py` | легаси-канон дуэлей, тики, `force`/`energy_pool`, контекстные фазы типа; активные сцены его не используют | не трогать без отдельного решения; целевой мир — 4-2-1 |
| `core41/` | срез 4-2-1: `Work`, `WorkReport`, `Automaton`, `DuelWorld`, `DuelEnv`, `ArenaAgent`, `ArenaMatch`, `run_duel_tick`, `SimulationClock`; одна универсальная энергия, обработчики, логистический успех, конверсии с потерями, здоровье/смерть, секундный тик и скорости | полный мир, кампанийный планировщик |
| Кампания автоматов (работа) | `campaign/work.py` строит `WorkPlan`; `campaign/handlers.py` выбирает JSON-правило по `form`; `apply_report` применяет проекции; `trace` версии 1 | дневной мир на том же конвейере (фаза 4b), кампании автоматов и сцена P6 |
| `campaign/actions.py` | манифест форм (`FormCatalog`), `ActionSpec`-нормализация и линтер, слияние каталогов по `id`, `entity_ref`, `build_spec_work`, выключенная по умолчанию импровизация | UI-адресация P6 |
| `campaign/item_automaton.py` | предмет как автомат `I/O/H/S/F/E/W`: нормализация JSON, обработчики, `F/E/S`, журнал `W`, снимок и восстановление; эффекты применяет `WorldEngine` | автономные реакции предмета без действия игрока |
| `agents/` | `BDIPolicy`, `QTablePolicy`, `ArenaAgent`-политики, `PolicyAgent` как легаси-мост, `load_policy`, online-обновление и CLI обучения; у BDI отдельные `campaign_weights` | production-модель, оценка и кампанийная загрузка чекпойнтов |
| Здоровье | `H=100`, отдых `+0.78/тик`, голод `-0.20/тик`, переполнение урона с коэффициентом `0.25` после `F=0`; факторы `aging/illness/stress/care`; болезнь `sickness ∈ [0,1]` с прогрессом, уроном, отдыхом, `treat()` и шестым действием `TREAT`; контактная передача `CONTAGION_*`; средовой резервуар болезни и острые раны `ArenaEnvironment`; кампанийная передача в одном узле; `condition_state()` и сейв текущих `health`/`sickness`; дневной срез болезни/смерти/распада в кампании; калибровка §2.3.2–2.3.5 | production-планировщик сквозного цикла игрока |
| `campaign/world.py` | дневной ход; production-мир `configs/worlds/agora_world.json` (44 узла, 72 должности, 65 действий после слияния `action_catalogs`, `norms`, `sandbox`/`realtime`, без `days` и главы), тестовый мир в `tests/fixtures/content/configs/worlds/`; `power/wealth/...`, `CampaignActor` на `E/F/H`, planner, экономика, отношения, ценности, коалиции; `entity_ref`/`target_ref` для персонажа, предмета, нормы, обязательства и узла; эффекты `item`/`item_work`/`norm`/`obligation` и `cost.items`; `requires.target_status` для отмены нормы и `requires.item_handler` для предмета; `relation_axes`/`relation_effect_weights` из конфига мира, эмоциональные оси `romance/family/ritual/vassalage`; grace-распад, смена роли, бесконечный горизонт, ограниченный догон; `profile_from_identity` собирает профиль свободного режима без фракции; навыки растут от действий с насыщением `CAMPAIGN_SKILL_CAP`; доход должности возвращает влияние/связи; блок `storyline` задаёт главу с `deadline_day`, `sandbox` отключает её | полная миграция организационных шкал в `F/E/H`, автоматическая карьера политики |
| `campaign/free_clock.py` | RTS-часы свободного режима: физические секунды, скорость `>= 1x`, без rewind, снимок часов | — |
| `campaign/clock.py` | `CampaignClock`, `offline_days`, `background_pause_reason`; `86400` физических секунд в сутках, догон не больше 7 дней | production-планировщик сквозного цикла игрока |
| `campaign/dialogue/` | read-only диалог над BDI и кампанией: разбор, вывод, планы, синтез, стили и дискурс D5.1–D5.4, сравнения D3.1, контрфакты D3.2/D6.2a–c, условия/уступки/косвенная и прямая речь, beam и корпус парафраз D6.2d, раскрытие и ложь D6.3, речевые действия D4 и 7 новых актов P5, память, цели/мост/императивы/псевдонимы D6.4, проекция каталога действий F-13, призма восприятия F-23, реестр типов ответа F-15, адаптеры мира F-16, живой мост F-17 (`declared`/`improvised`, `work`/`trace`), headless-текстовик D7.0, речевые акты как interactions кампании D7.1, перемещение по геометрии игрока D7.2, время и темп D7.3, описание сцены D7.4, аудит лексикона D6.1, `has_leverage`/`blackmail` D7.1 | — |
| `WorldScreen` | бесконечный день, смена должности, фоновый догон, win/lose/neutral в авторских мирах; вкладки «Персонажи/Организации/Нормы/Личность», адресация персонажа, предмета и нормы через `entity_ref`; в свободном режиме — RTS-время, `−`/`+` скорости, песочница (`test_view_world_targets.py`) | бесконечная RTS, только поражения |
| ИИ арены | `core41.ArenaAgent`: QTable/BDI-политики, `UtilityAI` — только baseline и эксперименты | BDI/не-BDI, стоимость работы, энергия |
| ИИ кампании | рейтинг действий, стоимость `E`/ресурсов, отношения, стратегии и коалиции в `_ai_score` | BDI/не-BDI, полная стоимость работы и энергии |
| Энергия | активные сцены — одна универсальная через `core41.arena`; `simulation.py` — контекстные фазы типа | одна универсальная энергия во всём мире |
| Предметы | автоматы `I/O/H/S/F/E/W` (`campaign/item_automaton.py`): `inputs`/`outputs`/`handlers`/`state`/`force`/`energy`/`work`, действие `use_item`, снимок состояния | расширение обработчиков и автономные реакции без игрока |
| Персонажи | частично автономны | BDI-автоматы, действуют сами |
| Старые шкалы | основные | проекции ядра |

**Важно:** текущий `simulation.py` остаётся действующим каноном легаси-кода,
а не целевой моделью мира. В нём есть трёхфазный тип энергии
(`WATER/FIRE/EARTH`). Активные сцены (`game_engine.py` и
`ui/battlefield.py`) уже используют `core41` с одной универсальной энергией и
контекстными обработчиками. `core41` пока остаётся дуэльным/аренным срезом, а
не всем миром; вопрос о переносе/удалении механизма `simulation.py` относится
к миграции кампании и пока не закрыт.

**Граница кампании и легаси-боя.** Прямых импортов `warfare`/`simulation`
в `campaign/` на верхнем уровне больше нет: `campaign.automata` и
`campaign.preset` создают `warfare.Character` лениво, внутри функций.
Поэтому `import campaign.automata` не загружает `warfare`. Остаётся
транзитивная зависимость через
`organizations.runtime.OrganizationRuntime`, который наследует
`simulation.Environment`; она зафиксирована guard-тестом
`tests/test_architecture_boundaries.py`. Полный разрыв потребует вынести
`Agent`/`Environment` в нейтральный модуль — это отдельная миграция.

---

## 5. Инварианты проекта

Это **целевые** инварианты. Текущий код может им не соответствовать; различия
перечислены в разделе 4 и в [`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md).

1. **Контекст важнее воздействия.** Эффект работы определяется входом,
   обработчиком, состоянием получателя и третьими автоматами.
2. **Нет прямых изменений статистики без работы.** Любое изменение состояния
   имеет вход/работу/обработчик.
3. **Нет бесплатных действий.** Работа стоит энергию/силу/время.
4. **Одна универсальная энергия.** Конверсии идут через обработчики, с
   потерями и энтропией.
5. **Сила и энергия — разные вещи.** Их нельзя смешивать без обработчика.
6. **BDI только у сознающих сущностей.** Предметы сознания не имеют.
7. **Природа — не декорация.** У неё есть обработчики, состояния и работа.
8. **Предметы и персонажи — автоматы.** Не бонусы к строке.
9. **Победы нет.** Есть цели игрока/сценария и условия поражения.
10. **Отношения асимметричны.**
11. **Композиция.** Организация — автомат из автоматов.
12. **Время непрерывно.** Действия имеют длительность; ускорение не отменяет
    причинность и стоимость.
13. **Наблюдаемость.** Игрок должен видеть, почему работа удалась/провалилась.
14. **Старые шкалы — проекции.** Не два параллельных мира.
15. **Эпистемическая непрозрачность.** Объективное состояние мира недоступно
    персонажу напрямую. Персонаж знает о мире только то, что есть в его
    убеждениях. Информация попадает в убеждения только через
    индивидуальную призму восприятия — с источником, каналом, уверенностью
    и возможным искажением. Прямая запись «мир → убеждение» запрещена.
    Реплики, слухи и ложь живут в слое разговора и не подменяют мир; факты
    мира принадлежат кампании, а не диалогу или сцене.
16. **Физическое время.** При скорости `1×` одна реальная секунда равна
    одной игровой секунде. Ускорение — только явный множитель `speed`;
    замедление ниже `1×`, пауза и rewind запрещены. Контентное поле
    `realtime.game_seconds_per_real_second` не может нарушить соответствие:
    оно нормализуется к `1.0`, а старые значения вроде `3600` игнорируются.
    Свободные сутки тоже физические: `seconds_per_day = 86400`.
17. **Люди — субъекты, а не бонусы.** У персонажа фракции есть личная цель,
    доверие, обида и память приказов. Цель двигает выбор работы, исполнитель
    влияет на её эффект, а приказ формирует поддержку или саботаж. Автономия
    задаётся данными `ai_model.character_agency`, а не зашита в код.

---

## 6. Карта документации и статусы

Статусы означают:

- **канон** — проектное решение, ему подчиняются остальные документы;
- **текущая реализация** — описывает код сегодня, может отставать от цели;
- **легаси** — сохраняется для воспроизведения, не активный поток;
- **руководство** — как что-то сделать, не источник онтологии;
- **исторический** — заморожен, числа и выводы относятся к своей дате;
- **трекер** — список работ, не описание модели.

### 6.1. Активные документы

| Документ | Роль | Статус |
|---|---|---|
| `SOURCE_OF_TRUTH.md` | главный источник истины и навигатор | канон |
| [`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md) | целевая модель 4-2-1, реестр закрытых решений и открытых пунктов (§7.0) | канон целевой модели |
| [`FORMULAS.md`](FORMULAS.md) | формулы ядра, арены, кампании и легаси: обозначения, единицы, примеры | справочник текущего кода + целевых констант |
| [`WORLD.md`](WORLD.md) | текущий поток `world_actor`/`WorldEngine` | текущая реализация |
| [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) | кампании автоматов: фракции, органы, темп, исходы, конвейер работы | текущая реализация |
| [`CAMPAIGN_EVENTS_BDI.md`](CAMPAIGN_EVENTS_BDI.md) | BDI, доклады, слухи, перехваты, контрмеры и лента событий кампании | текущая реализация |
| [`CAMPAIGN_LOGIC_AUDIT.md`](CAMPAIGN_LOGIC_AUDIT.md) | разбор исправленных проблем игрового слоя кампании и их проверки | аудит, не канон |
| [`WORK_MECHANIC_PLAN.md`](WORK_MECHANIC_PLAN.md) | действующий конвейер работы и открытый остаток; полный план — в `history/` | статус + остаток |
| [`AUTOMATA_GEOMETRY.md`](AUTOMATA_GEOMETRY.md) | семантическая геометрия автоматов: расстояния, углы, ориентация из JSON | текущая реализация (этап A) + план |
| [`AGENTS.md`](AGENTS.md) | слой обучаемых агентов и RL-срез `core41` | текущая реализация |
| [`ALGORITHMS.md`](ALGORITHMS.md) | точный справочник алгоритмов: такт, формулы, признаки, Duel-MLP, обучение | текущая реализация |
| [`CONTENT.md`](CONTENT.md) | JSON-контент, папки и загрузчики | руководство |
| [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md) | BDI, 15 делений, события и производные активы фракции | руководство |
| [`CONTENT_PLAN_LORE.md`](CONTENT_PLAN_LORE.md) | контент-план по лору: предикаты, сути, работы, органы, автоматы | проектный документ + источник контента |
| [`NAMING.md`](NAMING.md) | имена, культуры, фракционные политики | текущая реализация |
| [`ORGANIZATIONS.md`](ORGANIZATIONS.md) | организации, 16 потребностей, runtime | текущая реализация |
| [`SYSTEMS.md`](SYSTEMS.md) | среда, события, драматург | текущая реализация |
| [`INTERACTION.md`](INTERACTION.md) | доменно-нейтральные взаимодействия | текущая реализация |
| [`AUTOMATA.md`](AUTOMATA.md) | редактор автоматов | текущий инструмент |
| [`WARFARE.md`](WARFARE.md) | войсковые автоматы, психология отрядов | текущий код |
| [`CAMPAIGN_UI.md`](CAMPAIGN_UI.md) | кампанийный UI `view/` | текущая реализация |
| [`DIALOGUE_NLG.md`](DIALOGUE_NLG.md) | детерминированный диалог без LLM: архитектура, разбор, синтез, эпистемика | текущая реализация |
| [`SOAR_RIVESCRIPT_MIGRATION.md`](SOAR_RIVESCRIPT_MIGRATION.md) | переход всего ИИ на Soar + RiveScript: границы, NLU-конвейер, фазы, принятые решения §12 | Phase 0–4 закрыты; Phase 5: BDI-намерения, приказы/действия фракций и реакции на доклады/угрозы, дальше — LOD и мир; Phase 6 в плане |
| [`CHAT_STYLES_PLAN.md`](CHAT_STYLES_PLAN.md) | стилевой слой, регистровый профиль, автовыбор, дискурс | текущая реализация + план |
| [`DATA_DRIVEN_CORE_GAPS.md`](DATA_DRIVEN_CORE_GAPS.md) | только открытые GAP-пункты; полный аудит — в `history/` | аудит, не канон |
| [`DATA_DRIVEN_CORE_PLAN.md`](DATA_DRIVEN_CORE_PLAN.md) | только открытые фазы; полный план — в `history/` | план |
| [`ONBOARDING.md`](ONBOARDING.md) | карта проекта по потребностям | руководство |
| [`HOWTO.md`](HOWTO.md) | как играть, обучать, контрибьютить | руководство |
| [`SUMMARY.md`](SUMMARY.md) | сжатый конспект | не источник истины |
| [`TODO.md`](TODO.md) | открытые задачи | трекер |

### 6.2. Легаси и исторические документы

Эти документы **не переписываются** под текущий код. Их числа и выводы
относятся к своей дате; при расхождении действует этот документ, код и
тесты.

| Документ | Роль | Статус |
|---|---|---|
| [`history/STRATEGY.md`](history/STRATEGY.md) | гражданская гранд-стратегия «Хартия Агоры» | легаси-поток |
| [`history/GAME_ENGINE_CHANGES.md`](history/GAME_ENGINE_CHANGES.md) | хронология правок `game_engine.py` на 2026-10-17 | исторический |
| [`history/RELEASE_READINESS.md`](history/RELEASE_READINESS.md) | оценка масштаба работ до релиза | исторический срез 2026-11-01 |
| [`history/WORLD_MODEL_REVIEW.md`](history/WORLD_MODEL_REVIEW.md) | критика движка и эксперименты | обзор, не канон |
| [`history/FIX_HYPOTHESIS.md`](history/FIX_HYPOTHESIS.md) | проверка гипотезы H-A | исторический |
| [`history/code/ANALYSIS.md`](history/code/ANALYSIS.md) | поэтапный разбор кода | исторический анализ |
| [`history/code/DOCS_ANALYSIS.md`](history/code/DOCS_ANALYSIS.md) | аудит документации | исторический анализ |
| [`history/code/`](history/code/) | справочник по пакетам ранней версии, включая `INLINE_NOTES.md` | исторический |
| [`history/`](history/) | история решений и PR | заморожено |
| [`history/MODEL.md`](history/MODEL.md) | спецификация легаси-`simulation.py` | исторический |
| [`history/BASELINE.md`](history/BASELINE.md) | воспроизводимая база легаси-`simulation.py` | исторический |
| [`history/DESIGN_ADVANCED.md`](history/DESIGN_ADVANCED.md) | дизайн lossy/LOD/энтропии в легаси-`simulation.py` | исторический |
| [`history/UI.md`](history/UI.md) | легаси-клиент `ui/`: сцены, сейвы, RTS | исторический |
| [`history/WORK_MECHANIC_GAP.md`](history/WORK_MECHANIC_GAP.md) | GAP-анализ работы как сообщения и статус закрытия (§0.1) | исторический аудит |
| [`history/CHARACTER_ACTION_FLEXIBILITY_GAP.md`](history/CHARACTER_ACTION_FLEXIBILITY_GAP.md) | аудит F-01…F-23: гибкость персонажа, действий, диалога и эпистемики | исторический аудит (закрыт) |
| [`history/CHARACTER_ACTION_FLEXIBILITY_PLAN.md`](history/CHARACTER_ACTION_FLEXIBILITY_PLAN.md) | фазы P0–P7 закрытия F-01…F-23 | исторический план (выполнен) |
| [`history/DATA_DRIVEN_CORE_GAPS_FULL.md`](history/DATA_DRIVEN_CORE_GAPS_FULL.md) | полный аудит G-01…G-23 | исторический аудит |
| [`history/DATA_DRIVEN_CORE_PLAN_FULL.md`](history/DATA_DRIVEN_CORE_PLAN_FULL.md) | полный план P0–P10 | исторический план |
| [`history/WORK_MECHANIC_PLAN_FULL.md`](history/WORK_MECHANIC_PLAN_FULL.md) | полный план фаз 0–7 | исторический план |
| [`history/CHAT_STYLES_PLAN_FULL.md`](history/CHAT_STYLES_PLAN_FULL.md) | первый подход и полный прогресс стилевого слоя | исторический план |

**Правило статусов.** Документ из §6.2 не является каноном и не обязан
совпадать с кодом. Если его вывод нужен для решения, сначала проверьте
актуальный код/тесты и §0–§5 этого документа. Перенос в `history/`
меняет только расположение и относительные ссылки; содержание
исторических документов не актуализируется.

---

## 7. Открытые вопросы

Реестр закрытых решений и открытых пунктов — [`WORLD_CORE_MODEL.md`](WORLD_CORE_MODEL.md)
§7, сводка открытых пунктов — §7.0 там же. **Не все пункты §7 являются
блокерами:** большинство помечено «Закрыто» и фиксирует принятые решения.
На 2026-11-14 действительно открыты:

| Пункт | Что уже есть | Что осталось |
|---|---|---|
| `WORLD_CORE_MODEL.md` §7 №28 | grace-распад, дрейф, восстановление легитимности | точная экономика распада; легитимность как самостоятельный критерий |
| §7 №29 | рынок труда, очередь кандидатов, переговоры с соперником | автоматическая карьера политики; полная экономика распада коалиций |
| §7 №30 | бесконечный горизонт, `win/lose/neutral`, рост навыков | калибровка темпа; полный набор сюжетных финалов; экономика распада |
| §2.3.6 | JSON-стратегии узлов и бонус к `_ai_score()` (A10) | автоматическое порождение целей и планов без авторского JSON |
| §2.3.5 | план среды арены (A12) | связь кампанийных стратегий узлов с аренным планом |
| §2.8 | `F/E/H` у персонажа, реестр проекций | полная миграция `power/cohesion/...` |
| §2.10 | `relation_effect()` на приёме, `affinity` в автономии | полное влияние `trust/fear/respect` на обработчик и выход |
| [`AGENTS.md`](AGENTS.md) §5 | `IntentQueue`, слоты, `tick()` (A5) | production-планировщик: сквозной игровой цикл игрока |
| [`AGENTS.md`](AGENTS.md) §5 | многофазный план и цели среды — фон | полноценная стратегическая политика среды (`force/defense/in_open`) |

Закрыты и не являются блокерами: единицы `E/F/W`, конверсии и энтропия,
логистика и её коэффициенты, отношения и обязательства, проекции старых
шкал, внутридневные тики, приоритеты/отмена намерений, устойчивые раны, LOD
и журнал, а также диалоговые D0–D5.4, D3.2 (механизм), D6.2a–d
(ядро), D6.3 (политика раскрытия и ложь), D6.4 (цели, мост к действиям,
императивы и псевдонимы), D7.0–D7.1 (headless-текстовик и речевые
действия через interactions кампании), D7.2 (перемещение по
геометрии стороны игрока), D7.3 (ожидание, фазы суток и темп) и
D7.4 (описание сцены из story/log/events).
Детали формул — [`FORMULAS.md`](FORMULAS.md); текущий статус слоёв —
§9 ниже.

---

## 8. Правила изменений

1. Новое проектное решение сначала фиксируется здесь и/или в
   `WORLD_CORE_MODEL.md`.
2. Если меняется формула или константа, обновите [`FORMULAS.md`](FORMULAS.md)
   и, если затронут контент, [`CONTENT.md`](CONTENT.md).
3. Затем обновляются затронутые документы; статусы «текущее» и «целевое» не
   смешиваются.
4. Затем — код и тесты. Поведение текущего кода не меняется без отдельного
   решения и обновления baseline.
5. Если документ противоречит этому источнику, побеждает этот документ;
   противоречие нужно исправить, а не игнорировать.
6. Если код противоречит `history/MODEL.md`, для текущего поведения
   побеждают код и тесты; расхождение относится к историческому снимку,
   а активные документы описывают актуальный путь.
7. Если целевая модель противоречит текущему коду, для дизайна побеждает
   целевая модель; текущий код остаётся легаси до миграции.
8. В коде не должно быть inline-комментариев. Значимое объяснение живёт в
   документации (`docs/`, docstrings, `docs/history/code/INLINE_NOTES.md`), а не в
   строке кода.
9. Исторические документы (`docs/history/`, включая `history/code/`,
   `history/FIX_HYPOTHESIS.md`, `history/WORLD_MODEL_REVIEW.md`,
   `history/GAME_ENGINE_CHANGES.md`) не
   переписываются под текущий код. Их выводы относятся к своей дате.
10. `*.pdf` остаются в `.gitignore`; удалённые легаси-каталоги (включая
    `yet_another_project/`) не восстанавливаются.

---

## 9. Ближайший статус

- Онтология, одна энергия, BDI/не-BDI, реальное время, поражение и проекции
  старых шкал согласованы.
- Реализован вертикальный срез `core41`: одна универсальная энергия, форма
  работы как канал, обработчики, логистический успех и `DuelEnv` для обучения.
- Реализован runtime активной арены `core41.arena`: `ArenaAgent`,
  `ArenaMatch`, `run_duel_tick`, `check_capture` и UI-совместимый фасад.
- Срез A9 сделал такт одновременным (эффекты по снимку начала такта),
  связал здоровье с нападением (`HEALTH_ATTACK_FLOOR`), добавил `F`-лимит
  работы, двухтактную подготовку сильного удара, туман наблюдения
  (`core41/intel.py`) и разведку `info` со слабой точкой; легаси-пара
  `DuelWorld`/`DuelEnv` сохраняет последовательное разрешение.
- Работа кампании приведена к канону: `campaign/work.py` строит `Work`,
  `campaign/handlers.py` выбирает JSON-правило получателя по `form`,
  `WorkReport` считает `stored/loss/entropy`, а `campaign/effects.py::
  apply_report` применяет проекции. Арена вызывает
  `_receive_channel` из `resolve_work`. Дневной мир (фаза 4b), открытый
  payload-реестр и квинтуплы остаются остатком —
  [`WORK_MECHANIC_PLAN.md`](WORK_MECHANIC_PLAN.md) §2.
- Доклады источников разложены по швам: `campaign/dispatch.py` — фасад
  `ReportDispatcher`, реализация — в `campaign/dispatch_core.py`,
  `dispatch_news.py`, `dispatch_reports.py`, `dispatch_resolve.py`,
  `dispatch_intercepts.py`, `dispatch_briefing.py`, `dispatch_effects.py`,
  `dispatch_queue.py` и `dispatch_support.py`. Публичный API и формат
  снимка не менялись; полный набор 2026-11-24 — 2076 тестов, зелёный.
- `WorldEngine` разложен тем же способом: `campaign/world.py` — фасад
  с `__init__`, загрузчиками и `build_world`; реализация — в
  `campaign/world_core.py` (свойства, такт, день, журнал, LOD),
  `world_entities.py` (узлы, сущности, сцены, персонажи),
  `world_relations.py` (отношения, обязательства, ценности, коалиции),
  `world_career.py` (должности, рынок труда, карьера, намерения),
  `world_actions.py` (действия, проверки, эффекты, ИИ, стратегии),
  `world_day.py` (экономика, здоровье, предметы, сюжетные линии),
  `world_snapshot.py` (`to_dict`/`load_snapshot`) и `world_support.py`
  (константы, загрузка и валидация конфигов, профили). Публичный API,
  monkeypatch-точки `campaign.world` и формат снимка сохранены.
- `AutomataCampaign` разложен аналогично: `campaign/automata.py` — фасад
  с `__init__`; `automata_core.py` (инициализация, фракции, геометрия,
  часы, время), `automata_actions.py` (действия и взаимодействия),
  `automata_processes.py` (процессы, слоты, эффекты), `automata_ai.py`
  (ИИ и автоигра), `automata_characters.py` (агентность и цели),
  `automata_orders.py` (заказы фракций), `automata_reports.py` (доклады,
  решения, перехваты), `automata_snapshot.py` (снимок, сохранение, аудит),
  `automata_support.py` (константы, помощники, `FactionRuntime`).
  Алиасы `interact_organ`/`interact_automaton`/`interact_character` и
  `to_dict` сохранены как атрибуты класса; публичный API и формат снимка
  не менялись.
- View-слой разрезан по тем же швам. `view/app.py` — фасад `App` и точка
  входа `main`; реализация — в `app_core.py` (инициализация, окно, ввод,
  цикл), `app_storyline.py` (запуск сюжетов), `app_scenes.py` (сцены и
  переходы), `app_flow.py` (ходы и исходы), `app_dialogue.py` (сессия
  диалога), `app_saves.py` (сохранения) и `app_menu.py`; общие помощники —
  в `app_support.py`. `view/screens/world_screen.py` — фасад
  `WorldScreen` + `world_screen_{core,events,draw,detail,personality}.py`
  и `world_screen_support.py`. `view/screens/rts_screen.py` — фасад
  `RTSScreen` + `rts_screen_{core,commands,update,events,draw}.py` и
  `rts_screen_support.py`. `view/screens/automata_network.py` — фасад
  `AutomataNetworkScreen` +
  `automata_network_{core,selection,actions,events,draw}.py` и
  `automata_network_support.py`. Публичные имена, атрибуты классов и
  порядок `__init__` сохранены.
- Легаси-спецификации [`history/MODEL.md`](history/MODEL.md),
  [`history/BASELINE.md`](history/BASELINE.md),
  [`history/DESIGN_ADVANCED.md`](history/DESIGN_ADVANCED.md),
  [`history/UI.md`](history/UI.md) и GAP-аудит
  [`history/WORK_MECHANIC_GAP.md`](history/WORK_MECHANIC_GAP.md)
  перенесены в `docs/history/`; карта §6 и ссылки обновлены.
- Реализовано здоровье как отдельное состояние в дуэльном срезе `core41`:
  смерть при `health <= 0`, переполнение урона после `F=0`, отдых/голод и
  множители `aging/illness/stress/care`; дуэльный срез откалиброван
  экспериментом `experiments/exp_health_calibration.py`. В BDI-слое
  персонажей кампании смерть определяется `force <= 0`.
- Реализована болезнь как процесс: `sickness ∈ [0,1]`, прогресс без отдыха,
  восстановление отдыхом, урон здоровью и добавка к переполнению урона,
  API `infect()`/`treat()`. Лечение встроено шестым действием `TREAT`
  (`CORE_ACTIONS` из шести), политики видят `self_sickness`/
  `opponent_sickness`, BDI и QTable учитывают болезнь; `TREAT` предлагается
  только при `sickness > 0`. Источник — явное `--sickness`/`infect()`;
  успешный `force`-контакт может передать болезнь асимметрично
  (`CONTAGION_CHANCE`/`CONTAGION_SEVERITY`). Начальная болезнь задаётся
  `--sickness` (оба бойца) или `--sickness-rl`/`--sickness-ai`; `illness` не
  умножает урон от текущей `sickness` повторно, а `SICKNESS_*`,
  `TREAT_ENERGY_FRACTION` и `CONTAGION_*` входят в `CALIBRATABLE`.
  Острая болезнь снижает успех работы через `work_effectiveness`, не меняя
  навык и расход `E`. `health`/`sickness` — состояние персонажа:
  `condition_state()`/`load_condition()` переносят его, `GameApp.progress()`
  сохраняет текущие значения, а `GameScene` восстанавливает их после
  перемотки. В кампании персонаж — `CampaignActor` на том же ядре: `E` —
  дневной бюджет действий (`CAMPAIGN_ENERGY_MAX / actions_per_day` на
  действие), `F` — `standing`, `H`/`sickness` — общие с ареной;
  `actions_left` остаётся проекцией `E`. Есть дневной срез болезни, смерти
  героя/персонажей, grace-распад организации (`power`/`cohesion <= 0.05`
  два дня подряд, проверка идемпотентна в пределах дня), смена роли при
  увольнении (не чаще раза в день; потеря должности без замены завершает
  эпизод нейтральным исходом), бесконечный горизонт и доход должности
  (`_apply_daily_income()` возвращает влияние/связи по полномочиям и
  репутации, чтобы `E` оставался реальным бюджетом действий). Сюжетная
  глава задаётся блоком `storyline` (`min_day`, `deadline_day`,
  `win.standing_at_least`, `lose.standing_at_most` + `lose.days`):
  `_check_storyline()` завершает её `win`/`lose`/`neutral`, а без блока мир
  остаётся бесконечным. Production-мир свободной жизни не задаёт `days`:
  `sandbox` отключает главу и горизонт. Фон и
  оффлайн-догон ограничены `campaign/clock.py` и `saved_at`. В
  `CampaignEnv` есть `TREAT_SELF` (одно действие дня, снимает `0.20`
  болезни) и `target_mode="all"` по умолчанию — действия по всем доступным
  адресатам. UI арены,
  тактического поля и шапки кампании показывает болезнь; средовой резервуар
  болезни и острые раны закрыты первым срезом `ArenaEnvironment` (§2.3.5),
  кампанийная передача — контактом в одном узле; устойчивые раны
  реализованы срезом A2 (`wound`).
  Первый срез real-time-планировщика —
  `campaign/planner.py`: `schedule_intent()`/`IntentQueue` откладывают
  события на будущие дни, исполняются в начале `end_day()` до хода ИИ и
  входят в снимок мира; персонаж с `autonomous: true` сам назначает
  контакты. Срез 2 (A4, 2026-10-31): приоритеты намерений, отмена по
  условию (`cancel_when`/`condition_holds`) и политика автономных
  персонажей через общую `campaign_success_chance`. Внутридневные тики
  закрыты A5: `CampaignClock.slot` и `WorldEngine.tick(max_slot=...)`;
  открыт production-планировщик сквозного цикла игрока.
- Реализован секундный клок `core41.SimulationClock`: скорости
  `pause/1x/2x/4x/8x/16x`, авто-пауза (включая `SICKNESS_CRITICAL`) и
  ограниченный догон; это часы **арены**. Кампания автоматов и свободный
  режим живут по физическому времени `1:1`, где ускорение — только явный
  множитель `speed`.
- Реализован слой `agents`: `BDIPolicy` с online-обновлением,
  `QTablePolicy`, `MLPPolicy` (tanh-hidden=16, без PyTorch, с target-сетью),
  `PolicyAgent` как легаси-мост и CLI `python -m agents.train`. Вектор
  признаков — 22 (18 прежних, стабильный код действия и три признака среды:
  `env_pressure`, `env_season` и окно уязвимости `env_window` из среза A1),
  чекпойнты — `CHECKPOINT_VERSION = 3`; BDI
  v0/v1/v2 и MLP v1/v2 мигрируют дополнением нулями, старый MLP без target-сети
  копирует online-веса в target. `--max-steps` по умолчанию зависит от
  среды: `arena=2000`, `duel=160`, `campaign=30`; defaults Python API и CLI
  выровнены. Held-out `qtable`/`mlp` без чекпойнта прогреваются
  (`--eval-baseline-episodes`, по умолчанию 50) и помечаются
  `trained_episodes`/`policy_source`; явный `--eval-checkpoint NAME=PATH`
  отключает прогрев. `win_rate` сопровождается Wilson CI
  (`win_rate_ci`); для production-выбора есть `--save-best`/
  `--best-every`/`--best-eval-episodes`, а `--eval-campaign-baselines`
  добавляет warmed baseline-строки в кампанийную held-out матрицу.
- Реализован актор среды `ArenaEnvironment`: при `with_env=True`
  `ArenaMatch`/`MatchEngine`/`BattlefieldModel` получают реальный `env`,
  который по расписанию добавляет истощение/передышку, средовой источник
  болезни (`ENV_ILLNESS_INTERVAL`/`ENV_SICKNESS`) и острые раны
  (`ENV_WOUND_INTERVAL`/`ENV_WOUND_DAMAGE`), учитывает сезонность
  (`SEASONS`, `ENV_SEASON_LENGTH`) и асимметрию (основная сторона получает
  полный эффект, вторая — `ENV_SECONDARY_SHARE`). `public_state()` отдаёт
  наблюдаемое расписание в `Observation.env_pressure/env_season`, включая
  `illness`/`wound`. У среды есть собственная логистическая экономика с
  целью: `goal`/`collapse` — события фона, которые меняют `work_bonus` и
  поддержку, но не завершают партию. `ArenaEnv` по умолчанию `with_env=True`
  (train/serve alignment); при `with_env=False` среды нет и прежняя
  калибровка сохраняется.
- `game_engine.py` и `ui/battlefield.py` работают на `core41`; `UtilityAI` и
  `simulation.py` оставлены baseline/легаси-канону.
- Реализован диалоговый слой `campaign/dialogue/` — read-only над BDI и
  кампанией, без LLM и статистики. Данные лежат в `configs/dialogue/`,
  Python интерпретирует. Сделаны D0 (разбор), D1 (вопросы о мире), D1.5
  (композиционный синтез), D2 (QUD, референты, память), D3.1 (сравнения),
  D4 (речевые действия), D5.1–D5.4 (дискурс, регистры, агрегация,
  `topics`), D3.2 (движок контрфактов), D6.1 (аудит лексикона),
  D6.2a–d (отрицание,
  «то»-клауза, `predicate_relations`, условия/уступки, косвенная и
  прямая речь), D6.3 (раскрытие и ложь), D6.4 (цели, планировщик,
  мост к действиям, императивы и псевдонимы), D7.0 (история, откат,
  подсказки), D7.1 (social-действия через мост), D7.2 (перемещение
  по геометрии игрока), D7.3 (время и темп через текст) и D7.4
  (описание сцены из видимых story-событий, работ и прочих событий).
  В чате `DialogueChatScreen` стиль
  выбирается вручную; авторежим `DialogueSession(style_id=None)` доступен
  через API сессии. Сквозные контрфакты достижимы: `believe`, `have` и
  `fight` дают `changed`. Тесты — `tests/test_d3_counterfactual.py`,
  `tests/test_d6_grammar.py`, `tests/test_d6_lexicon.py`,
  `tests/test_d6_disclosure.py`,
  `tests/test_d6_planner.py`, `tests/test_d6_bridge.py`,
  `tests/test_d6_actions.py`, `tests/test_d7_console.py`,
  `tests/test_d7_social.py`, `tests/test_d7_movement.py`,
  `tests/test_d7_time.py`, `tests/test_d7_narrator.py`.
- Полная миграция остального UI, сейвов и организационных шкал кампании
  **не завершена**: персонаж уже на `E/F/H`, но `power/cohesion/...` остаются
  легаси-проекциями мира. Устойчивые раны и внутридневные действия закрыты;
  открыты полная миграция организационных шкал, связь кампанийных стратегий
  с аренным планом и стратегическая политика среды (`force/defense/in_open`).
  Калибровку здоровья нужно повторить после миграции и смены политик.
  Чекпойнт BDI/QTable загружается в активные сцены явно (`--checkpoint`)
  или находится автоматически (`agents/checkpoints.py`: `checkpoints/`,
  `best.json` → `latest.json` → свежий `*.json`, `--no-auto-checkpoint`,
  `--list-checkpoints`); тот же путь использует автопилот кампании.
  `--save-best` выбирает лучший held-out чекпойнт во время обучения.
- Следующий шаг — production-планировщик сквозного цикла игрока,
  автоматическая карьера политики, полная миграция организационных шкал и
  экономика распада/легитимности (см. §7), не выдавая аренный срез за весь
  мир.
