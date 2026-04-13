"""
Convert Mahjong Soul replay records into MJAI events.

This module is the first structured layer for the Mortal review pipeline:

1. fetch / load a Mahjong Soul paipu
2. convert replay actions to MJAI events
3. feed the events to an in-process reviewer

It intentionally does not depend on `tensoul` or `mjai-reviewer`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from majsoul.proto import liqi_pb2 as pb
from majsoul.utils import auto_parse_message_fields, parse_wrapper


MS_TILE_TO_MJAI_TILE = {
    "0m": "5mr",
    "1m": "1m",
    "2m": "2m",
    "3m": "3m",
    "4m": "4m",
    "5m": "5m",
    "6m": "6m",
    "7m": "7m",
    "8m": "8m",
    "9m": "9m",
    "0p": "5pr",
    "1p": "1p",
    "2p": "2p",
    "3p": "3p",
    "4p": "4p",
    "5p": "5p",
    "6p": "6p",
    "7p": "7p",
    "8p": "8p",
    "9p": "9p",
    "0s": "5sr",
    "1s": "1s",
    "2s": "2s",
    "3s": "3s",
    "4s": "4s",
    "5s": "5s",
    "6s": "6s",
    "7s": "7s",
    "8s": "8s",
    "9s": "9s",
    "1z": "E",
    "2z": "S",
    "3z": "W",
    "4z": "N",
    "5z": "P",
    "6z": "F",
    "7z": "C",
}

BAKAZE = ["E", "S", "W", "N"]

OPERATION_CHI = 0
OPERATION_PON = 1
OPERATION_MINKAN = 2
OPERATION_KAKAN = 2
OPERATION_ANKAN = 3


class MajsoulMjaiConversionError(RuntimeError):
    """Raised when a Mahjong Soul replay cannot be converted cleanly."""


@dataclass
class ConversionContext:
    dora_markers: list[str] = field(default_factory=list)
    pending_reach_actor: int | None = None
    last_discard_actor: int | None = None


def _to_mjai_tile(tile: str) -> str:
    if tile == "":
        return "?"
    try:
        return MS_TILE_TO_MJAI_TILE[tile]
    except KeyError as exc:
        raise MajsoulMjaiConversionError(f"unknown Mahjong Soul tile: {tile!r}") from exc


def _to_mjai_tiles(tiles: list[str]) -> list[str]:
    return [_to_mjai_tile(tile) for tile in tiles]


def _to_int_list(values: list[Any], *, expected: int | None = None) -> list[int]:
    ints = [int(value) for value in values]
    if expected is not None and len(ints) != expected:
        raise MajsoulMjaiConversionError(
            f"expected {expected} scores, got {len(ints)}: {ints!r}"
        )
    return ints


def _get_seat(item: dict[str, Any], fallback: int = 0) -> int:
    return int(item.get("seat", fallback))


def _accounts_with_inferred_seats(head: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    accounts = head.get("accounts", [])
    if len(accounts) != 4:
        raise MajsoulMjaiConversionError(
            f"only 4-player logs are supported for now, got {len(accounts)} players"
        )

    explicit_seats: set[int] = set()
    pending_accounts: list[dict[str, Any]] = []
    resolved: list[tuple[int, dict[str, Any]]] = []

    for account in accounts:
        if not isinstance(account, dict):
            continue
        if "seat" not in account:
            pending_accounts.append(account)
            continue
        seat = int(account["seat"])
        if not 0 <= seat < 4:
            raise MajsoulMjaiConversionError(f"invalid seat in head.accounts: {seat}")
        explicit_seats.add(seat)
        resolved.append((seat, account))

    missing_seats = [seat for seat in range(4) if seat not in explicit_seats]
    if len(missing_seats) != len(pending_accounts):
        raise MajsoulMjaiConversionError(
            f"failed to infer seats from head.accounts: explicit={sorted(explicit_seats)}, "
            f"missing={missing_seats}, pending={len(pending_accounts)}"
        )

    for seat, account in zip(missing_seats, pending_accounts):
        resolved.append((seat, account))

    return resolved


def _account_names_from_head(head: dict[str, Any]) -> list[str]:
    names = ["", "", "", ""]
    for seat, account in _accounts_with_inferred_seats(head):
        names[seat] = str(account.get("nickname", ""))

    if any(name == "" for name in names):
        raise MajsoulMjaiConversionError(f"failed to infer player names from head: {names!r}")
    return names


def _head_to_start_game_event(head: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "start_game",
        "names": _account_names_from_head(head),
        "kyoku_first": 0,
        "aka_flag": True,
    }


def _extract_round_hands(result: dict[str, Any]) -> list[list[str]]:
    hands: list[list[str]] = []
    for seat in range(4):
        key = f"tiles{seat}"
        if key not in result:
            raise MajsoulMjaiConversionError(f"missing {key} in RecordNewRound")
        tiles = list(result[key])
        if len(tiles) not in (13, 14):
            raise MajsoulMjaiConversionError(
                f"{key} should contain 13 or 14 tiles, got {len(tiles)}"
            )
        hands.append(_to_mjai_tiles(tiles[:13]))
    return hands


def _append_pending_reach_accept(ctx: ConversionContext, events: list[dict[str, Any]]) -> None:
    if ctx.pending_reach_actor is None:
        return
    events.append({"type": "reach_accepted", "actor": ctx.pending_reach_actor})
    ctx.pending_reach_actor = None


def _append_new_dora_events(
    result: dict[str, Any],
    ctx: ConversionContext,
    events: list[dict[str, Any]],
) -> None:
    raw_doras = list(result.get("doras", []))
    if not raw_doras:
        return

    mjai_doras = _to_mjai_tiles(raw_doras)
    if len(mjai_doras) < len(ctx.dora_markers):
        ctx.dora_markers = mjai_doras
        return

    for marker in mjai_doras[len(ctx.dora_markers) :]:
        events.append({"type": "dora", "dora_marker": marker})
    ctx.dora_markers = mjai_doras


def _convert_record_new_round(
    result: dict[str, Any],
    ctx: ConversionContext,
    events: list[dict[str, Any]],
) -> None:
    doras = list(result.get("doras", []))
    if not doras:
        dora = result.get("dora")
        if not dora:
            raise MajsoulMjaiConversionError("RecordNewRound is missing dora markers")
        doras = [dora]

    hands = _extract_round_hands(result)
    scores = _to_int_list(list(result.get("scores", [])), expected=4)
    oya = int(result.get("ju", 0))
    if not 0 <= oya < 4:
        raise MajsoulMjaiConversionError(f"invalid dealer seat in RecordNewRound: {oya}")

    ctx.dora_markers = _to_mjai_tiles(doras)
    ctx.pending_reach_actor = None
    ctx.last_discard_actor = None

    events.append(
        {
            "type": "start_kyoku",
            "bakaze": BAKAZE[int(result.get("chang", 0))],
            "dora_marker": ctx.dora_markers[0],
            "kyoku": int(result.get("ju", 0)) + 1,
            "honba": int(result.get("ben", 0)),
            "kyotaku": int(result.get("liqibang", 0)),
            "oya": oya,
            "scores": scores,
            "tehais": hands,
        }
    )

    dealer_tiles = list(result.get(f"tiles{oya}", []))
    if len(dealer_tiles) == 14:
        events.append(
            {
                "type": "tsumo",
                "actor": oya,
                "pai": _to_mjai_tile(dealer_tiles[13]),
            }
        )


def _convert_record_deal_tile(
    result: dict[str, Any],
    ctx: ConversionContext,
    events: list[dict[str, Any]],
) -> None:
    _append_pending_reach_accept(ctx, events)
    _append_new_dora_events(result, ctx, events)

    actor = _get_seat(result)
    events.append(
        {
            "type": "tsumo",
            "actor": actor,
            "pai": _to_mjai_tile(str(result.get("tile", ""))),
        }
    )


def _convert_record_discard_tile(
    result: dict[str, Any],
    ctx: ConversionContext,
    events: list[dict[str, Any]],
) -> None:
    _append_pending_reach_accept(ctx, events)
    _append_new_dora_events(result, ctx, events)

    actor = _get_seat(result)
    is_reach = bool(result.get("is_liqi", False))

    if is_reach:
        events.append({"type": "reach", "actor": actor})

    events.append(
        {
            "type": "dahai",
            "actor": actor,
            "pai": _to_mjai_tile(str(result.get("tile", ""))),
            "tsumogiri": bool(result.get("moqie", False)),
        }
    )

    ctx.last_discard_actor = actor
    if is_reach:
        ctx.pending_reach_actor = actor


def _split_called_tiles(
    actor: int,
    tiles: list[str],
    froms: list[int],
) -> tuple[int, str, list[str]]:
    if len(tiles) != len(froms):
        raise MajsoulMjaiConversionError(
            f"RecordChiPengGang tiles/froms length mismatch: {len(tiles)} vs {len(froms)}"
        )

    target: int | None = None
    called_tile: str | None = None
    consumed: list[str] = []

    for tile, from_seat in zip(tiles, froms):
        if from_seat == actor:
            consumed.append(_to_mjai_tile(tile))
            continue
        target = int(from_seat)
        called_tile = _to_mjai_tile(tile)

    if target is None or called_tile is None:
        raise MajsoulMjaiConversionError(
            f"failed to infer target tile for call: actor={actor}, tiles={tiles!r}, froms={froms!r}"
        )
    return target, called_tile, consumed


def _convert_record_chi_peng_gang(
    result: dict[str, Any],
    ctx: ConversionContext,
    events: list[dict[str, Any]],
) -> None:
    _append_pending_reach_accept(ctx, events)
    _append_new_dora_events(result, ctx, events)

    actor = _get_seat(result)
    target, pai, consumed = _split_called_tiles(
        actor=actor,
        tiles=list(result.get("tiles", [])),
        froms=[int(seat) for seat in result.get("froms", [])],
    )

    op_type = int(result.get("type", OPERATION_CHI))
    if op_type == OPERATION_CHI:
        if len(consumed) != 2:
            raise MajsoulMjaiConversionError(f"chi should consume 2 tiles, got {consumed!r}")
        events.append(
            {
                "type": "chi",
                "actor": actor,
                "target": target,
                "pai": pai,
                "consumed": consumed,
            }
        )
        return

    if op_type == OPERATION_PON:
        if len(consumed) != 2:
            raise MajsoulMjaiConversionError(f"pon should consume 2 tiles, got {consumed!r}")
        events.append(
            {
                "type": "pon",
                "actor": actor,
                "target": target,
                "pai": pai,
                "consumed": consumed,
            }
        )
        return

    if op_type == OPERATION_MINKAN:
        if len(consumed) != 3:
            raise MajsoulMjaiConversionError(
                f"daiminkan should consume 3 tiles, got {consumed!r}"
            )
        events.append(
            {
                "type": "daiminkan",
                "actor": actor,
                "target": target,
                "pai": pai,
                "consumed": consumed,
            }
        )
        return

    raise MajsoulMjaiConversionError(f"unsupported RecordChiPengGang type: {op_type}")


def _ankan_consumed(pai: str) -> list[str]:
    base = pai.replace("r", "")
    consumed = [base, base, base, base]
    if pai.startswith("5") and not pai.endswith(("z",)):
        if pai.endswith("r"):
            consumed[0] = pai
    return consumed


def _kakan_consumed(pai: str) -> list[str]:
    base = pai.replace("r", "")
    consumed = [base, base, base]
    if pai.startswith("5") and not pai.endswith("r"):
        consumed[0] = base + "r"
    return consumed


def _convert_record_angang_addgang(
    result: dict[str, Any],
    ctx: ConversionContext,
    events: list[dict[str, Any]],
) -> None:
    _append_pending_reach_accept(ctx, events)
    _append_new_dora_events(result, ctx, events)

    actor = _get_seat(result)
    pai = _to_mjai_tile(str(result.get("tiles", "")))
    op_type = int(result.get("type", -1))

    if op_type == OPERATION_ANKAN:
        events.append(
            {
                "type": "ankan",
                "actor": actor,
                "consumed": _ankan_consumed(pai),
            }
        )
        return

    if op_type == OPERATION_KAKAN:
        events.append(
            {
                "type": "kakan",
                "actor": actor,
                "pai": pai,
                "consumed": _kakan_consumed(pai),
            }
        )
        return

    raise MajsoulMjaiConversionError(f"unsupported RecordAnGangAddGang type: {op_type}")


def _convert_record_hule(
    result: dict[str, Any],
    ctx: ConversionContext,
    events: list[dict[str, Any]],
) -> None:
    _append_pending_reach_accept(ctx, events)
    _append_new_dora_events(result, ctx, events)

    hules = list(result.get("hules", []))
    delta_scores = result.get("delta_scores")

    for index, hule in enumerate(hules):
        actor = _get_seat(hule)
        target = actor if bool(hule.get("zimo", False)) else ctx.last_discard_actor
        if target is None:
            raise MajsoulMjaiConversionError(
                f"cannot infer ron target for hule: {hule!r}"
            )

        event: dict[str, Any] = {
            "type": "hora",
            "actor": actor,
            "target": target,
        }

        if len(hules) == 1 and delta_scores:
            event["deltas"] = _to_int_list(list(delta_scores), expected=4)

        li_doras = list(hule.get("li_doras", []))
        if li_doras:
            event["ura_markers"] = _to_mjai_tiles(li_doras)

        events.append(event)

        # For multi-ron, later hora events should target the same last discard actor.
        if index == len(hules) - 1:
            ctx.last_discard_actor = None

    events.append({"type": "end_kyoku"})
    ctx.pending_reach_actor = None


def _convert_record_no_tile(
    result: dict[str, Any],
    ctx: ConversionContext,
    events: list[dict[str, Any]],
) -> None:
    _append_pending_reach_accept(ctx, events)

    score_entries = list(result.get("scores", []))
    deltas = None
    if score_entries:
        delta_scores = score_entries[0].get("delta_scores")
        if delta_scores:
            deltas = _to_int_list(list(delta_scores), expected=4)

    event: dict[str, Any] = {"type": "ryukyoku"}
    if deltas is not None:
        event["deltas"] = deltas
    events.append(event)
    events.append({"type": "end_kyoku"})

    ctx.pending_reach_actor = None
    ctx.last_discard_actor = None


def _convert_action_result(
    result: dict[str, Any],
    ctx: ConversionContext,
    events: list[dict[str, Any]],
) -> None:
    wrapper_type = result.get("_wrapper_type")
    if wrapper_type == "RecordNewRound":
        _convert_record_new_round(result, ctx, events)
        return
    if wrapper_type == "RecordDealTile":
        _convert_record_deal_tile(result, ctx, events)
        return
    if wrapper_type == "RecordDiscardTile":
        _convert_record_discard_tile(result, ctx, events)
        return
    if wrapper_type == "RecordChiPengGang":
        _convert_record_chi_peng_gang(result, ctx, events)
        return
    if wrapper_type == "RecordAnGangAddGang":
        _convert_record_angang_addgang(result, ctx, events)
        return
    if wrapper_type == "RecordHule":
        _convert_record_hule(result, ctx, events)
        return
    if wrapper_type == "RecordNoTile":
        _convert_record_no_tile(result, ctx, events)
        return
    raise MajsoulMjaiConversionError(f"unsupported record action type: {wrapper_type}")


def parse_res_game_record(record: pb.ResGameRecord) -> dict[str, Any]:
    """Convert a protobuf `ResGameRecord` into a parsed dict."""
    head = auto_parse_message_fields(record.head)
    detail = auto_parse_message_fields(parse_wrapper(record.data, pb.GameDetailRecords))
    return {"head": head, "data": detail}


def convert_parsed_record_to_mjai_events(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a parsed Mahjong Soul record dict into MJAI events."""
    head = record.get("head")
    detail = record.get("data")
    if not isinstance(head, dict) or not isinstance(detail, dict):
        raise MajsoulMjaiConversionError("record must contain dict head/data fields")

    actions = detail.get("actions", [])
    if not isinstance(actions, list) or not actions:
        raise MajsoulMjaiConversionError("parsed record does not contain any actions")

    ctx = ConversionContext()
    events: list[dict[str, Any]] = [_head_to_start_game_event(head)]

    for action in actions:
        if not isinstance(action, dict):
            continue
        result = action.get("result")
        if not isinstance(result, dict):
            continue
        _convert_action_result(result, ctx, events)

    events.append({"type": "end_game"})
    return events


def convert_record_to_mjai_events(record: pb.ResGameRecord | dict[str, Any]) -> list[dict[str, Any]]:
    """Convert either protobuf or parsed JSON record into MJAI events."""
    if isinstance(record, pb.ResGameRecord):
        record = parse_res_game_record(record)
    return convert_parsed_record_to_mjai_events(record)


__all__ = [
    "MajsoulMjaiConversionError",
    "MS_TILE_TO_MJAI_TILE",
    "convert_parsed_record_to_mjai_events",
    "convert_record_to_mjai_events",
    "parse_res_game_record",
]
