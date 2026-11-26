"""Сборка и проверка золотого корпуса диалога.

Корпус фиксирует ``(seed, snapshot, input) → кадр`` для текущего
legacy-разбора. Это база parity-тестов: изменение кадра видно в diff,
а не тонет в случайных прогонах.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

from .corpus import CorpusEntry, GoldenCorpus
from .errors import CorpusError
from .nlu import LegacyNlu
from .nlu_lint import collect_phrases
from .parity import result_core

DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "cognition"
    / "golden_corpus.json"
)
DEFAULT_SEED = 13
DEFAULT_SNAPSHOT = {"source": "dialogue", "faction": "red"}
VARIANT_LIMIT = 20


def dialogue_variants(
    phrases: Iterable[Tuple[str, str]],
) -> Tuple[Tuple[str, str], ...]:
    """Фразы диалога плюс устойчивые варианты регистра и пунктуации."""

    base = [(str(identifier), str(text)) for identifier, text in phrases]
    variants: List[Tuple[str, str]] = list(base)
    for identifier, text in base[:VARIANT_LIMIT]:
        variants.append((identifier + ":upper", text.upper()))
        variants.append(
            (identifier + ":bang", text.rstrip(".!?") + "!")
        )
        variants.append((identifier + ":space", "  " + text + "  "))
    return tuple(variants)


def build_corpus(
    session: Any,
    phrases: Iterable[Tuple[str, str]],
    *,
    seed: int = DEFAULT_SEED,
    snapshot: Optional[dict] = None,
) -> GoldenCorpus:
    """Записать текущий legacy-разбор в корпус."""

    engine = LegacyNlu(session)
    corpus = GoldenCorpus()
    for index, (identifier, text) in enumerate(phrases):
        result = engine.understand(text)
        corpus.add(
            CorpusEntry(
                id="%03d:%s" % (index, identifier),
                seed=seed,
                snapshot=dict(snapshot or DEFAULT_SNAPSHOT),
                input=text,
                topic="default",
                category=identifier,
                expected=result.to_dict(),
            )
        )
    return corpus


def check_corpus(
    session: Any,
    corpus: GoldenCorpus,
    phrases: Iterable[Tuple[str, str]],
) -> None:
    """Проверить, что корпус совпадает с текущими фразами и разбором."""

    items = list(phrases)
    entries = corpus.sorted_entries()
    if len(entries) != len(items):
        raise CorpusError(
            "корпус устарел: %d записей против %d фраз"
            % (len(entries), len(items))
        )
    engine = LegacyNlu(session)
    for entry, (identifier, text) in zip(entries, items):
        if entry.input != text:
            raise CorpusError(
                "корпус устарел: %s содержит %r вместо %r"
                % (entry.id, entry.input, text)
            )
        result = engine.understand(text)
        if entry.expected != result.to_dict():
            raise CorpusError(
                "кадр %s изменился; перегенерируйте корпус" % entry.id
            )


def build_default_session(
    seed: int = DEFAULT_SEED,
    pragmatics: Any = None,
    inference: Any = None,
) -> Any:
    """Собрать сессию на игровых конфигах для CLI."""

    from campaign.automata import AutomataCampaign
    from campaign.dialogue import (
        DialogueSession,
        build_knowledge,
        load_dialogue,
        load_inference,
    )
    from campaign.preset import CampaignPresetGenerator
    from campaign.roles import RoleCatalog

    root = Path(__file__).resolve().parents[2]
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(root / "configs" / "roles"),
        template_path=root / "configs" / "campaigns" / "empire_campaign.json",
    )
    campaign = AutomataCampaign(generator.generate(seed=seed), seed=seed)
    catalog = load_dialogue(root / "configs" / "dialogue")
    knowledge = build_knowledge(catalog, campaign, "red")
    if inference is None:
        inference = load_inference(catalog, knowledge)
    return DialogueSession(
        catalog,
        knowledge,
        style_id="neutral",
        style_hints=False,
        pragmatics=pragmatics,
        inference=inference,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Золотой корпус диалога",
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--corpus", default=str(DEFAULT_CORPUS_PATH)
    )
    args = parser.parse_args(argv)
    if not args.write and not args.check:
        args.check = True
    try:
        session = build_default_session(args.seed)
        phrases = dialogue_variants(collect_phrases())
        if args.write:
            corpus = build_corpus(session, phrases, seed=args.seed)
            corpus.save(Path(args.corpus))
            print(
                "корпус обновлён: %d записей, digest %s"
                % (len(corpus), corpus.digest()[:12])
            )
        else:
            corpus = GoldenCorpus.load(Path(args.corpus))
            check_corpus(session, corpus, phrases)
            print(
                "корпус в порядке: %d записей, digest %s"
                % (len(corpus), corpus.digest()[:12])
            )
    except (CorpusError, OSError) as exc:
        print("ошибка: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_CORPUS_PATH",
    "DEFAULT_SEED",
    "DEFAULT_SNAPSHOT",
    "build_corpus",
    "build_default_session",
    "check_corpus",
    "dialogue_variants",
    "main",
]
