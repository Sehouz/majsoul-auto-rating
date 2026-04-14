#!/usr/bin/env python3
"""Export embedded Mortal Brain and DQN models to ONNX."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import torch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export embedded Mortal models to ONNX")
    parser.add_argument("--vendor-dir", type=Path, default=Path("vendor"), help="Vendored Mortal asset directory")
    parser.add_argument("--model", type=Path, default=Path("vendor/models/mortal.pth"), help="Mortal checkpoint path")
    parser.add_argument("--output-dir", type=Path, default=Path("vendor/models"), help="Directory for ONNX outputs")
    parser.add_argument("--opset", type=int, default=18, help="ONNX opset version")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    runtime_dir = (args.vendor_dir / "mortal_runtime").resolve()
    sys.path.insert(0, str(runtime_dir))

    from libriichi.consts import ACTION_SPACE, obs_shape  # type: ignore
    from model import Brain, DQN  # type: ignore

    args.output_dir.mkdir(parents=True, exist_ok=True)

    state = torch.load(args.model, map_location="cpu", weights_only=False, mmap=True)
    config = state["config"]
    version = int(config["control"].get("version", 1))
    num_blocks = int(config["resnet"]["num_blocks"])
    conv_channels = int(config["resnet"]["conv_channels"])

    with torch.device("meta"):
        brain = Brain(version=version, num_blocks=num_blocks, conv_channels=conv_channels).eval()
        dqn = DQN(version=version).eval()
    brain.load_state_dict(state["mortal"], assign=True)
    dqn.load_state_dict(state["current_dqn"], assign=True)

    channels, width = obs_shape(version)
    sample_obs = torch.randn(1, channels, width, dtype=torch.float32)
    sample_phi = brain(sample_obs)
    sample_mask = torch.ones(1, ACTION_SPACE, dtype=torch.bool)

    brain_path = args.output_dir / "brain.onnx"
    dqn_path = args.output_dir / "dqn.onnx"
    metadata_path = args.output_dir / "onnx_metadata.json"

    torch.onnx.export(
        brain,
        (sample_obs,),
        brain_path,
        input_names=["obs"],
        output_names=["phi"],
        dynamic_axes={"obs": {0: "batch"}, "phi": {0: "batch"}},
        opset_version=args.opset,
    )
    torch.onnx.export(
        dqn,
        (sample_phi, sample_mask),
        dqn_path,
        input_names=["phi", "mask"],
        output_names=["q_values"],
        dynamic_axes={
            "phi": {0: "batch"},
            "mask": {0: "batch"},
            "q_values": {0: "batch"},
        },
        opset_version=args.opset,
    )

    model_tag = state.get("tag")
    if model_tag is None:
        timestamp = state.get("timestamp")
        if timestamp is None:
            model_tag = f"mortal{version}-b{num_blocks}c{conv_channels}"
        else:
            from datetime import datetime, timezone

            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%y%m%d%H")
            model_tag = f"mortal{version}-b{num_blocks}c{conv_channels}-t{dt}"
    metadata = {
        "version": version,
        "num_blocks": num_blocks,
        "conv_channels": conv_channels,
        "model_tag": str(model_tag),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"exported {brain_path}")
    print(f"exported {dqn_path}")
    print(f"exported {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
