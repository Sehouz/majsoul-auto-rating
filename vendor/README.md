# Vendored Mortal Runtime

This directory contains the runtime assets copied into this repository so the
Mahjong Soul review pipeline no longer depends on loading code from an external
Mortal checkout at runtime.

Included:

- `mortal_runtime/engine.py`
- `mortal_runtime/model.py`
- `mortal_runtime/libriichi.so`
- `models/mortal.pth`
- `models/grp.pth`
- `libriichi-src/`

Origins:

- Mortal runtime files from `/Users/sehouz/Mahjang/Mortal/mortal`
- libriichi source from `/Users/sehouz/Mahjang/Mortal/libriichi`
- model weights from `/Users/sehouz/Mahjang/models`

Notes:

- `libriichi.so` is the currently vendored compiled extension used by the
  Python runtime wrapper.
- `libriichi-src/` is included so future Rust / `PyO3` integration work can be
  done inside this repository without referencing the external source tree.
- the current verification target is:
  `env PYO3_PYTHON=/Users/sehouz/Mahjang/Mortal/.venv/bin/python cargo build --release --lib`
  in `vendor/libriichi-src/`
- model files and local build outputs are ignored by git
