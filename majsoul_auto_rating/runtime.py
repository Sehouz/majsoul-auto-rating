"""
In-process Mortal runtime wrapper for majsoul-auto-rating.

This module provides a structured API over Mortal's Python runtime instead of
spawning its CLI process. It intentionally keeps the surface small:

- load Mortal model state
- create `libriichi.mjai.Bot` sessions
- feed MJAI events and receive structured reactions with metadata
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib
from importlib.resources import files
import json
from pathlib import Path
import pickle
import platform
import sys
import sysconfig
from typing import Any, Literal

from .onnx_engine import OrtEnginePaths, OrtMortalEngine


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_MORTAL_VENDOR_DIR = Path(str(files("majsoul_auto_rating").joinpath("vendor")))
DEFAULT_MORTAL_RUNTIME_DIR = DEFAULT_MORTAL_VENDOR_DIR / "mortal_runtime"
DEFAULT_LIBRIICHI_SOURCE_DIR = DEFAULT_MORTAL_VENDOR_DIR / "libriichi-src"
DEFAULT_MORTAL_MODEL = DEFAULT_MORTAL_VENDOR_DIR / "models" / "mortal.pth"
DEFAULT_BRAIN_ONNX = DEFAULT_MORTAL_VENDOR_DIR / "models" / "brain.onnx"
DEFAULT_DQN_ONNX = DEFAULT_MORTAL_VENDOR_DIR / "models" / "dqn.onnx"
DEFAULT_ONNX_METADATA = DEFAULT_MORTAL_VENDOR_DIR / "models" / "onnx_metadata.json"
DEFAULT_BOLTZMANN_EPSILON = 0.005
DEFAULT_BOLTZMANN_TEMP = 0.05
DEFAULT_TOP_P = 1.0
RuntimeBackend = Literal["torch", "onnxruntime"]


class MortalRuntimeError(RuntimeError):
    """Raised when the embedded Mortal runtime cannot be initialized or used."""


def _ensure_sys_path(path: Path) -> None:
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _import_or_raise(name: str, help_text: str) -> Any:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        raise MortalRuntimeError(help_text) from exc


def _load_checkpoint(torch_module: Any, path: Path) -> dict[str, Any]:
    try:
        return torch_module.load(str(path), weights_only=True, map_location="cpu", mmap=True)
    except pickle.UnpicklingError as exc:
        if "Weights only load failed" not in str(exc):
            raise
        # The bundled Mortal checkpoints are trusted local assets. PyTorch 2.6+
        # defaults to weights_only=True, but these older checkpoints include
        # numpy scalar metadata that still requires the legacy code path.
        return torch_module.load(str(path), weights_only=False, map_location="cpu", mmap=True)


def _init_module_on_meta(torch_module: Any, factory: Any, /, *args: Any, **kwargs: Any) -> Any:
    with torch_module.device("meta"):
        return factory(*args, **kwargs)


def _libriichi_extension_candidates(runtime_dir: Path) -> list[Path]:
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    names: list[str] = []
    if suffix:
        names.append(f"libriichi{suffix}")
    names.append("libriichi.so")
    if platform.system() == "Darwin":
        names.append("libriichi.dylib")
    return [runtime_dir / name for name in dict.fromkeys(names)]


@dataclass(frozen=True)
class MortalPaths:
    mortal_vendor_dir: Path = DEFAULT_MORTAL_VENDOR_DIR
    mortal_runtime_dir: Path = DEFAULT_MORTAL_RUNTIME_DIR
    libriichi_source_dir: Path = DEFAULT_LIBRIICHI_SOURCE_DIR
    model_state_path: Path = DEFAULT_MORTAL_MODEL
    brain_onnx_path: Path = DEFAULT_BRAIN_ONNX
    dqn_onnx_path: Path = DEFAULT_DQN_ONNX
    onnx_metadata_path: Path = DEFAULT_ONNX_METADATA


@dataclass(frozen=True)
class MortalReaction:
    event_index: int
    input_event: dict[str, Any]
    reaction: dict[str, Any] | None


@dataclass(frozen=True)
class MortalLogSummary:
    reaction_count: int
    reactions: list[MortalReaction]
    model_tag: str


class MortalBotSession:
    """Thin wrapper around `libriichi.mjai.Bot` with dict-based I/O."""

    def __init__(self, runtime: "MortalRuntime", player_id: int) -> None:
        if player_id not in range(4):
            raise MortalRuntimeError(f"player_id must be in [0, 3], got {player_id}")
        self.runtime = runtime
        self.player_id = int(player_id)
        self._bot = runtime._bot_class(runtime.engine, self.player_id)

    def react(self, event: dict[str, Any], *, include_none: bool = False) -> dict[str, Any] | None:
        line = json.dumps(event, ensure_ascii=False)
        output = self._bot.react(line)
        if output is None:
            if include_none:
                return {"type": "none", "meta": {"mask_bits": 0}}
            return None
        return json.loads(output)

    def react_many(
        self,
        events: list[dict[str, Any]],
        *,
        include_none: bool = False,
    ) -> list[MortalReaction]:
        reactions: list[MortalReaction] = []
        for index, event in enumerate(events):
            reaction = self.react(event, include_none=include_none)
            if reaction is None and not include_none:
                continue
            reactions.append(
                MortalReaction(
                    event_index=index,
                    input_event=event,
                    reaction=reaction,
                )
            )
        return reactions


class MortalRuntime:
    """Structured in-process Mortal runtime."""

    def __init__(
        self,
        *,
        paths: MortalPaths,
        backend: RuntimeBackend = "torch",
        device: str = "cpu",
        enable_amp: bool = False,
        enable_quick_eval: bool = False,
        enable_rule_based_agari_guard: bool = True,
        boltzmann_epsilon: float = DEFAULT_BOLTZMANN_EPSILON,
        boltzmann_temp: float = DEFAULT_BOLTZMANN_TEMP,
        top_p: float = DEFAULT_TOP_P,
    ) -> None:
        self.paths = paths
        self.backend = backend
        self.device_name = device
        self.enable_amp = bool(enable_amp)
        self.enable_quick_eval = bool(enable_quick_eval)
        self.enable_rule_based_agari_guard = bool(enable_rule_based_agari_guard)
        self.boltzmann_epsilon = float(boltzmann_epsilon)
        self.boltzmann_temp = float(boltzmann_temp)
        self.top_p = float(top_p)

        if not self.paths.mortal_runtime_dir.exists():
            raise MortalRuntimeError(
                f"Vendored Mortal runtime dir does not exist: {self.paths.mortal_runtime_dir}"
            )
        libriichi_ext = next(
            (candidate for candidate in _libriichi_extension_candidates(self.paths.mortal_runtime_dir) if candidate.exists()),
            None,
        )
        if libriichi_ext is None:
            raise MortalRuntimeError(
                "Vendored libriichi extension is missing. Build it from "
                f"{self.paths.libriichi_source_dir} and copy the result into {self.paths.mortal_runtime_dir}."
            )

        _ensure_sys_path(self.paths.mortal_runtime_dir)

        libriichi_mjai = _import_or_raise(
            "libriichi.mjai",
            f"Failed to import vendored `libriichi.mjai` from {self.paths.mortal_runtime_dir}",
        )
        self._bot_class = libriichi_mjai.Bot

        if self.backend == "torch":
            self._init_torch_backend()
        elif self.backend == "onnxruntime":
            self._init_onnx_backend()
        else:
            raise MortalRuntimeError(f"unsupported backend: {self.backend!r}")

    def _init_torch_backend(self) -> None:
        if not self.paths.model_state_path.exists():
            raise MortalRuntimeError(
                f"Mortal model state does not exist: {self.paths.model_state_path}"
            )

        self._torch = _import_or_raise(
            "torch",
            "Missing Python dependency `torch`. Install the torch backend dependencies first.",
        )
        self._model_module = _import_or_raise(
            "model",
            f"Failed to import vendored Mortal runtime module `model` from {self.paths.mortal_runtime_dir}",
        )
        self._engine_module = _import_or_raise(
            "engine",
            f"Failed to import vendored Mortal runtime module `engine` from {self.paths.mortal_runtime_dir}",
        )

        state = _load_checkpoint(self._torch, self.paths.model_state_path)
        config = state["config"]
        self.version = int(config["control"].get("version", 1))
        self.num_blocks = int(config["resnet"]["num_blocks"])
        self.conv_channels = int(config["resnet"]["conv_channels"])
        self.model_tag = self._build_model_tag(state, self.version, self.num_blocks, self.conv_channels)
        self.device = self._torch.device(self.device_name)

        Brain = self._model_module.Brain
        DQN = self._model_module.DQN
        MortalEngine = self._engine_module.MortalEngine

        self.brain = _init_module_on_meta(
            self._torch,
            Brain,
            version=self.version,
            num_blocks=self.num_blocks,
            conv_channels=self.conv_channels,
        ).eval()
        self.dqn = _init_module_on_meta(self._torch, DQN, version=self.version).eval()
        self.brain.load_state_dict(state["mortal"], assign=True)
        self.dqn.load_state_dict(state["current_dqn"], assign=True)
        del state

        self.engine = MortalEngine(
            self.brain,
            self.dqn,
            version=self.version,
            is_oracle=False,
            device=self.device,
            enable_amp=self.enable_amp,
            enable_quick_eval=self.enable_quick_eval,
            enable_rule_based_agari_guard=self.enable_rule_based_agari_guard,
            name=self.model_tag,
            boltzmann_epsilon=self.boltzmann_epsilon,
            boltzmann_temp=self.boltzmann_temp,
            top_p=self.top_p,
        )

    def _init_onnx_backend(self) -> None:
        if not self.paths.brain_onnx_path.exists():
            raise MortalRuntimeError(
                f"Brain ONNX model does not exist: {self.paths.brain_onnx_path}"
            )
        if not self.paths.dqn_onnx_path.exists():
            raise MortalRuntimeError(
                f"DQN ONNX model does not exist: {self.paths.dqn_onnx_path}"
            )
        if not self.paths.onnx_metadata_path.exists():
            raise MortalRuntimeError(
                f"ONNX metadata does not exist: {self.paths.onnx_metadata_path}"
            )

        metadata = json.loads(self.paths.onnx_metadata_path.read_text(encoding="utf-8"))
        self.version = int(metadata["version"])
        self.num_blocks = int(metadata["num_blocks"])
        self.conv_channels = int(metadata["conv_channels"])
        self.model_tag = str(metadata["model_tag"])

        _import_or_raise(
            "onnxruntime",
            "Missing Python dependency `onnxruntime`. Install the onnxruntime backend dependencies first.",
        )

        self.engine = OrtMortalEngine(
            paths=OrtEnginePaths(
                brain_onnx_path=self.paths.brain_onnx_path,
                dqn_onnx_path=self.paths.dqn_onnx_path,
            ),
            is_oracle=False,
            version=self.version,
            enable_quick_eval=self.enable_quick_eval,
            enable_rule_based_agari_guard=self.enable_rule_based_agari_guard,
            name=self.model_tag,
            boltzmann_epsilon=self.boltzmann_epsilon,
            boltzmann_temp=self.boltzmann_temp,
            top_p=self.top_p,
        )

    @staticmethod
    def _build_model_tag(state: dict[str, Any], version: int, num_blocks: int, conv_channels: int) -> str:
        tag = state.get("tag")
        if tag:
            return str(tag)
        timestamp = state.get("timestamp")
        if timestamp is None:
            return f"mortal{version}-b{num_blocks}c{conv_channels}"
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%y%m%d%H")
        return f"mortal{version}-b{num_blocks}c{conv_channels}-t{dt}"

    def create_bot(self, player_id: int) -> MortalBotSession:
        return MortalBotSession(self, player_id)

    def analyze_log(
        self,
        events: list[dict[str, Any]],
        *,
        player_id: int,
        include_none: bool = False,
    ) -> MortalLogSummary:
        bot = self.create_bot(player_id)
        reactions = bot.react_many(events, include_none=include_none)
        return MortalLogSummary(
            reaction_count=len(reactions),
            reactions=reactions,
            model_tag=self.model_tag,
        )


def load_mortal_runtime(
    *,
    backend: RuntimeBackend = "torch",
    model_state_path: Path | str = DEFAULT_MORTAL_MODEL,
    brain_onnx_path: Path | str = DEFAULT_BRAIN_ONNX,
    dqn_onnx_path: Path | str = DEFAULT_DQN_ONNX,
    onnx_metadata_path: Path | str = DEFAULT_ONNX_METADATA,
    mortal_vendor_dir: Path | str = DEFAULT_MORTAL_VENDOR_DIR,
    device: str = "cpu",
    enable_amp: bool = False,
    enable_quick_eval: bool = False,
    enable_rule_based_agari_guard: bool = True,
    boltzmann_epsilon: float = DEFAULT_BOLTZMANN_EPSILON,
    boltzmann_temp: float = DEFAULT_BOLTZMANN_TEMP,
    top_p: float = DEFAULT_TOP_P,
) -> MortalRuntime:
    vendor_dir = Path(mortal_vendor_dir)
    resolved_model_state_path = Path(model_state_path)
    resolved_brain_onnx_path = Path(brain_onnx_path)
    resolved_dqn_onnx_path = Path(dqn_onnx_path)
    resolved_onnx_metadata_path = Path(onnx_metadata_path)

    if resolved_model_state_path == DEFAULT_MORTAL_MODEL:
        resolved_model_state_path = vendor_dir / "models" / "mortal.pth"
    if resolved_brain_onnx_path == DEFAULT_BRAIN_ONNX:
        resolved_brain_onnx_path = vendor_dir / "models" / "brain.onnx"
    if resolved_dqn_onnx_path == DEFAULT_DQN_ONNX:
        resolved_dqn_onnx_path = vendor_dir / "models" / "dqn.onnx"
    if resolved_onnx_metadata_path == DEFAULT_ONNX_METADATA:
        resolved_onnx_metadata_path = vendor_dir / "models" / "onnx_metadata.json"

    paths = MortalPaths(
        mortal_vendor_dir=vendor_dir,
        mortal_runtime_dir=vendor_dir / "mortal_runtime",
        libriichi_source_dir=vendor_dir / "libriichi-src",
        model_state_path=resolved_model_state_path,
        brain_onnx_path=resolved_brain_onnx_path,
        dqn_onnx_path=resolved_dqn_onnx_path,
        onnx_metadata_path=resolved_onnx_metadata_path,
    )
    return MortalRuntime(
        paths=paths,
        backend=backend,
        device=device,
        enable_amp=enable_amp,
        enable_quick_eval=enable_quick_eval,
        enable_rule_based_agari_guard=enable_rule_based_agari_guard,
        boltzmann_epsilon=boltzmann_epsilon,
        boltzmann_temp=boltzmann_temp,
        top_p=top_p,
    )


__all__ = [
    "DEFAULT_BOLTZMANN_EPSILON",
    "DEFAULT_BOLTZMANN_TEMP",
    "DEFAULT_BRAIN_ONNX",
    "DEFAULT_DQN_ONNX",
    "DEFAULT_MORTAL_MODEL",
    "DEFAULT_MORTAL_RUNTIME_DIR",
    "DEFAULT_MORTAL_VENDOR_DIR",
    "DEFAULT_ONNX_METADATA",
    "DEFAULT_TOP_P",
    "DEFAULT_LIBRIICHI_SOURCE_DIR",
    "MortalBotSession",
    "MortalLogSummary",
    "MortalPaths",
    "MortalReaction",
    "MortalRuntime",
    "MortalRuntimeError",
    "RuntimeBackend",
    "load_mortal_runtime",
]
