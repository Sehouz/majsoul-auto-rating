#!/usr/bin/env python3
"""Smoke test for the lightweight in-process Mortal review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mortal_review import review_mjai_events
from mortal_runtime import (
    DEFAULT_GRP_MODEL,
    DEFAULT_MORTAL_MODEL,
    DEFAULT_MORTAL_REPO,
    load_mortal_runtime,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review a MJAI log with embedded Mortal")
    parser.add_argument("--parsed-record", help="Parsed Mahjong Soul record JSON with {head, data}")
    parser.add_argument("--mjai-log", help="MJAI JSONL file")
    parser.add_argument("--player-id", type=int, required=True, help="Target player id")
    parser.add_argument("--device", default="cpu", help="Torch device")
    parser.add_argument("--show-entries", type=int, default=5, help="Print first N review entries")
    parser.add_argument("--with-phi", action="store_true", help="Compute phi matrix")
    parser.add_argument("--mortal-repo", default=str(DEFAULT_MORTAL_REPO))
    parser.add_argument("--model", default=str(DEFAULT_MORTAL_MODEL))
    parser.add_argument("--grp-model", default=str(DEFAULT_GRP_MODEL))
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
        load_grp=args.with_phi,
    )
    result = review_mjai_events(
        events,
        player_id=args.player_id,
        runtime=runtime,
        include_phi_matrix=args.with_phi,
    )

    summary = {
        "model_tag": result.model_tag,
        "rating": result.rating,
        "total_reviewed": result.total_reviewed,
        "total_matches": result.total_matches,
        "entry_count": len(result.entries),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\nFirst review entries:")
    for entry in result.entries[: max(0, args.show_entries)]:
        payload = {
            "event_index": entry.event_index,
            "trigger_type": entry.trigger_event["type"],
            "expected": entry.expected,
            "actual": entry.actual,
            "is_equal": entry.is_equal,
            "shanten": entry.shanten,
            "at_furiten": entry.at_furiten,
            "actual_q_value": entry.actual_q_value,
        }
        print(json.dumps(payload, ensure_ascii=False))

    if result.phi_matrix is not None:
        print("\nPhi matrix summary:")
        print(json.dumps({
            "kyoku_count": len(result.phi_matrix),
            "first_kyoku": result.phi_matrix[0] if result.phi_matrix else None,
        }, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
