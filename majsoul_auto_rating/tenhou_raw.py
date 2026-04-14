"""Minimal Mahjong Soul -> Tenhou raw log conversion for GUI compatibility."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TSUMOGIRI = 60
_TENSOUL_DATA: dict[str, Any] | None = None


def split_tenhou_raw_log_by_kyoku(raw_log: dict[str, Any]) -> list[dict[str, Any]]:
    parent = {key: value for key, value in raw_log.items() if key != "log"}
    return [{**parent, "log": [kyoku]} for kyoku in raw_log.get("log", [])]


def to_tenhou_raw_log(record: dict[str, Any]) -> dict[str, Any]:
    head = record["head"]
    detail = record["data"]
    actions = detail.get("actions", [])
    if len(head.get("accounts", [])) != 4:
        raise ValueError("only 4-player records are supported")

    log: list[list[Any]] = []
    current: _KyokuState | None = None
    finishers = {
        "RecordNoTile": _KyokuState.finish_no_tile,
        "RecordLiuJu": _KyokuState.finish_liuju,
        "RecordHule": _KyokuState.finish_hule,
    }
    updaters = {
        "RecordDealTile": _KyokuState.on_deal,
        "RecordDiscardTile": _KyokuState.on_discard,
        "RecordChiPengGang": _KyokuState.on_call,
        "RecordAnGangAddGang": _KyokuState.on_kan,
    }
    for action in actions:
        result = action.get("result")
        if not isinstance(result, dict):
            continue
        wrapper_type = result.get("_wrapper_type")
        if wrapper_type == "RecordNewRound":
            current = _KyokuState(result)
            continue
        if current is None:
            continue
        updater = updaters.get(wrapper_type)
        if updater is not None:
            updater(current, result)
            continue
        finisher = finishers.get(wrapper_type)
        if finisher is not None:
            log.append(finisher(current, result))
            current = None
            continue

    return {
        "ver": "2.3",
        "ref": str(head.get("uuid", "")),
        "log": log,
        "name": _account_names(head),
        "rule": _rule_info(head),
    }


class _KyokuState:
    def __init__(self, leaf: dict[str, Any]) -> None:
        self.round = _round_tuple(leaf)
        self.initscores = [int(value) for value in leaf.get("scores", [])]
        self.doras = _dora_list(leaf)
        self.draws: list[list[Any]] = [[], [], [], []]
        self.discards: list[list[Any]] = [[], [], [], []]
        self.haipais = [[_tm2t(tile) for tile in list(leaf[f"tiles{seat}"])[:13]] for seat in range(4)]
        self.dealer = int(leaf.get("ju", 0))
        self.popped_tile = None
        dealer_tiles = list(leaf.get(f"tiles{self.dealer}", []))
        if len(dealer_tiles) >= 14:
            self.popped_tile = _tm2t(dealer_tiles[13])
            self.draws[self.dealer].append(self.popped_tile)
        self.ldseat = -1
        self.priichi = False
        self.nriichi = 0
        self.nkan = 0

    def on_deal(self, leaf: dict[str, Any]) -> None:
        self._settle_pending_riichi()
        self._update_doras(leaf)
        seat = int(leaf.get("seat", 0))
        tile = _tm2t(str(leaf["tile"]))
        self.draws[seat].append(tile)

    def on_discard(self, leaf: dict[str, Any]) -> None:
        seat = int(leaf.get("seat", 0))
        tile = _tm2t(str(leaf["tile"]))
        tsumogiri = bool(leaf.get("moqie", False))
        symbol: Any = TSUMOGIRI if tsumogiri else tile
        if seat == self.dealer and not self.discards[seat] and self.popped_tile is not None and symbol == self.popped_tile:
            symbol = TSUMOGIRI
        if bool(leaf.get("is_liqi", False)):
            self.priichi = True
            symbol = f"r{symbol}"
        self.discards[seat].append(symbol)
        self.ldseat = seat
        self._update_doras(leaf)

    def on_call(self, leaf: dict[str, Any]) -> None:
        self._settle_pending_riichi()
        seat = int(leaf["seat"])
        op_type = int(leaf.get("type", 0))
        tiles = [_tm2t(tile) for tile in leaf.get("tiles", [])]
        if op_type == 0:
            self.draws[seat].append("c" + "".join(str(tile) for tile in [tiles[2], tiles[0], tiles[1]]))
            return
        if op_type == 1:
            idx = _relative_seating(seat, self.ldseat)
            worktiles = list(tiles)
            worktiles.insert(idx, f"p{worktiles.pop()}")
            self.draws[seat].append("".join(str(tile) for tile in worktiles))
            return
        if op_type == 2:
            idx = _relative_seating(seat, self.ldseat)
            worktiles = list(tiles)
            worktiles.insert(3 if idx == 2 else idx, f"m{worktiles.pop()}")
            self.draws[seat].append("".join(str(tile) for tile in worktiles))
            self.discards[seat].append(0)
            self.nkan += 1

    def on_kan(self, leaf: dict[str, Any]) -> None:
        seat = int(leaf["seat"])
        op_type = int(leaf["type"])
        tile = _tm2t(str(leaf["tiles"]))
        self.ldseat = seat
        if op_type == 3:
            self.discards[seat].append(f"{tile}{tile}{tile}a{tile}")
            self.nkan += 1
            return
        if op_type == 2:
            self.discards[seat].append(f"{tile}k{tile}{tile}{tile}")
            self.nkan += 1

    def finish_no_tile(self, leaf: dict[str, Any]) -> list[Any]:
        entry = self.dump([])
        entry.append(["流し満貫" if bool(leaf.get("liujumanguan", False)) else "流局", _combined_delta_scores(leaf)])
        return entry

    def finish_liuju(self, leaf: dict[str, Any]) -> list[Any]:
        entry = self.dump([])
        entry.append([_liuju_label(leaf, nriichi=self.nriichi, nkan=self.nkan)])
        return entry

    def finish_hule(self, leaf: dict[str, Any]) -> list[Any]:
        ura: list[int] = []
        agari: list[Any] = []
        is_head_bump = True
        hules = list(leaf.get("hules", []))
        outer_delta_scores = [int(value) for value in leaf.get("delta_scores", [])] if leaf.get("delta_scores") else None
        for index, hule in enumerate(hules):
            li_doras = hule.get("li_doras", []) or []
            if len(ura) < len(li_doras):
                ura = [_tm2t(tile) for tile in li_doras]
            hule_delta_scores = outer_delta_scores if len(hules) == 1 and index == 0 else None
            agari.extend(_parse_hule(hule, self, is_head_bump, hule_delta_scores))
            is_head_bump = False
        entry = self.dump(ura)
        entry.append(["和了", *agari])
        return entry

    def dump(self, uras: list[int]) -> list[Any]:
        entry: list[Any] = [self.round, self.initscores, self.doras, uras]
        for seat in range(4):
            entry.append(self.haipais[seat])
            entry.append(self.draws[seat])
            entry.append(self.discards[seat])
        return entry

    def _settle_pending_riichi(self) -> None:
        if not self.priichi:
            return
        self.priichi = False
        self.nriichi += 1

    def _update_doras(self, leaf: dict[str, Any]) -> None:
        doras = leaf.get("doras")
        if not doras or len(doras) <= len(self.doras):
            return
        self.doras = [_tm2t(tile) for tile in doras]


def _parse_hule(
    hule: dict[str, Any],
    kyoku: _KyokuState,
    is_head_bump: bool,
    delta_scores: list[int] | None,
) -> list[Any]:
    seat = int(hule["seat"])
    zimo = bool(hule.get("zimo", False))
    target = seat if zimo else kyoku.ldseat
    deltas = list(delta_scores or [])
    if not any(deltas):
        # Fallback to the outer head-bump score only when explicit deltas are not available.
        rp = 1000 * (kyoku.nriichi + kyoku.round[2]) if is_head_bump else 0
        hb = 100 * kyoku.round[1] if is_head_bump else 0
        if zimo:
            point_zimo_xian = int(hule.get("point_zimo_xian", 0))
            point_zimo_qin = int(hule.get("point_zimo_qin", 0))
            if bool(hule.get("qinjia", False)):
                deltas = [-(hb + point_zimo_xian) for _ in range(4)]
                deltas[seat] = rp + 3 * (hb + point_zimo_xian)
            else:
                deltas = [-(hb + point_zimo_xian) for _ in range(4)]
                deltas[seat] = rp + hb + point_zimo_qin + 2 * (hb + point_zimo_xian)
                deltas[kyoku.dealer] = -(hb + point_zimo_qin)
        else:
            point_rong = int(hule.get("point_rong", 0))
            deltas = [0, 0, 0, 0]
            deltas[seat] = rp + 3 * hb + point_rong
            deltas[target] = -(3 * hb + point_rong)

    yaku_strings = [_score_string(hule), *_fan_strings(hule)]
    return [deltas, [seat, target, seat, *yaku_strings]]


def _score_string(hule: dict[str, Any]) -> str:
    fu = int(hule.get("fu", 0))
    han = int(hule.get("count", 0))
    point = int(hule.get("point_rong", 0) or hule.get("point_zimo_qin", 0) or hule.get("point_zimo_xian", 0) or 0)
    return f"{fu}符{han}飜{point}点"


def _fan_strings(hule: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for fan in hule.get("fans", []) or []:
        if not isinstance(fan, dict):
            continue
        fan_id = fan.get("id")
        fan_val = fan.get("val")
        if fan_id is None:
            continue
        fan_name = _fan_name(fan_id)
        if fan_val in (None, 0):
            items.append(f"{fan_name}")
        else:
            items.append(f"{fan_name}({fan_val}飜)")
    return items


def _fan_name(fan_id: int) -> str:
    fan_map = _tensoul_data()["fan"]["fan"]["map_"]
    entry = fan_map.get(str(int(fan_id))) or {}
    return str(entry.get("name_jp") or f"役种{fan_id}")


def _account_names(head: dict[str, Any]) -> list[str]:
    names = ["AI", "AI", "AI", "AI"]
    for account in head.get("accounts", []):
        names[int(account.get("seat", 0))] = str(account.get("nickname", "AI"))
    return names


def _rule_display(head: dict[str, Any]) -> str:
    mode = int(((head.get("config") or {}).get("mode") or {}).get("mode", 2) or 2)
    if mode in {1, 11}:
        return "東喰赤"
    return "南喰赤"


def _rule_info(head: dict[str, Any]) -> dict[str, Any]:
    return {"disp": _rule_display(head), "aka": 1, "aka51": 1, "aka52": 1, "aka53": 1}


def _round_tuple(leaf: dict[str, Any]) -> list[int]:
    return [4 * int(leaf.get("chang", 0)) + int(leaf.get("ju", 0)), int(leaf.get("ben", 0)), int(leaf.get("liqibang", 0))]


def _dora_list(leaf: dict[str, Any]) -> list[int]:
    return [_tm2t(tile) for tile in (leaf.get("doras") or [leaf.get("dora")]) if tile]


def _combined_delta_scores(leaf: dict[str, Any]) -> list[int]:
    delta = [0, 0, 0, 0]
    scores = leaf.get("scores") or []
    if not scores or not scores[0].get("delta_scores"):
        return delta
    for score in scores:
        deltas = score.get("delta_scores", [])
        delta = [left + int(right) for left, right in zip(delta, deltas, strict=False)]
    return delta


def _liuju_label(leaf: dict[str, Any], *, nriichi: int, nkan: int) -> str:
    liuju_type = int(leaf.get("type", 0))
    if liuju_type == 1:
        return "九種九牌"
    if liuju_type == 2:
        return "四風連打"
    if nriichi >= 4:
        return "四家立直"
    if nkan >= 4:
        return "四開槓"
    return "三家和"


def _tm2t(tile: str) -> int:
    num = int(tile[0]) if tile[0].isdigit() else 0
    suit = {"m": 1, "p": 2, "s": 3, "z": 4}[tile[1]]
    if num == 0:
        return 50 + suit
    return 10 * suit + num


def _tensoul_data() -> dict[str, Any]:
    global _TENSOUL_DATA
    if _TENSOUL_DATA is None:
        data_path = Path("/Users/sehouz/ZLTV/tensoul/data.json")
        _TENSOUL_DATA = json.loads(data_path.read_text(encoding="utf-8"))
    return _TENSOUL_DATA


def _final_scores(head: dict[str, Any]) -> list[float]:
    scores = [0.0] * 8
    players = ((head.get("result") or {}).get("players") or [])
    for player in players:
        seat = int(player.get("seat", 0))
        scores[seat * 2] = float(player.get("part_point_1", 0))
        scores[seat * 2 + 1] = float(player.get("total_point", 0)) / 1000.0
    return scores


def _relative_seating(seat0: int, seat1: int) -> int:
    return (seat0 - seat1 + 3) % 4


__all__ = ["split_tenhou_raw_log_by_kyoku", "to_tenhou_raw_log"]
