"""Feed endpoint tests via TestClient with dependency overrides."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from app import app
from podcast.deps import get_blob_store, get_settings
from tests.integration.helpers import make_settings, make_store


def _client(settings, store) -> TestClient:
    """Build a TestClient with settings/store overrides."""
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_blob_store] = lambda: store
    client = TestClient(app, raise_server_exceptions=False)
    return client


def test_feed_returns_rss_xml_with_valid_token(sample_manifest_entry) -> None:
    """Correct token yields 200 with RSS content type."""
    settings = make_settings()
    store = make_store()
    store.write_manifest([sample_manifest_entry])
    client = _client(settings, store)
    try:
        resp = client.get("/api/feed", params={"token": "feed-secret"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "application/rss+xml" in resp.headers["content-type"]
    assert "<rss" in resp.text


def test_feed_returns_403_with_wrong_token() -> None:
    """Wrong token yields 403."""
    settings = make_settings()
    client = _client(settings, make_store())
    try:
        resp = client.get("/api/feed", params={"token": "nope"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_feed_returns_403_with_missing_token() -> None:
    """Missing token yields 403 (not 422)."""
    settings = make_settings()
    client = _client(settings, make_store())
    try:
        resp = client.get("/api/feed")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_feed_cache_control_no_store() -> None:
    """Feed response carries Cache-Control: no-store."""
    settings = make_settings()
    client = _client(settings, make_store())
    try:
        resp = client.get("/api/feed", params={"token": "feed-secret"})
    finally:
        app.dependency_overrides.clear()
    assert resp.headers.get("cache-control") == "no-store"


def test_feed_request_is_recorded() -> None:
    """A feed request appends a hit to the injected store."""
    from podcast.feed.hits import read_feed_hits

    settings = make_settings()
    store = make_store()
    client = _client(settings, store)
    try:
        client.get("/api/feed", params={"token": "feed-secret"})
    finally:
        app.dependency_overrides.clear()
    (hit,) = read_feed_hits(store)
    assert hit.status == 200


def test_feed_head_returns_headers_without_body() -> None:
    """HEAD yields feed headers and an empty body."""
    settings = make_settings()
    client = _client(settings, make_store())
    try:
        resp = client.request(
            "HEAD", "/api/feed", params={"token": "feed-secret"}
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.content == b""
    assert "content-length" in resp.headers
    assert "etag" in resp.headers
    assert "last-modified" in resp.headers


def test_feed_conditional_get_returns_304() -> None:
    """Matching If-None-Match yields 304 with validators."""
    settings = make_settings()
    client = _client(settings, make_store())
    try:
        first = client.get("/api/feed", params={"token": "feed-secret"})
        etag = first.headers["etag"]
        second = client.get(
            "/api/feed",
            params={"token": "feed-secret"},
            headers={"if-none-match": etag},
        )
    finally:
        app.dependency_overrides.clear()
    assert second.status_code == 304
    assert second.headers["etag"] == etag


def test_feed_get_carries_caching_headers() -> None:
    """GET responses include length, ETag, and Last-Modified."""
    settings = make_settings()
    client = _client(settings, make_store())
    try:
        resp = client.get("/api/feed", params={"token": "feed-secret"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert int(resp.headers["content-length"]) == len(resp.content)
    assert resp.headers["etag"].startswith('"')
    assert "last-modified" in resp.headers


def test_feed_self_link_uses_configured_base_url(sample_manifest_entry) -> None:
    """atom self link matches config, not the incoming request host."""
    settings = make_settings(podcast_base_url="https://canonical.test")
    store = make_store()
    store.write_manifest([sample_manifest_entry])
    client = _client(settings, store)
    try:
        resp = client.get(
            "/api/feed",
            params={"token": "feed-secret"},
            headers={"host": "other-host.test"},
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert (
        'href="https://canonical.test/api/feed?token=feed-secret"' in resp.text
    )


def test_feed_contains_guid_and_locked(sample_manifest_entry) -> None:
    """Live feed carries deterministic guid and owner lock."""
    settings = make_settings()
    store = make_store()
    store.write_manifest([sample_manifest_entry])
    client = _client(settings, store)
    try:
        first = client.get("/api/feed", params={"token": "feed-secret"})
        second = client.get("/api/feed", params={"token": "feed-secret"})
    finally:
        app.dependency_overrides.clear()
    assert first.status_code == 200
    ns = "{https://podcastindex.org/namespace/1.0}"
    channel = ET.fromstring(first.text).find("channel")
    assert channel is not None
    assert channel.find(f"{ns}guid") is not None
    assert channel.find(f"{ns}locked").get("owner") == "a@b.com"
    first_guid = channel.find(f"{ns}guid").text
    second_guid = (
        ET.fromstring(second.text).find("channel").find(f"{ns}guid").text
    )
    assert first_guid == second_guid


def test_podcast_alias_serves_identical_feed(sample_manifest_entry) -> None:
    """The /api/podcast alias serves the same feed with matching self link."""
    settings = make_settings()
    store = make_store()
    store.write_manifest([sample_manifest_entry])
    client = _client(settings, store)
    try:
        legacy = client.get("/api/feed", params={"token": "feed-secret"})
        alias = client.get("/api/podcast", params={"token": "feed-secret"})
    finally:
        app.dependency_overrides.clear()
    assert alias.status_code == 200
    assert alias.text == legacy.text.replace("/api/feed?", "/api/podcast?")
    assert (
        'href="https://test.example/api/podcast?token=feed-secret"'
        in alias.text
    )
