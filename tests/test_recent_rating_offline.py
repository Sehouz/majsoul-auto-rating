from __future__ import annotations

from majsoul_auto_rating import AccountCandidate, RecentGame, review_recent_games
from majsoul_auto_rating.review import MortalReviewResult


def build_record(*, account_id: int, nickname: str, game_index: int) -> dict:
    return {
        "head": {
            "accounts": [
                {"account_id": account_id, "seat": 0, "nickname": nickname},
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
                        "_wrapper_type": "RecordDiscardTile",
                        "seat": 0,
                        "tile": "1m",
                        "moqie": True,
                    }
                },
                {
                    "result": {
                        "_wrapper_type": "RecordNoTile",
                        "scores": [{"delta_scores": [game_index, 0, 0, -game_index]}],
                    }
                },
            ],
        },
    }


class FakeClient:
    def __init__(self, records: dict[str, dict]) -> None:
        self.server = "cn"
        self._records = records

    async def fetch_game_record(self, game_uuid: str) -> dict:
        return self._records[game_uuid]


def fake_reviewer(
    events: list[dict],
    *,
    player_id: int,
    runtime=None,
    include_phi_matrix: bool = False,
) -> MortalReviewResult:
    del runtime, include_phi_matrix
    ryukyoku_event = next(event for event in events if event["type"] == "ryukyoku")
    bonus = ryukyoku_event.get("deltas", [0])[0]
    assert player_id == 0

    if bonus == 1:
        rating = 0.81
        raw_score_sum = 9.0
        total_reviewed = 10
        total_matches = 8
    else:
        rating = 0.64
        raw_score_sum = 6.4
        total_reviewed = 10
        total_matches = 6

    return MortalReviewResult(
        total_reviewed=total_reviewed,
        total_matches=total_matches,
        raw_score_sum=raw_score_sum,
        rating=rating,
        rating_percent=rating * 100.0,
        model_tag="fake-mortal",
        temperature=1.0,
        phi_matrix=None,
        entries=[],
    )


async def test_review_recent_games_offline_summary() -> None:
    account = AccountCandidate(
        account_id=12345,
        nickname="Target",
        level_id=0,
        level_score=0,
        level3_id=0,
        level3_score=0,
        verified=0,
    )
    recent_games = [
        RecentGame(
            uuid="game-1",
            start_time=1700000001,
            end_time=1700000901,
            rank=1,
            final_point=51200,
            tag=2,
            sub_tag=1,
        ),
        RecentGame(
            uuid="game-2",
            start_time=1700001001,
            end_time=1700001901,
            rank=2,
            final_point=28400,
            tag=2,
            sub_tag=1,
        ),
    ]
    client = FakeClient(
        {
            "game-1": build_record(account_id=account.account_id, nickname=account.nickname, game_index=1),
            "game-2": build_record(account_id=account.account_id, nickname=account.nickname, game_index=2),
        }
    )

    summary = await review_recent_games(
        client,
        account=account,
        recent_games=recent_games,
        requested_count=20,
        reviewer=fake_reviewer,
    )

    assert summary.reviewed_game_count == 2
    assert summary.failed_game_count == 0
    assert summary.total_reviewed == 20
    assert summary.total_matches == 14
    assert abs(summary.average_rating - 0.725) < 1e-9
    assert abs(summary.average_rating_percent - 72.5) < 1e-9
    assert abs(summary.aggregate_rating - 0.5929) < 1e-9
    assert abs(summary.aggregate_rating_percent - 59.29) < 1e-9
    assert [game.player_id for game in summary.games] == [0, 0]
