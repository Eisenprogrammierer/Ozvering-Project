"""Исполнение сгенерированного RiveScript в живом NLU.

Движок выбирает триггер и возвращает захваты ``<star>``. Точные
триггеры несут готовую логическую форму из манифеста, грамматические —
шаблон правила и роли слотов: лексикон превращает захваты в смысл,
после чего кадр собирает общий адаптер. ``ChartParser`` разбирает
вложенные ``S``-слоты и служит полным откатом, если триггер не найден
или слот не разрешился.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from campaign.dialogue.morphology import tokenize

from .backends import CognitionFlags, load_flags
from .errors import BackendError, RiveError
from .frame import UtteranceFrame
from .nlu import LegacyNlu
from .rive_compiler import (
    DEFAULT_RIVE_DIR,
    MANIFEST_NAME,
    PAYLOAD_SEPARATOR,
    RIVE_NAME,
    RiveManifest,
)
from .rive_macros import load_macros, register_macros

FALLBACK_ID = "__fallback__"
RUNTIME_VERSION = 2
_ENGINE_CACHE: Dict[Tuple[str, int], Any] = {}
_MANIFEST_CACHE: Dict[Tuple[str, int], RiveManifest] = {}


def default_manifest_path() -> Path:
    return DEFAULT_RIVE_DIR / MANIFEST_NAME


def default_rive_path() -> Path:
    return DEFAULT_RIVE_DIR / RIVE_NAME


def _nlu_subroutine(rs: Any, args: Tuple[str, ...]) -> str:
    # ``<call>`` режет аргументы по пробелам, а захваты ``<star>`` могут
    # быть многословными. Склейка возвращает исходную полезную нагрузку:
    # разделитель ``PAYLOAD_SEPARATOR`` остаётся границей id и звёзд.
    if not args:
        return FALLBACK_ID
    return " ".join(str(arg) for arg in args)


def _load_manifest(path: Path) -> RiveManifest:
    source = Path(path)
    try:
        stamp = source.stat().st_mtime_ns
    except OSError as exc:
        raise BackendError(
            "нет манифеста RiveScript: %s. "
            "Запустите python -m campaign.cognition.rive_compiler --write"
            % source
        ) from exc
    key = (str(source), stamp)
    cached = _MANIFEST_CACHE.get(key)
    if cached is not None:
        return cached
    manifest = RiveManifest.load(source)
    _MANIFEST_CACHE[key] = manifest
    return manifest


def _forget_engine(path: Path) -> None:
    """Выбросить упавший движок из кэша перед перезагрузкой."""

    target = str(path)
    for key in [key for key in _ENGINE_CACHE if key[0] == target]:
        _ENGINE_CACHE.pop(key, None)


def _load_engine(path: Path) -> Any:
    source = Path(path)
    try:
        stamp = source.stat().st_mtime_ns
    except OSError as exc:
        raise BackendError(
            "нет сгенерированного RiveScript: %s. "
            "Запустите python -m campaign.cognition.rive_compiler --write"
            % source
        ) from exc
    key = (str(source), stamp)
    cached = _ENGINE_CACHE.get(key)
    if cached is not None:
        # В RiveScript 1.15 словарь Python-объектов общий для всех
        # движков, поэтому чужая регистрация ``nlu`` может перетереть
        # нашу. Переустанавливаем подпрограмму при каждом обращении.
        cached.set_subroutine("nlu", _nlu_subroutine)
        return cached
    try:
        from rivescript import RiveScript
    except ImportError as exc:
        raise BackendError(
            "nlu_backend=rive требует пакет rivescript "
            "(pip install 'rivescript>=1.15,<2')"
        ) from exc
    engine = RiveScript(utf8=True)
    try:
        engine.load_file(str(source))
        engine.sort_replies()
    except Exception as exc:
        raise RiveError("не удалось загрузить %s" % source) from exc
    engine.set_subroutine("nlu", _nlu_subroutine)
    _ENGINE_CACHE[key] = engine
    return engine


class RiveNlu:
    """NLU-бэкенд: RiveScript выбирает триггер и слоты, кадр — из манифеста.

    Точные триггеры (парафразы, действия, маркеры) несут готовую
    логическую форму, скомпилированную из JSON. Грамматические триггеры
    несут шаблон правила и роли слотов: захваты ``<star>`` заполняют
    роли, а лексикон превращает формы в смысл. ``ChartParser`` остаётся
    путём отката, если триггер не сработал или слот не разрешился.
    """

    def __init__(
        self,
        session: Any,
        flags: Optional[CognitionFlags] = None,
        *,
        manifest_path: Optional[Path] = None,
        rive_path: Optional[Path] = None,
    ):
        resolved = flags or load_flags()
        self.session = session
        self.flags = resolved
        self.legacy = LegacyNlu(session, resolved)
        self.manifest = _load_manifest(
            Path(manifest_path) if manifest_path else default_manifest_path()
        )
        self.rive_path = (
            Path(rive_path) if rive_path else default_rive_path()
        )
        self.engine = _load_engine(self.rive_path)
        self.macros = load_macros()
        register_macros(self.engine, self.macros)
        self.counts: Dict[str, int] = {
            "total": 0,
            "matched": 0,
            "fallback": 0,
            "semantic_fallback": 0,
            "empty": 0,
        }
        self.sources: Dict[str, int] = {}
        self._index: Optional[Dict[Tuple[str, Tuple[str, ...]], Any]] = None
        self.last_sem: Any = None
        self.last_parse: Any = None
        self.last_source = ""
        self.last_rule = ""
        self.last_reason = ""
        self.last_trigger = ""
        self.last_match: Any = None

    def reset(self) -> None:
        """Сбросить счётчики живого ввода."""

        for key in self.counts:
            self.counts[key] = 0
        self.sources.clear()

    def recover(self) -> bool:
        """Перезагрузить движок после сбоя, сохранив манифест и макросы.

        Кэш движков ключуется путём и mtime, поэтому упавший экземпляр
        нужно выбросить явно: иначе ``_load_engine`` вернёт его же.
        Возвращает ``False``, если перезагрузка не удалась.
        """

        _forget_engine(self.rive_path)
        try:
            self.engine = _load_engine(self.rive_path)
            register_macros(self.engine, self.macros)
        except Exception:  # noqa: BLE001 — решение об отказе принимает бэкенд
            return False
        return True

    def report(self, threshold: Optional[float] = None) -> Dict[str, Any]:
        """Доля fallback на живом вводе и порог из конфига."""

        limit = (
            float(self.flags.nlu_fallback_max)
            if threshold is None
            else float(threshold)
        )
        total = self.counts["total"]
        fallback = self.counts["fallback"]
        rate = fallback / float(total) if total else 0.0
        return {
            "kind": "nlu_runtime",
            "version": RUNTIME_VERSION,
            "total": total,
            "matched": self.counts["matched"],
            "fallback": fallback,
            "semantic_fallback": self.counts["semantic_fallback"],
            "empty": self.counts["empty"],
            "fallback_rate": round(rate, 6),
            "threshold": limit,
            "ok": rate <= limit,
            "sources": {
                key: self.sources[key] for key in sorted(self.sources)
            },
        }

    def _match(self, text: str) -> Tuple[str, Tuple[str, ...]]:
        """Триггер и захваты ``<star>`` из ответа RiveScript."""

        # Словарь Python-объектов RiveScript общий для всех экземпляров:
        # переустанавливаем ``nlu`` прямо перед разбором, чтобы чужая
        # регистрация не потеряла захваты.
        self.engine.set_subroutine("nlu", _nlu_subroutine)
        try:
            reply = self.engine.reply("nlu", text)
        except Exception as exc:
            raise BackendError("RiveScript не смог разобрать фразу") from exc
        value = str(reply or "").strip()
        if value.startswith("[ERR:"):
            raise BackendError("RiveScript: %s" % value)
        if not value:
            return "", ()
        parts = value.split(PAYLOAD_SEPARATOR)
        return parts[0], tuple(parts[1:])

    def _adopt(self, base: Any) -> None:
        """Перенести последний legacy-разбор в публичные поля."""

        self.last_sem = self.legacy.last_sem
        self.last_parse = self.legacy.last_parse
        self.last_source = self.legacy.last_source
        self.last_rule = self.legacy.last_rule
        self.last_reason = self.legacy.last_reason
        self.last_trigger = ""
        self.last_match = None

    def understand(self, text: str, *, topic: str = "default"):
        raw = str(text or "")
        if not raw.strip():
            base = self.legacy.understand(raw, topic=topic)
            self._adopt(base)
            self.counts["empty"] += 1
            return base
        self.counts["total"] += 1
        trigger_id, stars = self._match(raw)
        match = self.manifest.get(trigger_id) if trigger_id else None
        if match is None or not match.frame:
            return self._fallback(raw, topic)
        sem = self._build_sem(match, stars, raw)
        if sem is None:
            self.counts["semantic_fallback"] += 1
            return self._fallback(raw, topic)
        resolved, unresolved = self.session.state.resolve_pronouns(sem)
        if isinstance(resolved, Mapping):
            sem = resolved
        self.counts["matched"] += 1
        self.sources[match.source] = self.sources.get(match.source, 0) + 1
        self.last_sem = sem
        self.last_parse = None
        self.last_source = "parser"
        self.last_rule = match.rule or match.id
        self.last_reason = ""
        self.last_trigger = match.id
        self.last_match = match
        result = self.legacy.build_result(
            sem,
            raw,
            "parser",
            self.last_rule,
            tuple(unresolved),
            topic=topic,
        )
        result = self._apply(result, match)
        if not isinstance(result, UtteranceFrame):
            # Триггер сработал, но уверенности не хватило: уточнение
            # должно дойти до движка диалога, а не раствориться в кадре.
            self.last_sem = None
            self.last_reason = str(getattr(result, "reason", "") or "")
        return result

    def _fallback(self, raw: str, topic: str):
        base = self.legacy.understand(raw, topic=topic)
        self._adopt(base)
        self.counts["fallback"] += 1
        return base

    # --- семантика из манифеста и захватов -------------------------

    def _lexicon_index(self) -> Dict[Tuple[str, Tuple[str, ...]], Any]:
        if self._index is not None:
            return self._index
        substitutions = self.manifest.substitutions
        index: Dict[Tuple[str, Tuple[str, ...]], Any] = {}
        for entry in getattr(self.session.catalog, "lexicon", ()) or ():
            category = str(getattr(entry, "cat", "") or "")
            semantic = getattr(entry, "semantic", None)
            if not category or not isinstance(semantic, Mapping):
                continue
            for form in entry.all_forms():
                tokens = tuple(tokenize(form.text))
                if not tokens:
                    continue
                key = (
                    category,
                    tuple(
                        substitutions.get(token, token) for token in tokens
                    ),
                )
                index.setdefault(key, dict(semantic))
        self._index = index
        return index

    def _lookup(self, category: str, tokens: Tuple[str, ...]) -> Any:
        return self._lexicon_index().get((category, tokens))

    def _resolve_np(
        self, tokens: Tuple[str, ...]
    ) -> Optional[Mapping[str, Any]]:
        for category in ("N", "PRON"):
            found = self._lookup(category, tokens)
            if found is not None:
                return {"kind": "np", "head": found}
        if len(tokens) == 2:
            modifier = self._lookup("ADJ", tokens[:1])
            head = self._lookup("N", tokens[1:])
            if modifier is not None and head is not None:
                return {
                    "kind": "np",
                    "head": head,
                    "modifiers": [modifier],
                }
        return None

    def _resolve_pp(
        self, tokens: Tuple[str, ...]
    ) -> Optional[Mapping[str, Any]]:
        for split in range(1, len(tokens)):
            prep = self._lookup("P", tokens[:split])
            if prep is None:
                continue
            obj = self._resolve_np(tokens[split:])
            if obj is not None:
                return {"kind": "pp", "prep": prep, "object": obj}
        return None

    def _resolve_s(self, raw_tokens: Tuple[str, ...]) -> Any:
        if not raw_tokens:
            return None
        try:
            parse = self.session.parser.parse_best(" ".join(raw_tokens))
        except Exception:  # noqa: BLE001 — слот уходит в откат
            return None
        sem = parse.sem if parse is not None else None
        return sem if isinstance(sem, Mapping) else None

    def _resolve_category(
        self,
        category: str,
        tokens: Tuple[str, ...],
        raw_tokens: Tuple[str, ...],
    ) -> Any:
        if category == "NP":
            return self._resolve_np(tokens)
        if category == "PP":
            return self._resolve_pp(tokens)
        if category == "S":
            return self._resolve_s(raw_tokens)
        return self._lookup(category, tokens)

    def _build_sem(
        self,
        match: Any,
        stars: Tuple[str, ...],
        raw: str,
    ) -> Optional[Mapping[str, Any]]:
        if match.source != "grammar":
            frame = match.frame
            return dict(frame) if isinstance(frame, Mapping) else None
        rhs = match.rhs
        if not rhs:
            from campaign.dialogue.semantics import flatten

            return flatten(dict(match.frame))
        if len(stars) != len(rhs):
            return None
        raw_tokens = tuple(tokenize(raw))
        substitutions = self.manifest.substitutions
        normalized = tuple(
            substitutions.get(token, token) for token in raw_tokens
        )
        position = 0
        roles: Dict[str, Any] = {}
        for (category, role), star in zip(rhs, stars):
            # RiveScript нормализует звёзды по своим правилам, но не
            # обязан знать лексиконные замены (например, «ждёт» →
            # «ждать»). Приводим захват к тому же виду, что и сырой ввод.
            star_tokens = tuple(
                substitutions.get(token, token)
                for token in tokenize(star)
            )
            if not star_tokens:
                return None
            found = None
            limit = len(normalized) - len(star_tokens) + 1
            for start in range(position, limit):
                if normalized[start:start + len(star_tokens)] == star_tokens:
                    found = start
                    break
            if found is None:
                return None
            raw_span = raw_tokens[found:found + len(star_tokens)]
            try:
                value = self._resolve_category(
                    category, star_tokens, raw_span
                )
            except Exception:  # noqa: BLE001 — слот уходит в откат
                return None
            if value is None:
                return None
            if role:
                roles[role] = value
            position = found + len(star_tokens)
        from campaign.dialogue.semantics import flatten, substitute

        try:
            sem = flatten(substitute(match.frame, roles))
        except Exception:  # noqa: BLE001 — неполный шаблон уходит в откат
            return None
        return sem if isinstance(sem, Mapping) else None

    def _apply(self, base: Any, match: Any) -> Any:
        if not isinstance(base, UtteranceFrame):
            return base
        evidence = base.evidence + (
            "rive:%s:%s" % (match.source, match.id),
        )
        if match.source in ("action", "marker"):
            floor = 0.9
        elif match.source == "grammar":
            floor = 0.8
        else:
            floor = 0.85
        confidence = min(1.0, max(float(base.confidence), floor))
        return replace(
            base,
            confidence=confidence,
            evidence=evidence,
        )


__all__ = [
    "FALLBACK_ID",
    "RUNTIME_VERSION",
    "RiveNlu",
    "default_manifest_path",
    "default_rive_path",
]
