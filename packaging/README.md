# Упаковка и установка

Три независимых сценария. Выбирайте по задаче.

## 1. Разработка / запуск из чекаута

```bash
python3 -m venv venv
venv/bin/pip install -e ".[dev]"
venv/bin/python main.py
```

Editable-установка (`-e`) добавляет корень репозитория в `sys.path`, поэтому
игра и обучения видят `assets/`, `configs/`, `music/` и остальные данные
ровно так же, как при запуске `python3 main.py` из корня.

## 2. Python-пакет (wheel)

```bash
pip install .
```

Даёт импортируемые пакеты (`agents`, `core41`, `campaign`, `view`, …) и
консольную команду `ozvering` (entry point `main:main`).

Этого достаточно для:

* `ozvering --list-checkpoints`;
* `python -m agents.train ...` (обучение агентов);
* использования среды обучения как библиотеки.

**Ограничение:** wheel не кладёт в `site-packages` каталоги данных
(`assets/`, `configs/`, `music/`, …). Полноценный GUI-запуск из wheel пока
не поддерживается — используйте editable-установку или сборку из п. 3.
Универсальный резолвер данных (пользовательский каталог + `importlib.resources`)
запланирован отдельным пунктом в
[`docs/RELEASE_READINESS.md`](../docs/RELEASE_READINESS.md).

## 3. Настольный дистрибутив (PyInstaller)

```bash
venv/bin/pip install -e ".[build]"
venv/bin/python -m PyInstaller --noconfirm --clean packaging/ozvering.spec
```

Результат — `dist/ozvering/` (onedir). Внутрь копируются `assets/`,
`configs/`, `scenarios/`, `campaigns/`, `checkpoints/` и `music/`, поэтому
запуск не зависит от текущего каталога:

```bash
./dist/ozvering/ozvering
```

Готовые обёртки:

```bash
packaging/build_linux.sh      # Linux/macOS
packaging\build_windows.bat   # Windows
```

### Установка на Linux

```bash
packaging/build_linux.sh
packaging/install_linux.sh
```

Скрипт копирует сборку в `~/.local/opt/ozvering` (переопределяется
`OZVERING_INSTALL_DIR`) и создаёт ярлык `ozvering.desktop` в
`~/.local/share/applications`.

### Замечания

* Сборка — **onedir**, а не onefile: так быстрее старт и проще обновлять
  данные без пересборки бинарника.
* `music/` занимает ~120 МБ и попадает и в sdist, и в сборку. Для облегчения
  дистрибутива каталог можно исключить из `DATA_DIRS` в `ozvering.spec` —
  игра продолжит работать без музыки.
* Консоль в GUI-сборке отключена (`console=False`). Для CLI-сценариев
  (обучение, `--list-checkpoints`) используйте Python-установку из п. 1–2.
* В дистрибутив не входят `tests/`, `experiments/`, `matplotlib`, `tkinter`
  и `yet_another_project/`; ленивые импорты пакетов собираются явно через
  `hiddenimports`, чтобы PyInstaller их не пропустил.
* Сейвы и лог по-прежнему пишутся в каталог проекта/сборки. Перенос в
  пользовательский каталог (`XDG_DATA_HOME` / `%APPDATA%`) — отдельный
  пункт релизной обвязки.
