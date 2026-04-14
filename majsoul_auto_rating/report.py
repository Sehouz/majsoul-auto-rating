"""Reviewer-like Mortal JSON report generation without phi matrix output."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as package_version
import math
import time
from typing import Any

from .review import (
    MJAI_TILE_LABELS,
    MortalReviewError,
    _actor_of,
    _actual_q_value,
    _candidate_q_values,
    _deaka,
    _equal_ignore_aka_consumed,
    _event_type,
    _masks_from_bits,
    _next_action,
    _to_kan_label,
    _to_label,
)
from .runtime import MortalRuntime, load_mortal_runtime
from .tenhou_raw import split_tenhou_raw_log_by_kyoku, to_tenhou_raw_log


@dataclass(frozen=True)
class ReviewerDetail:
    action: dict[str, Any]
    q_value: float
    prob: float


@dataclass(frozen=True)
class ReviewerStateView:
    tehai: list[str]
    fuuros: list[dict[str, Any]]


@dataclass(frozen=True)
class ReviewerEntry:
    junme: int
    tiles_left: int
    last_actor: int
    tile: str
    state: ReviewerStateView
    at_self_chi_pon: bool
    at_self_riichi: bool
    at_opponent_kakan: bool
    expected: dict[str, Any]
    actual: dict[str, Any]
    is_equal: bool
    details: list[ReviewerDetail]
    shanten: int | None
    at_furiten: bool | None
    actual_index: int


@dataclass(frozen=True)
class ReviewerKyoku:
    kyoku: int
    honba: int
    end_status: list[dict[str, Any]]
    relative_scores: list[int]
    entries: list[ReviewerEntry]


@dataclass(frozen=True)
class ReviewerReview:
    total_reviewed: int
    total_matches: int
    rating: float
    temperature: float
    kyokus: list[ReviewerKyoku]
    model_tag: str


@dataclass(frozen=True)
class ReviewerReport:
    engine: str
    game_length: str
    loading_time: str
    review_time: str
    show_rating: bool
    version: str
    review: ReviewerReview
    player_id: int | None = None
    split_logs: list[dict[str, Any]] | None = None
    mjai_log: list[dict[str, Any]] | None = None
    lang: str | None = None


@dataclass(frozen=True)
class _DetailCandidate:
    action: dict[str, Any]
    q_value: float
    label_kind: str
    label_value: int


class _StateTracker:
    def __init__(self, player_id: int) -> None:
        self.player_id = int(player_id)
        self.tehai: list[str] = []
        self.fuuros: list[dict[str, Any]] = []

    def snapshot(self) -> ReviewerStateView:
        return ReviewerStateView(tehai=list(self.tehai), fuuros=[dict(item) for item in self.fuuros])

    def has_tile(self, tile: str) -> bool:
        return tile in self.tehai

    def update(self, event: dict[str, Any]) -> None:
        event_type = _event_type(event)
        actor = _actor_of(event)

        if event_type == "start_kyoku":
            tehais = event.get("tehais", [])
            self.tehai = list(tehais[self.player_id])
            self._sort_tehai()
            self.fuuros = []
            return

        if actor != self.player_id:
            return

        if event_type == "tsumo":
            self.tehai.append(str(event["pai"]))
            return

        if event_type == "dahai":
            if bool(event.get("tsumogiri", False)):
                if self.tehai:
                    self.tehai.pop()
            else:
                self._remove_tile(str(event["pai"]))
            return

        if event_type == "chi":
            consumed = [str(tile) for tile in event.get("consumed", [])]
            self._remove_multiple(consumed)
            self.fuuros.append(
                {
                    "type": "chi",
                    "target": int(event["target"]),
                    "pai": str(event["pai"]),
                    "consumed": consumed,
                }
            )
            return

        if event_type == "pon":
            consumed = [str(tile) for tile in event.get("consumed", [])]
            self._remove_multiple(consumed)
            self.fuuros.append(
                {
                    "type": "pon",
                    "target": int(event["target"]),
                    "pai": str(event["pai"]),
                    "consumed": consumed,
                }
            )
            return

        if event_type == "daiminkan":
            consumed = [str(tile) for tile in event.get("consumed", [])]
            self._remove_multiple(consumed)
            self.fuuros.append(
                {
                    "type": "daiminkan",
                    "target": int(event["target"]),
                    "pai": str(event["pai"]),
                    "consumed": consumed,
                }
            )
            return

        if event_type == "ankan":
            consumed = [str(tile) for tile in event.get("consumed", [])]
            self._remove_multiple(consumed)
            self.fuuros.append({"type": "ankan", "consumed": consumed})
            return

        if event_type == "kakan":
            pai = str(event["pai"])
            consumed = [str(tile) for tile in event.get("consumed", [])]
            self._remove_tile(pai)
            previous = None
            for index, fuuro in enumerate(self.fuuros):
                if fuuro.get("type") != "pon":
                    continue
                candidate_tiles = [str(fuuro["pai"]), *[str(tile) for tile in fuuro.get("consumed", [])]]
                if _tile_multiset(candidate_tiles) == _tile_multiset(consumed):
                    previous = (index, fuuro)
                    break
            if previous is None:
                raise MortalReviewError(f"invalid state: previous Pon not found for Kakan: {event!r}")
            previous_index, fuuro = previous
            self.fuuros[previous_index] = {
                "type": "kakan",
                "pai": pai,
                "previous_pon_target": int(fuuro["target"]),
                "previous_pon_pai": str(fuuro["pai"]),
                "consumed": [str(tile) for tile in fuuro.get("consumed", [])],
            }

    def _remove_tile(self, tile: str) -> None:
        try:
            self.tehai.remove(tile)
        except ValueError as exc:
            raise MortalReviewError(f"tile {tile!r} is not in tehai {self.tehai!r}") from exc

    def _remove_multiple(self, tiles: list[str]) -> None:
        self._sort_tehai()
        for tile in tiles:
            self._remove_tile(tile)

    def _sort_tehai(self) -> None:
        self.tehai.sort(key=_tile_sort_key)


def _tile_multiset(tiles: list[str]) -> list[str]:
    return sorted((_deaka(tile) for tile in tiles), key=_tile_sort_key)


def _tile_sort_key(tile: str) -> tuple[int, int, int]:
    if tile.endswith("r"):
        base = tile[:-1]
        aka = 0
    else:
        base = tile
        aka = 1

    if base in {"E", "S", "W", "N", "P", "F", "C"}:
        suit_order = 3
        number = {"E": 1, "S": 2, "W": 3, "N": 4, "P": 5, "F": 6, "C": 7}[base]
        return suit_order, number, aka

    number = int(base[0])
    suit = base[1]
    suit_order = {"m": 0, "p": 1, "s": 2}[suit]
    return suit_order, number, aka


def _tile_next(tile: str) -> str:
    base = _deaka(tile)
    if len(base) != 2 or base[1] not in {"m", "p", "s"}:
        raise MortalReviewError(f"tile does not support next(): {tile!r}")
    number = int(base[0])
    return f"{number + 1}{base[1]}"


def _tile_prev(tile: str) -> str:
    base = _deaka(tile)
    if len(base) != 2 or base[1] not in {"m", "p", "s"}:
        raise MortalReviewError(f"tile does not support prev(): {tile!r}")
    number = int(base[0])
    return f"{number - 1}{base[1]}"


def _tile_akaize(tile: str) -> str:
    base = _deaka(tile)
    if base == "5m":
        return "5mr"
    if base == "5p":
        return "5pr"
    if base == "5s":
        return "5sr"
    return base


def _rotate_scores(scores: list[int], player_id: int) -> list[int]:
    offset = int(player_id) % len(scores)
    return scores[offset:] + scores[:offset]


def _to_event(
    state: _StateTracker,
    label: int,
    target: int,
    last_tsumo_or_discard: str | None,
    at_kan_select: bool,
) -> dict[str, Any]:
    actor = state.player_id

    if at_kan_select:
        if not 0 <= label < 34:
            raise MortalReviewError(f"invalid kan label: {label}")
        tile = MJAI_TILE_LABELS[label]
        return {"type": "ankan", "actor": actor, "consumed": [tile, tile, tile, tile]}

    if 0 <= label <= 36:
        pai = MJAI_TILE_LABELS[label]
        return {
            "type": "dahai",
            "actor": actor,
            "pai": pai,
            "tsumogiri": last_tsumo_or_discard is not None and last_tsumo_or_discard == pai,
        }
    if label == 37:
        return {"type": "reach", "actor": actor}
    if label in {38, 39, 40}:
        if last_tsumo_or_discard is None:
            raise MortalReviewError("missing last discard for Chi")
        pai = last_tsumo_or_discard
        if label == 38:
            can_akaize_consumed = pai in {"3m", "4m", "3p", "4p", "3s", "4s"} and state.has_tile(
                _tile_akaize(_tile_next(pai))
            )
            consumed = [_tile_next(pai), _tile_next(_tile_next(pai))]
        elif label == 39:
            can_akaize_consumed = pai in {"4m", "6m", "4p", "6p", "4s", "6s"} and state.has_tile(
                _tile_akaize("5" + _deaka(pai)[1])
            )
            consumed = [_tile_prev(pai), _tile_next(pai)]
        else:
            can_akaize_consumed = pai in {"6m", "7m", "6p", "7p", "6s", "7s"} and state.has_tile(
                _tile_akaize(_tile_prev(pai))
            )
            consumed = [_tile_prev(_tile_prev(pai)), _tile_prev(pai)]
        if can_akaize_consumed:
            consumed = [_tile_akaize(tile) for tile in consumed]
        return {"type": "chi", "actor": actor, "target": target, "pai": pai, "consumed": consumed}
    if label == 41:
        if last_tsumo_or_discard is None:
            raise MortalReviewError("missing last discard for Pon")
        pai = last_tsumo_or_discard
        if pai in {"5m", "5p", "5s"} and state.has_tile(_tile_akaize(pai)):
            consumed = [_tile_akaize(pai), _deaka(pai)]
        else:
            consumed = [_deaka(pai), _deaka(pai)]
        return {"type": "pon", "actor": actor, "target": target, "pai": pai, "consumed": consumed}
    if label == 42:
        if last_tsumo_or_discard is None:
            raise MortalReviewError("missing last discard for Daiminkan")
        tile = last_tsumo_or_discard
        consumed = [tile, _deaka(tile), _deaka(tile), _deaka(tile)]
        return {"type": "ankan", "actor": actor, "consumed": consumed}
    if label == 43:
        return {"type": "hora", "actor": actor, "target": target, "deltas": None, "ura_markers": None}
    if label == 44:
        return {"type": "ryukyoku", "deltas": None}
    if label == 45:
        return {"type": "none"}
    raise MortalReviewError(f"unexpected label: {label}")


def _softmax(values: list[float], temperature: float) -> list[float]:
    if not values:
        return []
    if temperature <= 0:
        raise MortalReviewError(f"temperature must be > 0, got {temperature}")
    maximum = max(values)
    exps = [math.exp((value - maximum) / temperature) for value in values]
    total = sum(exps)
    if total <= 0:
        return [0.0 for _ in values]
    return [value / total for value in exps]


def _build_details(
    *,
    meta: dict[str, Any],
    state: _StateTracker,
    last_actor: int,
    last_tsumo_or_discard: str | None,
    actual: dict[str, Any],
    temperature: float,
) -> tuple[list[ReviewerDetail], int]:
    mask_bits = int(meta.get("mask_bits", 0))
    masks = _masks_from_bits(mask_bits)
    root_q_values = [float(value) for value in meta.get("q_values", [])]
    details: list[_DetailCandidate] = []
    compact_index = 0
    for label, enabled in enumerate(masks):
        if not enabled:
            continue
        q_value = root_q_values[compact_index]
        compact_index += 1
        details.append(
            _DetailCandidate(
                action=_to_event(state, label, last_actor, last_tsumo_or_discard, False),
                q_value=q_value,
                label_kind="general",
                label_value=label,
            )
        )

    actual_kan_label = _to_kan_label(actual)
    kan_meta = meta.get("kan_select")
    if kan_meta:
        kan_mask_bits = int(kan_meta.get("mask_bits", 0))
        num_kans = kan_mask_bits.bit_count()
        if num_kans > 0:
            root_kan = next((detail for detail in details if detail.label_kind == "general" and detail.label_value == 42), None)
            if root_kan is None:
                raise MortalReviewError("in kan_select but no kan found in root action list")
            details = [detail for detail in details if not (detail.label_kind == "general" and detail.label_value == 42)]
            kan_q_values = [float(value) for value in kan_meta.get("q_values", [])]
            kan_compact_index = 0
            for kan_label, enabled in enumerate(_masks_from_bits(kan_mask_bits)):
                if not enabled:
                    continue
                q_value = root_kan.q_value if num_kans == 1 else kan_q_values[kan_compact_index]
                kan_compact_index += 1
                details.append(
                    _DetailCandidate(
                        action=_to_event(state, kan_label, last_actor, last_tsumo_or_discard, True),
                        q_value=q_value,
                        label_kind="kan_select",
                        label_value=kan_label,
                    )
                )

    probs = _softmax([detail.q_value for detail in details], temperature)
    ranked = sorted(
        [ReviewerDetail(action=detail.action, q_value=detail.q_value, prob=prob) for detail, prob in zip(details, probs)],
        key=lambda item: item.q_value,
        reverse=True,
    )

    actual_label = _to_label(actual)
    actual_index = -1
    for index, detail in enumerate(details):
        if detail.label_kind == "general" and actual_kan_label is None and detail.label_value == actual_label:
            actual_index = index
            break
        if detail.label_kind == "kan_select" and actual_kan_label is not None and detail.label_value == actual_kan_label:
            actual_index = index
            break
    if actual_index < 0:
        raise MortalReviewError(f"failed to find actual action {actual!r} in details")

    sorted_actual_index = next(
        index for index, detail in enumerate(ranked) if _equal_ignore_aka_consumed(detail.action, actual)
    )
    return ranked, sorted_actual_index


def _format_duration(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    if milliseconds < 1000:
        return f"{milliseconds}ms"
    whole_seconds, remaining_ms = divmod(milliseconds, 1000)
    if remaining_ms == 0:
        return f"{whole_seconds}s"
    return f"{whole_seconds}s {remaining_ms}ms"


def _default_version() -> str:
    try:
        return package_version("majsoul-auto-rating")
    except PackageNotFoundError:
        return "dev"


def build_reviewer_report(
    events: list[dict[str, Any]],
    *,
    player_id: int,
    runtime: MortalRuntime | None = None,
    parsed_record: dict[str, Any] | None = None,
    temperature: float = 0.1,
    loading_time_seconds: float = 0.0,
    show_rating: bool = False,
    version: str | None = None,
    game_length: str = "Hanchan",
    lang: str = "en",
) -> ReviewerReport:
    if runtime is None:
        runtime = load_mortal_runtime()

    begin_review = time.perf_counter()
    bot = runtime.create_bot(player_id)
    state = _StateTracker(player_id)

    kyokus: list[ReviewerKyoku] = []
    current_kyoku = ReviewerKyoku(kyoku=0, honba=0, end_status=[], relative_scores=[0, 0, 0, 0], entries=[])
    entries: list[ReviewerEntry] = []
    total_reviewed = 0
    total_matches = 0
    raw_rating = 0.0

    junme = 0
    tiles_left = 70
    last_tsumo_or_discard: str | None = None
    last_actor = 0

    for index, event in enumerate(events):
        reaction = bot.react(event)
        state.update(event)

        at_self_chi_pon = False
        at_self_riichi = False
        event_type = _event_type(event)
        actor = _actor_of(event)

        if event_type == "start_kyoku":
            current_kyoku = ReviewerKyoku(
                kyoku=("ESWN".index(str(event["bakaze"])) * 4) + int(event["kyoku"]) - 1,
                honba=int(event["honba"]),
                end_status=[],
                relative_scores=_rotate_scores([int(score) for score in event.get("scores", [])], player_id),
                entries=[],
            )
            tiles_left = 70
        elif event_type == "end_kyoku":
            kyokus.append(
                ReviewerKyoku(
                    kyoku=current_kyoku.kyoku,
                    honba=current_kyoku.honba,
                    end_status=list(current_kyoku.end_status),
                    relative_scores=list(current_kyoku.relative_scores),
                    entries=list(entries),
                )
            )
            entries = []
            junme = 0
        elif event_type in {"hora", "ryukyoku"}:
            current_kyoku.end_status.append(event)
        elif event_type == "tsumo":
            if actor == player_id:
                last_tsumo_or_discard = str(event.get("pai", "?"))
                junme += 1
            tiles_left -= 1
        elif event_type in {"chi", "pon"} and actor == player_id:
            at_self_chi_pon = True
            junme += 1
        elif event_type == "reach" and actor == player_id:
            at_self_riichi = True
        elif event_type in {"dahai", "kakan"}:
            last_tsumo_or_discard = str(event.get("pai", "?"))

        if actor is not None:
            last_actor = actor

        if event_type in {"start_game", "start_kyoku", "end_kyoku", "end_game"}:
            continue
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

        details, actual_index = _build_details(
            meta=meta,
            state=state,
            last_actor=last_actor,
            last_tsumo_or_discard=last_tsumo_or_discard,
            actual=actual,
            temperature=temperature,
        )

        if last_tsumo_or_discard is None:
            raise MortalReviewError("missing last tsumo or discard")
        entries.append(
            ReviewerEntry(
                junme=junme,
                tiles_left=tiles_left,
                last_actor=last_actor,
                tile=last_tsumo_or_discard,
                state=state.snapshot(),
                at_self_chi_pon=at_self_chi_pon,
                at_self_riichi=at_self_riichi,
                at_opponent_kakan=event_type == "kakan",
                expected=expected,
                actual=actual,
                is_equal=is_equal,
                details=details,
                shanten=meta.get("shanten"),
                at_furiten=meta.get("at_furiten"),
                actual_index=actual_index,
            )
        )

    rating = 0.0 if total_reviewed == 0 else math.pow(raw_rating / total_reviewed, 2)
    review = ReviewerReview(
        total_reviewed=total_reviewed,
        total_matches=total_matches,
        rating=rating,
        temperature=float(temperature),
        kyokus=kyokus,
        model_tag=runtime.model_tag,
    )
    split_logs = None
    if parsed_record is not None:
        split_logs = split_tenhou_raw_log_by_kyoku(to_tenhou_raw_log(parsed_record))

    return ReviewerReport(
        engine="Mortal",
        game_length=game_length,
        loading_time=_format_duration(loading_time_seconds),
        review_time=_format_duration(time.perf_counter() - begin_review),
        show_rating=bool(show_rating),
        version=version or _default_version(),
        review=review,
        player_id=int(player_id),
        split_logs=split_logs,
        mjai_log=events,
        lang=lang,
    )


__all__ = [
    "ReviewerDetail",
    "ReviewerEntry",
    "ReviewerKyoku",
    "ReviewerReport",
    "ReviewerReview",
    "ReviewerStateView",
    "build_reviewer_report",
]
