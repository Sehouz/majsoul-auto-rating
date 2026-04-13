from __future__ import annotations

from majsoul_auto_rating import convert_parsed_record_to_mjai_events


def test_convert_record_liuju_to_ryukyoku() -> None:
    record = {
        "head": {
            "accounts": [
                {"account_id": 12345, "seat": 0, "nickname": "Target"},
                {"account_id": 20001, "seat": 1, "nickname": "B"},
                {"account_id": 20002, "seat": 2, "nickname": "C"},
                {"account_id": 20003, "seat": 3, "nickname": "D"},
            ],
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
                        "_wrapper_type": "RecordLiuJu",
                        "type": 1,
                        "gameend": {"scores": [25000, 25000, 25000, 25000]},
                    }
                },
            ],
        },
    }

    events = convert_parsed_record_to_mjai_events(record)

    assert events[-3] == {"type": "ryukyoku", "deltas": [0, 0, 0, 0]}
    assert events[-2] == {"type": "end_kyoku"}
    assert events[-1] == {"type": "end_game"}
