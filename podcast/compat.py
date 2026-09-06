"""Garmin watch audio compatibility checks — pure functions, no I/O."""

from __future__ import annotations

from pathlib import Path

from podcast.models import ManifestEntry

__all__ = [
    "GARMIN_COMPATIBLE_EXTENSIONS",
    "GARMIN_COMPATIBLE_MIME_TYPES",
    "check_compatibility",
]

# Sources: Garmin support "Audio File Type Support for Garmin Music
# Watches" (mp3, m4b) and the Forerunner 970 manual, which additionally
# lists .m4a as loadable personal audio content.
GARMIN_COMPATIBLE_MIME_TYPES = frozenset(
    {
        "audio/mpeg",  # .mp3
        "audio/mp3",  # uppercase .MP3 as reported by Drive
        "audio/mp4",  # .m4a / .m4b as reported by Drive
        "audio/x-m4a",  # .m4a
        "audio/x-m4b",  # .m4b
    }
)

GARMIN_COMPATIBLE_EXTENSIONS = frozenset({".mp3", ".m4a", ".m4b"})


def check_compatibility(entry: ManifestEntry) -> str | None:
    """Check whether a synced file should play on a Garmin watch.

    MIME type decides first; the filename extension is a fallback for
    MIME types Drive reports unusually.

    Args:
        entry: Manifest entry representing the synced audio file.

    Returns:
        Human-readable reason if the file is likely unplayable,
        otherwise None.
    """
    mime = entry.mime_type.lower().split(";")[0].strip()
    if mime in GARMIN_COMPATIBLE_MIME_TYPES:
        return None
    if Path(entry.name).suffix.lower() in GARMIN_COMPATIBLE_EXTENSIONS:
        return None
    detail = mime or Path(entry.name).suffix.lower() or "unknown format"
    return (
        f"{detail} is not playable on Garmin watches "
        "(supported: MP3, M4A, M4B) — convert to MP3 and re-upload"
    )
