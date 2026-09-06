"""Shared helpers for integration route tests."""

from __future__ import annotations

from podcast.config import Settings
from tests.conftest import InMemoryBlobStore

__all__ = ["make_settings", "make_store"]


def make_settings(**overrides: object) -> Settings:
    """Build a Settings instance with dummy secrets and overrides."""
    base: dict[str, object] = {
        "google_sa_json_b64": "ZHVtbXk=",
        "google_drive_folder_id": "folder-123",
        "blob_read_write_token": "tok",
        "blob_quota_mb": 500,
        "feed_secret_token": "feed-secret",
        "podcast_title": "Test Cast",
        "podcast_base_url": "https://test.example",
        "google_oauth_client_id": "cid",
        "google_oauth_client_secret": "csecret",
        "allowed_emails": "a@b.com",
        "session_secret_key": "test-secret-key-32-bytes-exactly!!",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def make_store() -> InMemoryBlobStore:
    """Return an empty InMemoryBlobStore."""
    return InMemoryBlobStore()
