# Контент-план по лору: «две империи, один миф»

> **Статус:** проектный документ. Определяет, **что писать** в JSON после
> починки ядра по [`DATA_DRIVEN_CORE_PLAN.md`](DATA_DRIVEN_CORE_PLAN.md).
> Пока ядро не поддерживает убеждения/намерения/автоматы (см.
> [`DATA_DRIVEN_CORE_GAPS.md`](DATA_DRIVEN_CORE_GAPS.md)), этот план
> остаётся спецификацией, а не готовым контентом.
>
> **Источник:** [`docs/лор.pdf`](лор.pdf) (22 стр., 951 строка текста).
> Список автоматов в PDF **неполный и поверхностный** — он используется
> как нижняя граница, а не как исчерпывающий перечень.
>
> **Золотое правило:** больше — лучше. Богаче наборы предикатов, сутей,
> работ, состояний, событий и веток. Ограничение одно: 16 потребностей,
> 15 делений, 12 черт — их количество не меняется.
>
> **Дата:** 2026-11-11.

---

## 0. Инварианты

| Инвариант | Значение |
|---|---|
| Потребности | Ровно 16, имена из `bdi.NEEDS`; можно менять только числа, тексты, `spillover`, `satisfaction` |
| Деления | 15 измерений `configs/characters/divisions.json` |
| Черты | 12 черт `configs/characters/traits.json` |
| Предикаты | Не ограничены; расширяются свободно |
| Сути намерений | Не ограничены; каждая привязана к одной из 16 потребностей |
| Фракции | 4 верхних; 3 внутренних у Империи и Республики; культ и планета — монолиты с ячейками |
| Детерминизм | Все случайности через `seed`, без времени и `random` вне контракта |
| Язык | Русский; id — латиница, `snake_case`, точки как разделители пространств |

### 0.1. Пространства идентификаторов

```
faction.empire            верхний автомат
faction.republic
faction.cult
faction.trade
subfaction.empire.orthodox
subfaction.empire.moderate
subfaction.empire.revisionist
subfaction.republic.orthodox
subfaction.republic.moderate
subfaction.republic.revisionist
organ.empire.panzerwaffe
organ.republic.cyber
organ.cult.scriptorium
organ.trade.port
char.<faction>.<role>.<n>
work.<faction>.<id>
event.<id>
node.<id>                город, порт, столица, орбитальная станция
place.<id>               историческое место, мемориал
doctrine.<id>            доктрина/школа
```

Правило: субъект и объект убеждения — всегда одно из этих пространств,
либо `self`/`target`/`actor` внутри шаблона. Это делает убеждения
переносимыми между фракциями и проверяемыми линтером.

---

## 1. Канон: что есть в мире

### 1.1. Четыре верхних автомата

| Автомат | Самопонимание | Природа | Главная уязвимость | Асимметричный путь |
|---|---|---|---|---|
| **Империя** | единственная законная власть | принуждение массой, миф, вертикаль | публичное поражение бьёт по мифу | заставить признать законность |
| **Республика** | законная власть плебса | точность, инициатива, информация | потеря лица и внешнего канала | разрушить веру в законность Империи |
| **Культ Земли** | духовная альтернатива | паразит на обиде, обработчик | нарратив, лидер, низкая энергия | размывать лояльность государств |
| **Торговая планета** | медиатор | рынок, канал, доступ | нет легитимности, инфраструктура | закрыть канал, купить, санкционировать |

### 1.2. Внутренние фракции

| Верх | Ортодоксы | Модераты | Ревизионисты |
|---|---|---|---|
| Империя | порядок до предела: касты, рабство, рыцарство, феодальное войско | «не развались»: бюрократия, штаб, церковь-умеренные | свобода до предела: конституция, права, реформы |
| Республика | свобода до предела: легалайз, упразднение тюрем, открытые границы, общинная собственность | «не развались»: коалиции, процедуры, институты | порядок до предела: диктатура, милитаризм |

Ключевое: совпадение программ не делает союзниками. Ревизионисты
Республики и ортодоксы Империи могут ненавидеть друг друга.

### 1.3. Органы (нижняя граница из лора)

**Империя — принуждение (24):** Имперская ставка, Панцерваффе, Вермахт,
Военно-космическое адмиралтейство, Артиллерийский корпус, Штурмовой
корпус, Сверхтяжёлый корпус, Бомбардировочный флот, Ракетно-ядерное
управление, Разведывательно-диверсионная служба, Вельтраумфлотте, Осадный
корпус, Служба РЭБ, Люфтфлотте, Абвер, Пропагандистская служба, Охранные
отряды, Орднунг-полицай, Инженерный корпус, Гвардейский корпус,
Киберотдел спецслужбы, Имперское министерство юстиции, Имперский собор,
Караульный полк.

**Империя — поддержание (11):** Медицинская служба,
Эвакуационно-ремонтный корпус, Интендантская служба, Учебный корпус,
Штабное управление, Корпус связи, Шифровальный корпус, Военная полиция,
Военно-гражданская администрация, Аналитический корпус, Гестапо.

**Республика — принуждение (25):** Федеральный генштаб, Танковый корпус,
Полевой корпус, Воздушный флот, Космическое адмиралтейство,
Артиллерийский корпус, Корпус высокоточных вооружений, Бомбардировочный
флот, Диверсионно-разведывательный корпус, Ракетно-ядерные силы
сдерживания, Космический флот, Корпус РЭБ, Воздушная армия, Центральное
разведывательное управление, Пропагандистский корпус, Оккупационная
администрация, Военная комендатура, Полевое типографское управление,
Гарнизон, Инженерный корпус, Правозащитное ведомство, Киберкорпус,
Подпольное радиовещание, Интернет-управление, Сеть агентов влияния.

**Республика — поддержание (18):** Медицинская служба,
Эвакуационно-ремонтный корпус, Эвакуационный корпус, Тыловая служба,
Учебный корпус, Транспортный корпус, Информационное управление, Штабное
управление, Корпус связи, Шифровальный корпус, Федеральная инспекционная
служба, Военная полиция, Гражданская администрация, Психологическое
управление, Аналитический корпус, Дипломатическое ведомство, Торговое
ведомство, Отдел защиты канала.

**Культ (9):** Проповедническое управление, Общинное управление,
Подпольное типографское управление, Сеть сочувствующих,
Агентурно-разведывательная служба, Благотворительное управление,
Скрипториум, Синедрион, Рыцари Земли и Солнца.

**Торговая планета (10):** Торговое ведомство, Портовое управление,
Финансовое ведомство, Дипломатическое ведомство, Разведывательное
управление, Складское управление, Медийное управление, Агентурное
управление, Служба защиты, Инженерное управление.

> **Золотое правило.** К списку добавляются органы сверх лора: у Империи
> и Республики — школы, кафедры, архивы, госпитали, тюрьмы, цензура,
> картография, метеорология, ветеранские союзы, профсоюзы, банки,
> страховые общества; у культа — паломнические дома, реликварии,
> катакомбные архивы, суды милосердия; у планеты — биржа, таможня,
> страховое и долговое управления, гостиничные дома, карантин.

---

## 2. Каталог предикатов

Формат: `id` — вид — объект — смысл. Вид `property` не требует объекта;
`relation` требует. Для числовых свойств используется `value` (0..1).

### 2.1. Легитимность и власть

| Предикат | Вид | Объект | Смысл |
|---|---|---|---|
| `is_legitimate` | property | — | субъект считает себя/кого-то законным |
| `is_recognized_by` | relation | субъект признания | «признан X» |
| `has_monopoly_on_legitimacy` | property | — | претензия на единственную законность |
| `is_usurper` | property | — | незаконный захватчик |
| `has_mandate` | property | — | мандат доверия/бога/народа |
| `is_sovereign` | property | — | суверен |
| `owes_allegiance_to` | relation | сюзерен | присяга |
| `is_loyal_to` | relation | объект верности | лояльность |
| `has_claim_on` | relation | территория/титул | претензия |
| `is_in_revolt` | property | — | мятеж |
| `grants_amnesty` | property | — | предлагает амнистию |
| `is_purged` | property | — | вычищен из структур |
| `is_outlaw` | property | — | вне закона |
| `is_martyr` | property | — | мученик |
| `is_heretic` | property | — | еретик |
| `is_saint` | property | — | святой/образец |
| `is_corrupt` | property | — | коррумпирован |
| `is_competent` | property | — | компетентен |
| `is_popular` | property | — | популярен |
| `is_despised` | property | — | презираем |
| `is_compromised` | property | — | скомпрометирован |

### 2.2. Война и принуждение

| Предикат | Вид | Объект | Смысл |
|---|---|---|---|
| `at_war_with` | relation (sym) | сторона | война |
| `is_at_ceasefire_with` | relation (sym) | сторона | перемирие |
| `controls` | relation | узел | контроль узла |
| `occupies` | relation | территория | оккупация |
| `besieges` | relation | узел | осада |
| `is_threat_to` | relation | сторона | угроза |
| `is_deterrent_to` | relation | сторона | сдерживание |
| `has_superiority_over` | relation | сторона | превосходство |
| `was_defeated_by` | relation | сторона | поражение |
| `defeated` | property | — | разгромлен |
| `is_mobilized` | property | — | мобилизован |
| `is_overstretched` | property | — | перенапряжён |
| `has_reserves` | property | — | есть резервы |
| `is_blockaded` | property | — | блокирован |
| `raids` | relation | сторона/узел | рейды |
| `protects` | relation | объект защиты | защита |
| `is_fortified` | property | — | укреплён |
| `has_initiative` | property | — | владеет инициативой |

### 2.3. Вера и обработчик

| Предикат | Вид | Объект | Смысл |
|---|---|---|---|
| `believes_in_myth` | property | — | верит в непобедимость |
| `doubts_myth` | property | — | сомневается в мифе |
| `believes_in_cause` | property | — | верит в правоту дела |
| `sees_enemy_as_evil` | relation | сторона | враг — зло |
| `sees_enemy_as_legitimate` | relation | сторона | враг законен |
| `trusts_propaganda` | property | — | доверяет пропаганде |
| `is_disillusioned` | property | — | разочарован |
| `has_faith_in_leader` | relation | лидер | вера в лидера |
| `expects_victory` | property | — | ждёт победы |
| `expects_defeat` | property | — | ждёт поражения |
| `fears_punishment` | property | — | боится кары |
| `hopes_for_amnesty` | property | — | надеется на амнистию |
| `feels_betrayed_by` | relation | сторона | чувство предательства |
| `resents` | relation | сторона | обида |
| `is_radicalized` | property | — | радикализован |
| `is_infiltrated_by` | relation | организация | внедрение |
| `is_sympathetic_to` | relation | сторона | сочувствие |
| `is_apocalyptic` | property | — | апокалиптический настрой |

### 2.4. Экономика и канал

| Предикат | Вид | Объект | Смысл |
|---|---|---|---|
| `controls_channel` | property | — | контролирует канал |
| `trades_with` | relation (sym) | сторона | торговля |
| `depends_on` | relation | сторона/узел | зависимость |
| `supplies` | relation | сторона | снабжает |
| `is_indebted_to` | relation | сторона | долг |
| `sanctions` | relation | сторона | санкции |
| `blackmails` | relation | сторона | шантаж |
| `bribes` | relation | сторона | подкуп |
| `smuggles` | relation | сторона | контрабанда |
| `has_access_to` | relation | узел/канал | доступ |
| `is_nationalized` | property | — | национализирован |
| `price_controlled_by` | relation | сторона | ценовое давление |

### 2.5. Информация

| Предикат | Вид | Объект | Смысл |
|---|---|---|---|
| `knows` | relation | факт/субъект | знание |
| `suspects` | relation | факт | подозрение |
| `has_proof_of` | relation | факт | доказательство |
| `leaked` | property | — | утечка |
| `is_secret` | property | — | тайна |
| `is_exposed` | property | — | раскрыт |
| `spreads_narrative_about` | relation | субъект | нарратив |
| `intercepts` | relation | сторона | перехват |
| `has_source_in` | relation | организация | источник |
| `disinforms` | relation | сторона | дезинформация |
| `fabricated` | property | — | сфабриковано |

### 2.6. Социальные связи

`trusts`, `distrusts`, `respects`, `fears`, `loves`, `hates`,
`friends_with` (sym), `rival_of` (sym), `allied_with` (sym),
`subordinate_of`, `member_of`, `leads`, `serves`, `betrayed`,
`reconciled_with`, `owes_favor_to`, `patron_of`, `client_of`.

### 2.7. Организации и состояния

`is_functional`, `is_disbanded`, `is_underground`, `is_overloaded`,
`is_reformed`, `is_autonomous`, `is_subordinated_to`, `is_alive`,
`is_wounded`, `is_sick`, `is_exhausted`, `is_panicked`, `is_confident`,
`is_isolated`.

**Итого:** ~100 предикатов. Это верхняя граница полезности; линтер
разрешает объявлять новые по мере надобности.

---

## 3. Каталог сутей намерений

Каждая суть привязана к одной из 16 потребностей — это единственный
способ добавить «политическую мотивацию», не добавляя потребность.

### 3.1. Базовые (уже есть, 25)

`eat, drink, rest, heal, seek_safety, seek_order, socialize, reproduce,
learn, create, entertain, seek_status, seek_meaning, practice, court,
befriend, help, attack, defend, trade, inspect, build_network, reconcile,
probe, retreat`.

### 3.2. Принуждение и война

| Суть | Опора (need) | Объект | Смысл |
|---|---|---|---|
| `coerce` | fear | сторона | навязать волю |
| `demonstrate` | status | сторона/узел | показать силу |
| `terrorize` | fear | население | ужас как аргумент |
| `purge` | anxiety | группа | чистка |
| `repress` | anxiety | население | подавление |
| `besiege` | fear | узел | осада |
| `raid` | hunger | сторона | рейд на каналы |
| `blockade` | hunger | сторона | блокада |
| `mobilize` | anxiety | своя фракция | мобилизация |
| `occupy` | status | узел | занятие узла |
| `withdraw` | fear | фронт | отход |
| `fortify` | fear | узел | укрепление |
| `retaliate` | status | сторона | ответная кара |
| `deter` | fear | сторона | сдерживание |
| `suppress` | anxiety | сторона | подавление огнём |
| `strike` | status | орган/узел | точечный удар |

### 3.3. Политика и легитимность

| Суть | Опора | Объект | Смысл |
|---|---|---|---|
| `legitimize` | spirituality | своя фракция | укрепить законность |
| `delegitimize` | knowledge | сторона | разрушить веру в законность |
| `recognize` | friendship | сторона | признать |
| `deny_recognition` | status | сторона | не признавать |
| `reform` | anxiety | институт | реформа |
| `preserve` | anxiety | институт | сохранить порядок |
| `coup` | status | своя фракция | переворот |
| `amnesty` | love | сторона | амнистия |
| `negotiate` | friendship | сторона | переговоры |
| `sanction` | hunger | сторона | санкции |
| `crown` | spirituality | лидер | коронация |
| `inaugurate` | status | лидер | инаугурация |
| `martyrize` | spirituality | персонаж | сделать мучеником |
| `judge` | anxiety | персонаж | суд |
| `excommunicate` | spirituality | персонаж | отлучение |

### 3.4. Информация и разведка

| Суть | Опора | Объект | Смысл |
|---|---|---|---|
| `analyze` | knowledge | сторона/узел | анализ |
| `intercept` | knowledge | сторона | перехват |
| `encrypt` | anxiety | своя фракция | защита связи |
| `deceive` | knowledge | сторона | обман |
| `expose` | knowledge | персонаж/сторона | разоблачение |
| `leak` | knowledge | сторона | утечка |
| `fabricate` | creativity | сторона | фабрикация |
| `blackmail` | status | персонаж | шантаж |
| `infiltrate` | knowledge | организация | внедрение |
| `subvert` | knowledge | организация | подрыв изнутри |
| `recruit` | friendship | персонаж | вербовка |
| `turn` | status | персонаж | перевербовать |

### 3.5. Экономика

| Суть | Опора | Объект | Смысл |
|---|---|---|---|
| `invest` | creativity | институт | вложение |
| `hoard` | hunger | своя фракция | накопление |
| `distribute` | love | население | распределение |
| `tax` | hunger | население | поборы |
| `smuggle` | hunger | канал | контрабанда |
| `sponsor` | status | сторона | финансирование |
| `bribe` | status | персонаж | подкуп |
| `price_war` | hunger | сторона | демпинг |
| `nationalize` | anxiety | орган | национализация |
| `insure` | anxiety | канал | страхование рисков |

### 3.6. Вера и община

| Суть | Опора | Объект | Смысл |
|---|---|---|---|
| `preach` | spirituality | население | проповедь |
| `convert` | spirituality | персонаж | обращение |
| `shelter` | love | персонаж | укрытие |
| `charity` | love | население | милосердие |
| `educate` | knowledge | население | обучение |
| `ritualize` | spirituality | община | ритуал |
| `pilgrim` | spirituality | место | паломничество |
| `sacrifice` | spirituality | своя фракция | жертва |
| `mourn` | love | персонаж | траур |

### 3.7. Организация

| Суть | Опора | Объект | Смысл |
|---|---|---|---|
| `train` | skill | персонаж | обучение |
| `supply` | hunger | своя фракция | снабжение |
| `repair` | health | орган | ремонт |
| `evacuate` | health | персонаж | эвакуация |
| `centralize` | anxiety | своя фракция | централизация |
| `decentralize` | fear | своя фракция | автономия ячеек |
| `administer` | anxiety | территория | управление |
| `coordinate` | knowledge | своя фракция | координация |
| `celebrate` | status | население | праздник |

**Итого:** ~60 сутей. Все опираются на 16 существующих потребностей.

---

## 4. Каталог работ

Формат строки: `id` | `label` | орган | форма | суть | ключевой эффект.
`форма` — из `configs/naming/interactions` (coercion, information,
exchange, care, order, knowledge, meaning, negotiation, recruitment,
reconnaissance). Требования и тексты пишутся при реализации; здесь —
содержание и роль в системе.

### 4.1. Империя — принуждение (20)

| id | Работа | Орган | Форма | Суть | Эффект |
|---|---|---|---|---|---|
| `imperial_edict` | Имперский эдикт | justice | information | legitimize | +legitimacy, belief `is_legitimate` |
| `show_of_force` | Демонстрация силы | guard | coercion | demonstrate | +fear, −target cohesion |
| `panzer_breakthrough` | Танковый прорыв | panzerwaffe | coercion | raid | −target supply, −target cohesion |
| `terror_bombing` | Террористическая бомбардировка | bomber | coercion | terrorize | −target morale, +fear, risk −own legitimacy |
| `siege_operation` | Осада узла | siege | coercion | besiege | `besieges` node, −target supply |
| `superheavy_demo` | Сверхтяжёлая демонстрация | superheavy | coercion | demonstrate | +myth, −supply, шанс скандала |
| `rocket_strike` | Ракетный удар | rocket | coercion | deter | −target infrastructure, +fear |
| `space_raid` | Рейд Вельтраумфлотте | space | coercion | raid | −target orbital node |
| `abwehr_sabotage` | Диверсия Абвера | abwehr | reconnaissance | subvert | −target organ, belief `is_infiltrated_by` |
| `cyber_osint` | Киберразведка | cyber | knowledge | analyze | +intel, belief `knows` |
| `myth_campaign` | Кампания о непобедимости | propaganda | information | legitimize | +myth, belief `believes_in_myth` |
| `enemy_of_state` | Враг государства | justice | order | purge | −target influence, +fear, belief `is_outlaw` |
| `church_ritual` | Имперский ритуал | cathedral | meaning | ritualize | +legitimacy, +church_support |
| `guard_parade` | Парад гвардии | guards | information | demonstrate | +status, +myth |
| `military_police_raid` | Облава военной полиции | police | order | repress | +order, −liberty |
| `occupation_regime` | Оккупационный режим | admin | order | occupy | +control, −target legitimacy |
| `punitive_expedition` | Карательная экспедиция | wehrmacht | coercion | retaliate | +fear, −target supply |
| `amnesty_edict` | Амнистия за признание | justice | negotiation | amnesty | target belief `hopes_for_amnesty`, −orthodox influence |
| `symbolic_retake` | Возврат символической территории | staff | coercion | occupy | +symbolic_territory, +myth |
| `general_offensive` | Общее наступление | staff | coercion | mobilize | +momentum, −supply |

### 4.2. Империя — поддержание (16)

| id | Работа | Орган | Форма | Суть | Эффект |
|---|---|---|---|---|---|
| `staff_plan` | Планирование ставки | staff | knowledge | analyze | +command, +intel |
| `signal_coordination` | Наладить связь | signal | knowledge | coordinate | +command |
| `cipher_protection` | Защита шифров | cipher | knowledge | encrypt | +secrecy |
| `intendant_supply` | Интендантское снабжение | intendant | exchange | supply | +supply |
| `medical_service` | Медицинская служба | medical | care | repair | +health, −needs |
| `evac_repair` | Эвакуация и ремонт | evac | care | repair | +organ integrity |
| `training_corps` | Учебный корпус | training | knowledge | train | +skill, +reserves |
| `discipline_drive` | Дисциплинарная кампания | police | order | repress | +cohesion |
| `civil_administration` | Военно-гражданская администрация | admin | order | administer | +control, +supply |
| `analytical_report` | Аналитический доклад | analysis | knowledge | analyze | +intel, +planning |
| `gestapo_conspiracy` | Дело о заговоре | gestapo | order | purge | −subfaction influence, +fear |
| `border_garrisons` | Гарнизоны на границе | wehrmacht | order | fortify | +defense, −supply |
| `industrial_mobilization` | Мобилизация промышленности | intendant | exchange | mobilize | +supply, −needs |
| `church_hospitals` | Церковные госпитали | cathedral | care | charity | +legitimacy, −unrest |
| `officer_purge` | Чистка офицерского корпуса | gestapo | order | purge | −elite_loyalty, +cohesion (риск) |
| `wunderwaffe_program` | Программа вундерваффе | staff | knowledge | create | +myth, −supply, шанс провала |

### 4.3. Республика — принуждение (24)

| id | Работа | Орган | Форма | Суть | Эффект |
|---|---|---|---|---|---|
| `information_campaign` | Информационная кампания | propaganda | information | delegitimize | −target myth, belief `doubts_myth` |
| `parliament_debate` | Парламентские слушания | parliament | negotiation | legitimize | +procedure, +legitimacy |
| `precision_strike` | Высокоточный удар | precision | coercion | strike | −target organ |
| `human_rights_court` | Суд по правам человека | rights | order | expose | +moral_authority, −target legitimacy |
| `channel_deal` | Сделка по каналу | trade | exchange | trade | +external_channel |
| `cyber_leak` | Киберутечка | cyber | knowledge | leak | −target secrecy, +intel |
| `underground_radio` | Подпольное радио | radio | information | disinform | −target morale |
| `agent_network` | Сеть агентов | agents | reconnaissance | infiltrate | +intel, belief `is_infiltrated_by` |
| `general_mobilization` | Всеобщая мобилизация | staff | order | mobilize | +force, −supply |
| `republic_medicine` | Республиканская медицина | medical | care | repair | +health |
| `counteroffensive` | Контрнаступление | field | coercion | raid | −target supply |
| `tank_raid` | Танковый рейд | tank | coercion | raid | −target cohesion |
| `air_campaign` | Воздушная кампания | air | coercion | strike | −target supply |
| `space_fleet_op` | Операция космофлота | space | coercion | deter | +fear target |
| `artillery_barrage` | Артиллерийский налёт | artillery | coercion | suppress | −target cohesion |
| `smart_munitions` | Умные боеприпасы | precision | coercion | strike | −target organ |
| `strategic_deterrence` | Стратегическое сдерживание | rocket | coercion | deter | +deterrence |
| `electronic_warfare` | Радиоэлектронная борьба | ew | knowledge | intercept | −target command |
| `special_operation` | Спецоперация | cia | reconnaissance | subvert | −target leader/command |
| `field_printing` | Полевая типография | printing | information | disinform | belief `doubts_myth` |
| `occupation_admin` | Оккупационная администрация | admin | order | occupy | +control |
| `military_commandant` | Военная комендатура | commandant | order | repress | +order, −liberty |
| `garrison_defense` | Оборона гарнизона | garrison | order | fortify | +defense |
| `influence_network` | Сеть влияния | agents | recruitment | build_network | +influence |

### 4.4. Республика — поддержание (16)

| id | Работа | Орган | Форма | Суть | Эффект |
|---|---|---|---|---|---|
| `rights_documentation` | Документирование преступлений | rights | knowledge | expose | belief `is_outlaw` target |
| `internet_ops` | Интернет-операция | internet | information | fabricate | −target legitimacy |
| `negotiation_offer` | Предложение переговоров | diplomacy | negotiation | negotiate | +ceasefire, −orthodox |
| `amnesty_for_soldiers` | Амнистия солдатам | rights | negotiation | amnesty | target belief `hopes_for_amnesty` |
| `purge_capitalists` | Чистка «капиталистических крыс» | cia | order | purge | +orthodox, −moral_authority |
| `federal_inspection` | Федеральная инспекция | inspection | knowledge | analyze | +elite_unity |
| `psychological_ops` | Психологическая операция | psych | information | subvert | +trust, belief |
| `transport_logistics` | Транспортная логистика | transport | exchange | supply | +supply |
| `training_academy` | Учебная академия | training | knowledge | train | +skill |
| `signal_coordination` | Координация связи | signal | knowledge | coordinate | +command |
| `diplomatic_channel` | Дипломатический канал | diplomacy | negotiation | negotiate | +external_channel |
| `trade_office` | Торговое ведомство | trade | exchange | invest | +supply, +channel |
| `channel_defense` | Защита канала | channel | order | fortify | +external_channel, +secrecy |
| `constitutional_reform` | Конституционная реформа | parliament | negotiation | reform | +procedure, −orthodox |
| `emergency_powers` | Чрезвычайные полномочия | staff | order | centralize | +command, −procedure |
| `engineering_works` | Инженерные работы | engineer | order | fortify | +defense |

### 4.5. Культ Земли (25)

| id | Работа | Орган | Форма | Суть | Эффект |
|---|---|---|---|---|---|
| `sermon` | Проповедь | preaching | meaning | preach | +narrative |
| `community_network` | Сеть общин | communities | care | build_network | +communities |
| `martyr_narrative` | Нарратив мученика | preaching | meaning | martyrize | +narrative, +recruits |
| `infiltration` | Внедрение | agents | reconnaissance | infiltrate | +infiltration |
| `earth_ritual` | Ритуал Земли | rites | meaning | ritualize | +faith |
| `scriptorium_schools` | Школы Скрипториума | scriptorium | knowledge | educate | +converts, −state legitimacy |
| `parallel_court` | Суд Синедриона | synedrion | order | judge | +parallel_structures |
| `charity_hospitals` | Больницы милосердия | charity | care | charity | +communities, +legitimacy |
| `knights_patrol` | Патруль рыцарей | knights | coercion | protect | +security, −secrecy |
| `underground_printing` | Подпольная типография | printing | information | disinform | +doubt |
| `relic_procession` | Процессия реликвий | relics | meaning | ritualize | +narrative |
| `shelter_network` | Сеть убежищ | shelters | care | shelter | +communities |
| `apocalyptic_prophecy` | Апокалиптическое пророчество | preaching | meaning | radicalize | +fear, +recruits |
| `convert_officer` | Обращение офицера | agents | recruitment | convert | +infiltration |
| `black_market` | Чёрный рынок | communities | exchange | smuggle | +energy |
| `sabotage_myth` | Подрыв мифа | agents | information | delegitimize | −target myth |
| `confession_tribunal` | Исповедальный трибунал | synedrion | order | judge | +control, −trust |
| `pilgrimage` | Паломничество | pilgrimage | meaning | pilgrim | +narrative |
| `charity_fund` | Фонд милосердия | charity | exchange | sponsor | +communities |
| `hidden_cells` | Скрытые ячейки | communities | order | decentralize | +secrecy |
| `leader_sermon` | Проповедь лидера | preaching | meaning | demonstrate | +charisma |
| `purge_traitors` | Чистка предателей | knights | order | purge | +cohesion, −trust |
| `catacomb_archive` | Катакомбный архив | scriptorium | knowledge | encrypt | +secrecy |
| `relief_after_bombing` | Помощь после бомбардировки | charity | care | charity | +communities, −target legitimacy |
| `call_to_peace` | Призыв к миру | preaching | negotiation | negotiate | +narrative (риск: −recruits) |

### 4.6. Торговая планета (25)

| id | Работа | Орган | Форма | Суть | Эффект |
|---|---|---|---|---|---|
| `trade_route` | Торговый маршрут | trade | exchange | trade | +channel, +supply |
| `price_dumping` | Демпинг | finance | exchange | price_war | −target supply/morale |
| `buy_silence` | Купить молчание | intel | exchange | bribe | +secrecy |
| `blackmail_operation` | Шантаж | intel | information | blackmail | +influence |
| `close_channel` | Закрыть канал | diplomacy | negotiation | sanction | −target supply |
| `open_channel` | Открыть канал | diplomacy | negotiation | negotiate | +channel |
| `port_expansion` | Расширение порта | port | exchange | invest | +infrastructure |
| `warehouse_reserves` | Складские резервы | warehouse | exchange | hoard | +supply |
| `currency_manipulation` | Валютная операция | finance | exchange | invest | +liquidity |
| `insurance_scheme` | Страховая схема | finance | exchange | insure | +reputation |
| `smuggling_run` | Контрабандный рейс | logistics | exchange | smuggle | +channel, −reputation |
| `intelligence_market` | Рынок информации | intel | knowledge | expose | +intel |
| `media_narrative` | Медийный нарратив | media | information | legitimize | +reputation |
| `diplomatic_mediation` | Посредничество | diplomacy | negotiation | negotiate | +balance |
| `mercenary_contract` | Наёмный контракт | security | coercion | protect | +security, −neutrality |
| `neutrality_pledge` | Пакт нейтралитета | diplomacy | negotiation | preserve | +neutrality |
| `infrastructure_repair` | Ремонт инфраструктуры | engineering | care | repair | +infrastructure |
| `debt_leverage` | Долговой рычаг | bank | information | blackmail | +influence |
| `contract_auction` | Аукцион контрактов | trade | exchange | invest | +liquidity |
| `evacuation_service` | Эвакуационный сервис | logistics | care | evacuate | +reputation |
| `customs_control` | Таможенный контроль | customs | order | control | +channel |
| `blockade_run` | Прорыв блокады | port | coercion | raid | +supply, риск |
| `buy_organ` | Купить орган | agents | recruitment | subvert | −target organ integrity |
| `balance_war` | Поддержание баланса | diplomacy | negotiation | preserve | +balance, −target momentum |
| `emergency_reserve` | Аварийный резерв | warehouse | exchange | distribute | +stability |

> **Объём.** 126 работ — нижняя граница. При реализации каждая работа
> получает 2–3 варианта текста, `failure`, `cooldown`, `requires` и
> `ai`-профиль. Итог — 300+ записей.

---

## 5. Каталог автоматов

### 5.1. Верхние автоматы

#### Империя (`faction.empire`)

Состояния: `latent` → `mobilization` → `campaign` → `overstretch` →
`legitimacy_crisis` → (`restoration` | `dissolution`).

| Переход | Условие | Приоритет |
|---|---|---|
| latent → mobilization | `supply ≥ 0.5`, `legitimacy ≥ 0.4` | 2 |
| mobilization → campaign | `energy ≥ 0.4`, `fear ≥ 0.3` | 2 |
| campaign → overstretch | `supply ≤ 0.3` или `organs.overloaded ≥ 2` | 3 |
| overstretch → legitimacy_crisis | `legitimacy ≤ 0.35` | 4 |
| legitimacy_crisis → restoration | `church_support ≥ 0.6` и `myth ≥ 0.5` | 2 |
| legitimacy_crisis → dissolution | `energy ≤ 0.05` | 9 |

Входы: эдикты, наступления, потери, церковь, субфракции.
Выходы: `fear`, `myth`, `legitimacy`, `supply`-дренаж, доступные работы.

#### Республика (`faction.republic`)

`deliberation` → `consolidation` → `counteroffensive` → `attrition` →
`polarization` → (`reform` | `collapse`).

Отличие: переходы медленнее (2 хода), но восстановление быстрее;
`legitimacy` падает от поражений и растёт от процедур.

#### Культ (`faction.cult`)

`hidden` → `recruitment` → `infiltration` → `exposure` → `martyrdom` →
(`revival` | `eradication`).

Ключ: `secrecy` падает при `exposure`; `martyrdom` повышает `narrative`
и `communities`, но снижает `energy`.

#### Торговая планета (`faction.trade`)

`neutral` → `profitable` → `pressured` → `embargo` → (`broker_war` |
`nationalized`).

Ключ: `balance` падает, если одна сторона доминирует; `autonomy` падает
при национализации.

### 5.2. Подфракции (6)

Общий архетип: `underground` → `growth` → `legitimacy` → `dominance` →
`crackdown` → (`purge` | `return`).

| Подфракция | Особый вход | Особый выход |
|---|---|---|
| Ортодоксы Империи | страх, традиция, церковь | +`order`, −`freedom`, +`purge` |
| Модераты Империи | бюрократия, штаб | +`cohesion`, +`legitimacy` |
| Ревизионисты Империи | поражения, реформы | +`freedom`, −`myth` |
| Ортодоксы Республики | пафос, права | +`conviction`, −`procedure` |
| Модераты Республики | коалиции | +`procedure`, +`elite_unity` |
| Ревизионисты Республики | страх, война | +`order`, −`freedom`, риск диктатуры |

Смена власти: переход `dominance` + условие `influence ≥ 0.6` →
эффект «доктрина меняется», набор работ пересобирается.

### 5.3. Органы: архетипы автоматов

| Архетип | Состояния | Ключевые входы | Ключевые выходы |
|---|---|---|---|
| `command` | forming → staffing → planning → overloaded → reformed | приказы, бюджет | +`command`, +`planning` |
| `coercion` | garrison → mobilized → offensive → attrition → replenishment | приказы, потери | −target `supply`, +`fear` |
| `intel` | dormant → collecting → operation → exposed → purge | приказы, риск | +`intel`, belief `knows` |
| `legitimacy` | ritual → public_campaign → scandal → restoration | эдикты, скандалы | +`legitimacy`, +`myth` |
| `supply` | stocked → strained → priority → depleted | бюджет, потери | +`supply` |
| `covert` | hidden → cell_growth → infiltration → crackdown → underground | вербовка, облава | +`infiltration`, +`secrecy` |
| `care` | staffed → overloaded → triage → restored | раненые, бюджет | +`health`, −`needs` |
| `media` | silent → narrative → campaign → discredited | факты, скандалы | +`narrative`, ±`legitimacy` |

Каждый орган из §1.3 получает конкретный архетип + 1–2 уникальных
состояния. Пример: `organ.empire.panzerwaffe` — `coercion` +
`fuel_crisis`; `organ.republic.cyber` — `intel` + `leak_window`;
`organ.cult.synedrion` — `legitimacy` + `parallel_court`.

### 5.4. Схема файлов

```
configs/campaigns/base/automata/
  faction.empire.json
  faction.republic.json
  faction.cult.json
  faction.trade.json
  subfaction.empire.orthodox.json
  ...
  organ.empire.panzerwaffe.json
  ...
```

Индекс — `configs/campaigns/base/automata/index.json` со списком файлов и
владельцев. Загрузчик читает индекс, линтер проверяет ссылки.

---

## 6. Активы фракций и формулы

Базовые семь: `legitimacy`, `influence`, `cohesion`, `supply`, `fear`,
`morale`, `energy`.

### 6.1. Империя

| Актив | Формула (термы) |
|---|---|
| `myth` | `0.35·mean:trait.loyalty + 0.25·organs.kind:legitimacy + 0.2·context.myth + 0.2·subfactions.orthodox.influence` |
| `vertical` | `0.4·characters.mean:satisfaction.status + 0.3·organs.kind:command + 0.3·context.vertical` |
| `elite_loyalty` | `0.4·characters.mean:trait.loyalty + 0.3·subfactions.moderate.influence + 0.3·organization.willing_share` |
| `symbolic_territory` | `0.6·context.symbolic_territory + 0.4·organs.kind:command` |
| `punishment_credibility` | `0.5·fear + 0.3·organs.kind:coercion + 0.2·context.punishment` |
| `church_support` | `0.5·organs.kind:legitimacy + 0.3·characters.mean:satisfaction.spirituality + 0.2·context.church` |

### 6.2. Республика

| Актив | Формула |
|---|---|
| `conviction` | `0.4·characters.mean:satisfaction.spirituality + 0.3·organs.kind:information + 0.3·context.conviction` |
| `procedure` | `0.4·organs.kind:command + 0.3·characters.mean:trait.loyalty + 0.3·context.procedure` |
| `external_channel` | `0.5·context.channel + 0.3·organs.kind:trade + 0.2·faction.trade.influence` |
| `moral_authority` | `0.5·organs.kind:legitimacy + 0.3·characters.mean:satisfaction.spirituality + 0.2·context.moral` |
| `elite_unity` | `0.4·characters.mean:satisfaction.friendship + 0.3·organs.kind:command + 0.3·context.unity` |

### 6.3. Культ

| Актив | Формула |
|---|---|
| `narrative` | `0.5·organs.kind:meaning + 0.3·characters.mean:satisfaction.spirituality + 0.2·context.narrative` |
| `charisma` | `0.5·characters.max:satisfaction.status + 0.3·organs.kind:meaning + 0.2·context.charisma` |
| `secrecy` | `0.5·context.secrecy + 0.3·organs.kind:intelligence + 0.2·(1 − target.intel)` |
| `communities` | `0.5·organs.kind:care + 0.3·characters.mean:satisfaction.friendship + 0.2·context.communities` |
| `resentment` | `0.4·characters.mean:need.anxiety + 0.3·target.supply_drop + 0.3·context.resentment` |

### 6.4. Торговая планета

| Актив | Формула |
|---|---|
| `autonomy` | `0.5·context.autonomy + 0.3·(1 − faction.empire.influence) + 0.2·organs.kind:command` |
| `neutrality` | `0.5·context.neutrality + 0.3·(1 − max(war_domination)) + 0.2·organs.kind:diplomacy` |
| `infrastructure` | `0.5·organs.kind:maintenance + 0.3·context.infrastructure + 0.2·supply` |
| `reputation` | `0.5·characters.mean:satisfaction.status + 0.3·organs.kind:media + 0.2·context.reputation` |
| `channel` | `0.5·context.channel + 0.3·organs.kind:trade + 0.2·neutrality` |
| `liquidity` | `0.5·context.market + 0.3·organs.kind:exchange + 0.2·supply` |

> Все формулы — в `faction_state.assets`; новые ключи добавляются в
> `asset_labels`. Это единственная часть контента, которая уже сейчас
> работает без правки Python.

---

## 7. Персонажи

### 7.1. Лидеры

| Фракция | Архетип | Приоритетные потребности | Черты | Стартовые убеждения | Стартовое намерение |
|---|---|---|---|---|---|
| Империя | `veteran` | status, fear, anxiety | loyalty 0.8, order 0.8, cruelty 0.6 | `is_legitimate`, `at_war_with` Республика, `believes_in_myth` 0.8 | `coerce` Республика |
| Республика | `officer` | status, knowledge, anxiety | loyalty 0.6, empathy 0.6, ambition 0.5 | `is_legitimate`, `sees_enemy_as_evil` Империя, `believes_in_cause` 0.8 | `delegitimize` Империя |
| Культ | `chaplain` | spirituality, love, loneliness | faith 0.9, charisma 0.8, secrecy 0.6 | `is_martyr` (о Земле), `sees_enemy_as_evil` оба государства | `preach` население |
| Планета | `clerk` | status, hunger, security | greed 0.8, patience 0.7, pragmatism 0.8 | `controls_channel`, `depends_on` Империя, `is_secret` | `trade` обе стороны |

### 7.2. Посты

У Империи и Республики — 14–16 постов: лидер, начальник штаба, глава
спецслужбы, глава пропаганды, командующий фронтом, командующий флотом,
глава церкви/правозащиты, глава экономики, губернатор, инспектор,
палач, придворный, лидер подфракции (3). У культа — 8–10. У планеты —
10–12.

Каждый пост задаёт:

```json
{
  "id": "empire_chief_of_staff",
  "title": "Начальник Имперской ставки",
  "organ_id": "imperial_staff",
  "priority_needs": ["anxiety", "status", "knowledge"],
  "traits": {"loyalty": 0.7, "competence": 0.8},
  "beliefs": [
    {"predicate": "believes_in_myth", "value": 0.6},
    {"predicate": "trusts", "object": "character.empire.leader"}
  ],
  "intentions": [{"target": "faction.republic", "essence": "coordinate"}],
  "divisions": {"rank": "general", "school": "staff"}
}
```

---

## 8. События (слой отражения)

**Контракт.** Событие — ролевой компонент, а не часть ядра. Оно ничего не
производит и не порождается другими событиями: у него нет `effects`,
`apply` или `emit`. Событие только **читает** состояние через `conditions`
и `visibility` и отдаёт `text`/`templates`, `weight`, `category`. Всё, что
ниже в таблицах, — это «что событие отражает», а не «что оно меняет».
Причина изменений — работы (`actions`), переходы автоматов и действия
игрока; событие описывает уже случившееся.

Формат таблиц: `id | что отражает | условие видимости | тон/текст`.

### 8.1. Империя

| id | Что отражает | Условие | Тон/текст |
|---|---|---|---|
| `empire_symbolic_defeat` | миф о непобедимости треснул после потери гвардии | `myth ≤ 0.5`, гвардия потеряна | «Знамя унесли в пыль; газеты ещё пишут о победе» |
| `empire_general_killed` | гибель командира и провал вертикали | командир мёртв, `command ≤ 0.5` | «Генерала нет, а приказ всё ещё ждёт подписи» |
| `empire_wunderwaffe_reveal` | «чудо-оружие» показано, но резерв исчерпан | `supply ≥ 0.5`, `turn ≥ 10` | «Прожекторы, оркестр и пустые ящики за сценой» |
| `empire_wunderwaffe_failure` | провал обещанного чуда | после `empire_wunderwaffe_reveal`, техника не сработала | «Обещанный рассвет не наступил» |
| `empire_amnesty_offer` | режим ищет выход через амнистию | `legitimacy ≤ 0.4` | «Указ об амнистии читают как признание вины» |
| `empire_purge_scandal` | чистка ударила по элитам | частая чистка, `elite_loyalty ≤ 0.45` | «Списки расстрелянных длиннее списков живых» |
| `empire_church_scandal` | церковь потеряла опору | скандал в церкви, `church_support ≤ 0.4` | «Кадило качается над опустевшим клиром» |
| `empire_overstretch` | фронт растянут, снабжение сорвано | `supply ≤ 0.25` | «Солдаты делят последний сухарь на троих» |

### 8.2. Республика

| id | Что отражает | Условие | Тон/текст |
|---|---|---|---|
| `republic_mass_execution` | Республика применила казни и потеряла моральное превосходство | казни использованы, `moral_authority ≤ 0.5` | «Свобода подписала приговор собственной совести» |
| `republic_leak_scandal` | утечка ударила по законности | утечка случилась, `legitimacy ≤ 0.5` | «Документ уже в чужих руках, а трибуна ещё пуста» |
| `republic_channel_closed` | внешний канал перекрыт | канал закрыт, `supply ≤ 0.4` | «Караваны стоят у шлагбаума, которого больше нет» |
| `republic_polarization` | парламент расколот на лагеря | `elite_unity ≤ 0.3` | «Два зала, два председателя, один микрофон» |
| `republic_revisionist_coup` | ревизионисты взяли аппарат | ревизионисты `influence ≥ 0.6` | «Доктрину переписали за одну ночь, не разбудив прессу» |
| `republic_peace_accusation` | переговорщика обвиняют в измене | переговоры начаты, `conviction ≤ 0.5` | «Мир подают как капитуляцию, и зал верит» |
| `republic_heroic_defense` | оборона удалась и сплотила | оборона удержана, `conviction ≥ 0.6` | «Баррикада держится, и впервые все поют один гимн» |

### 8.3. Культ

| id | Что отражает | Условие | Тон/текст |
|---|---|---|---|
| `cult_martyrdom` | гибель лидера/ячейки стала реликвией | лидер или ячейка уничтожены | «Мёртвый проповедник собирает больше, чем живой» |
| `cult_exposure` | секретность рухнула, культ на виду | `secrecy ≤ 0.3` | «Прихожане узнают своих соседей в списках арестованных» |
| `cult_mass_conversion` | голод и бомбардировки гонят людей в культ | `hunger ≥ 0.6` или разрушения | «Хлеб кончился, осталась только вера» |
| `cult_leader_crisis` | лидер дискредитирован изнутри | лидер дискредитирован, `narrative ≤ 0.4` | «Пророк молчит, а толпа требует знамения» |
| `cult_peace_dividend` | мир отнял у культа топливо | мир между сторонами | «Без войны проповедь звучит как сказка» |
| `cult_infiltration_high` | культ проник в чужие структуры | `infiltration ≥ 0.6` | «В каждом штабе есть свой тихий человек» |

### 8.4. Планета

| id | Что отражает | Условие | Тон/текст |
|---|---|---|---|
| `trade_price_spike` | война взвинтила цены | война и дефицит | «Цена хлеба растёт быстрее сводок с фронта» |
| `trade_embargo` | санкции перекрыли канал | санкции введены | «Порт полон, но ни один трюм не разгружают» |
| `trade_nationalization` | Империя проглотила торговлю | Империя `influence ≥ 0.7` | «Вывеску сменили, а долги оставили прежние» |
| `trade_balance_broken` | одна сторона доминирует в обмене | перекос баланса | «Весы больше не притворяются весами» |
| `trade_intel_sale` | компромат стал товаром | есть компромат | «Секрет продан дважды, и оба покупателя довольны» |
| `trade_humanitarian_credit` | помощь купила репутацию | помощь оказана | «Мешки с мукой подписаны именем дарителя» |

### 8.5. Сквозные

`war_exhaustion`, `food_crisis`, `refugee_wave`, `mutiny`,
`assassination_attempt`, `peace_talks`, `border_incident`,
`propaganda_coup`, `currency_collapse`, `epidemic` — те же правила: это
пороги чтения, а не эффекты. Каждое событие обязано ссылаться на уже
существующее состояние (актив, потребность, условие, убеждение, намерение),
но не менять его.

---

## 9. Сюжеты

### 9.1. Империя: «Порядок против хаоса»

* **Акт I.** Император стабилизирует вертикаль: эдикт, парад, чистка.
  Выбор: миф или компетентность.
* **Акт II.** Наступление и перенапряжение. Выбор: символическая
  территория или каналы. Внутренние фракции предлагают три программы.
* **Акт III.** Кризис легитимности. Ветки: восстановление через церковь;
  амнистия и признание; распад.
* **Концовки:** `win` — Республика признала законность; `lose` —
  символическое поражение и распад; `neutral` — хрупкое перемирие.

### 9.2. Республика: «Свобода против тирании»

* **Акт I.** Коалиция и процедура; выбор между пафосом и моралью.
* **Акт II.** Информационная война; выбор между казнями и правами.
* **Акт III.** Поляризация; ветки: реформа, чрезвычайные полномочия,
  переговоры.
* **Концовки:** `win` — Империя delegitimized; `lose` — диктатура
  ревизионистов или потеря канала; `neutral` — мир без победы.

### 9.3. Культ: «Энтропия во плоти»

* **Акт I.** Общины и проповедь.
* **Акт II.** Внедрение и параллельные структуры; риск раскрытия.
* **Акт III.** Мученичество или искоренение.
* **Концовки:** `win` — оба государства потеряли веру; `lose` —
  раскрыт и уничтожен; `neutral` — ушёл в катакомбы.

### 9.4. Планета: «Канал без репутации»

* **Акт I.** Торговля с обеими сторонами.
* **Акт II.** Давление, санкции, выбор стороны.
* **Акт III.** Баланс или национализация.
* **Концовки:** `win` — стал незаменимым посредником; `lose` —
  национализирован; `neutral` — сохранил автономию ценой репутации.

В каждой кампании — 3–4 развилки, 6–8 сцен, 3 концовки, 2–3 скрытых
ветки по доминирующей подфракции.

---

## 10. Целевой объём

| Сущность | Минимум | Цель |
|---|---|---|
| Предикаты | 70 | 100 |
| Сути намерений | 50 | 60 |
| Фракции верхние | 4 | 4 |
| Подфракции | 6 | 6 |
| Органы | 100 | 140 |
| Работы | 100 | 160 |
| Автоматы (файлы) | 40 | 120 |
| События | 30 | 60 |
| Сюжетные сцены | 24 | 40 |
| Активы фракции | 24 | 40 |
| Посты | 40 | 60 |
| Убеждения (стартовые) | 30 | 80 |

---

## 11. Калибровка и приёмка

### 11.1. Прогоны

* 72 хода × 4 фракции × 10 seed.
* Ни одна фракция не распадается раньше 12-го хода без действий игрока.
* Ни одна фракция не стабилизируется в бесконечном равновесии: хотя бы
  один актив меняется на ≥ 0.05 за 10 ходов.
* Смена подфракции случается в 10–30% прогонов.
* Культ не доминирует без войны; планета не выигрывает без канала.

### 11.2. Смысловые проверки

* Каждая работа ссылается на существующий орган, предикат и суть.
* Каждая суть ссылается на существующую потребность (одну из 16).
* Каждое событие имеет хотя бы один достижимый триггер.
* Каждая фракция имеет работу на каждую подцель из лора.
* Ни одно убеждение не требует отсутствующего пространства id.
* Тексты работ/событий не дублируются.

### 11.3. Инструменты

* `python -m campaign.lint` — схема, ссылки, неизвестные ключи.
* `pytest tests/test_content_pipeline.py` — загрузка.
* `pytest tests/test_bdi.py` — 16 потребностей.
* Новый `tests/test_data_driven_core.py` — сценарии из §6
  `DATA_DRIVEN_CORE_GAPS.md`.
* Golden-снимок 72 ходов для детерминизма.

---

## 12. Порядок написания

1. **Предикаты и сути** — сначала словарь, иначе работы не на что
   ссылать.
2. **Активы и формулы** — уже работают, дают раннюю обратную связь.
3. **Органы и их автоматы** — каркас, к которому цепляются работы.
4. **Работы** — по одной доктрине за раз (Империя-принуждение, затем
   поддержание, затем Республика, культ, планета).
5. **Подфракции** — после того как базовые работы играются.
6. **События** — после работ, чтобы триггеры были достижимы.
7. **Сюжеты** — последними, когда механика стабильна.
8. **Калибровка** — итеративно, не в конце.

### 12.1. Разбиение файлов

Текущий `lore_factions.json` (2915 строк) при полном объёме вырастет до
10–15 тыс. строк. Предлагается:

```
configs/campaigns/base/
  factions.index.json
  factions/empire.json
  factions/republic.json
  factions/cult.json
  factions/trade.json
  automata/index.json
  automata/*.json
  assets.json
  events.json
```

`factions_path` в шаблоне кампании указывает на индекс; загрузчик
поддерживает и одиночный файл (совместимость).

---

## 13. Что не делать

* Не добавлять потребности. Политические мотивы — сути, привязанные к
  16 существующим.
* Не кодировать лорные эффекты в Python. Если эффект нельзя выразить —
  расширять DSL, а не писать ветку.
* Не дублировать тексты в коде и JSON.
* Не делать работу «просто +актив», если у неё есть лорный смысл:
  добавлять убеждение, намерение или состояние.
* Не описывать автомат только состояниями без входов/выходов/условий —
  это иллюстрация, а не автомат.

---

## 14. Связанные документы

* [`DATA_DRIVEN_CORE_GAPS.md`](DATA_DRIVEN_CORE_GAPS.md) — почему сейчас
  нельзя.
* [`DATA_DRIVEN_CORE_PLAN.md`](DATA_DRIVEN_CORE_PLAN.md) — как сделать
  можно.
* [`SOURCE_OF_TRUTH.md`](SOURCE_OF_TRUTH.md) — канон.
* [`CONTENT.md`](CONTENT.md) — карта загрузчиков.
* [`CONTENT_BDI_DIVISIONS_EVENTS.md`](CONTENT_BDI_DIVISIONS_EVENTS.md) —
  контракт BDI.
* [`AUTOMATA_CAMPAIGN.md`](AUTOMATA_CAMPAIGN.md) — текущие автоматы.
