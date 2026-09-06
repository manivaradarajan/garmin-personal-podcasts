"""Tests for Drive shortcut resolution — fake service, no network."""

from __future__ import annotations

import pytest

from podcast.drive.client import (
    _SHORTCUT_MIME_TYPE,
    DriveClient,
    DriveListError,
)


class _FakeCall:
    """Mimics googleapiclient's request object with .execute()."""

    def __init__(
        self,
        payload: dict | None = None,
        error: Exception | None = None,
        captured: dict | None = None,
        kwargs: dict | None = None,
    ) -> None:
        """Store a canned payload, error, and capture dict."""
        self._payload = payload or {}
        self._error = error
        self._captured = captured
        self._kwargs = kwargs or {}

    def execute(self) -> dict:
        """Return payload, record kwargs, or raise the canned error."""
        if self._captured is not None:
            self._captured.update(self._kwargs)
        if self._error is not None:
            raise self._error
        return dict(self._payload)


class _FakeFiles:
    """Mimics the Drive files() resource with scripted responses."""

    def __init__(
        self,
        pages: list[dict] | None = None,
        targets: dict[str, dict | Exception] | None = None,
        captured: dict | None = None,
    ) -> None:
        """Store paged listings and per-ID target responses."""
        self._pages = pages or []
        self._targets = targets or {}
        self._captured = captured if captured is not None else {}

    def list(self, **kwargs):
        """Return the next canned page, capturing kwargs."""
        self._captured["list"] = kwargs
        return _FakeCall(self._pages.pop(0) if self._pages else {})

    def get(self, **kwargs):
        """Return the canned target for fileId, capturing kwargs."""
        self._captured["get"] = kwargs
        outcome = self._targets.get(kwargs.get("fileId"), {})
        if isinstance(outcome, Exception):
            return _FakeCall(error=outcome)
        return _FakeCall(outcome)


class _FakeService:
    """Mimics the Drive service object."""

    def __init__(self, files: _FakeFiles) -> None:
        """Store the files resource."""
        self._files = files

    def files(self) -> _FakeFiles:
        """Return the files resource."""
        return self._files


def _client(
    pages: list[dict] | None = None,
    targets: dict[str, dict | Exception] | None = None,
    captured: dict | None = None,
) -> DriveClient:
    """Build a DriveClient with a fake service (no credentials)."""
    client = DriveClient.__new__(DriveClient)
    client._folder_id = "folder-123"
    client._service = _FakeService(
        _FakeFiles(pages=pages, targets=targets, captured=captured)
    )
    return client


def _audio_target(**over) -> dict:
    """Build a target metadata dict with overrides."""
    base: dict = {
        "id": "target-1",
        "name": "real.mp3",
        "mimeType": "audio/mpeg",
        "size": "1234",
        "md5Checksum": "abc",
        "trashed": False,
    }
    base.update(over)
    return base


def _shortcut(target_id: str = "target-1") -> dict:
    """Build a shortcut listing item."""
    return {
        "id": "shortcut-1",
        "name": "Link Name.mp3",
        "mimeType": _SHORTCUT_MIME_TYPE,
        "shortcutDetails": {
            "targetId": target_id,
            "targetMimeType": "audio/mpeg",
        },
    }


def test_audio_shortcut_resolves_to_target_content() -> None:
    """Shortcut yields DriveFile with shortcut id/name, target bytes meta."""
    client = _client(
        pages=[{"files": [_shortcut()]}],
        targets={"target-1": _audio_target()},
    )
    (found,) = client.list_audio_files()
    assert found.id == "shortcut-1"
    assert found.name == "Link Name.mp3"
    assert found.md5 == "abc" and found.size_bytes == 1234
    assert found.mime_type == "audio/mpeg"


def test_non_audio_target_is_skipped() -> None:
    """Shortcut to a doc yields no files."""
    client = _client(
        pages=[{"files": [_shortcut()]}],
        targets={"target-1": _audio_target(mimeType="application/pdf")},
    )
    assert client.list_audio_files() == []


def test_broken_target_is_skipped() -> None:
    """Unreadable target (unshared/deleted) yields no files, no raise."""
    client = _client(
        pages=[{"files": [_shortcut()]}],
        targets={"target-1": RuntimeError("not found")},
    )
    assert client.list_audio_files() == []


def test_trashed_target_is_skipped() -> None:
    """Trashed audio target yields no files."""
    client = _client(
        pages=[{"files": [_shortcut()]}],
        targets={"target-1": _audio_target(trashed=True)},
    )
    assert client.list_audio_files() == []


def test_shortcut_without_details_is_skipped() -> None:
    """Shortcut missing shortcutDetails yields no files."""
    item = {"id": "s", "name": "x", "mimeType": _SHORTCUT_MIME_TYPE}
    client = _client(pages=[{"files": [item]}])
    assert client.list_audio_files() == []


def test_query_includes_shortcut_mime_and_details() -> None:
    """Listing query covers shortcuts and requests target details."""
    captured: dict = {}
    _client(pages=[{"files": []}], captured=captured).list_audio_files()
    assert _SHORTCUT_MIME_TYPE in captured["list"]["q"]
    assert "shortcutDetails" in captured["list"]["fields"]


def test_target_id_for_shortcut_returns_target() -> None:
    """_target_id_for maps a shortcut ID to its target ID."""
    client = _client(
        targets={
            "shortcut-1": {
                "mimeType": _SHORTCUT_MIME_TYPE,
                "shortcutDetails": {"targetId": "target-1"},
            }
        }
    )
    assert client._target_id_for("shortcut-1") == "target-1"


def test_target_id_for_plain_file_returns_input() -> None:
    """_target_id_for passes regular file IDs through."""
    client = _client(targets={"file-1": {"mimeType": "audio/mpeg"}})
    assert client._target_id_for("file-1") == "file-1"


def test_page_failure_still_aborts_with_shortcuts() -> None:
    """A failing page raises DriveListError even with shortcut query."""
    client = _client(pages=[])

    def _boom(**kwargs):
        raise RuntimeError("down")

    client._service._files.list = _boom  # type: ignore[method-assign]
    with pytest.raises(DriveListError):
        client.list_audio_files()
