from pathlib import Path

from majsoul_auto_rating.runtime import DEFAULT_GRP_MODEL, DEFAULT_MORTAL_MODEL, MortalPaths
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
    assert paths.grp_state_path == vendor_dir / "models" / "grp.pth"


def test_explicit_model_paths_are_preserved(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyRuntime:
        def __init__(self, *, paths: MortalPaths, **kwargs) -> None:
            captured["paths"] = paths
            captured["kwargs"] = kwargs

    monkeypatch.setattr("majsoul_auto_rating.runtime.MortalRuntime", DummyRuntime)

    vendor_dir = Path("/tmp/custom-vendor")
    model_path = Path("/tmp/models/custom-mortal.pth")
    grp_path = Path("/tmp/models/custom-grp.pth")
    runtime = load_mortal_runtime(
        mortal_vendor_dir=vendor_dir,
        model_state_path=model_path,
        grp_state_path=grp_path,
    )

    assert isinstance(runtime, DummyRuntime)
    paths = captured["paths"]
    assert isinstance(paths, MortalPaths)
    assert paths.model_state_path == model_path
    assert paths.grp_state_path == grp_path
