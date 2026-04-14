#!/usr/bin/env python3
"""Manual runner for recent Majsoul account rating review."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import sys
from pathlib import Path

from majsoul import AuthenticationError
from majsoul_auto_rating import (
    AuthInputError,
    FOUR_PLAYER_CATEGORY,
    DEFAULT_BOLTZMANN_EPSILON,
    DEFAULT_BOLTZMANN_TEMP,
    DEFAULT_GRP_MODEL,
    DEFAULT_MORTAL_MODEL,
    DEFAULT_MORTAL_VENDOR_DIR,
    DEFAULT_TOP_P,
    authenticated_client,
    fetch_and_review_recent_games,
    load_mortal_runtime,
)
from majsoul_auto_rating.recent_paipu import DEFAULT_TYPE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch and review a Majsoul user's recent ranked paipu")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--uid", type=int, help="Target account id")
    target.add_argument("--eid", type=int, help="Target friend id / eid")
    auth = parser.add_mutually_exclusive_group(required=False)
    auth.add_argument("--access-token", help="OAuth access token used for Majsoul login")
    auth.add_argument("--token-file", type=Path, help="JSON file produced by capture_access_token.py")
    parser.add_argument("--server", default=None, help="Target server: cn/jp/en")
    parser.add_argument("--count", type=int, default=20, help="Requested recent ranked paipu count")
    parser.add_argument("--type", dest="game_type", type=int, default=DEFAULT_TYPE, help="fetchAccountInfoExtra type")
    parser.add_argument("--request-timeout", type=float, default=30.0, help="Request timeout in seconds")
    parser.add_argument("--device", default="cpu", help="Torch device")
    parser.add_argument("--with-phi", action="store_true", help="Also compute GRP phi matrix for each game")
    parser.add_argument("--strict", action="store_true", help="Fail fast when any single paipu review fails")
    parser.add_argument("--mortal-vendor-dir", default=str(DEFAULT_MORTAL_VENDOR_DIR))
    parser.add_argument("--model", default=str(DEFAULT_MORTAL_MODEL))
    parser.add_argument("--grp-model", default=str(DEFAULT_GRP_MODEL))
    parser.add_argument("--boltzmann-epsilon", type=float, default=DEFAULT_BOLTZMANN_EPSILON)
    parser.add_argument("--boltzmann-temp", type=float, default=DEFAULT_BOLTZMANN_TEMP)
    parser.add_argument("--top-p", type=float, default=DEFAULT_TOP_P)
    return parser


async def run_query(args: argparse.Namespace) -> int:
    runtime = load_mortal_runtime(
        mortal_vendor_dir=args.mortal_vendor_dir,
        model_state_path=args.model,
        grp_state_path=args.grp_model,
        device=args.device,
        enable_quick_eval=False,
        load_grp=args.with_phi,
        boltzmann_epsilon=args.boltzmann_epsilon,
        boltzmann_temp=args.boltzmann_temp,
        top_p=args.top_p,
    )

    async with authenticated_client(
        access_token=args.access_token,
        token_file=args.token_file,
        server=args.server,
        request_timeout=args.request_timeout,
    ) as client:
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

    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
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
