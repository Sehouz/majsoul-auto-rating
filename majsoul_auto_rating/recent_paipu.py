"""
Recent Majsoul paipu UUID lookup helpers.

This module is intentionally narrow in scope:
- it does not read credential files
- it does not create or log in a client
- it only uses an already authenticated Majsoul client
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


DEFAULT_CATEGORY = 2
DEFAULT_TYPE = 1
DEFAULT_COUNT = 10


class RecentPaipuError(RuntimeError):
    """Base error for recent paipu lookup."""


class AccountResolutionError(RecentPaipuError):
    """Raised when a uid or eid cannot be resolved cleanly."""


@dataclass(frozen=True)
class AccountCandidate:
    account_id: int
    nickname: str
    level_id: int
    level_score: int
    level3_id: int
    level3_score: int
    verified: int


@dataclass(frozen=True)
class RecentGame:
    uuid: str
    start_time: int
    end_time: int
    rank: int
    final_point: int
    tag: int
    sub_tag: int


def _chunked(items: Iterable[int], size: int) -> Iterable[list[int]]:
    batch: list[int] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _level_tuple(level_obj) -> tuple[int, int]:
    if level_obj is None:
        return 0, 0
    return int(getattr(level_obj, "id", 0)), int(getattr(level_obj, "score", 0))


def _signed_int32(value: int) -> int:
    value = int(value)
    if value >= 2**31:
        return value - 2**32
    return value


def _pb():
    from majsoul.proto import liqi_pb2 as protobuf_module

    return protobuf_module


def _to_account_candidate(player) -> AccountCandidate:
    level_id, level_score = _level_tuple(getattr(player, "level", None))
    level3_id, level3_score = _level_tuple(getattr(player, "level3", None))
    return AccountCandidate(
        account_id=int(getattr(player, "account_id", 0)),
        nickname=str(getattr(player, "nickname", "")),
        level_id=level_id,
        level_score=level_score,
        level3_id=level3_id,
        level3_score=level3_score,
        verified=int(getattr(player, "verified", 0)),
    )


class RecentPaipuService:
    """Query recent paipu UUIDs from an already authenticated Majsoul client."""

    def __init__(self, client) -> None:
        self.client = client

    async def _fetch_multi_account_brief(self, account_ids: Iterable[int]) -> list[AccountCandidate]:
        normalized_ids = [int(account_id) for account_id in account_ids if int(account_id) > 0]
        if not normalized_ids:
            return []

        candidates: list[AccountCandidate] = []
        for batch in _chunked(normalized_ids, 50):
            req = _pb().ReqMultiAccountId()
            req.account_id_list.extend(batch)
            res = await self.client.call(".lq.Lobby.fetchMultiAccountBrief", req)
            candidates.extend(_to_account_candidate(player) for player in getattr(res, "players", []))
        return candidates

    async def resolve_account_by_id(self, account_id: int) -> AccountCandidate:
        req = _pb().ReqSearchAccountById()
        req.account_id = int(account_id)
        res = await self.client.call(".lq.Lobby.searchAccountById", req)
        player = res.player
        if not getattr(player, "account_id", 0):
            fallback = await self._fetch_multi_account_brief([account_id])
            if fallback:
                return fallback[0]
            raise AccountResolutionError(f"account id not found: {account_id}")
        return _to_account_candidate(player)

    async def resolve_account_by_eid(self, eid: int) -> AccountCandidate:
        req = _pb().ReqSearchAccountByEidLobby()
        req.eid = int(eid)
        res = await self.client.call(".lq.Lobby.searchAccountByEid", req)
        account_id = int(getattr(res, "account_id", 0) or 0)
        if not account_id:
            raise AccountResolutionError(f"eid not found: {eid}")
        return await self.resolve_account_by_id(account_id)

    async def fetch_recent_games(
        self,
        *,
        account_id: int,
        category: int = DEFAULT_CATEGORY,
        game_type: int = DEFAULT_TYPE,
    ) -> list[RecentGame]:
        req = _pb().ReqFetchAccountInfoExtra()
        req.account_id = int(account_id)
        req.category = int(category)
        req.type = int(game_type)
        res = await self.client.call(".lq.Lobby.fetchAccountInfoExtra", req)

        games: list[RecentGame] = []
        for game in getattr(res, "recent_games", []):
            uuid = str(getattr(game, "uuid", "")).strip()
            if not uuid:
                continue
            games.append(
                RecentGame(
                    uuid=uuid,
                    start_time=int(getattr(game, "start_time", 0)),
                    end_time=int(getattr(game, "end_time", 0)),
                    rank=int(getattr(game, "rank", 0)),
                    final_point=_signed_int32(getattr(game, "final_point", 0)),
                    tag=int(getattr(game, "tag", 0)),
                    sub_tag=int(getattr(game, "sub_tag", 0)),
                )
            )
        return games

    async def fetch_recent_game_uuids_by_uid(
        self,
        uid: int,
        *,
        count: int = DEFAULT_COUNT,
        category: int = DEFAULT_CATEGORY,
        game_type: int = DEFAULT_TYPE,
        validate_uid: bool = True,
    ) -> list[str]:
        if validate_uid:
            await self.resolve_account_by_id(uid)
        games = await self.fetch_recent_games(account_id=uid, category=category, game_type=game_type)
        games.reverse()
        return [game.uuid for game in games[: max(0, count)]]

    async def fetch_recent_game_uuids_by_eid(
        self,
        eid: int,
        *,
        count: int = DEFAULT_COUNT,
        category: int = DEFAULT_CATEGORY,
        game_type: int = DEFAULT_TYPE,
    ) -> tuple[AccountCandidate, list[str]]:
        account = await self.resolve_account_by_eid(eid)
        uuids = await self.fetch_recent_game_uuids_by_uid(
            account.account_id,
            count=count,
            category=category,
            game_type=game_type,
            validate_uid=False,
        )
        return account, uuids

async def fetch_recent_game_uuids(
    client,
    *,
    uid: Optional[int] = None,
    eid: Optional[int] = None,
    count: int = DEFAULT_COUNT,
    category: int = DEFAULT_CATEGORY,
    game_type: int = DEFAULT_TYPE,
) -> dict:
    if uid is None and eid is None:
        raise RecentPaipuError("either uid or eid is required")

    service = RecentPaipuService(client)
    if uid is not None:
        account = await service.resolve_account_by_id(uid)
        uuids = await service.fetch_recent_game_uuids_by_uid(
            uid,
            count=count,
            category=category,
            game_type=game_type,
            validate_uid=False,
        )
        return {
            "account": account,
            "uuids": uuids,
            "category": category,
            "type": game_type,
        }

    if eid is not None:
        account, uuids = await service.fetch_recent_game_uuids_by_eid(
            eid,
            count=count,
            category=category,
            game_type=game_type,
        )
        return {
            "account": account,
            "uuids": uuids,
            "category": category,
            "type": game_type,
        }


__all__ = [
    "AccountCandidate",
    "AccountResolutionError",
    "DEFAULT_CATEGORY",
    "DEFAULT_COUNT",
    "DEFAULT_TYPE",
    "RecentGame",
    "RecentPaipuError",
    "RecentPaipuService",
    "fetch_recent_game_uuids",
]
