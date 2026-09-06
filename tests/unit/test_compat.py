"""Tests for Garmin compatibility checks — pure."""

from __future__ import annotations

from podcast.compat import check_compatibility
from podcast.models import ManifestEntry


def _entry(name: str = "ep.mp3", mime: str = "audio/mpeg") -> ManifestEntry:
    """Build a ManifestEntry with overridable name/mime."""
    return ManifestEntry(
        drive_file_id="fid",
        drive_md5="md5",
        blob_url="https://blob.test/ep",
        name=name,
        size_bytes=100,
        mime_type=mime,
        published_at="2026-09-05T12:00:00Z",
    )


def test_mp3_is_compatible() -> None:
    """Standard MP3 passes."""
    assert check_compatibility(_entry("ep.mp3", "audio/mpeg")) is None


def test_uppercase_mp3_mime_is_compatible() -> None:
    """Drive's audio/mp3 for uppercase .MP3 passes."""
    assert check_compatibility(_entry("EP.MP3", "audio/mp3")) is None


def test_m4a_mime_types_are_compatible() -> None:
    """M4A MIME variants pass (listed in the 970 manual)."""
    assert check_compatibility(_entry("ep.m4a", "audio/mp4")) is None
    assert check_compatibility(_entry("ep.m4a", "audio/x-m4a")) is None


def test_m4b_is_compatible() -> None:
    """Audiobook M4B passes."""
    assert check_compatibility(_entry("book.m4b", "audio/mp4")) is None


def test_ogg_is_incompatible() -> None:
    """OGG yields a reason mentioning the format."""
    reason = check_compatibility(_entry("ep.ogg", "audio/ogg"))
    assert reason is not None and "audio/ogg" in reason


def test_wav_flac_aac_are_incompatible() -> None:
    """WAV, FLAC, and raw AAC yield reasons."""
    for name, mime in (
        ("ep.wav", "audio/wav"),
        ("ep.flac", "audio/flac"),
        ("ep.aac", "audio/aac"),
    ):
        assert check_compatibility(_entry(name, mime)) is not None


def test_extension_fallback_covers_odd_mime() -> None:
    """Unknown MIME with an MP3 extension still passes."""
    assert (
        check_compatibility(_entry("ep.mp3", "application/octet-stream"))
        is None
    )


def test_unknown_mime_and_extension_is_incompatible() -> None:
    """Unknown MIME with unknown extension yields a reason."""
    reason = check_compatibility(_entry("ep.xyz", "audio/xyz"))
    assert reason is not None and "MP3" in reason


def test_reason_names_supported_formats() -> None:
    """Incompatibility reason tells the user what to convert to."""
    reason = check_compatibility(_entry("ep.ogg", "audio/ogg"))
    assert reason is not None
    assert "MP3" in reason and "M4A" in reason and "M4B" in reason
