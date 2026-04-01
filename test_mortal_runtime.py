#!/usr/bin/env python3
"""Smoke test for the in-process Mortal runtime wrapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mortal_runtime import (
    DEFAULT_GRP_MODEL,
    DEFAULT_MORTAL_MODEL,
    DEFAULT_MORTAL_REPO,
    load_mortal_runtime,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke test the in-process Mortal runtime")
    parser.add_argument(
        "--parsed-record",
        help="Parsed Mahjong Soul record JSON with {head, data}",
    )
    parser.add_argument(
        "--mjai-log",
        help="MJAI JSONL file",
    )
    parser.add_argument("--player-id", type=int, default=0, help="Target player id")
    parser.add_argument("--device", default="cpu", help="Torch device")
    parser.add_argument("--show-events", type=int, default=5, help="Show first N reactions")
    parser.add_argument("--show-phi", action="store_true", help="Print phi matrix summary")
    parser.add_argument("--mortal-repo", default=str(DEFAULT_MORTAL_REPO), help="Path to Mortal repo")
    parser.add_argument("--model", default=str(DEFAULT_MORTAL_MODEL), help="Path to Mortal model state")
    parser.add_argument("--grp-model", default=str(DEFAULT_GRP_MODEL), help="Path to GRP model state")
    parser.add_argument(
        "--include-none",
        action="store_true",
        help="Include non-reactable events as synthetic none reactions",
    )
    return parser


def load_events(args: argparse.Namespace) -> list[dict]:
    if bool(args.parsed_record) == bool(args.mjai_log):
        raise SystemExit("exactly one of --parsed-record or --mjai-log is required")

    if args.parsed_record:
        from majsoul_to_mjai import convert_parsed_record_to_mjai_events

        with Path(args.parsed_record).open("r", encoding="utf-8") as handle:
            record = json.load(handle)
        return convert_parsed_record_to_mjai_events(record)

    events: list[dict] = []
    with Path(args.mjai_log).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def main() -> int:
    args = build_parser().parse_args()
    events = load_events(args)

    runtime = load_mortal_runtime(
        mortal_repo=args.mortal_repo,
        model_state_path=args.model,
        grp_state_path=args.grp_model,
        device=args.device,
        enable_quick_eval=False,
        load_grp=args.show_phi,
    )
    summary = runtime.analyze_log(
        events,
        player_id=args.player_id,
        include_none=args.include_none,
        include_phi_matrix=args.show_phi,
    )

    output = {
        "model_tag": summary.model_tag,
        "event_count": len(events),
        "reaction_count": summary.reaction_count,
        "player_id": args.player_id,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    print("\nFirst reactions:")
    for item in summary.reactions[: max(0, args.show_events)]:
        payload = {
            "event_index": item.event_index,
            "input_type": item.input_event["type"],
            "reaction": item.reaction,
        }
        print(json.dumps(payload, ensure_ascii=False))

    if summary.phi_matrix is not None:
        print("\nPhi matrix summary:")
        print(json.dumps({
            "kyoku_count": len(summary.phi_matrix),
            "first_kyoku": summary.phi_matrix[0] if summary.phi_matrix else None,
        }, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
