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


def ensure_id3_tags(data: bytes, title: str, album: str) -> bytes:
    """Prepend minimal ID3v2.3 tags to an untagged MP3.

    Garmin watches need ID3 metadata to list and categorise episodes;
    tagless files may merge into one entry or not display at all. Files
    that already carry a title tag, and all non-MP3 content, pass
    through byte-identical.

    Args:
        data: Raw audio file bytes.
        title: Episode title (filename without extension).
        album: Podcast/album name for the TALB frame.

    Returns:
        Tagged bytes, or the input unchanged when tagging is
        unnecessary or impossible.
    """
    if not _looks_like_mp3(data):
        return data
    try:
        audio = mutagen.File(BytesIO(data))
    except Exception as exc:
        _LOG.warning("Skipping ID3 tagging (unparseable): %s", exc)
        return data
    if audio is None or not isinstance(audio, mutagen.mp3.MP3):
        return data
    if audio.tags is not None and "TIT2" in audio.tags:
        return data
    try:
        tag = mutagen.id3.ID3()
        stem = Path(title).stem
        tag["TIT2"] = mutagen.id3.TIT2(encoding=3, text=stem)
        tag["TPE1"] = mutagen.id3.TPE1(encoding=3, text=album)
        tag["TALB"] = mutagen.id3.TALB(encoding=3, text=album)
        tag["TCON"] = mutagen.id3.TCON(encoding=3, text="Podcast")
        out = BytesIO()
        tag.save(out, v1=0, v2_version=3)
        return out.getvalue() + _strip_id3v2(data)
    except Exception as exc:
        _LOG.warning("Skipping ID3 tagging (failed): %s", exc)
        return data


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
