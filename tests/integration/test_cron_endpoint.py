"""Cron endpoint tests via TestClient with dependency overrides."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import app
from podcast.deps import get_blob_store, get_drive_client, get_settings
from podcast.models import DriveFile
from tests.integration.helpers import make_settings, make_store


class _StubDrive:
    """Minimal stub exposing list_audio_files/stream_file."""

    def __init__(self, files: list[DriveFile] | None = None) -> None:
        """Store canned files."""
        self._files = files or []

    def list_audio_files(self) -> list[DriveFile]:
        """Return canned files."""
        return list(self._files)

    def stream_file(self, file_id: str):  # type: ignore[no-untyped-def]
        """Yield canned bytes."""
        yield b"bytes"


def _client(settings, store, drive) -> TestClient:
    """Build a TestClient with cron dependency overrides."""
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_blob_store] = lambda: store
    app.dependency_overrides[get_drive_client] = lambda: drive
    return TestClient(app, raise_server_exceptions=False)


def test_cron_returns_403_without_header() -> None:
    """Missing cron header yields 403."""
    settings = make_settings()
    client = _client(settings, make_store(), _StubDrive())
    try:
        resp = client.get("/api/cron/sync")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_cron_returns_409_when_lock_held() -> None:
    """Fresh lock yields 409 locked status."""
    settings = make_settings()
    store = make_store()
    stamp = datetime.now(UTC) - timedelta(seconds=10)
    store.write("sync.lock", stamp.isoformat().encode(), 0)
    client = _client(settings, store, _StubDrive())
    try:
        resp = client.get(
            "/api/cron/sync", headers={"x-vercel-cron-schedule": "*"}
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 409
    assert resp.json() == {"status": "locked"}


def test_cron_returns_sync_result_counts() -> None:
    """Successful sync yields 200 with result count keys."""
    settings = make_settings()
    store = make_store()
    drive = _StubDrive(
        [
            DriveFile(
                id="id-1",
                name="a.mp3",
                mime_type="audio/mpeg",
                size_bytes=5,
                md5="m",
            )
        ]
    )
    client = _client(settings, store, drive)
    try:
        resp = client.get(
            "/api/cron/sync", headers={"x-vercel-cron-schedule": "*"}
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["added"] == 1
    assert {"updated", "deleted", "unchanged", "errors"} <= set(body)
