"""Tests for ID3 tagging — pure, uses a committed MP3 fixture."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import mutagen

from podcast.audio.tags import ensure_id3_tags, has_id3_title

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "untagged.mp3"


def _raw() -> bytes:
    """Read the untagged fixture bytes."""
    return _FIXTURE.read_bytes()


def _tags(data: bytes):
    """Load ID3 tags from bytes."""
    return mutagen.File(BytesIO(data))


def test_untagged_mp3_gains_id3v2_tag() -> None:
    """Tagless MP3 gets an ID3v2 header with the episode title."""
    out, _ = ensure_id3_tags(_raw(), "My Episode", "My Cast")
    assert out[:3] == b"ID3"
    assert _tags(out)["TIT2"].text == ["My Episode"]


def test_tagging_sets_podcast_frames() -> None:
    """Album, genre, track, and length frames mark the file as a podcast."""
    out, duration = ensure_id3_tags(_raw(), "T", "My Cast")
    tags = _tags(out)
    assert tags["TALB"].text == ["My Cast"]
    assert "Podcast" in tags["TCON"].text
    assert tags["TRCK"].text == ["1"]
    assert duration is not None
    assert tags["TLEN"].text == [str(int(duration * 1000))]


def test_duration_matches_audio_length() -> None:
    """Returned duration matches the audio content length."""
    _, duration = ensure_id3_tags(_raw(), "T", "A")
    assert duration is not None
    assert abs(duration - _tags(_raw()).info.length) < 0.1


def test_tagging_preserves_audio() -> None:
    """Tagged output keeps the same audio length."""
    out, _ = ensure_id3_tags(_raw(), "T", "A")
    assert _tags(out).info.length == _tags(_raw()).info.length


def test_already_tagged_bytes_pass_through() -> None:
    """Second run returns input byte-identical (idempotent)."""
    once, _ = ensure_id3_tags(_raw(), "My Episode", "My Cast")
    assert ensure_id3_tags(once, "My Episode", "My Cast")[0] == once


def test_non_audio_bytes_pass_through() -> None:
    """Non-MP3 bytes are returned unchanged with unknown duration."""
    out, duration = ensure_id3_tags(b"not audio at all", "T", "A")
    assert out == b"not audio at all" and duration is None
    assert ensure_id3_tags(b"", "T", "A") == (b"", None)


def test_has_id3_title_detects_presence() -> None:
    """has_id3_title is False before tagging, True after."""
    assert has_id3_title(_raw()) is False
    out, _ = ensure_id3_tags(_raw(), "T", "A")
    assert has_id3_title(out) is True


def test_has_id3_title_rejects_non_audio() -> None:
    """has_id3_title is False for non-audio and empty bytes."""
    assert has_id3_title(b"not audio") is False
    assert has_id3_title(b"") is False


def test_partial_tags_are_upgraded() -> None:
    """TIT2-only file gains the missing track/length frames."""
    import mutagen.id3

    out, _ = ensure_id3_tags(_raw(), "T", "A")
    tag = mutagen.id3.ID3(BytesIO(out))
    del tag["TRCK"]
    del tag["TLEN"]
    buf = BytesIO()
    tag.save(buf, v1=0, v2_version=3)
    partial = buf.getvalue() + out[out.find(b"\xff\xfb") :]

    upgraded, _ = ensure_id3_tags(partial, "T", "A")
    frames = mutagen.File(BytesIO(upgraded))
    assert "TRCK" in frames.tags and "TLEN" in frames.tags
    assert frames["TIT2"].text == ["T"]
