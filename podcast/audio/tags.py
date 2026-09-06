"""ID3 tagging for Garmin watch compatibility — pure functions, no I/O."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import mutagen
import mutagen.id3
import mutagen.mp3

__all__ = ["ensure_id3_tags", "has_id3_title", "snapshot_id3_tags"]

_LOG = logging.getLogger(__name__)


def ensure_id3_tags(
    data: bytes, title: str, album: str, year: str | None = None
) -> tuple[bytes, float | None]:
    """Normalise ID3v2.3 tags so episodes group as one podcast.

    Show-level frames (artist, album, genre) are always set to the
    podcast values so every episode groups under one show on the
    watch. Episode-level frames (title, track, date, length) keep
    creator values when present and are filled in otherwise. Files
    already matching the desired set, and all non-MP3 content, pass
    through byte-identical.

    Args:
        data: Raw audio file bytes.
        title: Episode title fallback (filename without extension).
        album: Podcast name for artist/album frames.
        year: Four-digit year fallback for the TDRC frame, if known.

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
    existing = audio.tags
    desired = _desired_frames(existing, Path(title).stem, album, year, duration)
    if existing is not None and _frames_match(existing, desired):
        return data, duration
    try:
        tag = mutagen.id3.ID3()
        _apply_frames(tag, desired)
        out = BytesIO()
        tag.save(out, v1=0, v2_version=3)
        v1_block = bytearray(bytes(mutagen.id3.MakeID3v1(tag)))
        # Force genre 12 ("Other"): mutagen maps "Podcast" to an
        # extended-table id most firmware genre tables don't contain.
        v1_block[127] = 12
        return out.getvalue() + _strip_id3v2(data) + bytes(v1_block), duration
    except Exception as exc:
        _LOG.warning("Skipping ID3 tagging (failed): %s", exc)
        return data, duration


def _desired_frames(
    existing: mutagen.id3.ID3 | None,
    stem: str,
    album: str,
    year: str | None,
    duration: float | None,
) -> dict[str, str]:
    """Compute the wanted frame texts, preserving episode-level values.

    Args:
        existing: Current tag set, if any.
        stem: Episode title fallback.
        album: Podcast name for show-level frames.
        year: Year fallback for the date frame.
        duration: Audio duration in seconds, if known.

    Returns:
        Mapping of frame ID to desired text.
    """

    def _keep(frame: str, fallback: str | None) -> str | None:
        if existing is not None and frame in existing:
            return str(existing[frame].text[0])
        return fallback

    desired: dict[str, str | None] = {
        "TIT2": _keep("TIT2", stem),
        "TPE1": album,
        "TALB": album,
        "TCON": "Podcast",
        "TRCK": _keep("TRCK", "1"),
        "TDRC": _keep("TDRC", year),
        "TLEN": (
            str(int(duration * 1000))
            if duration is not None
            else _keep("TLEN", None)
        ),
    }
    return {k: v for k, v in desired.items() if v is not None}


def _frames_match(existing: mutagen.id3.ID3, desired: dict[str, str]) -> bool:
    """Return True if existing frames already equal the desired set.

    Args:
        existing: Current tag set.
        desired: Wanted frame texts from _desired_frames.

    Returns:
        True when every desired frame is present with equal Latin-1
        text, meaning a rebuild would be byte-equivalent.
    """
    for frame, text in desired.items():
        current = existing.get(frame)
        if current is None:
            return False
        if str(current.text[0]) != text:
            return False
        if getattr(current, "encoding", 0) != _frame_encoding(text):
            return False
    return True


def _apply_frames(tag: mutagen.id3.ID3, desired: dict[str, str]) -> None:
    """Populate a fresh ID3 tag with the desired frames.

    Args:
        tag: Empty ID3 tag to populate.
        desired: Wanted frame texts from _desired_frames.
    """
    makers = {
        "TIT2": mutagen.id3.TIT2,
        "TPE1": mutagen.id3.TPE1,
        "TALB": mutagen.id3.TALB,
        "TCON": mutagen.id3.TCON,
        "TRCK": mutagen.id3.TRCK,
        "TLEN": mutagen.id3.TLEN,
        "TDRC": mutagen.id3.TDRC,
    }
    for frame, text in desired.items():
        tag[frame] = makers[frame](encoding=_frame_encoding(text), text=text)


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


_MAX_SNAPSHOT_FRAMES = 24
_MAX_SNAPSHOT_CHARS = 120
_ENCODING_NAMES = {0: "LATIN1", 1: "UTF16", 2: "UTF16BE", 3: "UTF8"}


def snapshot_id3_tags(data: bytes) -> dict[str, str]:
    """Snapshot text ID3 frames for dashboard display.

    Args:
        data: Raw audio file bytes to inspect.

    Returns:
        Mapping of frame ID to "text [Encoding]", capped in count
        and length. Empty when no text frames exist or content is
        unparseable. Binary frames (e.g. APIC artwork) are skipped.
    """
    try:
        audio = mutagen.File(BytesIO(data))
    except Exception:
        return {}
    if audio is None or audio.tags is None:
        return {}
    snapshot: dict[str, str] = {}
    for frame_id in sorted(audio.tags.keys()):
        if len(snapshot) >= _MAX_SNAPSHOT_FRAMES:
            break
        frame = audio.tags[frame_id]
        text = getattr(frame, "text", None)
        if not text:
            continue
        enc_name = _ENCODING_NAMES.get(int(getattr(frame, "encoding", -1)), "?")
        value = str(text[0])[:_MAX_SNAPSHOT_CHARS]
        snapshot[str(frame_id)] = f"{value} [{enc_name}]"
    return snapshot
