#!/usr/bin/env python3
"""
Manual test runner for majsoul_recent_paipu.py.

Examples:
    python test_recent_paipu_fetcher.py --access-token TOKEN --uid 12345678
    python test_recent_paipu_fetcher.py --token-file captured_token.json --eid 87654321 --count 5
    python test_recent_paipu_fetcher.py --token-file captured_token.json --username 某玩家 --count 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from majsoul_recent_paipu import (
    DEFAULT_CATEGORY,
    DEFAULT_COUNT,
    DEFAULT_TYPE,
    RecentPaipuError,
    fetch_recent_game_uuids,
)


DEFAULT_TOKEN_FILE = Path(__file__).resolve().with_name("captured_token.json")


def resolve_auth_inputs(args: argparse.Namespace) -> tuple[str, str]:
    if args.access_token:
        return args.access_token, args.server or "cn"

    token_file = args.token_file or DEFAULT_TOKEN_FILE
    if not token_file.exists():
        raise RecentPaipuError(
            f"token file not found: {token_file}. Use --access-token or run capture_access_token.py first."
        )

    try:
        payload = json.loads(token_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecentPaipuError(f"invalid token file json: {token_file}") from exc

    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise RecentPaipuError(f"token file missing access_token: {token_file}")

    server = args.server or str(payload.get("server") or "cn")
    return access_token, server


async def run_test(args: argparse.Namespace) -> int:
    from majsoul import MajsoulClient

    access_token, server = resolve_auth_inputs(args)
    client = MajsoulClient(server=server, request_timeout=args.request_timeout)

    try:
        await client.connect()
        await client.login(access_token)
        result = await fetch_recent_game_uuids(
            client,
            uid=args.uid,
            eid=args.eid,
            username=args.username,
            count=args.count,
            category=args.category,
            game_type=args.game_type,
            exact_match=not args.fuzzy,
            max_pages=args.max_pages,
        )
    finally:
        await client.close()

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test recent Majsoul paipu lookup against live APIs")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--uid", type=int, help="Lookup by account id")
    target.add_argument("--eid", type=int, help="Lookup by friend id / eid")
    target.add_argument("--username", type=str, help="Lookup by nickname")
    auth = parser.add_mutually_exclusive_group(required=False)
    auth.add_argument("--access-token", help="OAuth access token used for Majsoul login")
    auth.add_argument(
        "--token-file",
        type=Path,
        help="JSON file produced by capture_access_token.py; defaults to ./captured_token.json if present",
    )
    parser.add_argument("--server", default=None, help="Target server: cn/jp/en; defaults to token file server or cn")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="Requested recent UUID count")
    parser.add_argument("--category", type=int, default=DEFAULT_CATEGORY, help="fetchAccountInfoExtra category")
    parser.add_argument("--type", dest="game_type", type=int, default=DEFAULT_TYPE, help="fetchAccountInfoExtra type")
    parser.add_argument("--max-pages", type=int, default=5, help="Username search pagination limit")
    parser.add_argument("--request-timeout", type=float, default=30.0, help="Request timeout in seconds")
    parser.add_argument("--fuzzy", action="store_true", help="Allow non-exact username match if only one result remains")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return asyncio.run(run_test(args))
    except RecentPaipuError as exc:
        print(f"Lookup error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        error_type = type(exc).__name__
        if error_type == "AuthenticationError":
            print(f"Authentication error: {exc}", file=sys.stderr)
            return 1
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
