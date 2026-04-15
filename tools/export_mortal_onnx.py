#!/usr/bin/env python3
"""Export embedded Mortal model to a single ONNX file."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import onnx
import torch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export embedded Mortal model to ONNX")
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

    class MortalOnnxWrapper(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            with torch.device("meta"):
                self.brain = Brain(version=version, num_blocks=num_blocks, conv_channels=conv_channels).eval()
                self.dqn = DQN(version=version).eval()
            self.brain.load_state_dict(state["mortal"], assign=True)
            self.dqn.load_state_dict(state["current_dqn"], assign=True)

        def forward(self, obs, mask):
            return self.dqn(self.brain(obs), mask)

    model = MortalOnnxWrapper().eval()

    channels, width = obs_shape(version)
    sample_obs = torch.randn(1, channels, width, dtype=torch.float32)
    sample_mask = torch.ones(1, ACTION_SPACE, dtype=torch.bool)

    model_path = args.output_dir / "mortal.onnx"

    torch.onnx.export(
        model,
        (sample_obs, sample_mask),
        model_path,
        input_names=["obs", "mask"],
        output_names=["q_values"],
        dynamic_axes={
            "obs": {0: "batch"},
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
    onnx_model = onnx.load(model_path, load_external_data=True)
    metadata = {
        "version": str(version),
        "num_blocks": str(num_blocks),
        "conv_channels": str(conv_channels),
        "model_tag": str(model_tag),
    }
    for key, value in metadata.items():
        prop = onnx_model.metadata_props.add()
        prop.key = key
        prop.value = value
    onnx.save(onnx_model, model_path, save_as_external_data=False)
    external_data_path = model_path.with_name(f"{model_path.name}.data")
    if external_data_path.exists():
        external_data_path.unlink()

    print(f"exported {model_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
