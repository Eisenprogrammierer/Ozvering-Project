"""Хранилище автоматов: JSON-файлы в ``configs/automata/``.

Один файл — один автомат. Запись атомарная (временный файл + ``os.replace``),
кодировка UTF-8. Чтение не роняет список: повреждённый файл показывается
отдельной записью с текстом ошибки.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

from .model import Automaton, AutomatonError, slugify

ROOT = Path(__file__).resolve().parents[1] / "configs" / "automata"


class StoreError(RuntimeError):
    """Ошибка чтения/записи файла автомата."""


class AutomataStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else ROOT

    # --- пути -----------------------------------------------------------
    def _path(self, slug):
        slug = str(slug or "")
        if not slug or Path(slug).name != slug or slug in (".", ".."):
            raise StoreError("некорректное имя файла: %r" % (slug,))
        return self.root / ("%s.json" % slug)

    def ensure(self):
        self.root.mkdir(parents=True, exist_ok=True)

    def exists(self, slug):
        try:
            return self._path(slug).is_file()
        except StoreError:
            return False

    # --- чтение ---------------------------------------------------------
    def load(self, slug):
        path = self._path(slug)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            raise StoreError("файл не найден: %s" % path.name)
        except Exception as exc:
            raise StoreError("не удалось прочитать %s: %s"
                             % (path.name, exc))
        try:
            return Automaton.from_dict(data)
        except AutomatonError as exc:
            raise StoreError("%s: %s" % (path.name, exc))

    def list_entries(self):
        """Список ``{slug, name, states, transitions, updated, error}``."""
        if not self.root.is_dir():
            return []
        entries = []
        for path in sorted(self.root.glob("*.json")):
            slug = path.stem
            updated = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
            try:
                automaton = self.load(slug)
                states, transitions = automaton.counts()
                entries.append({
                    "slug": slug,
                    "name": automaton.name or slug,
                    "states": states,
                    "transitions": transitions,
                    "updated": updated,
                    "error": "",
                })
            except StoreError as exc:
                entries.append({
                    "slug": slug,
                    "name": slug,
                    "states": 0,
                    "transitions": 0,
                    "updated": updated,
                    "error": str(exc),
                })
        entries.sort(key=lambda item: (item["name"].lower(), item["slug"]))
        return entries

    # --- запись ---------------------------------------------------------
    def _write(self, path, payload):
        self.ensure()
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def unique_slug(self, base):
        base = slugify(base)
        candidate = base
        number = 2
        while self.exists(candidate):
            candidate = "%s_%d" % (base, number)
            number += 1
        return candidate

    def save(self, automaton, slug=None):
        """Записать автомат. Без ``slug`` имя файла выводится из названия."""
        if slug is None:
            slug = self.unique_slug(automaton.name)
        path = self._path(slug)
        self._write(path, automaton.to_dict())
        return slug

    def create(self, automaton, name=None):
        if name is not None:
            automaton.name = str(name)
        slug = self.unique_slug(automaton.name)
        self.save(automaton, slug)
        return slug

    def duplicate(self, slug):
        automaton = self.load(slug)
        automaton.name = "Копия — %s" % (automaton.name or slug)
        return self.create(automaton)

    def delete(self, slug):
        try:
            self._path(slug).unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise StoreError("не удалось удалить %s: %s" % (slug, exc))
