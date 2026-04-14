from __future__ import annotations

from datetime import UTC, datetime

from majsoul_auto_rating.publish import build_public_path, build_report_storage_key, build_viewer_url
from majsoul_auto_rating.publish_oss import AliyunOssConfig, AliyunOssPublisher


def test_build_report_storage_key_uses_short_hash_and_model_suffix() -> None:
    key = build_report_storage_key(
        uuid="260414-37ae1c1e-de1f-4413-894d-6b81a036e8b6",
        player_id=0,
        model_key_suffix="mortal-b40c256-onnx",
        prefix="report/majsoul",
        now=datetime(2026, 4, 14, tzinfo=UTC),
    )
    assert key.startswith("report/majsoul/2026-04-14/")
    assert key.endswith(".json")
    assert "mortal-b40c256-onnx" not in key


def test_build_public_path_and_viewer_url() -> None:
    key = "report/majsoul/2026-04-14/abc123_model.json"
    public_path = build_public_path(key)
    assert public_path == "/report/majsoul/2026-04-14/abc123_model.json"
    viewer_url = build_viewer_url(
        viewer_base_url="https://rabbitbot.selenaz.cn/killerducky/index.html",
        public_path=public_path,
    )
    assert (
        viewer_url
        == "https://rabbitbot.selenaz.cn/killerducky/index.html?data=/report/majsoul/2026-04-14/abc123_model.json"
    )


def test_aliyun_oss_publisher_sets_public_read_acl(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyBucket:
        def put_object(self, key, payload, headers):
            captured["key"] = key
            captured["payload"] = payload
            captured["headers"] = headers

    monkeypatch.setattr("majsoul_auto_rating.publish_oss._build_bucket", lambda _config: DummyBucket())
    publisher = AliyunOssPublisher(
        AliyunOssConfig(
            endpoint="https://oss-cn-hangzhou.aliyuncs.com",
            bucket_name="rabbitbot-report",
            access_key_id="id",
            access_key_secret="secret",
            public_base_url="https://rabbitbot.selenaz.cn",
        )
    )
    public_url = publisher.publish_json(
        key="report/majsoul/2026-04-14/demo.json",
        payload=b"{}",
        content_type="application/json; charset=utf-8",
    )
    assert public_url == "https://rabbitbot.selenaz.cn/report/majsoul/2026-04-14/demo.json"
    assert captured["headers"] == {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-cache",
        "x-oss-object-acl": "public-read",
    }
