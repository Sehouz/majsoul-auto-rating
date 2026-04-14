from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Protocol


@dataclass(frozen=True)
class PublishedReport:
    key: str
    public_url: str
    viewer_url: str | None
    size: int


class ReportPublisher(Protocol):
    def publish_json(self, *, key: str, payload: bytes, content_type: str) -> str: ...


def build_report_storage_key(
    *,
    uuid: str,
    player_id: int,
    model_key_suffix: str,
    prefix: str = "report/majsoul",
    now: datetime | None = None,
) -> str:
    timestamp = now or datetime.now(UTC)
    date_part = timestamp.strftime("%Y-%m-%d")
    normalized_suffix = _model_suffix(model_key_suffix)
    digest = hashlib.sha256(f"{uuid}_{player_id}_{normalized_suffix}".encode("utf-8")).hexdigest()[:20]
    normalized_prefix = prefix.strip("/")
    filename = f"{digest}.json"
    return f"{normalized_prefix}/{date_part}/{filename}"


def publish_report_json(
    report: Any,
    *,
    uuid: str,
    player_id: int,
    model_key_suffix: str,
    publisher: ReportPublisher,
    prefix: str = "report/majsoul",
    viewer_base_url: str | None = None,
    public_path_prefix: str = "/",
    now: datetime | None = None,
) -> PublishedReport:
    payload = json.dumps(_to_jsonable(report), ensure_ascii=False).encode("utf-8")
    key = build_report_storage_key(
        uuid=uuid,
        player_id=player_id,
        model_key_suffix=model_key_suffix,
        prefix=prefix,
        now=now,
    )
    public_url = publisher.publish_json(key=key, payload=payload, content_type="application/json; charset=utf-8")
    viewer_url = build_viewer_url(viewer_base_url=viewer_base_url, public_path=build_public_path(key, public_path_prefix))
    return PublishedReport(key=key, public_url=public_url, viewer_url=viewer_url, size=len(payload))


def build_public_path(key: str, public_path_prefix: str = "/") -> str:
    prefix = public_path_prefix.rstrip("/") or ""
    normalized_key = key.lstrip("/")
    if not prefix:
        return f"/{normalized_key}"
    return f"{prefix}/{normalized_key}"


def build_viewer_url(*, viewer_base_url: str | None, public_path: str) -> str | None:
    if not viewer_base_url:
        return None
    separator = "&" if "?" in viewer_base_url else "?"
    return f"{viewer_base_url}{separator}data={public_path}"


def _model_suffix(model_tag: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in model_tag).strip("-")
    collapsed = "-".join(part for part in normalized.split("-") if part)
    return collapsed or "model"


def _to_jsonable(report: Any) -> Any:
    if hasattr(report, "__dataclass_fields__"):
        return asdict(report)
    return report


__all__ = [
    "PublishedReport",
    "ReportPublisher",
    "build_public_path",
    "build_report_storage_key",
    "build_viewer_url",
    "publish_report_json",
]
