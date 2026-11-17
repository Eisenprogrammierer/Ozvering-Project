"""Простые факты здравого смысла: загрузка, запросы и проверка.

Данные лежат в ``configs/knowledge/commonsense/``. Это не канон мира и не
замена диалоговой онтологии: набор служит подсказкой для распознавания
речевого режима, причин эмоций и назначения предметов. Формат намеренно
плоский — ``s`` (субъект), ``r`` (отношение), ``o`` (объект), вес и
провенанс, — поэтому его можно расширять JSONL-строками без правки Python.

Сырые LLM-выгрузки лежат в ``raw/`` и не читаются: загрузчик обходит только
верхний уровень каталога и сверяется со ``schema.json``.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import (
    Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "configs" / "knowledge" / "commonsense"

CAUSAL_RELATIONS = (
    "Causes",
    "ResultsIn",
    "Prevents",
    "Reduces",
    "Increases",
)
REQUIRED_FIELDS = ("s", "r", "o", "weight")
OPTIONAL_FIELDS = ("lang", "origin", "source")
_WORD = r"0-9a-zа-я"


class CommonsenseError(ValueError):
    """Ошибка данных или схемы фактов."""


def normalize(text: Any) -> str:
    """Свести строку к сравнимому виду: регистр, ё, пробелы, края."""

    value = str(text or "").casefold().replace("ё", "е")
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip(".,;:!?«»\"'()[]")


def _mentions(text: str, phrase: str) -> bool:
    """Встречается ли фраза в тексте как отдельное слово/оборот."""

    phrase = normalize(phrase)
    if not phrase:
        return False
    if " " in phrase:
        return phrase in text
    pattern = r"(?<![%s])%s(?![%s])" % (
        _WORD,
        re.escape(phrase),
        _WORD,
    )
    return re.search(pattern, text) is not None


@dataclass(frozen=True)
class Fact:
    """Один факт: субъект, отношение, объект и провенанс."""

    s: str
    r: str
    o: str
    weight: float = 1.0
    lang: str = "ru"
    origin: str = "curated"
    source: str = ""
    file: str = ""

    @property
    def key(self) -> Tuple[str, str, str]:
        return (
            normalize(self.s),
            self.r,
            normalize(self.o),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "s": self.s,
            "r": self.r,
            "o": self.o,
            "weight": self.weight,
            "lang": self.lang,
            "origin": self.origin,
            "source": self.source,
        }


@dataclass(frozen=True)
class Reading:
    """Что факты говорят о фразе игрока."""

    text: str
    acts: Tuple[str, ...] = ()
    modes: Tuple[str, ...] = ()
    styles: Tuple[str, ...] = ()
    evidence: Tuple[Fact, ...] = field(default_factory=tuple)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "acts": list(self.acts),
            "modes": list(self.modes),
            "styles": list(self.styles),
            "evidence": [fact.as_dict() for fact in self.evidence],
        }


class FactBase:
    """Индекс фактов с запросами по субъекту, отношению и объекту."""

    def __init__(
        self,
        facts: Iterable[Fact],
        schema: Mapping[str, Any],
    ) -> None:
        self.schema = dict(schema)
        self.facts: Tuple[Fact, ...] = tuple(facts)
        self.acts = tuple(self.schema.get("acts") or ())
        self.modes = tuple(self.schema.get("modes") or ())
        self.style_hints = dict(self.schema.get("style_hints") or {})
        self.relations = tuple(self.schema.get("relations") or ())
        self._by_subject: Dict[str, List[Fact]] = {}
        self._by_object: Dict[str, List[Fact]] = {}
        self._by_relation: Dict[str, List[Fact]] = {}
        for fact in self.facts:
            self._by_subject.setdefault(normalize(fact.s), []).append(fact)
            self._by_object.setdefault(normalize(fact.o), []).append(fact)
            self._by_relation.setdefault(fact.r, []).append(fact)

    def __len__(self) -> int:
        return len(self.facts)

    def lookup(
        self,
        subject: Optional[str] = None,
        relation: Optional[str] = None,
        object: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[Fact, ...]:
        """Точный поиск по нормализованным полям, сильные факты первыми."""

        result = list(self.facts)
        if subject is not None:
            wanted = normalize(subject)
            result = [item for item in result if normalize(item.s) == wanted]
        if object is not None:
            wanted = normalize(object)
            result = [item for item in result if normalize(item.o) == wanted]
        if relation is not None:
            result = [item for item in result if item.r == relation]
        result.sort(key=lambda item: (-item.weight, item.s, item.o))
        if limit is not None:
            result = result[: max(0, int(limit))]
        return tuple(result)

    def by_relation(self, relation: str) -> Tuple[Fact, ...]:
        return tuple(
            sorted(
                self._by_relation.get(str(relation), ()),
                key=lambda item: (-item.weight, item.s, item.o),
            )
        )

    def related(
        self, term: str, limit: Optional[int] = None
    ) -> Tuple[Fact, ...]:
        """Все факты, где термин стоит субъектом или объектом."""

        wanted = normalize(term)
        seen = set()
        result = []
        for fact in self._by_subject.get(wanted, ()) + self._by_object.get(
            wanted, ()
        ):
            if fact.key in seen:
                continue
            seen.add(fact.key)
            result.append(fact)
        result.sort(key=lambda item: (-item.weight, item.s, item.o))
        if limit is not None:
            result = result[: max(0, int(limit))]
        return tuple(result)

    def effects_of(
        self,
        cause: str,
        relations: Sequence[str] = CAUSAL_RELATIONS,
    ) -> Tuple[Fact, ...]:
        return tuple(
            fact
            for fact in self.lookup(subject=cause)
            if fact.r in relations
        )

    def classes_of(self, entity: str) -> Tuple[Fact, ...]:
        return self.lookup(subject=entity, relation="IsA")

    def properties_of(self, entity: str) -> Tuple[Fact, ...]:
        return self.lookup(subject=entity, relation="HasProperty")

    def uses_of(self, entity: str) -> Tuple[Fact, ...]:
        return self.lookup(subject=entity, relation="UsedFor")

    def style_for(self, mode: str) -> str:
        """Подсказка стиля для режима разговора, если она объявлена."""

        return str(self.style_hints.get(str(mode)) or "")

    def classify(self, text: str) -> Reading:
        """Распознать речевые акты и режимы по фразам-маркерам."""

        normalized = normalize(text)
        if not normalized:
            return Reading(text=str(text or ""))
        best_acts: Dict[str, Tuple[float, Fact]] = {}
        best_modes: Dict[str, Tuple[float, Fact]] = {}
        for fact in self.facts:
            if not _mentions(normalized, fact.s):
                continue
            if fact.r == "IsA" and fact.o in self.acts:
                current = best_acts.get(fact.o)
                if current is None or fact.weight > current[0]:
                    best_acts[fact.o] = (fact.weight, fact)
            elif fact.r == "UsedIn" and fact.o in self.modes:
                current = best_modes.get(fact.o)
                if current is None or fact.weight > current[0]:
                    best_modes[fact.o] = (fact.weight, fact)

        acts = tuple(
            name
            for name, _ in sorted(
                best_acts.items(), key=lambda item: (-item[1][0], item[0])
            )
        )
        modes = tuple(
            name
            for name, _ in sorted(
                best_modes.items(), key=lambda item: (-item[1][0], item[0])
            )
        )
        styles = tuple(
            dict.fromkeys(
                self.style_for(mode)
                for mode in modes
                if self.style_for(mode)
            )
        )
        evidence = tuple(
            dict.fromkeys(
                [fact for _, fact in best_acts.values()]
                + [fact for _, fact in best_modes.values()]
            )
        )
        return Reading(
            text=str(text or ""),
            acts=acts,
            modes=modes,
            styles=styles,
            evidence=evidence,
        )

    def summary(self) -> Dict[str, Any]:
        by_relation: Dict[str, int] = {}
        for fact in self.facts:
            by_relation[fact.r] = by_relation.get(fact.r, 0) + 1
        files: Dict[str, int] = {}
        for fact in self.facts:
            files[fact.file] = files.get(fact.file, 0) + 1
        return {
            "facts": len(self.facts),
            "relations": by_relation,
            "files": files,
            "acts": len(self.acts),
            "modes": len(self.modes),
        }


def _schema_path(directory: pathlib.Path) -> pathlib.Path:
    return directory / "schema.json"


def load_schema(directory: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    directory = pathlib.Path(directory or DEFAULT_DIR)
    path = _schema_path(directory)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CommonsenseError("%s: %s" % (path, error)) from error
    except ValueError as error:
        raise CommonsenseError("%s: %s" % (path, error)) from error
    if not isinstance(raw, Mapping):
        raise CommonsenseError("%s: схема должна быть объектом" % path)
    if int(raw.get("schema") or 0) != 1:
        raise CommonsenseError("%s: поддерживается schema=1" % path)
    relations = raw.get("relations")
    if not isinstance(relations, Mapping) or not relations:
        raise CommonsenseError("%s: пустой relations" % path)
    for key in ("acts", "modes", "languages", "origins", "files"):
        if not isinstance(raw.get(key), (list, Mapping)) or not raw.get(key):
            raise CommonsenseError("%s: пустой %s" % (path, key))
    hints = raw.get("style_hints")
    if hints is not None:
        if not isinstance(hints, Mapping):
            raise CommonsenseError(
                "%s: style_hints должен быть объектом" % path
            )
        unknown = sorted(set(hints) - set(raw.get("modes") or ()))
        if unknown:
            raise CommonsenseError(
                "%s: style_hints ссылается на неизвестные режимы %s"
                % (path, ", ".join(unknown))
            )
        for key, value in hints.items():
            if not str(value or "").strip():
                raise CommonsenseError(
                    "%s: style_hints.%s пуст" % (path, key)
                )
    return dict(raw)


def _row_error(
    path: pathlib.Path, line: int, message: str
) -> CommonsenseError:
    return CommonsenseError("%s:%d: %s" % (path, line, message))


def _validate_row(
    row: Any,
    path: pathlib.Path,
    line: int,
    schema: Mapping[str, Any],
    file_spec: Mapping[str, Any],
) -> Fact:
    if not isinstance(row, Mapping):
        raise _row_error(path, line, "запись должна быть объектом")
    for key in REQUIRED_FIELDS:
        if key not in row:
            raise _row_error(path, line, "нет поля %r" % key)
    if not normalize(row.get("s")) or not normalize(row.get("o")):
        raise _row_error(path, line, "пустой s или o")
    weight = row.get("weight")
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        raise _row_error(path, line, "weight должен быть числом")
    weight = float(weight)
    if not 0.0 <= weight <= 1.0:
        raise _row_error(path, line, "weight вне диапазона 0..1")
    relation = str(row.get("r") or "")
    if relation not in schema["relations"]:
        raise _row_error(path, line, "неизвестное отношение %r" % relation)
    lang = str(row.get("lang") or "ru")
    if lang not in schema["languages"]:
        raise _row_error(path, line, "неизвестный язык %r" % lang)
    origin = str(row.get("origin") or "curated")
    if origin not in schema["origins"]:
        raise _row_error(path, line, "неизвестное происхождение %r" % origin)
    if normalize(row.get("s")) == normalize(row.get("o")):
        raise _row_error(path, line, "субъект совпадает с объектом")
    required = str(file_spec.get("required_relation") or "")
    if required and relation != required:
        raise _row_error(
            path,
            line,
            "ожидалось отношение %r, получено %r" % (required, relation),
        )
    relation_list = file_spec.get("relations") or ()
    if relation_list and relation not in relation_list:
        raise _row_error(
            path, line, "отношение %r не разрешено для файла" % relation
        )
    object_in = str(file_spec.get("object_in") or "")
    if object_in:
        allowed = schema.get(object_in) or ()
        if str(row.get("o")) not in allowed:
            raise _row_error(
                path,
                line,
                "объект %r не входит в %s" % (row.get("o"), object_in),
            )
    return Fact(
        s=str(row.get("s")),
        r=relation,
        o=str(row.get("o")),
        weight=weight,
        lang=lang,
        origin=origin,
        source=str(row.get("source") or ""),
        file=path.name,
    )


def _read_lines(path: pathlib.Path) -> Iterable[Tuple[int, str]]:
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if text:
                yield number, text


def load_commonsense(
    directory: Optional[pathlib.Path] = None,
) -> FactBase:
    """Загрузить верхнеуровневые JSONL-файлы и проверить схему."""

    directory = pathlib.Path(directory or DEFAULT_DIR)
    schema = load_schema(directory)
    files = schema.get("files") or {}
    facts: List[Fact] = []
    seen: Dict[Tuple[str, str, str], pathlib.Path] = {}
    for path in sorted(directory.glob("*.jsonl")):
        file_spec = files.get(path.name) or {}
        for line, text in _read_lines(path):
            try:
                raw = json.loads(text)
            except ValueError as error:
                raise _row_error(path, line, "невалидный JSON: %s" % error)
            fact = _validate_row(raw, path, line, schema, file_spec)
            if fact.key in seen:
                raise _row_error(
                    path,
                    line,
                    "дубликат факта из %s" % seen[fact.key].name,
                )
            seen[fact.key] = path
            facts.append(fact)
    if not facts:
        raise CommonsenseError("%s: нет файлов с фактами" % directory)
    return FactBase(facts, schema)


_DEFAULT_BASE: Optional[FactBase] = None


def default_factbase() -> FactBase:
    """Ленивый общий экземпляр для консоли и утилит."""

    global _DEFAULT_BASE
    if _DEFAULT_BASE is None:
        _DEFAULT_BASE = load_commonsense()
    return _DEFAULT_BASE


def lint_commonsense(
    directory: Optional[pathlib.Path] = None,
) -> List[str]:
    """Проверить данные, вернув список проблем вместо исключения."""

    directory = pathlib.Path(directory or DEFAULT_DIR)
    try:
        schema = load_schema(directory)
    except CommonsenseError as error:
        return [str(error)]
    problems: List[str] = []
    files = schema.get("files") or {}
    for name in files:
        if not (directory / name).is_file():
            problems.append("%s: нет обязательного файла" % (directory / name))
    paths = sorted(directory.glob("*.jsonl"))
    if not paths:
        problems.append("%s: нет JSONL-файлов" % directory)
    for path in paths:
        file_spec = files.get(path.name) or {}
        if path.name not in files:
            problems.append("%s: файл не описан в schema.json" % path)
        seen: Dict[Tuple[str, str, str], int] = {}
        for line, text in _read_lines(path):
            try:
                raw = json.loads(text)
            except ValueError as error:
                problems.append(
                    "%s:%d: невалидный JSON: %s" % (path, line, error)
                )
                continue
            try:
                fact = _validate_row(raw, path, line, schema, file_spec)
            except CommonsenseError as error:
                problems.append(str(error))
                continue
            if fact.key in seen:
                problems.append(
                    "%s:%d: дубликат факта из строки %d"
                    % (path, line, seen[fact.key])
                )
                continue
            seen[fact.key] = line
        if not seen:
            problems.append("%s: файл пуст" % path)
    return problems


def _print_reading(reading: Reading) -> None:
    print("фраза: %s" % reading.text)
    print("акты: %s" % (", ".join(reading.acts) or "—"))
    print("режимы: %s" % (", ".join(reading.modes) or "—"))
    print("стиль: %s" % (", ".join(reading.styles) or "—"))
    if reading.evidence:
        print("основания:")
        for fact in reading.evidence:
            print(
                "  %s --%s--> %s (%.2f)"
                % (fact.s, fact.r, fact.o, fact.weight)
            )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m campaign.commonsense",
        description="Факты здравого смысла: проверка и подсказки по фразе.",
    )
    parser.add_argument("text", nargs="*", help="фраза для разбора")
    parser.add_argument(
        "--check",
        action="store_true",
        help="только проверить данные",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="показать сводку по фактам",
    )
    parser.add_argument(
        "--dir",
        default=str(DEFAULT_DIR),
        help="каталог с schema.json и JSONL",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    directory = pathlib.Path(args.dir)
    if args.check:
        problems = lint_commonsense(directory)
        for problem in problems:
            print(problem)
        if problems:
            print("найдено проблем: %d" % len(problems), file=sys.stderr)
            return 1
        try:
            base = load_commonsense(directory)
        except CommonsenseError as error:
            print(str(error), file=sys.stderr)
            return 1
        print("факты здравого смысла в порядке: %d" % len(base))
        return 0
    try:
        base = load_commonsense(directory)
    except CommonsenseError as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.text:
        _print_reading(base.classify(" ".join(args.text)))
        return 0
    summary = base.summary()
    print("фактов: %d" % summary["facts"])
    print("актов: %d, режимов: %d" % (summary["acts"], summary["modes"]))
    for relation in sorted(summary["relations"]):
        print("  %-12s %d" % (relation, summary["relations"][relation]))
    for name in sorted(summary["files"]):
        print("  %-24s %d" % (name, summary["files"][name]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
