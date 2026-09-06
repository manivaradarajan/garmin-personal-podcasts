"""Shared fixtures for podcast tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from podcast.models import DriveFile, ManifestEntry

__all__ = [
    "InMemoryBlobStore",
    "secret_key",
    "sample_drive_file",
    "sample_manifest_entry",
]


@pytest.fixture
def secret_key() -> str:
    """Return a fixed secret key for signing tests."""
    return "test-secret-key-32-bytes-exactly!!"


@pytest.fixture
def sample_drive_file() -> DriveFile:
    """Return a sample DriveFile for tests."""
    return DriveFile(
        id="drive-id-1",
        name="ep1.mp3",
        mime_type="audio/mpeg",
        size_bytes=1_000_000,
        md5="abc123",
    )


@pytest.fixture
def sample_manifest_entry() -> ManifestEntry:
    """Return a sample ManifestEntry for tests."""
    return ManifestEntry(
        drive_file_id="drive-id-1",
        drive_md5="abc123",
        blob_url="https://blob.example.com/ep1.mp3",
        name="ep1.mp3",
        size_bytes=1_000_000,
        mime_type="audio/mpeg",
        published_at="2026-09-05T12:00:00Z",
    )


class InMemoryBlobStore:
    """In-memory BlobStore for tests — no network, deterministic."""

    def __init__(self) -> None:
        """Initialise empty backing dicts."""
        self._blobs: dict[str, bytes] = {}
        self._urls: dict[str, str] = {}

    def upload(
        self,
        path: str,
        data: bytes | Iterator[bytes],
        mime_type: str,
        cache_max_age: int,
    ) -> str:
        """Store bytes under path and return a fake public URL."""
        if not isinstance(data, bytes):
            data = b"".join(data)
        self._blobs[path] = data
        url = f"https://blob.test/{path}"
        self._urls[path] = url
        return url

    def delete(self, url: str) -> None:
        """Delete by URL; unknown URLs are a no-op (already gone)."""
        for path, known_url in list(self._urls.items()):
            if known_url == url:
                del self._urls[path]
                del self._blobs[path]
                return

    def read(self, path: str, use_cache: bool = True) -> bytes | None:
        """Return stored bytes or None if absent."""
        return self._blobs.get(path)

    def write(self, path: str, data: bytes, cache_max_age: int) -> None:
        """Overwrite stored bytes at path."""
        self._blobs[path] = data

    def read_manifest(self) -> list[ManifestEntry]:
        """Deserialise the manifest; return [] on any problem."""
        raw = self.read("manifest.json", use_cache=False)
        if raw is None:
            return []
        try:
            payload = json.loads(raw)
            return [ManifestEntry(**e) for e in payload.get("entries", [])]
        except json.JSONDecodeError, TypeError, KeyError, AttributeError:
            return []

    def write_manifest(self, entries: list[ManifestEntry]) -> None:
        """Serialise entries with an updated_at timestamp."""
        from dataclasses import asdict

        payload = {
            "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entries": [asdict(e) for e in entries],
        }
        self.write("manifest.json", json.dumps(payload, indent=2).encode(), 60)
