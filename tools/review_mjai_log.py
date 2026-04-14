#!/usr/bin/env python3
"""Run lightweight in-process Mortal review over a MJAI log."""

from __future__ import annotations

import argparse
import json

from majsoul_auto_rating import (
    DEFAULT_BOLTZMANN_EPSILON,
    DEFAULT_BOLTZMANN_TEMP,
    DEFAULT_BRAIN_ONNX,
    DEFAULT_DQN_ONNX,
    DEFAULT_MORTAL_MODEL,
    DEFAULT_MORTAL_VENDOR_DIR,
    DEFAULT_TOP_P,
    load_mortal_runtime,
    review_mjai_events,
)

from tools._io import load_events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review a MJAI log with embedded Mortal")
    parser.add_argument("--parsed-record", help="Parsed Mahjong Soul record JSON with {head, data}")
    parser.add_argument("--mjai-log", help="MJAI JSONL file")
    parser.add_argument("--player-id", type=int, required=True, help="Target player id")
    parser.add_argument("--device", default="cpu", help="Torch device")
    parser.add_argument("--backend", choices=["torch", "onnxruntime"], default="torch", help="Inference backend")
    parser.add_argument("--show-entries", type=int, default=5, help="Print first N review entries")
    parser.add_argument("--mortal-vendor-dir", default=str(DEFAULT_MORTAL_VENDOR_DIR))
    parser.add_argument("--model", default=str(DEFAULT_MORTAL_MODEL))
    parser.add_argument("--brain-onnx", default=str(DEFAULT_BRAIN_ONNX))
    parser.add_argument("--dqn-onnx", default=str(DEFAULT_DQN_ONNX))
    parser.add_argument("--boltzmann-epsilon", type=float, default=DEFAULT_BOLTZMANN_EPSILON)
    parser.add_argument("--boltzmann-temp", type=float, default=DEFAULT_BOLTZMANN_TEMP)
    parser.add_argument("--top-p", type=float, default=DEFAULT_TOP_P)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    events = load_events(parsed_record=args.parsed_record, mjai_log=args.mjai_log)
    runtime = load_mortal_runtime(
        backend=args.backend,
        mortal_vendor_dir=args.mortal_vendor_dir,
        model_state_path=args.model,
        brain_onnx_path=args.brain_onnx,
        dqn_onnx_path=args.dqn_onnx,
        device=args.device,
        enable_quick_eval=False,
        boltzmann_epsilon=args.boltzmann_epsilon,
        boltzmann_temp=args.boltzmann_temp,
        top_p=args.top_p,
    )
    result = review_mjai_events(
        events,
        player_id=args.player_id,
        runtime=runtime,
    )

    summary = {
        "model_tag": result.model_tag,
        "rating": result.rating,
        "boltzmann_epsilon": result.boltzmann_epsilon,
        "boltzmann_temp": result.boltzmann_temp,
        "top_p": result.top_p,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
