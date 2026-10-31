"""Production-чекпойнты: соглашение о каталоге и автопоиск (P2).

`agents.train` умеет писать чекпойнты (`--out`, `--save-best`), но активная
игра до сих пор требовала явный `--checkpoint`. Этот модуль задаёт
соглашение, по которому игра сама находит готовую политику:

- каталог `checkpoints/` в корне проекта (переопределяется
  `OZVERING_CHECKPOINT_DIR` или флагом `--checkpoints-dir`);
- внутри сначала `best.json`, затем `latest.json`, затем самый свежий
  `*.json` по `mtime`;
- файл должен быть JSON-объектом известного вида (`bdi`/`qtable`/`mlp`) и
  не быть новее поддерживаемой версии `CHECKPOINT_VERSION`.

Автопоиск только выбирает файл: загрузка и валидация остаются за
`load_policy`. Битые, чужие и «слишком новые» файлы молча пропускаются,
поэтому испорченный `best.json` не ломает запуск игры.
"""

import json
import os
from pathlib import Path

from .policies import (
    CHECKPOINT_VERSION,
    DUEL_CHECKPOINT_VERSION,
    checkpoint_version,
)

CHECKPOINT_DIR_ENV = "OZVERING_CHECKPOINT_DIR"
DEFAULT_CHECKPOINT_DIR = "checkpoints"
# Имена, которые `--save-best`/`--out` пишут чаще всего. Порядок важен:
# `best.json` — осознанный выбор по held-out, `latest.json` — последний.
PREFERRED_NAMES = ("best.json", "latest.json")
# A9: `duel-mlp` (A7/A8) живёт в каталоге чекпойнтов наравне с остальными —
# без него автопоиск игры (`find_checkpoint`) отвергал production-файл.
KNOWN_KINDS = ("bdi", "qtable", "mlp", "duel-mlp")


def project_root():
    """Корень проекта (каталог, где лежат `agents/`, `core41/`, ...)."""
    return Path(__file__).resolve().parents[1]


def default_checkpoint_dir(root=None):
    """Каталог чекпойнтов: env-переменная важнее корня проекта."""
    override = os.environ.get(CHECKPOINT_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path(root or project_root()) / DEFAULT_CHECKPOINT_DIR


def read_checkpoint(path):
    """Прочитать JSON-чекпойнт; `None` для битого или нечитаемого файла."""
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def checkpoint_kind(path):
    """Вид политики в файле; пустая строка, если файл не читается."""
    state = read_checkpoint(path)
    if state is None:
        return ""
    kind = state.get("kind")
    return kind if isinstance(kind, str) else ""


def is_loadable(path, kind=None):
    """Можно ли отдать файл в `load_policy` (без фактической загрузки)."""
    state = read_checkpoint(path)
    if state is None:
        return False
    state_kind = state.get("kind")
    if state_kind not in KNOWN_KINDS:
        return False
    if kind and state_kind != kind:
        return False
    # A8: duel-MLP имеет собственный формат чекпойнтов (v4); для него
    # предельная версия — DUEL_CHECKPOINT_VERSION, остальные политики
    # используют базовый CHECKPOINT_VERSION.
    limit = (
        DUEL_CHECKPOINT_VERSION
        if state_kind == "duel-mlp"
        else CHECKPOINT_VERSION
    )
    try:
        return checkpoint_version(state) <= limit
    except (TypeError, ValueError):
        return False


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _candidates(directory, preferred):
    """Файлы каталога в порядке предпочтения, без дублей."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    ordered = []
    for name in preferred:
        path = directory / name
        if path.is_file():
            ordered.append(path)
    rest = [
        path
        for path in directory.glob("*.json")
        if path.is_file() and path not in ordered
    ]
    rest.sort(key=lambda item: (_mtime(item), item.name), reverse=True)
    return ordered + rest


def list_checkpoints(
    directory=None,
    kind=None,
    root=None,
    preferred=PREFERRED_NAMES,
):
    """Валидные чекпойнты в порядке предпочтения.

    Возвращает список словарей `{path, name, kind, size, mtime}`; пустой
    список — если каталога нет или в нём нет ни одного пригодного файла.
    """
    directory = Path(directory) if directory else default_checkpoint_dir(root)
    rows = []
    for path in _candidates(directory, preferred):
        if not is_loadable(path, kind=kind):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        rows.append(
            {
                "path": str(path),
                "name": path.name,
                "kind": checkpoint_kind(path),
                "size": int(size),
                "mtime": _mtime(path),
            }
        )
    return rows


def find_checkpoint(
    directory=None,
    kind=None,
    root=None,
    preferred=PREFERRED_NAMES,
):
    """Путь к лучшему чекпойнту или `""`, если ничего не найдено."""
    rows = list_checkpoints(
        directory=directory,
        kind=kind,
        root=root,
        preferred=preferred,
    )
    return rows[0]["path"] if rows else ""


def resolve_checkpoint(
    explicit="",
    directory=None,
    kind=None,
    root=None,
    auto=True,
    preferred=PREFERRED_NAMES,
):
    """Явный путь важнее автопоиска; `auto=False` отключает поиск.

    Явный путь возвращается как есть, даже если файл отсутствует: вызывающий
    код (`game_engine._ai_policy`) уже умеет логировать ошибку и падать на
    BDI, а молчаливая подмена чужого пути скрыла бы опечатку.
    """
    if explicit:
        return str(explicit)
    if not auto:
        return ""
    return find_checkpoint(
        directory=directory,
        kind=kind,
        root=root,
        preferred=preferred,
    )


__all__ = [
    "CHECKPOINT_DIR_ENV",
    "DEFAULT_CHECKPOINT_DIR",
    "KNOWN_KINDS",
    "PREFERRED_NAMES",
    "checkpoint_kind",
    "default_checkpoint_dir",
    "find_checkpoint",
    "is_loadable",
    "list_checkpoints",
    "project_root",
    "read_checkpoint",
    "resolve_checkpoint",
]
