"""Tests for _parse_drive_item() — pure."""

from __future__ import annotations

from podcast.drive.client import _parse_drive_item


def _item(**over: object) -> dict[str, object]:
    """Build a valid Drive item dict with overrides."""
    base: dict[str, object] = {
        "id": "fid",
        "name": "ep.mp3",
        "mimeType": "audio/mpeg",
        "md5Checksum": "abc",
        "size": "1234",
    }
    base.update(over)
    return base  # type: ignore[return-value]


def test_valid_item_returns_drive_file() -> None:
    """Complete dict parses to a DriveFile with all fields."""
    parsed = _parse_drive_item(_item())
    assert parsed is not None
    assert parsed.id == "fid" and parsed.size_bytes == 1234
    assert parsed.md5 == "abc"


def test_missing_id_returns_none() -> None:
    """Dict without id returns None."""
    item = _item()
    del item["id"]
    assert _parse_drive_item(item) is None


def test_missing_md5_returns_none() -> None:
    """Dict without md5Checksum returns None."""
    item = _item()
    del item["md5Checksum"]
    assert _parse_drive_item(item) is None


def test_non_numeric_size_returns_none() -> None:
    """Non-numeric size returns None."""
    assert _parse_drive_item(_item(size="not-a-number")) is None


def test_all_audio_mime_types_accepted() -> None:
    """Each allowlisted audio MIME type passes through."""
    for mime in (
        "audio/mpeg",
        "audio/mp4",
        "audio/ogg",
        "audio/wav",
        "audio/flac",
        "audio/aac",
        "audio/x-m4a",
    ):
        parsed = _parse_drive_item(_item(mimeType=mime))
        assert parsed is not None and parsed.mime_type == mime


def test_extra_fields_are_ignored() -> None:
    """Unexpected extra keys still yield a valid DriveFile."""
    parsed = _parse_drive_item(_item(extra="x", kind="drive#file"))
    assert parsed is not None and parsed.id == "fid"
