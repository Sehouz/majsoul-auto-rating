from __future__ import annotations

import os
from pathlib import Path
from shutil import copy2, copytree, rmtree
import subprocess
import sys
import sysconfig

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from wheel.bdist_wheel import bdist_wheel as _bdist_wheel


PACKAGE_NAME = "majsoul_auto_rating"
REPO_ROOT = Path(__file__).resolve().parent
SOURCE_VENDOR_DIR = REPO_ROOT / "vendor"
SOURCE_LIBRIICHI_DIR = SOURCE_VENDOR_DIR / "libriichi-src"
PACKAGE_MODE = os.environ.get("MAJSOUL_PACKAGE_BACKEND", "torch")


def _libriichi_extension_name() -> str:
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not suffix:
        return "libriichi.so"
    return f"libriichi{suffix}"


def _build_libriichi(target_runtime_dir: Path) -> None:
    env = os.environ.copy()
    env.setdefault("PYO3_PYTHON", sys.executable)
    subprocess.run(
        ["cargo", "build", "--locked", "--release", "--lib"],
        cwd=SOURCE_LIBRIICHI_DIR,
        check=True,
        env=env,
    )

    target_dir = Path(env.get("CARGO_TARGET_DIR", SOURCE_LIBRIICHI_DIR / "target"))
    release_dir = target_dir / "release"
    candidates = sorted(
        path
        for pattern in ("libriichi*.so", "libriichi*.dylib", "libriichi*.pyd")
        for path in release_dir.glob(pattern)
    )
    if not candidates:
        raise RuntimeError("failed to build libriichi extension with cargo")

    target_runtime_dir.mkdir(parents=True, exist_ok=True)
    copy2(candidates[0], target_runtime_dir / _libriichi_extension_name())


class build_py(_build_py):
    def run(self) -> None:
        super().run()
        self._copy_vendor_tree()
        self._build_platform_libriichi()

    def _copy_vendor_tree(self) -> None:
        target_package_dir = Path(self.build_lib) / PACKAGE_NAME
        target_vendor_dir = target_package_dir / "vendor"
        target_data_dir = target_package_dir / "data"
        if not target_data_dir.exists():
            source_data_dir = REPO_ROOT / PACKAGE_NAME / "data"
            if source_data_dir.exists():
                copytree(source_data_dir, target_data_dir)
        if target_vendor_dir.exists():
            return
        target_vendor_dir.mkdir(parents=True, exist_ok=True)
        copy2(SOURCE_VENDOR_DIR / "README.md", target_vendor_dir / "README.md")
        source_models_dir = SOURCE_VENDOR_DIR / "models"
        if source_models_dir.exists():
            copied_models_dir = target_vendor_dir / "models"
            copytree(source_models_dir, copied_models_dir)
            self._prune_models(copied_models_dir)
        copytree(SOURCE_VENDOR_DIR / "mortal_runtime", target_vendor_dir / "mortal_runtime")
        self._prune_vendor_tree(target_vendor_dir)

    def _build_platform_libriichi(self) -> None:
        target_runtime_dir = (
            Path(self.build_lib) / PACKAGE_NAME / "vendor" / "mortal_runtime"
        )
        _build_libriichi(target_runtime_dir)

    def _prune_vendor_tree(self, target_vendor_dir: Path) -> None:
        runtime_dir = target_vendor_dir / "mortal_runtime"
        for path in runtime_dir.glob("libriichi*.so"):
            path.unlink()
        for path in runtime_dir.glob("libriichi*.dylib"):
            path.unlink()
        for path in runtime_dir.glob("libriichi*.pyd"):
            path.unlink()
        pycache_dir = runtime_dir / "__pycache__"
        if pycache_dir.exists():
            rmtree(pycache_dir)

        libriichi_source_dir = target_vendor_dir / "libriichi-src"
        if libriichi_source_dir.exists():
            rmtree(libriichi_source_dir)

    def _prune_models(self, target_models_dir: Path) -> None:
        if PACKAGE_MODE == "torch":
            for name in ("brain.onnx", "brain.onnx.data", "dqn.onnx", "dqn.onnx.data", "onnx_metadata.json"):
                path = target_models_dir / name
                if path.exists():
                    path.unlink()
            return
        if PACKAGE_MODE == "onnxruntime":
            mortal_path = target_models_dir / "mortal.pth"
            if mortal_path.exists():
                mortal_path.unlink()
            return
        raise RuntimeError(f"unsupported MAJSOUL_PACKAGE_BACKEND={PACKAGE_MODE!r}")


class bdist_wheel(_bdist_wheel):
    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False


setup(cmdclass={"build_py": build_py, "bdist_wheel": bdist_wheel})
