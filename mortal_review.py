#!/usr/bin/env python3
"""Lightweight in-process Mortal review over MJAI events."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from mortal_runtime import MortalRuntime, load_mortal_runtime


MJAI_TILE_LABELS = [
    "1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
    "1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p",
    "1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s",
    "E", "S", "W", "N", "P", "F", "C",
    "5mr", "5pr", "5sr",
    "?",
]
TILE_TO_LABEL = {tile: index for index, tile in enumerate(MJAI_TILE_LABELS)}


class MortalReviewError(RuntimeError):
    """Raised when a MJAI log cannot be reviewed cleanly."""


@dataclass(frozen=True)
class MortalReviewEntry:
    event_index: int
    trigger_event: dict[str, Any]
    expected: dict[str, Any]
    actual: dict[str, Any]
    is_equal: bool
    shanten: int | None
    at_furiten: bool | None
    actual_label: int
    actual_q_value: float
    q_value_min: float
    q_value_max: float
    mask_bits: int


@dataclass(frozen=True)
class MortalReviewResult:
    total_reviewed: int
    total_matches: int
    raw_score_sum: float
    rating: float
    rating_percent: float
    model_tag: str
    temperature: float
    phi_matrix: list[list[list[float]]] | None
    entries: list[MortalReviewEntry]


def _deaka(tile: str) -> str:
    if tile in {"5mr", "5pr", "5sr"}:
        return tile[:-1]
    return tile


def _actor_of(event: dict[str, Any]) -> int | None:
    actor = event.get("actor")
    if actor is None:
        return None
    return int(actor)


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("type", ""))


def _equal_ignore_aka_consumed(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_type = _event_type(left)
    right_type = _event_type(right)
    if left_type != right_type:
        return False

    if left_type in {"dahai", "kakan"}:
        return left.get("pai") == right.get("pai")

    if left_type in {"chi", "pon", "daiminkan", "ankan"}:
        left_consumed = sorted(_deaka(tile) for tile in left.get("consumed", []))
        right_consumed = sorted(_deaka(tile) for tile in right.get("consumed", []))
        return left_consumed == right_consumed

    if left_type in {"reach", "hora", "ryukyoku", "none"}:
        return True

    return left == right


def _tile_label(tile: str) -> int:
    try:
        return TILE_TO_LABEL[tile]
    except KeyError as exc:
        raise MortalReviewError(f"unknown MJAI tile label: {tile!r}") from exc


def _to_label(event: dict[str, Any]) -> int:
    event_type = _event_type(event)
    if event_type == "dahai":
        return _tile_label(str(event["pai"]))
    if event_type == "reach":
        return 37
    if event_type == "chi":
        pai = _tile_label(_deaka(str(event["pai"])))
        consumed = sorted(_tile_label(_deaka(str(tile))) for tile in event.get("consumed", []))
        minimum = min(consumed)
        maximum = max(consumed)
        if pai < minimum:
            return 38
        if pai < maximum:
            return 39
        return 40
    if event_type == "pon":
        return 41
    if event_type in {"daiminkan", "ankan", "kakan"}:
        return 42
    if event_type == "hora":
        return 43
    if event_type == "ryukyoku":
        return 44
    if event_type == "none":
        return 45
    raise MortalReviewError(f"unsupported action label for event: {event!r}")


def _to_kan_label(event: dict[str, Any]) -> int | None:
    event_type = _event_type(event)
    if event_type == "ankan":
        consumed = event.get("consumed", [])
        if not consumed:
            raise MortalReviewError(f"ankan event is missing consumed tiles: {event!r}")
        return _tile_label(_deaka(str(consumed[0])))
    if event_type == "kakan":
        return _tile_label(_deaka(str(event["pai"])))
    return None


def _masks_from_bits(bits: int) -> list[bool]:
    return [((bits >> index) & 1) == 1 for index in range(46)]


def _compact_q_lookup(q_values: list[float], mask_bits: int, label: int) -> float:
    compact_index = 0
    for candidate_label in range(46):
        if ((mask_bits >> candidate_label) & 1) == 0:
            continue
        if candidate_label == label:
            return float(q_values[compact_index])
        compact_index += 1
    raise MortalReviewError(
        f"label {label} is not present in mask_bits={mask_bits} with compact q_values={q_values!r}"
    )


def _candidate_q_values(meta: dict[str, Any]) -> list[float]:
    root_q_values = [float(value) for value in meta.get("q_values", [])]
    root_mask_bits = int(meta.get("mask_bits", 0))
    kan_meta = meta.get("kan_select")
    if not kan_meta:
        return root_q_values

    kan_mask_bits = int(kan_meta.get("mask_bits", 0))
    num_kans = kan_mask_bits.bit_count()
    if num_kans <= 1:
        return root_q_values

    flattened: list[float] = []
    compact_index = 0
    for label in range(46):
        if ((root_mask_bits >> label) & 1) == 0:
            continue
        q_value = float(root_q_values[compact_index])
        if label != 42:
            flattened.append(q_value)
        compact_index += 1

    flattened.extend(float(value) for value in kan_meta.get("q_values", []))
    return flattened


def _actual_q_value(meta: dict[str, Any], actual: dict[str, Any]) -> float:
    actual_label = _to_label(actual)
    root_q_values = [float(value) for value in meta.get("q_values", [])]
    root_mask_bits = int(meta.get("mask_bits", 0))
    kan_meta = meta.get("kan_select")

    if actual_label != 42 or not kan_meta:
        return _compact_q_lookup(root_q_values, root_mask_bits, actual_label)

    kan_mask_bits = int(kan_meta.get("mask_bits", 0))
    if kan_mask_bits.bit_count() <= 1:
        return _compact_q_lookup(root_q_values, root_mask_bits, 42)

    kan_label = _to_kan_label(actual)
    if kan_label is None:
        raise MortalReviewError(f"missing kan label for actual event: {actual!r}")
    kan_q_values = [float(value) for value in kan_meta.get("q_values", [])]
    return _compact_q_lookup(kan_q_values, kan_mask_bits, kan_label)


def _next_action(
    events: list[dict[str, Any]],
    player_id: int,
    *,
    can_pon_or_daiminkan: bool,
    can_agari: bool,
    can_ryukyoku: bool,
) -> dict[str, Any] | None:
    if not events:
        return None

    event = events[0]
    event_type = _event_type(event)
    if event_type in {"dora", "reach_accepted"}:
        return _next_action(
            events[1:],
            player_id,
            can_pon_or_daiminkan=can_pon_or_daiminkan,
            can_agari=can_agari,
            can_ryukyoku=can_ryukyoku,
        )

    if event_type == "tsumo":
        return {"type": "none"}

    if event_type == "hora":
        for candidate in events[:3]:
            if _event_type(candidate) == "hora" and _actor_of(candidate) == player_id:
                return candidate
        if can_agari:
            return {"type": "none"}
        return None

    if event_type == "ryukyoku":
        return event if can_ryukyoku else None

    actual_actor = _actor_of(event)
    if actual_actor is not None and actual_actor != player_id:
        if can_agari or can_pon_or_daiminkan:
            return {"type": "none"}
        return None

    return event


def review_mjai_events(
    events: list[dict[str, Any]],
    *,
    player_id: int,
    runtime: MortalRuntime | None = None,
    temperature: float = 1.0,
    include_phi_matrix: bool = True,
) -> MortalReviewResult:
    if runtime is None:
        runtime = load_mortal_runtime(load_grp=include_phi_matrix)

    bot = runtime.create_bot(player_id)
    entries: list[MortalReviewEntry] = []
    total_reviewed = 0
    total_matches = 0
    raw_rating = 0.0

    for index, event in enumerate(events):
        reaction = bot.react(event)
        if reaction is None:
            continue

        meta = reaction.get("meta") or {}
        mask_bits = int(meta.get("mask_bits", 0))
        if mask_bits.bit_count() <= 1:
            continue

        masks = _masks_from_bits(mask_bits)
        actual = _next_action(
            events[index + 1 :],
            player_id,
            can_pon_or_daiminkan=bool(masks[41] or masks[42]),
            can_agari=bool(masks[43]),
            can_ryukyoku=bool(masks[44]),
        )
        if actual is None:
            continue

        expected = {key: value for key, value in reaction.items() if key != "meta"}
        is_equal = _equal_ignore_aka_consumed(expected, actual)
        actual_label = _to_label(actual)
        actual_q_value = _actual_q_value(meta, actual)
        q_candidates = _candidate_q_values(meta)
        q_value_min = min(q_candidates)
        q_value_max = max(q_candidates)

        if is_equal:
            raw_rating += 1.0
            total_matches += 1
        else:
            raw_rating += (actual_q_value - q_value_min) / max(q_value_max - q_value_min, 1e-6)
        total_reviewed += 1

        entries.append(
            MortalReviewEntry(
                event_index=index,
                trigger_event=event,
                expected=expected,
                actual=actual,
                is_equal=is_equal,
                shanten=meta.get("shanten"),
                at_furiten=meta.get("at_furiten"),
                actual_label=actual_label,
                actual_q_value=actual_q_value,
                q_value_min=q_value_min,
                q_value_max=q_value_max,
                mask_bits=mask_bits,
            )
        )

    phi_matrix = runtime.compute_phi_matrix(events) if include_phi_matrix else None
    rating = 0.0 if total_reviewed == 0 else math.pow(raw_rating / total_reviewed, 2)
    return MortalReviewResult(
        total_reviewed=total_reviewed,
        total_matches=total_matches,
        raw_score_sum=raw_rating,
        rating=rating,
        rating_percent=rating * 100.0,
        model_tag=runtime.model_tag,
        temperature=float(temperature),
        phi_matrix=phi_matrix,
        entries=entries,
    )


__all__ = [
    "MortalReviewEntry",
    "MortalReviewError",
    "MortalReviewResult",
    "review_mjai_events",
]
