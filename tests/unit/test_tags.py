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


def test_injected_frames_are_latin1() -> None:
    """Injected ASCII frames use Latin-1, the Garmin-readable encoding."""
    from mutagen.id3 import Encoding

    out, _ = ensure_id3_tags(_raw(), "My Episode", "My Cast")
    tags = mutagen.File(BytesIO(out))
    for frame in ("TIT2", "TPE1", "TALB", "TCON", "TRCK", "TLEN"):
        assert tags[frame].encoding == Encoding.LATIN1, frame


def test_non_ascii_title_falls_back_to_utf16() -> None:
    """Non-Latin-1 text falls back to UTF-16 instead of failing."""
    from mutagen.id3 import Encoding

    out, _ = ensure_id3_tags(_raw(), "Épisode α", "My Cast")
    assert out[:3] == b"ID3"
    assert mutagen.File(BytesIO(out))["TIT2"].encoding == Encoding.UTF16


def test_id3v1_trailer_present() -> None:
    """Tagged output ends with an ID3v1 trailer for old parsers."""
    out, _ = ensure_id3_tags(_raw(), "My Episode", "My Cast")
    assert out[-128:-125] == b"TAG"


def test_utf16_input_upgrades_to_latin1() -> None:
    """UTF-16-framed input is rebuilt with Latin-1 frames."""
    from mutagen.id3 import ID3, Encoding

    tag = ID3()
    tag["TIT2"] = mutagen.id3.TIT2(encoding=1, text="T")
    tag["TRCK"] = mutagen.id3.TRCK(encoding=1, text="1")
    tag["TLEN"] = mutagen.id3.TLEN(encoding=1, text="1000")
    buf = BytesIO()
    tag.save(buf, v1=0, v2_version=3)
    partial = buf.getvalue() + _raw()[_raw().find(b"\xff\xfb") :]
    assert mutagen.File(BytesIO(partial))["TIT2"].encoding == Encoding.UTF16

    upgraded, _ = ensure_id3_tags(partial, "T", "A")
    assert mutagen.File(BytesIO(upgraded))["TIT2"].encoding == Encoding.LATIN1


def test_latin1_complete_file_passes_through() -> None:
    """Complete Latin-1 tag set returns byte-identical (preserve path)."""
    out, _ = ensure_id3_tags(_raw(), "My Episode", "My Cast")
    assert ensure_id3_tags(out, "My Episode", "My Cast")[0] == out


def test_tdrc_year_frame_injected_when_known() -> None:
    """Known year lands in a Latin-1 TDRC frame."""
    from mutagen.id3 import Encoding

    out, _ = ensure_id3_tags(_raw(), "T", "A", "2026")
    tag = mutagen.File(BytesIO(out))
    assert tag["TDRC"].encoding == Encoding.LATIN1
    assert str(tag["TDRC"].text[0]) == "2026"


def test_no_tdrc_when_year_unknown() -> None:
    """Missing year leaves no TDRC frame behind."""
    out, _ = ensure_id3_tags(_raw(), "T", "A")
    assert "TDRC" not in mutagen.File(BytesIO(out)).tags


def test_v1_genre_byte_is_other() -> None:
    """v1 trailer genre is 12 (Other), safe for old firmware tables."""
    out, _ = ensure_id3_tags(_raw(), "T", "A", "2026")
    assert out[-1] == 12


def test_show_frames_normalized_episode_frames_kept() -> None:
    """Creator show frames are overwritten; episode frames preserved."""
    import mutagen.id3

    tag = mutagen.id3.ID3()
    tag["TIT2"] = mutagen.id3.TIT2(encoding=0, text="Creator Title")
    tag["TPE1"] = mutagen.id3.TPE1(encoding=0, text="Artist")
    tag["TALB"] = mutagen.id3.TALB(encoding=0, text="Album")
    tag["TCON"] = mutagen.id3.TCON(encoding=0, text="genre")
    tag["TRCK"] = mutagen.id3.TRCK(encoding=0, text="3")
    tag["TLEN"] = mutagen.id3.TLEN(encoding=0, text="1000")
    buf = BytesIO()
    tag.save(buf, v1=0, v2_version=3)
    creator = buf.getvalue() + _raw()[_raw().find(b"\xff\xfb") :]

    out, _ = ensure_id3_tags(creator, "file.mp3", "My Cast", "2026")
    frames = mutagen.File(BytesIO(out))
    assert frames["TIT2"].text == ["Creator Title"]
    assert frames["TRCK"].text == ["3"]
    assert frames["TPE1"].text == ["My Cast"]
    assert frames["TALB"].text == ["My Cast"]
    assert frames["TCON"].text == ["Podcast"]


def test_normalized_output_is_stable() -> None:
    """A normalized file passes through byte-identical."""
    import mutagen.id3

    duration_ms = str(int(mutagen.File(BytesIO(_raw())).info.length * 1000))
    tag = mutagen.id3.ID3()
    tag["TIT2"] = mutagen.id3.TIT2(encoding=0, text="Creator Title")
    tag["TPE1"] = mutagen.id3.TPE1(encoding=0, text="My Cast")
    tag["TALB"] = mutagen.id3.TALB(encoding=0, text="My Cast")
    tag["TCON"] = mutagen.id3.TCON(encoding=0, text="Podcast")
    tag["TRCK"] = mutagen.id3.TRCK(encoding=0, text="3")
    tag["TLEN"] = mutagen.id3.TLEN(encoding=0, text=duration_ms)
    tag["TDRC"] = mutagen.id3.TDRC(encoding=0, text="2026")
    buf = BytesIO()
    tag.save(buf, v1=0, v2_version=3)
    complete = buf.getvalue() + _raw()[_raw().find(b"\xff\xfb") :]

    assert (
        ensure_id3_tags(complete, "file.mp3", "My Cast", "2026")[0] == complete
    )


def test_snapshot_lists_frames_with_encodings() -> None:
    """Snapshot maps frame IDs to text plus encoding names."""
    from podcast.audio.tags import snapshot_id3_tags

    out, _ = ensure_id3_tags(_raw(), "My Episode", "My Cast")
    snap = snapshot_id3_tags(out)
    assert snap["TIT2"] == "My Episode [LATIN1]"
    assert snap["TALB"] == "My Cast [LATIN1]"
    assert "TRCK" in snap and "TLEN" in snap and "TDRC" not in snap


def test_snapshot_empty_for_untagged_and_non_audio() -> None:
    """Tagless fixture shows only its encoder tag; non-audio is empty."""
    from podcast.audio.tags import snapshot_id3_tags

    snap = snapshot_id3_tags(_raw())
    assert "TIT2" not in snap
    assert snap["TSSE"].endswith("[UTF8]")
    assert snapshot_id3_tags(b"not audio") == {}
    assert snapshot_id3_tags(b"") == {}
