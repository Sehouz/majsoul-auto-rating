#!/usr/bin/env python3
"""Live/manual runner for recent Majsoul account rating review."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import sys
from pathlib import Path

from majsoul_recent_paipu import DEFAULT_TYPE, RecentPaipuError
from majsoul_recent_rating import FOUR_PLAYER_CATEGORY, fetch_and_review_recent_games
from mortal_runtime import (
    DEFAULT_GRP_MODEL,
    DEFAULT_MORTAL_MODEL,
    DEFAULT_MORTAL_VENDOR_DIR,
    load_mortal_runtime,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch and review a Majsoul user's recent ranked paipu")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--uid", type=int, help="Target account id")
    target.add_argument("--eid", type=int, help="Target friend id / eid")
    auth = parser.add_mutually_exclusive_group(required=False)
    auth.add_argument("--access-token", help="OAuth access token used for Majsoul login")
    auth.add_argument(
        "--token-file",
        type=Path,
        help="JSON file produced by capture_access_token.py; defaults to ./captured_token.json if present",
    )
    parser.add_argument("--server", default=None, help="Target server: cn/jp/en; defaults to token file server or cn")
    parser.add_argument("--count", type=int, default=20, help="Requested recent ranked paipu count")
    parser.add_argument("--type", dest="game_type", type=int, default=DEFAULT_TYPE, help="fetchAccountInfoExtra type")
    parser.add_argument("--request-timeout", type=float, default=30.0, help="Request timeout in seconds")
    parser.add_argument("--device", default="cpu", help="Torch device")
    parser.add_argument("--with-phi", action="store_true", help="Also compute GRP phi matrix for each game")
    parser.add_argument("--strict", action="store_true", help="Fail fast when any single paipu review fails")
    parser.add_argument("--mortal-vendor-dir", default=str(DEFAULT_MORTAL_VENDOR_DIR))
    parser.add_argument("--model", default=str(DEFAULT_MORTAL_MODEL))
    parser.add_argument("--grp-model", default=str(DEFAULT_GRP_MODEL))
    return parser


async def run_test(args: argparse.Namespace) -> int:
    from majsoul import MajsoulClient

    access_token, server = resolve_auth_inputs(args)
    runtime = load_mortal_runtime(
        mortal_vendor_dir=args.mortal_vendor_dir,
        model_state_path=args.model,
        grp_state_path=args.grp_model,
        device=args.device,
        enable_quick_eval=False,
        load_grp=args.with_phi,
    )

    client = MajsoulClient(server=server, request_timeout=args.request_timeout)
    try:
        await client.connect()
        await client.login(access_token)
        summary = await fetch_and_review_recent_games(
            client,
            uid=args.uid,
            eid=args.eid,
            count=args.count,
            category=FOUR_PLAYER_CATEGORY,
            game_type=args.game_type,
            runtime=runtime,
            include_phi_matrix=args.with_phi,
            strict=args.strict,
        )
    finally:
        await client.close()

    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    args = build_parser().parse_args()
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
