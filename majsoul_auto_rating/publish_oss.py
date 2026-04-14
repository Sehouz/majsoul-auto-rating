from __future__ import annotations

from dataclasses import dataclass

from .publish import ReportPublisher


@dataclass(frozen=True)
class AliyunOssConfig:
    endpoint: str
    bucket_name: str
    access_key_id: str
    access_key_secret: str
    public_base_url: str


class AliyunOssPublisher(ReportPublisher):
    def __init__(self, config: AliyunOssConfig) -> None:
        self.config = config
        self._bucket = _build_bucket(config)

    def publish_json(self, *, key: str, payload: bytes, content_type: str) -> str:
        self._bucket.put_object(key, payload, headers=_json_headers(content_type))
        return f"{self.config.public_base_url.rstrip('/')}/{key.lstrip('/')}"


def _build_bucket(config: AliyunOssConfig):
    try:
        import oss2
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing Python dependency `oss2`. Install the oss extra first.") from exc

    auth = oss2.Auth(config.access_key_id, config.access_key_secret)
    return oss2.Bucket(auth, config.endpoint, config.bucket_name)


def _json_headers(content_type: str) -> dict[str, str]:
    return {
        "Content-Type": content_type,
        "Cache-Control": "no-cache",
        "x-oss-object-acl": "public-read",
    }


__all__ = ["AliyunOssConfig", "AliyunOssPublisher"]
