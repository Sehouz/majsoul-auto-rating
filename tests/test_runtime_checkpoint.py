from __future__ import annotations

import pickle
from pathlib import Path

from majsoul_auto_rating.runtime import _load_checkpoint


class FakeTorch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, str]] = []

    def load(self, path: str, *, weights_only: bool, map_location: str):
        self.calls.append((path, weights_only, map_location))
        if weights_only:
            raise pickle.UnpicklingError(
                "Weights only load failed. Unsupported global: numpy.core.multiarray.scalar"
            )
        return {"ok": True}


def test_load_checkpoint_falls_back_when_weights_only_rejected() -> None:
    fake_torch = FakeTorch()
    path = Path("/tmp/mortal.pth")

    result = _load_checkpoint(fake_torch, path)

    assert result == {"ok": True}
    assert fake_torch.calls == [
        (str(path), True, "cpu"),
        (str(path), False, "cpu"),
    ]
