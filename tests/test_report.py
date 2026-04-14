from __future__ import annotations

from dataclasses import asdict

from majsoul_auto_rating.report import build_reviewer_report
from majsoul_auto_rating.tenhou_raw import to_tenhou_raw_log


class FakeBot:
    def __init__(self, reactions: list[dict | None]) -> None:
        self._reactions = reactions
        self._index = 0

    def react(self, _line: str):
        reaction = self._reactions[self._index]
        self._index += 1
        return reaction


class FakeRuntime:
    def __init__(self, reactions: list[dict | None]) -> None:
        self.model_tag = "fake-mortal"
        self._reactions = reactions

    def create_bot(self, _player_id: int):
        return FakeBot(self._reactions)


def test_build_reviewer_report_minimal() -> None:
    events = [
        {"type": "start_game", "names": ["A", "B", "C", "D"], "kyoku_first": 0, "aka_flag": True},
        {
            "type": "start_kyoku",
            "bakaze": "E",
            "kyoku": 1,
            "honba": 0,
            "kyotaku": 0,
            "oya": 0,
            "scores": [25000, 25000, 25000, 25000],
            "dora_marker": "E",
            "tehais": [
                ["2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m", "1p", "2p", "3p", "4p", "5p"],
                ["1m"] * 13,
                ["2m"] * 13,
                ["3m"] * 13,
            ],
        },
        {"type": "tsumo", "actor": 0, "pai": "1m"},
        {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": True},
        {"type": "ryukyoku", "deltas": [0, 0, 0, 0]},
        {"type": "end_kyoku"},
        {"type": "end_game"},
    ]
    reactions = [
        None,
        None,
        {
            "type": "dahai",
            "actor": 0,
            "pai": "1m",
            "tsumogiri": True,
            "meta": {
                "mask_bits": (1 << 0) | (1 << 27),
                "q_values": [1.0, 0.25],
                "shanten": 2,
                "at_furiten": False,
            },
        },
        None,
        None,
        None,
        None,
    ]
    runtime = FakeRuntime(reactions)

    report = build_reviewer_report(
        events,
        player_id=0,
        runtime=runtime,
        temperature=0.1,
        loading_time_seconds=0.001,
        show_rating=False,
        version="test-version",
    )

    payload = asdict(report)
    assert payload["engine"] == "Mortal"
    assert payload["game_length"] == "Hanchan"
    assert payload["loading_time"] == "1ms"
    assert payload["show_rating"] is False
    assert payload["version"] == "test-version"
    review = payload["review"]
    assert review["model_tag"] == "fake-mortal"
    assert review["total_reviewed"] == 1
    assert review["total_matches"] == 1
    assert len(review["kyokus"]) == 1
    kyoku = review["kyokus"][0]
    assert kyoku["kyoku"] == 0
    assert kyoku["honba"] == 0
    assert kyoku["relative_scores"] == [25000, 25000, 25000, 25000]
    assert len(kyoku["end_status"]) == 1
    entry = kyoku["entries"][0]
    assert entry["junme"] == 1
    assert entry["tiles_left"] == 69
    assert entry["last_actor"] == 0
    assert entry["tile"] == "1m"
    assert entry["expected"] == {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": True}
    assert entry["actual"] == {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": True}
    assert entry["is_equal"] is True
    assert entry["actual_index"] == 0
    assert entry["state"]["tehai"][-1] == "1m"
    assert entry["state"]["fuuros"] == []
    assert len(entry["details"]) == 2
    assert entry["details"][0]["action"]["pai"] == "1m"
    assert entry["details"][0]["q_value"] == 1.0


def test_report_includes_gui_compat_fields_for_parsed_record() -> None:
    parsed_record = {
        "head": {
            "accounts": [
                {"account_id": 1, "seat": 0, "nickname": "A"},
                {"account_id": 2, "seat": 1, "nickname": "B"},
                {"account_id": 3, "seat": 2, "nickname": "C"},
                {"account_id": 4, "seat": 3, "nickname": "D"},
            ],
            "result": {"players": [{"seat": 0, "part_point_1": 25000, "total_point": 25000000}]},
            "config": {"mode": {"mode": 2}},
        },
        "data": {
            "actions": [
                {
                    "result": {
                        "_wrapper_type": "RecordNewRound",
                        "chang": 0,
                        "ju": 0,
                        "ben": 0,
                        "liqibang": 0,
                        "dora": "1z",
                        "scores": [25000, 25000, 25000, 25000],
                        "tiles0": ["1m"] * 14,
                        "tiles1": ["2m"] * 13,
                        "tiles2": ["3m"] * 13,
                        "tiles3": ["4m"] * 13,
                    }
                },
                {
                    "result": {
                        "_wrapper_type": "RecordDiscardTile",
                        "seat": 0,
                        "tile": "1m",
                        "moqie": True,
                    }
                },
                {
                    "result": {
                        "_wrapper_type": "RecordNoTile",
                        "scores": [{"delta_scores": [0, 0, 0, 0]}],
                    }
                },
            ]
        },
    }
    events = [
        {"type": "start_game", "names": ["A", "B", "C", "D"], "kyoku_first": 0, "aka_flag": True},
        {
            "type": "start_kyoku",
            "bakaze": "E",
            "kyoku": 1,
            "honba": 0,
            "kyotaku": 0,
            "oya": 0,
            "scores": [25000, 25000, 25000, 25000],
            "dora_marker": "E",
            "tehais": [["1m"] * 13, ["2m"] * 13, ["3m"] * 13, ["4m"] * 13],
        },
        {"type": "tsumo", "actor": 0, "pai": "1m"},
        {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": True},
        {"type": "ryukyoku", "deltas": [0, 0, 0, 0]},
        {"type": "end_kyoku"},
        {"type": "end_game"},
    ]
    reactions = [None, None, {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": True, "meta": {"mask_bits": (1 << 0) | (1 << 1), "q_values": [1.0, 0.0], "shanten": 1, "at_furiten": False}}, None, None, None, None]
    report = asdict(
        build_reviewer_report(
            events,
            player_id=0,
            runtime=FakeRuntime(reactions),
            parsed_record=parsed_record,
            lang="en",
            version="test-version",
        )
    )
    assert report["player_id"] == 0
    assert report["lang"] == "en"
    assert report["mjai_log"][0]["type"] == "start_game"
    assert len(report["split_logs"]) == 1
    split_log = report["split_logs"][0]
    assert split_log["name"] == ["A", "B", "C", "D"]
    assert "rule" in split_log
    raw_round = split_log["log"][0]
    assert len(raw_round) == 17
    assert raw_round[0] == [0, 0, 0]
    assert raw_round[1] == [25000, 25000, 25000, 25000]
    assert raw_round[16][0] == "流局"


def test_tenhou_raw_log_minimal_shape() -> None:
    parsed_record = {
        "head": {
            "accounts": [
                {"account_id": 1, "seat": 0, "nickname": "A"},
                {"account_id": 2, "seat": 1, "nickname": "B"},
                {"account_id": 3, "seat": 2, "nickname": "C"},
                {"account_id": 4, "seat": 3, "nickname": "D"},
            ],
            "result": {"players": []},
            "config": {"mode": {"mode": 2}},
        },
        "data": {
            "actions": [
                {
                    "result": {
                        "_wrapper_type": "RecordNewRound",
                        "chang": 0,
                        "ju": 0,
                        "ben": 0,
                        "liqibang": 0,
                        "dora": "1z",
                        "scores": [25000, 25000, 25000, 25000],
                        "tiles0": ["1m"] * 14,
                        "tiles1": ["2m"] * 13,
                        "tiles2": ["3m"] * 13,
                        "tiles3": ["4m"] * 13,
                    }
                },
                {
                    "result": {
                        "_wrapper_type": "RecordNoTile",
                        "scores": [{"delta_scores": [0, 0, 0, 0]}],
                    }
                },
            ]
        },
    }
    raw = to_tenhou_raw_log(parsed_record)
    assert raw["name"] == ["A", "B", "C", "D"]
    assert len(raw["log"]) == 1
    assert len(raw["log"][0]) == 17
