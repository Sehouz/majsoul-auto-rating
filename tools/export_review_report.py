#!/usr/bin/env python3
"""Export a reviewer-like Mortal JSON report without phi matrix."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from majsoul_auto_rating import (
    DEFAULT_MORTAL_MODEL,
    DEFAULT_MORTAL_ONNX,
    DEFAULT_MORTAL_VENDOR_DIR,
    build_reviewer_report,
    load_mortal_runtime,
)

from tools._io import load_events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a reviewer-like Mortal JSON report")
    parser.add_argument("--parsed-record", help="Parsed Mahjong Soul record JSON with {head, data}")
    parser.add_argument("--mjai-log", help="MJAI JSONL file")
    parser.add_argument("--player-id", type=int, required=True, help="Target player id")
    parser.add_argument("--device", default="cpu", help="Torch device")
    parser.add_argument("--backend", choices=["torch", "onnxruntime"], default="torch", help="Inference backend")
    parser.add_argument("--mortal-vendor-dir", default=str(DEFAULT_MORTAL_VENDOR_DIR))
    parser.add_argument("--model", default=str(DEFAULT_MORTAL_MODEL))
    parser.add_argument("--onnx-model", default=str(DEFAULT_MORTAL_ONNX))
    parser.add_argument("--temperature", type=float, default=0.1, help="Display softmax temperature for details.prob")
    parser.add_argument("--show-rating", action="store_true", help="Mirror mjai-reviewer JSON show_rating flag")
    parser.add_argument("--game-length", default="Hanchan", help="Top-level game_length field")
    parser.add_argument("--version", default=None, help="Override top-level report version")
    parser.add_argument("--lang", default="en", help="Top-level report lang field")
    parser.add_argument("--out", default="-", help="Output file path, or '-' for stdout")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    begin_loading = time.perf_counter()
    events = load_events(parsed_record=args.parsed_record, mjai_log=args.mjai_log)
    parsed_record = None
    if args.parsed_record:
        with open(args.parsed_record, "r", encoding="utf-8") as handle:
            parsed_record = json.load(handle)
    runtime = load_mortal_runtime(
        backend=args.backend,
        mortal_vendor_dir=args.mortal_vendor_dir,
        model_state_path=args.model,
        model_onnx_path=args.onnx_model,
        device=args.device,
        enable_quick_eval=False,
    )
    loading_time_seconds = time.perf_counter() - begin_loading

    report = build_reviewer_report(
        events,
        player_id=args.player_id,
        runtime=runtime,
        parsed_record=parsed_record,
        temperature=args.temperature,
        loading_time_seconds=loading_time_seconds,
        show_rating=args.show_rating,
        version=args.version,
        game_length=args.game_length,
        lang=args.lang,
    )
    payload = json.dumps(asdict(report), ensure_ascii=False)
    if args.out == "-":
        print(payload)
        return 0
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
