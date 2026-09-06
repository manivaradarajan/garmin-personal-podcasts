"""Feed endpoint tests via TestClient with dependency overrides."""

from __future__ import annotations

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
