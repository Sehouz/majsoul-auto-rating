from pathlib import Path

from majsoul_auto_rating.runtime import (
    DEFAULT_BOLTZMANN_EPSILON,
    DEFAULT_BOLTZMANN_TEMP,
    DEFAULT_MORTAL_MODEL,
    DEFAULT_MORTAL_ONNX,
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
    assert paths.model_onnx_path == vendor_dir / "models" / "mortal.onnx"
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
    onnx_path = Path("/tmp/models/custom-mortal.onnx")
    runtime = load_mortal_runtime(
        mortal_vendor_dir=vendor_dir,
        model_state_path=model_path,
        model_onnx_path=onnx_path,
        boltzmann_epsilon=0.2,
        boltzmann_temp=0.7,
        top_p=0.9,
    )

    assert isinstance(runtime, DummyRuntime)
    paths = captured["paths"]
    assert isinstance(paths, MortalPaths)
    assert paths.model_state_path == model_path
    assert paths.model_onnx_path == onnx_path
    kwargs = captured["kwargs"]
    assert kwargs["boltzmann_epsilon"] == 0.2
    assert kwargs["boltzmann_temp"] == 0.7
    assert kwargs["top_p"] == 0.9
