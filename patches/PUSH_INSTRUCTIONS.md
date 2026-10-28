# Как запушить ветку realm/faction-leader (проблемы готовности №2–№7)

В контейнере разработки **нет remote и нет сетевых учёных данных**, поэтому `git push`
технически невозможен. Подготовлены два эквивалентных способа перенести 4 коммита:

Коммиты (на базе 3d690da "in progress"):
1. 50bf3d8  docs: close training-readiness questions 2-3 (reward calibration, self-play/eval tracker)
2. 3803463  feat: close training-readiness questions 4-5 (MLP capacity, checkpoint versioning/resume)
3. 42e19d2  feat: close training-readiness question 6 (CampaignEnv over WorldEngine)
4. a49d7d5  feat: close training-readiness question 7 (domain randomization in train CLI)

## Способ A — git am (рекомендуется, сохраняет сообщения/авторов/даты)
```bash
cd <репозиторий-с-базой-3d690da>
git checkout realm/faction-leader   # или ваша ветка на базе 3d690da
git am --whitespace=nowarn patches/mbox-all.mbx
git push origin realm/faction-leader
```
Проверено: `git am` применяется начисто поверх 3d690da, итоговое дерево
байт-в-байт совпадает с рабочей копией (diff пустой).

## Способ B — по отдельным патчам
```bash
git am patches/0001-*.patch patches/0002-*.patch patches/0003-*.patch patches/0004-*.patch
```

## Примечание про bundle
transfer.bundle не прилагается: история в этом контейнере shallow-grafted
(родитель 3d690da оборван), поэтому bundle требует отсутствующий предок и
не может быть импортирован без него. mbox-патчи этой проблемы не имеют.
