# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-сборка «Операции Озверин» (onedir).

Данные (assets/, configs/, scenarios/, campaigns/, checkpoints/, music/)
кладутся рядом с кодом внутри каталога сборки: игровые модули находят их
через `Path(__file__).parents[...]`, и в замороженном виде `__file__`
указывает внутрь `_internal`/`_MEIPASS`, куда PyInstaller копирует datas.

Сборка:
    python -m pip install -e ".[build]"
    python -m PyInstaller --noconfirm --clean packaging/ozvering.spec
Результат: dist/ozvering/ (Linux/macOS) или dist\\ozvering\\ (Windows).
"""

import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

DATA_DIRS = (
    "assets",
    "configs",
    "scenarios",
    "campaigns",
    "checkpoints",
    "music",
)

datas = [
    (os.path.join(ROOT, name), name)
    for name in DATA_DIRS
    if os.path.isdir(os.path.join(ROOT, name))
]

PACKAGES = (
    "agents",
    "automata",
    "campaign",
    "core41",
    "interaction",
    "naming",
    "organizations",
    "systems",
    "ui",
    "view",
)
hiddenimports = []
for package in PACKAGES:
    hiddenimports.extend(collect_submodules(package))

analysis = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tests",
        "experiments",
        "matplotlib",
        "tkinter",
        "yet_another_project",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ozvering",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ozvering",
)
