"""Authentication helpers shared by tools and future integrations."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Any, AsyncIterator

from majsoul import MajsoulClient


DEFAULT_TOKEN_FILE = Path(__file__).resolve().parent.parent / "captured_token.json"


class AuthInputError(RuntimeError):
    """Raised when access token inputs cannot be resolved cleanly."""


def load_token_payload(token_file: Path | str = DEFAULT_TOKEN_FILE) -> dict[str, Any]:
    path = Path(token_file)
    if not path.exists():
        raise AuthInputError(
            f"token file not found: {path}. Provide --access-token or run tools/capture_access_token.py first."
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthInputError(f"invalid token file json: {path}") from exc

    if not isinstance(payload, dict):
        raise AuthInputError(f"token file must contain a JSON object: {path}")
    return payload


def resolve_auth_inputs(
    *,
    access_token: str | None = None,
    token_file: Path | str | None = None,
    server: str | None = None,
) -> tuple[str, str]:
    if access_token:
        return str(access_token).strip(), server or "cn"

    payload = load_token_payload(token_file or DEFAULT_TOKEN_FILE)
    resolved_access_token = str(payload.get("access_token") or "").strip()
    if not resolved_access_token:
        raise AuthInputError(f"token file missing access_token: {token_file or DEFAULT_TOKEN_FILE}")

    resolved_server = server or str(payload.get("server") or "cn")
    return resolved_access_token, resolved_server


@asynccontextmanager
async def authenticated_client(
    *,
    access_token: str | None = None,
    token_file: Path | str | None = None,
    server: str | None = None,
    request_timeout: float = 30.0,
) -> AsyncIterator[MajsoulClient]:
    resolved_access_token, resolved_server = resolve_auth_inputs(
        access_token=access_token,
        token_file=token_file,
        server=server,
    )

    client = MajsoulClient(server=resolved_server, request_timeout=request_timeout)
    try:
        await client.connect()
        await client.login(resolved_access_token)
        yield client
    finally:
        await client.close()


__all__ = [
    "AuthInputError",
    "DEFAULT_TOKEN_FILE",
    "authenticated_client",
    "load_token_payload",
    "resolve_auth_inputs",
]
