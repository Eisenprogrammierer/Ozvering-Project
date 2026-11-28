"""Согласованность активной документации с кодом.

Проверки намеренно узкие: версии схем, устаревшие числа, существование
упомянутых Python-модулей и CLI-флагов. Они не переписывают документы,
а ловят расхождения, которые уже случались в истории проекта.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
ACTIVE_DOCS = sorted((ROOT / "docs").glob("*.md")) + [ROOT / "README.md"]

# Удалённые, плановые или примерные имена, которые документы упоминают
# осознанно.
PATH_ALLOWLIST = {
    "action_menu.py",  # удалён, CAMPAIGN_UI.md говорит об этом
    "hq_scene.py",  # удалён
    "map_screen.py",  # удалён
    "my_screen.py",  # пример нового экрана в ONBOARDING.md
    "test_data_driven_core.py",  # планируемый тест
    "warfare_support.py",  # планируемый модуль
    "nlu_frame.py",
    "nlu_entities.py",
    "nlu_morph.py",
    "nlu_compile.py",
    "lint_nlu.py",
    "soar_agent.py",
}

FLAG_ALLOWLIST = {"--debug-dialogue"}  # документ явно говорит, что флага нет


def _docs():
    for path in ACTIVE_DOCS:
        yield path, path.read_text(encoding="utf-8")


def _constant(relpath, name):
    text = (ROOT / relpath).read_text(encoding="utf-8")
    match = re.search(r"^%s\s*=\s*(\d+)" % name, text, re.M)
    assert match, "в %s нет %s" % (relpath, name)
    return match.group(1)


def test_save_version_in_docs_matches_code():
    expected = _constant("view/support/save_system.py", "SAVE_VERSION")
    bad = []
    for path, text in _docs():
        for match in re.finditer(r"SAVE_VERSION\s*=\s*`?(\d+)", text):
            if match.group(1) != expected:
                bad.append((str(path.relative_to(ROOT)), match.group(0)))
    assert not bad, "SAVE_VERSION в доках: %s" % bad


def test_schema_and_checkpoint_versions_match_code():
    expected = {
        "SCHEMA_VERSION": _constant(
            "campaign/projections.py", "SCHEMA_VERSION"
        ),
        "CHECKPOINT_VERSION": _constant(
            "agents/policies.py", "CHECKPOINT_VERSION"
        ),
        "DUEL_CHECKPOINT_VERSION": _constant(
            "agents/policies.py", "DUEL_CHECKPOINT_VERSION"
        ),
    }
    bad = []
    for path, text in _docs():
        for name, value in expected.items():
            equals = r"(?<![A-Z_])%s\s*=\s*`?(\d+)" % name
            table = (
                r"\|\s*`?(?<![A-Z_])%s`?\s*[^|\n]*\|\s*`?(\d+)`?\s*\|"
                % name
            )
            for pattern in (equals, table):
                for match in re.finditer(pattern, text):
                    if match.group(1) != value:
                        bad.append(
                            (
                                str(path.relative_to(ROOT)),
                                name,
                                match.group(1),
                            )
                        )
    assert not bad, "версии в доках: %s" % bad


def test_no_stale_test_counts_or_versions():
    stale = ("2076 тест", "2125 тест", "1098 с", "SAVE_VERSION = 3")
    found = []
    for path, text in _docs():
        for item in stale:
            if item in text:
                found.append((str(path.relative_to(ROOT)), item))
    assert not found, "устаревшие числа: %s" % found


def test_documented_python_paths_exist():
    pattern = re.compile(r"`([A-Za-z0-9_./-]+\.py)`")
    names = {
        path.name
        for path in ROOT.rglob("*.py")
        if "venv" not in path.parts and "__pycache__" not in path.parts
    }
    missing = []
    for path, text in _docs():
        for match in pattern.finditer(text):
            raw = match.group(1)
            candidate = ROOT / raw
            if candidate.exists() or pathlib.Path(raw).name in names:
                continue
            if pathlib.Path(raw).name in PATH_ALLOWLIST:
                continue
            missing.append((str(path.relative_to(ROOT)), raw))
    assert not missing, "несуществующие модули: %s" % missing


def test_documented_cli_flags_exist():
    code_flags = set()
    for path in ROOT.rglob("*.py"):
        if "venv" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        code_flags.update(
            re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", text)
        )
    pattern = re.compile(r"`(--[a-z][a-z0-9-]*)`")
    missing = []
    for path, text in _docs():
        for match in pattern.finditer(text):
            flag = match.group(1)
            if flag in code_flags or flag in FLAG_ALLOWLIST:
                continue
            missing.append((str(path.relative_to(ROOT)), flag))
    assert not missing, "несуществующие флаги: %s" % missing


def test_production_roles_and_world_are_documented_as_current():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    world = (ROOT / "docs" / "WORLD.md").read_text(encoding="utf-8")
    assert "начинается с роли `world_actor`" not in readme
    assert "`configs/worlds/` пуст" not in readme
    assert "free_citizen" in world
    assert "пять ролей" in readme
