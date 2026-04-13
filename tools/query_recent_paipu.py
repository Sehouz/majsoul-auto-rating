#!/usr/bin/env python3
"""Manual runner for recent Majsoul paipu lookup against live APIs."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from majsoul import AuthenticationError
from majsoul_auto_rating import AuthInputError, authenticated_client, fetch_recent_game_uuids
from majsoul_auto_rating.recent_paipu import DEFAULT_CATEGORY, DEFAULT_COUNT, DEFAULT_TYPE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query recent Majsoul paipu against live APIs")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--uid", type=int, help="Lookup by account id")
    target.add_argument("--eid", type=int, help="Lookup by friend id / eid")
    auth = parser.add_mutually_exclusive_group(required=False)
    auth.add_argument("--access-token", help="OAuth access token used for Majsoul login")
    auth.add_argument("--token-file", type=Path, help="JSON file produced by capture_access_token.py")
    parser.add_argument("--server", default=None, help="Target server: cn/jp/en")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Requested recent UUID count")
    parser.add_argument("--category", type=int, default=DEFAULT_CATEGORY, help="fetchAccountInfoExtra category")
    parser.add_argument("--type", dest="game_type", type=int, default=DEFAULT_TYPE, help="fetchAccountInfoExtra type")
    parser.add_argument("--request-timeout", type=float, default=30.0, help="Request timeout in seconds")
    return parser


async def run_query(args: argparse.Namespace) -> int:
    server = args.server
    async with authenticated_client(
        access_token=args.access_token,
        token_file=args.token_file,
        server=server,
        request_timeout=args.request_timeout,
    ) as client:
        server = client.server
        result = await fetch_recent_game_uuids(
            client,
            uid=args.uid,
            eid=args.eid,
            count=args.count,
            category=args.category,
            game_type=args.game_type,
        )

    account = result["account"]
    payload = {
        "account_id": account.account_id,
        "nickname": account.nickname,
        "server": server,
        "category": result["category"],
        "type": result["type"],
        "count": len(result["uuids"]),
        "uuids": result["uuids"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(run_query(args))
    except AuthInputError as exc:
        print(f"Auth input error: {exc}", file=sys.stderr)
        return 1
    except AuthenticationError as exc:
        print(f"Authentication error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
