#!/usr/bin/env python3
"""
Capture a Majsoul access token through a Playwright-driven browser session.

The user logs in manually. This script only inspects browser storage state,
extracts token candidates from local/session storage, and validates them by
trying oauth2Login.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


SERVER_URLS = {
    "cn": "https://game.maj-soul.com/1/",
    "jp": "https://game.mahjongsoul.com/",
    "en": "https://mahjongsoul.game.yo-star.com/",
}

CAPTURE_PREFIX = "__MS_CAPTURE__"
UUID_RE = re.compile(
    r"(?i)\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b"
)
ACCOUNT_RE = re.compile(r"(?i)(?:account[_-]?id|accountId)[^0-9]{0,16}(\d{6,12})")

CAPTURE_HOOK_JS = r"""
(() => {
  const prefix = "__MS_CAPTURE__";

  function emit(source, payload) {
    try {
      console.debug(prefix + JSON.stringify({ source, payload }));
    } catch (err) {
      console.debug(prefix + JSON.stringify({ source, payload: String(payload) }));
    }
  }

  function asText(value) {
    try {
      if (typeof value === "string") return value;
      if (value instanceof ArrayBuffer) return new TextDecoder().decode(new Uint8Array(value));
      if (value && value.buffer instanceof ArrayBuffer) {
        return new TextDecoder().decode(new Uint8Array(value.buffer));
      }
    } catch (err) {}
    return null;
  }

  function patchStorage(storage, name) {
    if (!storage) return;
    const originalSetItem = storage.setItem.bind(storage);
    storage.setItem = function(key, value) {
      emit(name + ".setItem", { key, value });
      return originalSetItem(key, value);
    };
  }

  patchStorage(window.localStorage, "localStorage");
  patchStorage(window.sessionStorage, "sessionStorage");

  const originalPushState = history.pushState.bind(history);
  history.pushState = function(...args) {
    const result = originalPushState(...args);
    emit("history.pushState", location.href);
    return result;
  };

  const originalReplaceState = history.replaceState.bind(history);
  history.replaceState = function(...args) {
    const result = originalReplaceState(...args);
    emit("history.replaceState", location.href);
    return result;
  };

  window.addEventListener("load", () => emit("window.load", location.href));
})();
"""


@dataclass
class CaptureState:
    server: str
    access_token: str | None = None
    account_id: int | None = None
    oauth_code: str | None = None
    oauth_uid: str | None = None
    sources: dict[str, str] = field(default_factory=dict)
    token_candidates: dict[str, set[str]] = field(default_factory=dict)
    rejected_candidates: dict[str, str] = field(default_factory=dict)

    def done(self) -> bool:
        return self.access_token is not None

    def add_token_candidate(self, token: str, source: str) -> None:
        normalized = token.lower()
        sources = self.token_candidates.setdefault(normalized, set())
        before = len(sources)
        sources.add(source)
        if before == 0:
            print(f"[*] Found token candidate from {source}: {normalized}")

    def set_validated_token(self, token: str, source: str) -> None:
        normalized = token.lower()
        if self.access_token == normalized:
            return
        self.access_token = normalized
        self.sources["access_token"] = source
        print(f"[+] Validated access_token from {source}")

    def set_account_id(self, account_id: int, source: str) -> None:
        if not self.account_id:
            self.account_id = account_id
            self.sources["account_id"] = source
            print(f"[*] Captured account_id={account_id} from {source}")

    def set_oauth_code(self, oauth_code: str, source: str) -> None:
        if not self.oauth_code:
            self.oauth_code = oauth_code
            self.sources["oauth_code"] = source
            print(f"[*] Captured oauth code from {source}")

    def set_oauth_uid(self, oauth_uid: str, source: str) -> None:
        if not self.oauth_uid:
            self.oauth_uid = oauth_uid
            self.sources["oauth_uid"] = source
            print(f"[*] Captured oauth uid={oauth_uid} from {source}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "access_token": self.access_token,
            "account_id": self.account_id,
            "oauth_code": self.oauth_code,
            "oauth_uid": self.oauth_uid,
            "sources": self.sources,
            "token_candidates": {
                token: sorted(sources) for token, sources in sorted(self.token_candidates.items())
            },
            "rejected_candidates": self.rejected_candidates,
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }


def try_parse_json(text: str) -> Any | None:
    text = text.strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def scan_storage_object(state: CaptureState, obj: Any, source: str, path: str = "") -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            next_path = f"{path}.{key}" if path else str(key)
            key_lower = str(key).lower()
            if key_lower in {"access_token", "accesstoken"} and isinstance(value, str):
                match = UUID_RE.search(value)
                if match:
                    state.add_token_candidate(match.group(1), f"{source}:{next_path}")
            elif key_lower in {"account_id", "accountid"}:
                try:
                    state.set_account_id(int(value), f"{source}:{next_path}")
                except (TypeError, ValueError):
                    pass
            elif key_lower == "token" and "oauth" in next_path.lower() and isinstance(value, str):
                match = UUID_RE.search(value)
                if match:
                    state.add_token_candidate(match.group(1), f"{source}:{next_path}")
            scan_storage_object(state, value, source, next_path)
        return

    if isinstance(obj, list):
        for index, value in enumerate(obj):
            scan_storage_object(state, value, source, f"{path}[{index}]")
        return

    if isinstance(obj, str):
        parsed = try_parse_json(obj)
        if parsed is not None:
            scan_storage_object(state, parsed, source, f"{path}<json>")
        account_match = ACCOUNT_RE.search(obj)
        if account_match:
            state.set_account_id(int(account_match.group(1)), f"{source}:{path or '<string>'}")
        for match in UUID_RE.finditer(obj):
            state.add_token_candidate(match.group(1), f"{source}:{path or '<string>'}")


def scan_navigation_text(state: CaptureState, text: str, source: str) -> None:
    if not text:
        return

    try:
        parsed_url = urlparse(text)
        if parsed_url.scheme and parsed_url.netloc:
            query = parse_qs(parsed_url.query)
            code = query.get("code", [None])[0]
            uid = query.get("uid", [None])[0]
            if isinstance(code, str) and code:
                state.set_oauth_code(code, source)
            if isinstance(uid, str) and uid:
                state.set_oauth_uid(uid, source)
    except Exception:
        pass

    account_match = ACCOUNT_RE.search(text)
    if account_match:
        state.set_account_id(int(account_match.group(1)), source)


async def validate_token_candidates(state: CaptureState, request_timeout: float = 10.0) -> None:
    unchecked = [
        token for token in state.token_candidates
        if token != state.access_token and token not in state.rejected_candidates
    ]
    if not unchecked:
        return

    try:
        from majsoul import AuthenticationError, MajsoulClient
    except Exception as exc:
        state.rejected_candidates["__import__"] = str(exc)
        return

    client = MajsoulClient(server=state.server, request_timeout=request_timeout)
    try:
        await client.connect()
        for token in unchecked:
            try:
                result = await client.login(token)
            except AuthenticationError as exc:
                state.rejected_candidates[token] = str(exc)
                continue
            except Exception as exc:
                state.rejected_candidates[token] = str(exc)
                continue

            account_id = int(getattr(result, "account_id", 0) or getattr(client, "account_id", 0) or 0)
            source = "validated:" + ", ".join(sorted(state.token_candidates.get(token, []))[:3])
            state.set_validated_token(token, source)
            if account_id:
                state.set_account_id(account_id, "oauth2Login")
            break
    finally:
        await client.close()


def validate_token_candidates_sync(state: CaptureState, request_timeout: float = 10.0) -> None:
    error: Exception | None = None

    def runner() -> None:
        nonlocal error
        try:
            asyncio.run(validate_token_candidates(state, request_timeout=request_timeout))
        except Exception as exc:
            error = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if error is not None:
        raise error


def scan_browser_state(state: CaptureState, snapshot: dict[str, Any]) -> None:
    scan_navigation_text(state, str(snapshot.get("url", "")), "page.url")
    scan_storage_object(state, snapshot.get("localStorage", {}), "localStorage")
    scan_storage_object(state, snapshot.get("sessionStorage", {}), "sessionStorage")


def poll_page_snapshot(page) -> dict[str, Any] | None:
    try:
        return page.evaluate(
            """() => ({
                url: location.href,
                localStorage: Object.fromEntries(
                    Array.from({ length: localStorage.length }, (_, i) => {
                        const key = localStorage.key(i);
                        return [key, localStorage.getItem(key)];
                    })
                ),
                sessionStorage: Object.fromEntries(
                    Array.from({ length: sessionStorage.length }, (_, i) => {
                        const key = sessionStorage.key(i);
                        return [key, sessionStorage.getItem(key)];
                    })
                ),
            })"""
        )
    except Exception:
        return None


def capture_access_token(
    *,
    server: str,
    output: Path | None,
    timeout_seconds: int,
    headless: bool,
) -> dict[str, Any] | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed. Install dependencies from requirements.txt first.") from exc

    if server not in SERVER_URLS:
        raise ValueError(f"invalid server: {server}")

    state = CaptureState(server=server)
    target_url = SERVER_URLS[server]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.add_init_script(CAPTURE_HOOK_JS)

        def on_console(msg) -> None:
            text = msg.text
            if not text.startswith(CAPTURE_PREFIX):
                return
            try:
                payload = json.loads(text[len(CAPTURE_PREFIX):])
            except json.JSONDecodeError:
                return

            source = str(payload.get("source", "console"))
            content = payload.get("payload")
            if not (source.startswith("localStorage") or source.startswith("sessionStorage")):
                if isinstance(content, str):
                    scan_navigation_text(state, content, f"console:{source}")
                return
            if isinstance(content, str):
                scan_storage_object(state, content, f"console:{source}")
                return
            if isinstance(content, dict):
                scan_storage_object(state, content, f"console:{source}")
                return
            scan_storage_object(state, str(content), f"console:{source}")

        page.on("console", on_console)

        print("=" * 60)
        print(f"Opening {target_url}")
        print("Login manually in the browser window.")
        print("Watching localStorage/sessionStorage for token candidates.")
        print(f"Waiting up to {timeout_seconds} seconds for capture and validation.")
        print("=" * 60)

        page.goto(target_url, wait_until="domcontentloaded")

        deadline = time.time() + timeout_seconds
        last_validation_at = 0.0
        while time.time() < deadline:
            snapshot = poll_page_snapshot(page)
            if snapshot is not None:
                scan_browser_state(state, snapshot)

            now = time.time()
            if state.token_candidates and now - last_validation_at >= 2.0 and not state.done():
                try:
                    validate_token_candidates_sync(state)
                except Exception as exc:
                    print(f"[*] Token validation failed: {exc}")
                last_validation_at = now

            if state.done():
                break
            page.wait_for_timeout(1000)

        if state.access_token:
            for _ in range(5):
                snapshot = poll_page_snapshot(page)
                if snapshot is not None:
                    scan_browser_state(state, snapshot)
                if state.account_id:
                    break
                page.wait_for_timeout(500)

        if not state.access_token and state.token_candidates:
            try:
                validate_token_candidates_sync(state)
            except Exception as exc:
                print(f"[*] Final token validation failed: {exc}")

        browser.close()

    result = state.as_dict() if state.access_token else None
    if result and output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a fresh Majsoul access token with Playwright")
    parser.add_argument("--server", choices=sorted(SERVER_URLS), default="cn", help="Target server")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path")
    parser.add_argument("--timeout", type=int, default=600, help="Capture timeout in seconds")
    parser.add_argument("--headless", action="store_true", help="Run Chromium headless")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        result = capture_access_token(
            server=args.server,
            output=args.output,
            timeout_seconds=args.timeout,
            headless=args.headless,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not result:
        print("No access token captured.", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output is not None:
        print(f"Saved to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
