from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort


@dataclass(frozen=True)
class OrtEnginePaths:
    model_onnx_path: Path


class OrtMortalEngine:
    def __init__(
        self,
        *,
        paths: OrtEnginePaths,
        is_oracle: bool,
        version: int,
        enable_quick_eval: bool = True,
        enable_rule_based_agari_guard: bool = False,
        name: str = "NoName",
        boltzmann_epsilon: float = 0.0,
        boltzmann_temp: float = 1.0,
        top_p: float = 1.0,
        providers: list[str] | None = None,
    ) -> None:
        self.engine_type = "mortal"
        self.is_oracle = bool(is_oracle)
        self.version = int(version)
        self.enable_quick_eval = bool(enable_quick_eval)
        self.enable_rule_based_agari_guard = bool(enable_rule_based_agari_guard)
        self.name = str(name)
        self.boltzmann_epsilon = float(boltzmann_epsilon)
        self.boltzmann_temp = float(boltzmann_temp)
        self.top_p = float(top_p)

        session_opts = ort.SessionOptions()
        session_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        chosen_providers = providers or ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(
            str(paths.model_onnx_path),
            sess_options=session_opts,
            providers=chosen_providers,
        )

    def react_batch(self, obs: list[Any], masks: list[Any], invisible_obs: list[Any] | None):
        del invisible_obs
        obs_np = np.stack(obs, axis=0).astype(np.float32, copy=False)
        masks_np = np.stack(masks, axis=0).astype(np.bool_, copy=False)
        q_out = self.session.run(["q_values"], {"obs": obs_np, "mask": masks_np})[0]

        if self.boltzmann_epsilon > 0:
            is_greedy = np.random.binomial(1, 1 - self.boltzmann_epsilon, size=q_out.shape[0]).astype(bool)
            logits = np.where(masks_np, q_out / self.boltzmann_temp, -np.inf)
            sampled = _sample_top_p(logits, self.top_p)
            actions = np.where(is_greedy, q_out.argmax(-1), sampled)
        else:
            is_greedy = np.ones(q_out.shape[0], dtype=bool)
            actions = q_out.argmax(-1)

        return actions.tolist(), q_out.tolist(), masks_np.tolist(), is_greedy.tolist()


def _sample_top_p(logits: np.ndarray, p: float) -> np.ndarray:
    if p >= 1:
        return np.array([_sample_categorical_from_logits(row) for row in logits], dtype=np.int64)
    if p <= 0:
        return logits.argmax(-1)

    probs = _softmax(logits)
    sampled: list[int] = []
    for row in probs:
        order = np.argsort(row)[::-1]
        probs_sorted = row[order].copy()
        csum = np.cumsum(probs_sorted)
        mask = csum - probs_sorted > p
        probs_sorted[mask] = 0.0
        total = probs_sorted.sum()
        if total <= 0:
            sampled.append(int(order[0]))
            continue
        probs_sorted /= total
        sampled.append(int(np.random.choice(order, p=probs_sorted)))
    return np.asarray(sampled, dtype=np.int64)


def _sample_categorical_from_logits(logits: np.ndarray) -> int:
    probs = _softmax(logits[None, :])[0]
    return int(np.random.choice(np.arange(len(probs)), p=probs))


def _softmax(logits: np.ndarray) -> np.ndarray:
    max_logits = np.max(logits, axis=-1, keepdims=True)
    shifted = logits - max_logits
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


__all__ = ["OrtEnginePaths", "OrtMortalEngine"]
