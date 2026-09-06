"""Sync trigger endpoint tests via TestClient."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import app
from podcast.auth.session import create_session_cookie
from podcast.deps import get_blob_store, get_drive_client, get_settings
from podcast.models import DriveFile
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


def test_trigger_redirects_to_dashboard_with_flash() -> None:
    """Successful trigger redirects to / with a flash param."""
    settings = make_settings()
    client = _authed_client(settings, make_store(), _StubDrive())
    try:
        resp = client.post("/api/sync/trigger", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/?flash=")


def test_trigger_redirects_with_lock_held_flash() -> None:
    """Held lock redirects with an in-progress flash message."""
    from urllib.parse import unquote

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


def test_trigger_redirects_with_error_flash() -> None:
    """Sync exception redirects with a failure flash message."""
    from urllib.parse import unquote

    settings = make_settings()
    client = _authed_client(settings, make_store(), _StubDrive("boom"))
    try:
        resp = client.post("/api/sync/trigger", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 302
    assert "failed" in unquote(resp.headers["location"]).lower()


def test_trigger_requires_auth_redirects_to_login() -> None:
    """Missing session cookie redirects toward the login page."""
    settings = make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_blob_store] = make_store
    app.dependency_overrides[get_drive_client] = lambda: _StubDrive()
    client = TestClient(app, raise_server_exceptions=False)
    try:
        resp = client.post("/api/sync/trigger", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code in (307, 401, 403)
