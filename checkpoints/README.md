# Production-чекпойнты

Сюда `agents.train` пишет чекпойнты, а игра ищет их автоматически
(`agents/checkpoints.py`).

## Как положить чекпойнт

```bash
# лучший по held-out во время обучения
venv/bin/python -m agents.train --episodes 2000 --seed 0 \
    --policy qtable --save-best checkpoints/best.json

# или финальный
venv/bin/python -m agents.train --episodes 2000 --seed 0 \
    --policy mlp --out checkpoints/latest.json
```

## Как игра его находит

Порядок поиска:

1. явный `--checkpoint PATH` (важнее всего);
2. `best.json`;
3. `latest.json`;
4. самый свежий `*.json` по `mtime`.

Файл должен быть JSON-объектом известного вида (`bdi`, `qtable`, `mlp`,
`duel-mlp`) и не новее своей версии (`CHECKPOINT_VERSION` для базовых
политик, `DUEL_CHECKPOINT_VERSION` для duel-MLP). Битые и чужие файлы
пропускаются.

Исключение из правила «JSON-файлы не коммитятся»:
`checkpoints/duel_mlp_production.json` — поставляемый production-агент
(ось A, задача A9; обучен через `python3 -m agents.train --env arena
--policy duel-mlp`). Он намеренно закоммичен, чтобы автопоиск игры
находил его «из коробки».

```bash
python3 main.py --list-checkpoints            # что найдено
python3 main.py --arena --list-checkpoints    # то же для арены
python3 main.py --no-auto-checkpoint          # игнорировать этот каталог
```

Каталог можно переопределить переменной `OZVERING_CHECKPOINT_DIR` или флагом
`--checkpoints-dir`.

JSON-файлы в этом каталоге не коммитятся (см. `.gitignore`).
