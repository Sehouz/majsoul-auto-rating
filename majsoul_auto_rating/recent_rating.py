"""Fetch and review a Majsoul user's recent ranked paipu with embedded Mortal."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Sequence

from majsoul.proto import liqi_pb2 as pb
from .mjai import convert_parsed_record_to_mjai_events, parse_res_game_record
from .recent_paipu import (
    AccountCandidate,
    DEFAULT_TYPE,
    RecentGame,
    RecentPaipuError,
    RecentPaipuService,
)
from .review import MortalReviewResult, review_mjai_events
from .runtime import MortalRuntime


class RecentRatingError(RuntimeError):
    """Raised when a recent paipu batch cannot be reviewed cleanly."""


ReviewCallable = Callable[..., MortalReviewResult]
FOUR_PLAYER_CATEGORY = 1
FOUR_PLAYER_COUNT = 4


@dataclass(frozen=True)
class ReviewedGame:
    uuid: str
    start_time: int
    end_time: int
    rank: int
    final_point: int
    tag: int
    sub_tag: int
    player_id: int
    event_count: int
    total_reviewed: int
    total_matches: int
    raw_score_sum: float
    rating: float
    rating_percent: float
    model_tag: str


@dataclass(frozen=True)
class ReviewFailure:
    uuid: str
    error: str


@dataclass(frozen=True)
class RecentAccountReviewSummary:
    account_id: int
    nickname: str
    server: str
    category: int
    game_type: int
    requested_count: int
    fetched_count: int
    reviewed_game_count: int
    failed_game_count: int
    total_reviewed: int
    total_matches: int
    raw_score_sum: float
    average_rating: float
    average_rating_percent: float
    aggregate_rating: float
    aggregate_rating_percent: float
    model_tag: str | None
    games: list[ReviewedGame]
    failures: list[ReviewFailure]


def _head_accounts_with_inferred_seats(head: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    accounts = head.get("accounts", [])
    if not isinstance(accounts, list):
        raise RecentRatingError("record head.accounts is missing or invalid")
    if len(accounts) != FOUR_PLAYER_COUNT:
        raise RecentRatingError(f"expected 4-player record, got {len(accounts)} players")

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
        if seat not in range(FOUR_PLAYER_COUNT):
            raise RecentRatingError(f"resolved invalid seat={seat} from record head")
        explicit_seats.add(seat)
        resolved.append((seat, account))

    missing_seats = [seat for seat in range(FOUR_PLAYER_COUNT) if seat not in explicit_seats]
    if len(missing_seats) != len(pending_accounts):
        raise RecentRatingError(
            f"failed to infer seats from record head: explicit={sorted(explicit_seats)}, "
            f"missing={missing_seats}, pending={len(pending_accounts)}"
        )

    for seat, account in zip(missing_seats, pending_accounts):
        resolved.append((seat, account))

    return resolved


def _resolve_player_id(head: dict[str, Any], account_id: int) -> int:
    for player_id, account in _head_accounts_with_inferred_seats(head):
        if int(account.get("account_id", 0)) != int(account_id):
            continue
        return player_id

    raise RecentRatingError(f"target account_id={account_id} is not present in record head")


def _parse_record(record: pb.ResGameRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(record, dict):
        return record

    error = getattr(record, "error", None)
    if getattr(error, "code", 0):
        raise RecentRatingError(
            f"fetchGameRecord failed with error_code={int(getattr(error, 'code', 0))}"
        )
    if not getattr(record, "data", b""):
        data_url = str(getattr(record, "data_url", "") or "")
        if data_url:
            raise RecentRatingError(
                f"fetchGameRecord returned data_url instead of inline data, unsupported for now: {data_url}"
            )
        raise RecentRatingError("fetchGameRecord returned empty replay data")
    return parse_res_game_record(record)


def _review_single_game(
    *,
    game: RecentGame,
    record: pb.ResGameRecord | dict[str, Any],
    account_id: int,
    runtime: MortalRuntime | None,
    reviewer: ReviewCallable,
    include_phi_matrix: bool,
) -> ReviewedGame:
    parsed_record = _parse_record(record)
    player_id = _resolve_player_id(parsed_record["head"], account_id)
    events = convert_parsed_record_to_mjai_events(parsed_record)
    result = reviewer(
        events,
        player_id=player_id,
        runtime=runtime,
        include_phi_matrix=include_phi_matrix,
    )
    return ReviewedGame(
        uuid=game.uuid,
        start_time=game.start_time,
        end_time=game.end_time,
        rank=game.rank,
        final_point=game.final_point,
        tag=game.tag,
        sub_tag=game.sub_tag,
        player_id=player_id,
        event_count=len(events),
        total_reviewed=result.total_reviewed,
        total_matches=result.total_matches,
        raw_score_sum=result.raw_score_sum,
        rating=result.rating,
        rating_percent=result.rating_percent,
        model_tag=result.model_tag,
    )


def _build_summary(
    *,
    account: AccountCandidate,
    server: str,
    category: int,
    game_type: int,
    requested_count: int,
    fetched_count: int,
    games: Sequence[ReviewedGame],
    failures: Sequence[ReviewFailure],
) -> RecentAccountReviewSummary:
    total_reviewed = sum(game.total_reviewed for game in games)
    total_matches = sum(game.total_matches for game in games)
    raw_score_sum = sum(game.raw_score_sum for game in games)
    average_rating = (
        0.0 if not games else sum(game.rating for game in games) / len(games)
    )
    aggregate_rating = (
        0.0 if total_reviewed == 0 else math.pow(raw_score_sum / total_reviewed, 2)
    )

    model_tag = games[0].model_tag if games else None
    return RecentAccountReviewSummary(
        account_id=account.account_id,
        nickname=account.nickname,
        server=server,
        category=category,
        game_type=game_type,
        requested_count=requested_count,
        fetched_count=fetched_count,
        reviewed_game_count=len(games),
        failed_game_count=len(failures),
        total_reviewed=total_reviewed,
        total_matches=total_matches,
        raw_score_sum=raw_score_sum,
        average_rating=average_rating,
        average_rating_percent=average_rating * 100.0,
        aggregate_rating=aggregate_rating,
        aggregate_rating_percent=aggregate_rating * 100.0,
        model_tag=model_tag,
        games=list(games),
        failures=list(failures),
    )


async def review_recent_games(
    client: Any,
    *,
    account: AccountCandidate,
    recent_games: Sequence[RecentGame],
    category: int = FOUR_PLAYER_CATEGORY,
    game_type: int = DEFAULT_TYPE,
    requested_count: int | None = None,
    runtime: MortalRuntime | None = None,
    reviewer: ReviewCallable = review_mjai_events,
    include_phi_matrix: bool = False,
    strict: bool = False,
) -> RecentAccountReviewSummary:
    server = str(getattr(client, "server", "") or "")
    reviewed_games: list[ReviewedGame] = []
    failures: list[ReviewFailure] = []

    for game in recent_games:
        try:
            record = await client.fetch_game_record(game.uuid)
            reviewed_games.append(
                _review_single_game(
                    game=game,
                    record=record,
                    account_id=account.account_id,
                    runtime=runtime,
                    reviewer=reviewer,
                    include_phi_matrix=include_phi_matrix,
                )
            )
        except Exception as exc:
            if strict:
                raise RecentRatingError(f"failed to review game {game.uuid}: {exc}") from exc
            failures.append(ReviewFailure(uuid=game.uuid, error=str(exc)))

    return _build_summary(
        account=account,
        server=server,
        category=category,
        game_type=game_type,
        requested_count=len(recent_games) if requested_count is None else int(requested_count),
        fetched_count=len(recent_games),
        games=reviewed_games,
        failures=failures,
    )


async def fetch_and_review_recent_games(
    client: Any,
    *,
    uid: int | None = None,
    eid: int | None = None,
    count: int = 20,
    category: int = FOUR_PLAYER_CATEGORY,
    game_type: int = DEFAULT_TYPE,
    runtime: MortalRuntime | None = None,
    reviewer: ReviewCallable = review_mjai_events,
    include_phi_matrix: bool = False,
    strict: bool = False,
) -> RecentAccountReviewSummary:
    if uid is None and eid is None:
        raise RecentPaipuError("either uid or eid is required")

    service = RecentPaipuService(client)
    if uid is not None:
        account = await service.resolve_account_by_id(uid)
    else:
        account = await service.resolve_account_by_eid(int(eid))

    recent_games = await service.fetch_recent_games(
        account_id=account.account_id,
        category=category,
        game_type=game_type,
    )
    selected_games = recent_games[: max(0, int(count))]
    return await review_recent_games(
        client,
        account=account,
        recent_games=selected_games,
        category=category,
        game_type=game_type,
        requested_count=count,
        runtime=runtime,
        reviewer=reviewer,
        include_phi_matrix=include_phi_matrix,
        strict=strict,
    )


__all__ = [
    "RecentAccountReviewSummary",
    "RecentRatingError",
    "ReviewFailure",
    "ReviewedGame",
    "fetch_and_review_recent_games",
    "review_recent_games",
]
