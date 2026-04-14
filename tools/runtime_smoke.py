#!/usr/bin/env python3
"""Smoke test the in-process Mortal runtime wrapper."""

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
)

from tools._io import load_events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke test the in-process Mortal runtime")
    parser.add_argument("--parsed-record", help="Parsed Mahjong Soul record JSON with {head, data}")
    parser.add_argument("--mjai-log", help="MJAI JSONL file")
    parser.add_argument("--player-id", type=int, default=0, help="Target player id")
    parser.add_argument("--device", default="cpu", help="Torch device")
    parser.add_argument("--backend", choices=["torch", "onnxruntime"], default="torch", help="Inference backend")
    parser.add_argument("--show-events", type=int, default=5, help="Show first N reactions")
    parser.add_argument("--mortal-vendor-dir", default=str(DEFAULT_MORTAL_VENDOR_DIR), help="Path to vendored Mortal runtime assets")
    parser.add_argument("--model", default=str(DEFAULT_MORTAL_MODEL), help="Path to Mortal model state")
    parser.add_argument("--brain-onnx", default=str(DEFAULT_BRAIN_ONNX), help="Path to Brain ONNX model")
    parser.add_argument("--dqn-onnx", default=str(DEFAULT_DQN_ONNX), help="Path to DQN ONNX model")
    parser.add_argument("--boltzmann-epsilon", type=float, default=DEFAULT_BOLTZMANN_EPSILON, help="Exploration epsilon")
    parser.add_argument("--boltzmann-temp", type=float, default=DEFAULT_BOLTZMANN_TEMP, help="Boltzmann sampling temperature")
    parser.add_argument("--top-p", type=float, default=DEFAULT_TOP_P, help="Nucleus sampling cutoff")
    parser.add_argument("--include-none", action="store_true", help="Include non-reactable events as synthetic none reactions")
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
    summary = runtime.analyze_log(
        events,
        player_id=args.player_id,
        include_none=args.include_none,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
