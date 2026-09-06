"""Tests for ID3 tagging — pure, uses a committed MP3 fixture."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import mutagen

from podcast.audio.tags import ensure_id3_tags

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "untagged.mp3"


def _raw() -> bytes:
    """Read the untagged fixture bytes."""
    return _FIXTURE.read_bytes()


def test_untagged_mp3_gains_id3v2_tag() -> None:
    """Tagless MP3 gets an ID3v2 header with the episode title."""
    out = ensure_id3_tags(_raw(), "My Episode", "My Cast")
    assert out[:3] == b"ID3"
    assert mutagen.File(BytesIO(out))["TIT2"].text == ["My Episode"]


def test_tagging_preserves_audio() -> None:
    """Tagged output keeps the same audio length."""
    before = mutagen.File(BytesIO(_raw())).info.length
    after = mutagen.File(BytesIO(ensure_id3_tags(_raw(), "T", "A")))
    assert after.info.length == before


def test_tagging_sets_podcast_frames() -> None:
    """Album and genre frames mark the file as a podcast."""
    tags = mutagen.File(BytesIO(ensure_id3_tags(_raw(), "T", "My Cast")))
    assert tags["TALB"].text == ["My Cast"]
    assert "Podcast" in tags["TCON"].text


def test_already_tagged_bytes_pass_through() -> None:
    """Second run returns input byte-identical (idempotent)."""
    once = ensure_id3_tags(_raw(), "My Episode", "My Cast")
    assert ensure_id3_tags(once, "My Episode", "My Cast") == once


def test_non_audio_bytes_pass_through() -> None:
    """Non-MP3 bytes are returned unchanged."""
    assert ensure_id3_tags(b"not audio at all", "T", "A") == b"not audio at all"
    assert ensure_id3_tags(b"", "T", "A") == b""


def test_has_id3_title_detects_presence() -> None:
    """has_id3_title is False before tagging, True after."""
    from podcast.audio.tags import has_id3_title

    assert has_id3_title(_raw()) is False
    assert has_id3_title(ensure_id3_tags(_raw(), "T", "A")) is True


def test_has_id3_title_rejects_non_audio() -> None:
    """has_id3_title is False for non-audio and empty bytes."""
    from podcast.audio.tags import has_id3_title

    assert has_id3_title(b"not audio") is False
    assert has_id3_title(b"") is False
