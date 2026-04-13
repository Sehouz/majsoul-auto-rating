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


def _libriichi_extension_name() -> str:
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not suffix:
        return "libriichi.so"
    return f"libriichi{suffix}"


def _build_libriichi(target_runtime_dir: Path) -> None:
    env = os.environ.copy()
    env.setdefault("PYO3_PYTHON", sys.executable)
    subprocess.run(
        ["cargo", "build", "--release", "--lib"],
        cwd=SOURCE_LIBRIICHI_DIR,
        check=True,
        env=env,
    )

    release_dir = SOURCE_LIBRIICHI_DIR / "target" / "release"
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
        if target_vendor_dir.exists():
            return
        copytree(SOURCE_VENDOR_DIR, target_vendor_dir)
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

        cargo_target_dir = target_vendor_dir / "libriichi-src" / "target"
        if cargo_target_dir.exists():
            rmtree(cargo_target_dir)
        cargo_lock = target_vendor_dir / "libriichi-src" / "Cargo.lock"
        if cargo_lock.exists():
            cargo_lock.unlink()


class bdist_wheel(_bdist_wheel):
    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False


setup(cmdclass={"build_py": build_py, "bdist_wheel": bdist_wheel})
