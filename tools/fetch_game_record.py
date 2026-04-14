#!/usr/bin/env python3
"""Fetch a Mahjong Soul game record and dump its parsed JSON form."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from majsoul import AuthenticationError
from majsoul_auto_rating import AuthInputError, authenticated_client, parse_res_game_record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch a Mahjong Soul game record and dump parsed JSON")
    auth = parser.add_mutually_exclusive_group(required=False)
    auth.add_argument("--access-token", help="OAuth access token used for Majsoul login")
    auth.add_argument("--token-file", type=Path, help="JSON file produced by capture_access_token.py")
    parser.add_argument("--server", default=None, help="Target server: cn/jp/en")
    parser.add_argument("--request-timeout", type=float, default=30.0, help="Request timeout in seconds")
    parser.add_argument("--uuid", required=True, help="Game UUID")
    parser.add_argument("--out", default="-", help="Output file path, or '-' for stdout")
    return parser


async def run_fetch(args: argparse.Namespace) -> int:
    async with authenticated_client(
        access_token=args.access_token,
        token_file=args.token_file,
        server=args.server,
        request_timeout=args.request_timeout,
    ) as client:
        record = await client.fetch_game_record(args.uuid)
    parsed = parse_res_game_record(record)
    payload = json.dumps(parsed, ensure_ascii=False)
    if args.out == "-":
        print(payload)
        return 0
    Path(args.out).write_text(payload, encoding="utf-8")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(run_fetch(args))
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
