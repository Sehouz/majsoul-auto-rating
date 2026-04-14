from pathlib import Path

from majsoul_auto_rating.runtime import (
    DEFAULT_BOLTZMANN_EPSILON,
    DEFAULT_BOLTZMANN_TEMP,
    DEFAULT_BRAIN_ONNX,
    DEFAULT_DQN_ONNX,
    DEFAULT_MORTAL_MODEL,
    DEFAULT_ONNX_METADATA,
    DEFAULT_TOP_P,
    MortalPaths,
)
from majsoul_auto_rating.runtime import load_mortal_runtime


def test_custom_vendor_dir_rewrites_default_model_paths(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyRuntime:
        def __init__(self, *, paths: MortalPaths, **kwargs) -> None:
            captured["paths"] = paths
            captured["kwargs"] = kwargs

    monkeypatch.setattr("majsoul_auto_rating.runtime.MortalRuntime", DummyRuntime)

    vendor_dir = Path("/tmp/custom-vendor")
    runtime = load_mortal_runtime(mortal_vendor_dir=vendor_dir)

    assert isinstance(runtime, DummyRuntime)
    paths = captured["paths"]
    assert isinstance(paths, MortalPaths)
    assert paths.mortal_vendor_dir == vendor_dir
    assert paths.mortal_runtime_dir == vendor_dir / "mortal_runtime"
    assert paths.libriichi_source_dir == vendor_dir / "libriichi-src"
    assert paths.model_state_path == vendor_dir / "models" / "mortal.pth"
    assert paths.brain_onnx_path == vendor_dir / "models" / "brain.onnx"
    assert paths.dqn_onnx_path == vendor_dir / "models" / "dqn.onnx"
    assert paths.onnx_metadata_path == vendor_dir / "models" / "onnx_metadata.json"
    kwargs = captured["kwargs"]
    assert kwargs["boltzmann_epsilon"] == DEFAULT_BOLTZMANN_EPSILON
    assert kwargs["boltzmann_temp"] == DEFAULT_BOLTZMANN_TEMP
    assert kwargs["top_p"] == DEFAULT_TOP_P


def test_explicit_model_paths_are_preserved(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyRuntime:
        def __init__(self, *, paths: MortalPaths, **kwargs) -> None:
            captured["paths"] = paths
            captured["kwargs"] = kwargs

    monkeypatch.setattr("majsoul_auto_rating.runtime.MortalRuntime", DummyRuntime)

    vendor_dir = Path("/tmp/custom-vendor")
    model_path = Path("/tmp/models/custom-mortal.pth")
    brain_path = Path("/tmp/models/custom-brain.onnx")
    dqn_path = Path("/tmp/models/custom-dqn.onnx")
    metadata_path = Path("/tmp/models/custom-onnx-metadata.json")
    runtime = load_mortal_runtime(
        mortal_vendor_dir=vendor_dir,
        model_state_path=model_path,
        brain_onnx_path=brain_path,
        dqn_onnx_path=dqn_path,
        onnx_metadata_path=metadata_path,
        boltzmann_epsilon=0.2,
        boltzmann_temp=0.7,
        top_p=0.9,
    )

    assert isinstance(runtime, DummyRuntime)
    paths = captured["paths"]
    assert isinstance(paths, MortalPaths)
    assert paths.model_state_path == model_path
    assert paths.brain_onnx_path == brain_path
    assert paths.dqn_onnx_path == dqn_path
    assert paths.onnx_metadata_path == metadata_path
    kwargs = captured["kwargs"]
    assert kwargs["boltzmann_epsilon"] == 0.2
    assert kwargs["boltzmann_temp"] == 0.7
    assert kwargs["top_p"] == 0.9
