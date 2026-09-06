"""Sync trigger and status endpoint tests via TestClient."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

from fastapi.testclient import TestClient

from app import app
from podcast.auth.session import create_session_cookie
from podcast.deps import get_blob_store, get_drive_client, get_settings
from podcast.models import DriveFile
from podcast.sync.engine import is_sync_locked
from tests.integration.helpers import make_settings, make_store


class _StubDrive:
    """Drive stub with controllable failure modes."""

    def __init__(self, mode: str = "ok") -> None:
        """Set mode: ok, boom."""
        self._mode = mode

    def list_audio_files(self) -> list[DriveFile]:
        """Return empty list or raise based on mode."""
        if self._mode == "boom":
            raise RuntimeError("drive down")
        return []

    def stream_file(self, file_id: str):  # type: ignore[no-untyped-def]
        """Yield canned bytes."""
        yield b"x"


def _authed_client(settings, store, drive) -> TestClient:
    """Build a TestClient with a valid session cookie set."""
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_blob_store] = lambda: store
    app.dependency_overrides[get_drive_client] = lambda: drive
    client = TestClient(app, raise_server_exceptions=False)
    cookie = create_session_cookie("a@b.com", settings.session_secret_key)
    client.cookies.set("session", cookie)
    return client


def _wait_until_idle(client: TestClient, timeout: float = 10.0) -> dict:
    """Poll the status endpoint until the run finishes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/api/sync/status").json()
        if not body.get("running"):
            return body
        time.sleep(0.05)
    raise TimeoutError("background sync did not finish in time")


def test_trigger_returns_immediately_with_started_flash() -> None:
    """Trigger redirects at once; the run completes in the background."""
    settings = make_settings()
    store = make_store()
    client = _authed_client(settings, store, _StubDrive())
    try:
        resp = client.post("/api/sync/trigger", follow_redirects=False)
        assert resp.status_code == 302
        assert unquote(resp.headers["location"]).startswith(
            "/?flash=Sync started"
        )
        body = _wait_until_idle(client)
    finally:
        app.dependency_overrides.clear()
    assert body.get("flash", "").startswith("Sync complete")
    assert not is_sync_locked(store)


def test_trigger_redirects_with_lock_held_flash() -> None:
    """Held lock redirects with an in-progress flash message."""
    settings = make_settings()
    store = make_store()
    stamp = datetime.now(UTC) - timedelta(seconds=10)
    store.write("sync.lock", stamp.isoformat().encode(), 0)
    client = _authed_client(settings, store, _StubDrive())
    try:
        resp = client.post("/api/sync/trigger", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 302
    assert "already+in+progress" in resp.headers["location"] or (
        "already in progress" in unquote(resp.headers["location"])
    )


def test_status_reports_error_flash_on_drive_failure() -> None:
    """Background Drive failure surfaces as an error flash in status."""
    settings = make_settings()
    store = make_store()
    client = _authed_client(settings, store, _StubDrive("boom"))
    try:
        resp = client.post("/api/sync/trigger", follow_redirects=False)
        assert resp.status_code == 302
        body = _wait_until_idle(client)
    finally:
        app.dependency_overrides.clear()
    assert "failed" in body.get("flash", "").lower()
    assert not is_sync_locked(store)


def test_status_idle_without_run() -> None:
    """Status without any run reports not running and no flash."""
    import podcast.web.sync_routes as sync_routes

    with sync_routes._state_lock:
        sync_routes._last_summary = None
        sync_routes._last_error = None
    settings = make_settings()
    client = _authed_client(settings, make_store(), _StubDrive())
    try:
        body = client.get("/api/sync/status").json()
    finally:
        app.dependency_overrides.clear()
    assert body == {"running": False}


def test_trigger_requires_auth_redirects_to_login() -> None:
    """Missing session cookie redirects toward the login page."""
    settings = make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_blob_store] = make_store
    app.dependency_overrides[get_drive_client] = lambda: _StubDrive()
    client = TestClient(app, raise_server_exceptions=False)
    try:
        resp = client.post("/api/sync/trigger", follow_redirects=False)
        status_resp = client.get("/api/sync/status", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code in (307, 401, 403)
    assert status_resp.status_code in (307, 401, 403)
