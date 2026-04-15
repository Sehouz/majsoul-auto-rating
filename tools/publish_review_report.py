#!/usr/bin/env python3
"""Export a reviewer report and publish it to Aliyun OSS."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from majsoul_auto_rating import (
    AliyunOssConfig,
    AliyunOssPublisher,
    DEFAULT_MORTAL_MODEL,
    DEFAULT_MORTAL_ONNX,
    DEFAULT_MORTAL_VENDOR_DIR,
    build_reviewer_report,
    load_mortal_runtime,
    publish_report_json,
)
from tools._io import load_events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a reviewer report and publish it to Aliyun OSS")
    parser.add_argument("--parsed-record", help="Parsed Mahjong Soul record JSON with {head, data}")
    parser.add_argument("--mjai-log", help="MJAI JSONL file")
    parser.add_argument("--player-id", type=int, required=True, help="Target player id")
    parser.add_argument("--uuid", required=True, help="Majsoul game UUID used for object key hashing")
    parser.add_argument("--device", default="cpu", help="Torch device")
    parser.add_argument("--backend", choices=["torch", "onnxruntime"], default="torch", help="Inference backend")
    parser.add_argument("--mortal-vendor-dir", default=str(DEFAULT_MORTAL_VENDOR_DIR))
    parser.add_argument("--model", default=str(DEFAULT_MORTAL_MODEL))
    parser.add_argument("--onnx-model", default=str(DEFAULT_MORTAL_ONNX))
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--show-rating", action="store_true")
    parser.add_argument("--game-length", default="Hanchan")
    parser.add_argument("--version", default=None)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--oss-endpoint", required=True)
    parser.add_argument("--oss-bucket", required=True)
    parser.add_argument("--oss-access-key-id", required=True)
    parser.add_argument("--oss-access-key-secret", required=True)
    parser.add_argument("--oss-public-base-url", required=True)
    parser.add_argument("--oss-prefix", default="report/majsoul")
    parser.add_argument("--viewer-base-url", default=None)
    parser.add_argument("--public-path-prefix", default="/")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    begin_loading = time.perf_counter()
    events = load_events(parsed_record=args.parsed_record, mjai_log=args.mjai_log)
    parsed_record = _load_parsed_record(args.parsed_record)
    runtime = _load_runtime(args)
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

    publisher = AliyunOssPublisher(
        AliyunOssConfig(
            endpoint=args.oss_endpoint,
            bucket_name=args.oss_bucket,
            access_key_id=args.oss_access_key_id,
            access_key_secret=args.oss_access_key_secret,
            public_base_url=args.oss_public_base_url,
        )
    )
    published = publish_report_json(
        report,
        uuid=args.uuid,
        player_id=args.player_id,
        model_key_suffix=report.review.model_tag,
        publisher=publisher,
        prefix=args.oss_prefix,
        viewer_base_url=args.viewer_base_url,
        public_path_prefix=args.public_path_prefix,
    )
    print(json.dumps(asdict(published), ensure_ascii=False, indent=2))
    return 0


def _load_parsed_record(parsed_record_path: str | None) -> dict | None:
    if not parsed_record_path:
        return None
    with open(parsed_record_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_runtime(args: argparse.Namespace):
    return load_mortal_runtime(
        backend=args.backend,
        mortal_vendor_dir=args.mortal_vendor_dir,
        model_state_path=args.model,
        model_onnx_path=args.onnx_model,
        device=args.device,
        enable_quick_eval=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
