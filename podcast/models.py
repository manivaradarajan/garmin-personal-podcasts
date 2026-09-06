"""Frozen dataclasses for core domain objects."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DriveFile", "ManifestEntry", "SyncResult"]


@dataclass(frozen=True)
class DriveFile:
    """A single audio file returned from the Google Drive listing.

    Attributes:
        id: Drive file ID (stable, used as RSS guid).
        name: Filename as stored in Drive.
        mime_type: MIME type reported by Drive (e.g. audio/mpeg).
        size_bytes: File size in bytes.
        md5: Drive md5Checksum field — used for change detection.
    """

    id: str
    name: str
    mime_type: str
    size_bytes: int
    md5: str


@dataclass(frozen=True)
class ManifestEntry:
    """A synced file entry stored in the Blob manifest.

    Attributes:
        drive_file_id: Drive file ID — used as RSS guid; stable across renames.
        drive_md5: Drive md5Checksum — change detection (not modifiedTime).
        blob_url: Vercel Blob public URL — used in enclosure url.
        name: Original filename — used as RSS title.
        size_bytes: File size — used in enclosure length.
        mime_type: MIME type — used in enclosure type.
        published_at: ISO 8601 UTC — set at first upload, never updated.
    """

    drive_file_id: str
    drive_md5: str
    blob_url: str
    name: str
    size_bytes: int
    mime_type: str
    published_at: str


@dataclass(frozen=True)
class SyncResult:
    """Counts from a completed sync run.

    Attributes:
        added: Number of new files uploaded.
        updated: Number of existing files re-uploaded due to content change.
        deleted: Number of files removed from Blob.
        unchanged: Number of files with no change.
        errors: Number of per-file failures (skipped, not fatal).
    """

    added: int
    updated: int
    deleted: int
    unchanged: int
    errors: int
