"""ID3 tagging for Garmin watch compatibility — pure functions, no I/O."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import mutagen
import mutagen.id3
import mutagen.mp3

__all__ = ["ensure_id3_tags", "has_id3_title"]

_LOG = logging.getLogger(__name__)


def ensure_id3_tags(
    data: bytes, title: str, album: str
) -> tuple[bytes, float | None]:
    """Prepend minimal ID3v2.3 tags to an untagged MP3.

    Garmin watches need ID3 metadata to list and categorise episodes;
    tagless files may merge into one entry or not display at all. The
    injected set mirrors what working podcast files carry: title,
    artist, album, genre, track number, and length. Files that already
    carry a title tag, and all non-MP3 content, pass through
    byte-identical.

    Args:
        data: Raw audio file bytes.
        title: Episode title (filename without extension).
        album: Podcast/album name for the TALB frame.

    Returns:
        Tuple of (possibly tagged bytes, audio duration in seconds or
        None when unknown). Input is returned unchanged when tagging is
        unnecessary or impossible.
    """
    if not _looks_like_mp3(data):
        return data, None
    try:
        audio = mutagen.File(BytesIO(data))
    except Exception as exc:
        _LOG.warning("Skipping ID3 tagging (unparseable): %s", exc)
        return data, None
    if audio is None or not isinstance(audio, mutagen.mp3.MP3):
        return data, None
    duration = _duration_sec(audio)
    if audio.tags is not None and _tags_complete(audio.tags):
        return data, duration
    try:
        tag = mutagen.id3.ID3()
        stem = Path(title).stem
        tag["TIT2"] = mutagen.id3.TIT2(
            encoding=_frame_encoding(stem), text=stem
        )
        tag["TPE1"] = mutagen.id3.TPE1(
            encoding=_frame_encoding(album), text=album
        )
        tag["TALB"] = mutagen.id3.TALB(
            encoding=_frame_encoding(album), text=album
        )
        tag["TCON"] = mutagen.id3.TCON(
            encoding=_frame_encoding("Podcast"), text="Podcast"
        )
        tag["TRCK"] = mutagen.id3.TRCK(encoding=_frame_encoding("1"), text="1")
        if duration is not None:
            length_ms = str(int(duration * 1000))
            tag["TLEN"] = mutagen.id3.TLEN(
                encoding=_frame_encoding(length_ms), text=length_ms
            )
        out = BytesIO()
        tag.save(out, v1=0, v2_version=3)
        v1_block = bytes(mutagen.id3.MakeID3v1(tag))
        return out.getvalue() + _strip_id3v2(data) + v1_block, duration
    except Exception as exc:
        _LOG.warning("Skipping ID3 tagging (failed): %s", exc)
        return data, duration


def _frame_encoding(text: str) -> int:
    """Choose the ID3v2.3 text encoding for a frame value.

    Latin-1 (0) is preferred: watch firmware parses it reliably,
    while UTF-16 frames are ignored by some players. UTF-8 does not
    exist in ID3v2.3, so non-Latin-1 text falls back to UTF-16 (1).

    Args:
        text: Frame text to encode.

    Returns:
        0 for Latin-1-encodable text, else 1.
    """
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        return 1
    return 0


def _tags_complete(tags: mutagen.id3.ID3) -> bool:
    """Return True if tags need no upgrade.

    Complete means the required frames are present and every text
    frame among them is Latin-1 encoded (the Garmin-readable form).

    Args:
        tags: Parsed ID3 tag set.

    Returns:
        True when tagging can be skipped.
    """
    for frame in ("TIT2", "TRCK", "TLEN"):
        if frame not in tags:
            return False
    for frame in ("TIT2", "TPE1", "TALB", "TCON", "TRCK", "TLEN"):
        existing = tags.get(frame)
        if existing is not None and getattr(existing, "encoding", 0) != 0:
            return False
    return True


def _duration_sec(audio: mutagen.mp3.MP3) -> float | None:
    """Extract audio duration in seconds, or None when unknown.

    Args:
        audio: Loaded MP3 object.

    Returns:
        Duration in seconds, or None if unavailable.
    """
    try:
        length = audio.info.length
    except Exception:
        return None
    return length if isinstance(length, (int, float)) else None


def has_id3_title(data: bytes) -> bool:
    """Return True if the bytes carry an ID3 title tag.

    Args:
        data: Raw audio file bytes to inspect.

    Returns:
        True when a TIT2 frame is present, False otherwise (including
        for unparseable content).
    """
    try:
        audio = mutagen.File(BytesIO(data))
    except Exception:
        return False
    return audio is not None and audio.tags is not None and "TIT2" in audio.tags


def _looks_like_mp3(data: bytes) -> bool:
    """Return True if bytes start with an ID3v2 header or MPEG sync.

    Args:
        data: Raw file bytes to inspect.

    Returns:
        True for probable MP3 content, False otherwise.
    """
    if len(data) < 2:
        return False
    if data[:3] == b"ID3":
        return True
    return data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def _strip_id3v2(data: bytes) -> bytes:
    """Remove a leading ID3v2 header, returning raw audio frames.

    Args:
        data: Raw audio file bytes, optionally with an ID3v2 header.

    Returns:
        Audio bytes without the leading ID3v2 tag.
    """
    if data[:3] == b"ID3" and len(data) > 10:
        size = (
            ((data[6] & 0x7F) << 21)
            | ((data[7] & 0x7F) << 14)
            | ((data[8] & 0x7F) << 7)
            | (data[9] & 0x7F)
        )
        return data[10 + size :]
    return data
