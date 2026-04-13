#!/usr/bin/env python3
"""Convert a parsed Mahjong Soul record to MJAI events."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from majsoul_auto_rating import convert_parsed_record_to_mjai_events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert a parsed Mahjong Soul record to MJAI")
    parser.add_argument("record_json", help="Path to parsed record JSON with {head, data}")
    parser.add_argument("--dump-output", help="Optional path to save MJAI events as JSON lines")
    parser.add_argument("--show-first", type=int, default=12, help="Print the first N MJAI events")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    record_path = Path(args.record_json)
    with record_path.open("r", encoding="utf-8") as handle:
        record = json.load(handle)

    events = convert_parsed_record_to_mjai_events(record)
    counts = Counter(event["type"] for event in events)
    summary = {
        "input": str(record_path),
        "event_count": len(events),
        "event_types": dict(counts),
        "start_game": events[0],
        "last_event": events[-1],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\nFirst events:")
    for event in events[: max(0, args.show_first)]:
        print(json.dumps(event, ensure_ascii=False))

    if args.dump_output:
        output_path = Path(args.dump_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False))
                handle.write("\n")
        print(f"\nSaved MJAI log to: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
