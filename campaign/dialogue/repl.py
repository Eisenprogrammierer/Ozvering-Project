"""CLI диалога: python -m campaign.dialogue.repl --side red --ask "..."."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from campaign.automata import AutomataCampaign
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

from .engine import DialogueSession
from .knowledge import build_knowledge
from .loader import load_dialogue

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATES = {
    "red": "empire_campaign",
    "blue": "republic_campaign",
    "green": "cult_campaign",
    "amber": "corporation_campaign",
}


def build_session(
    side: str = "red",
    template: str = "",
    seed: int = 13,
    character: str = "",
    allow_actions: bool = False,
) -> DialogueSession:
    template_id = template or DEFAULT_TEMPLATES.get(side, "empire_campaign")
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / (
            "%s.json" % template_id
        ),
    )
    preset = generator.generate(seed=seed)
    campaign = AutomataCampaign(preset, seed=seed)
    catalog = load_dialogue()
    knowledge = build_knowledge(
        catalog, campaign, side, character or None
    )
    return DialogueSession(
        catalog,
        knowledge,
        allow_actions=allow_actions,
        campaign=campaign,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Диалог с агентом кампании (read-only)."
    )
    parser.add_argument("--side", default="red",
                        choices=sorted(DEFAULT_TEMPLATES))
    parser.add_argument("--template", default="")
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--character", default="")
    parser.add_argument("--ask", default="", help="один вопрос и выход")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    session = build_session(
        args.side, args.template, args.seed, args.character
    )
    if args.ask:
        return _ask(session, args.ask, args.debug, args.json)

    print(
        "Диалог со стороной %s. Пустая строка — выход."
        % args.side
    )
    while True:
        try:
            text = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text.strip():
            return 0
        _ask(session, text, args.debug, args.json)
    return 0


def _ask(
    session: DialogueSession, text: str, debug: bool = False,
    as_json: bool = False,
) -> int:
    turn = session.respond(text)
    answer = turn.answer
    ok = turn.sem is not None
    if as_json:
        payload = {
            "input": text,
            "kind": answer.kind,
            "text": answer.text,
            "plan": answer.plan_id,
            "source": turn.source,
            "proof": list(answer.proof[0].lines()) if answer.proof else [],
            "sem": turn.sem,
        }
        print(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        )
        return 0 if ok else 2
    print(answer.text)
    if debug:
        print("[источник] %s" % turn.source)
        if turn.sem is None:
            print("[форма не восстановлена]")
        else:
            print("[план] %s" % answer.plan_id)
            print(
                "[форма] "
                + json.dumps(turn.sem, ensure_ascii=False, sort_keys=True)
            )
            if answer.proof:
                for line in answer.proof[0].lines():
                    print("[вывод] " + line)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
