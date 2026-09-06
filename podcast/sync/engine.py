"""Sync engine — diff Drive vs Blob manifest and apply changes."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from podcast.audio.tags import (
    ensure_id3_tags,
    has_id3_title,
    snapshot_id3_tags,
)
from podcast.blob.protocol import BlobStore
from podcast.config import Settings
from podcast.drive.client import DriveClient
from podcast.models import DriveFile, ManifestEntry, SyncResult

__all__ = [
    "LockHeldError",
    "is_sync_locked",
    "run_sync",
    "_acquire_lock",
    "_release_lock",
]

_LOG = logging.getLogger(__name__)
_LOCK_PATH = "sync.lock"
_LOCK_MAX_AGE_SECONDS = 300  # 5 minutes
_EPISODES_PREFIX = "episodes"
_EPISODE_CACHE_MAX_AGE = 300  # 5 minutes; bounds stale bytes after overwrite


def _blob_path(drive_file: DriveFile) -> str:
    """Return the stable Blob path for a Drive file.

    Derived from the Drive file ID (not the filename) so renames and
    re-uploads keep the same enclosure URL forever.

    Args:
        drive_file: Drive file metadata.

    Returns:
        Stable pathname preserving the original extension.
    """
    suffix = Path(drive_file.name).suffix.lower() or ".mp3"
    return f"{_EPISODES_PREFIX}/{drive_file.id}{suffix}"


class LockHeldError(Exception):
    """Raised when the sync lock is already held by another invocation."""


# ---


def run_sync(
    settings: Settings,
    blob_store: BlobStore,
    drive_client: DriveClient,
) -> SyncResult:
    """Execute a full sync pass: list Drive, diff, apply changes.

    The manifest is written incrementally after each file operation
    so that a partial run leaves Blob contents consistent.

    Args:
        settings: App settings (kept for extensibility).
        blob_store: Blob storage implementation.
        drive_client: Drive API client.

    Returns:
        Counts of added, updated, deleted, unchanged, errored files.

    Raises:
        DriveListError: If Drive listing fails — manifest untouched.
    """
    manifest = blob_store.read_manifest()
    drive_files = drive_client.list_audio_files()  # raises on failure

    to_add, to_update, to_delete, unchanged = compute_diff(
        drive_files, manifest
    )

    added = updated = deleted = errors = 0
    current_manifest = list(manifest)

    for drive_file in to_add:
        entry = _upload_file(
            drive_file, blob_store, drive_client, settings.podcast_title
        )
        if entry is not None:
            current_manifest.append(entry)
            blob_store.write_manifest(current_manifest)
            added += 1
        else:
            errors += 1

    for drive_file, old_entry in to_update:
        new_entry = _reupload_file(
            drive_file,
            old_entry,
            blob_store,
            drive_client,
            settings.podcast_title,
        )
        if new_entry is not None:
            current_manifest = [
                new_entry if e.drive_file_id == old_entry.drive_file_id else e
                for e in current_manifest
            ]
            blob_store.write_manifest(current_manifest)
            updated += 1
        else:
            errors += 1

    for old_entry in to_delete:
        success = _delete_blob_entry(old_entry, blob_store)
        if success:
            current_manifest = [
                e
                for e in current_manifest
                if e.drive_file_id != old_entry.drive_file_id
            ]
            blob_store.write_manifest(current_manifest)
            deleted += 1
        else:
            errors += 1

    return SyncResult(
        added=added,
        updated=updated,
        deleted=deleted,
        unchanged=unchanged,
        errors=errors,
    )


def compute_diff(
    drive_files: list[DriveFile],
    manifest: list[ManifestEntry],
) -> tuple[
    list[DriveFile],
    list[tuple[DriveFile, ManifestEntry]],
    list[ManifestEntry],
    int,
]:
    """Compute which files to add, update, delete, and which are unchanged.

    Args:
        drive_files: Current listing from Google Drive.
        manifest: Current manifest entries from Blob storage.

    Returns:
        Tuple of (to_add, to_update, to_delete, unchanged_count).
        - to_add: DriveFiles not in the manifest.
        - to_update: (DriveFile, ManifestEntry) pairs where md5 differs.
        - to_delete: ManifestEntries whose drive_file_id is absent from Drive.
        - unchanged_count: Number of files with identical md5.
    """
    drive_by_id = {f.id: f for f in drive_files}
    manifest_by_id = {e.drive_file_id: e for e in manifest}

    to_add = [f for fid, f in drive_by_id.items() if fid not in manifest_by_id]

    to_update = [
        (drive_by_id[fid], entry)
        for fid, entry in manifest_by_id.items()
        if fid in drive_by_id and drive_by_id[fid].md5 != entry.drive_md5
    ]

    to_delete = [
        entry for fid, entry in manifest_by_id.items() if fid not in drive_by_id
    ]

    unchanged = sum(
        1
        for fid, entry in manifest_by_id.items()
        if fid in drive_by_id and drive_by_id[fid].md5 == entry.drive_md5
    )

    return to_add, to_update, to_delete, unchanged


def _parse_lock_time(raw: bytes) -> datetime | None:
    """Parse a lock blob timestamp, assuming UTC if naive.

    Args:
        raw: Raw lock blob content.

    Returns:
        Aware datetime, or None if unparseable.
    """
    try:
        parsed = datetime.fromisoformat(raw.decode().strip())
    except ValueError, UnicodeDecodeError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def is_sync_locked(blob_store: BlobStore) -> bool:
    """Return True if a fresh (non-stale) sync lock is present.

    Args:
        blob_store: Blob storage implementation.

    Returns:
        True if a lock younger than the TTL exists; False otherwise.
    """
    existing = blob_store.read(_LOCK_PATH, use_cache=False)
    if existing is None:
        return False
    lock_time = _parse_lock_time(existing)
    if lock_time is None:
        return False
    try:
        age = (datetime.now(UTC) - lock_time).total_seconds()
    except TypeError:
        return False
    return age < _LOCK_MAX_AGE_SECONDS


def _acquire_lock(blob_store: BlobStore) -> None:
    """Write the sync lock blob; raise LockHeldError if already locked.

    Uses a timestamp-based TTL: if a lock exists and is younger than
    _LOCK_MAX_AGE_SECONDS, a LockHeldError is raised. Older locks are
    considered stale and overwritten (crash-safe behaviour).

    Args:
        blob_store: Blob storage implementation.

    Raises:
        LockHeldError: If an active (non-stale) lock is already present.
    """
    existing = blob_store.read(_LOCK_PATH, use_cache=False)
    if existing is not None:
        lock_time = _parse_lock_time(existing)
        if lock_time is not None:
            try:
                age = (datetime.now(UTC) - lock_time).total_seconds()
            except TypeError:
                age = _LOCK_MAX_AGE_SECONDS
            if age < _LOCK_MAX_AGE_SECONDS:
                raise LockHeldError(f"Sync lock held; age={age:.0f}s")

    now_str = datetime.now(UTC).isoformat()
    blob_store.write(_LOCK_PATH, now_str.encode(), cache_max_age=0)


def _release_lock(blob_store: BlobStore) -> None:
    """Release the sync lock by writing a stale timestamp.

    Rather than deleting the lock blob (which requires knowing its URL),
    we overwrite it with an epoch timestamp that will always be considered
    stale by _acquire_lock. Failures are logged but not re-raised — the
    TTL mechanism handles recovery in the worst case.

    Args:
        blob_store: Blob storage implementation.
    """
    try:
        blob_store.write(
            _LOCK_PATH, b"1970-01-01T00:00:00+00:00", cache_max_age=0
        )
    except Exception as exc:
        _LOG.warning("Failed to release sync lock: %s", exc)


# ---


def _upload_file(
    drive_file: DriveFile,
    blob_store: BlobStore,
    drive_client: DriveClient,
    album: str,
) -> ManifestEntry | None:
    """Upload a new Drive file to Blob storage.

    MP3s gain ID3 tags for Garmin display; the manifest records the
    tagged size so enclosure lengths match the served bytes.

    Args:
        drive_file: Drive file metadata.
        blob_store: Blob storage implementation.
        drive_client: Drive API client for streaming content.
        album: Podcast name for the ID3 album frame.

    Returns:
        New ManifestEntry on success, None on failure.
    """
    try:
        raw = b"".join(drive_client.stream_file(drive_file.id))
        published_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        data, duration = ensure_id3_tags(
            raw, drive_file.name, album, published_at[:4]
        )
        blob_url = blob_store.upload(
            _blob_path(drive_file),
            data,
            drive_file.mime_type,
            cache_max_age=_EPISODE_CACHE_MAX_AGE,
        )
        return ManifestEntry(
            drive_file_id=drive_file.id,
            drive_md5=drive_file.md5,
            blob_url=blob_url,
            name=drive_file.name,
            size_bytes=len(data),
            mime_type=drive_file.mime_type,
            published_at=published_at,
            tagged=has_id3_title(data),
            duration_sec=int(duration) if duration is not None else None,
            id3=snapshot_id3_tags(data),
        )
    except Exception as exc:
        _LOG.error("Failed to upload %s: %s", drive_file.name, exc)
        return None


def _reupload_file(
    drive_file: DriveFile,
    old_entry: ManifestEntry,
    blob_store: BlobStore,
    drive_client: DriveClient,
    album: str,
) -> ManifestEntry | None:
    """Re-upload a changed Drive file to Blob storage.

    published_at is preserved from the old entry so RSS clients don't treat
    content updates as new episodes.

    Args:
        drive_file: Updated Drive file metadata.
        old_entry: Existing manifest entry to update.
        blob_store: Blob storage implementation.
        drive_client: Drive API client for streaming content.
        album: Podcast name for the ID3 album frame.

    Returns:
        Updated ManifestEntry on success, None on failure.
    """
    try:
        raw = b"".join(drive_client.stream_file(drive_file.id))
        data, duration = ensure_id3_tags(
            raw, drive_file.name, album, old_entry.published_at[:4]
        )
        blob_url = blob_store.upload(
            _blob_path(drive_file),
            data,
            drive_file.mime_type,
            cache_max_age=_EPISODE_CACHE_MAX_AGE,
        )
        new_entry = replace(
            old_entry,
            drive_md5=drive_file.md5,
            blob_url=blob_url,
            name=drive_file.name,
            size_bytes=len(data),
            mime_type=drive_file.mime_type,
            tagged=has_id3_title(data),
            duration_sec=int(duration) if duration is not None else None,
            id3=snapshot_id3_tags(data),
        )
        if blob_url != old_entry.blob_url:
            try:
                blob_store.delete(old_entry.blob_url)
            except Exception as exc:
                _LOG.warning(
                    "Failed to delete superseded blob %s: %s",
                    old_entry.blob_url,
                    exc,
                )
        return new_entry
    except Exception as exc:
        _LOG.error("Failed to re-upload %s: %s", drive_file.name, exc)
        return None


def _delete_blob_entry(
    entry: ManifestEntry,
    blob_store: BlobStore,
) -> bool:
    """Delete a Blob object corresponding to a manifest entry.

    Args:
        entry: Manifest entry whose blob should be deleted.
        blob_store: Blob storage implementation.

    Returns:
        True if deletion succeeded, False on failure.
    """
    try:
        blob_store.delete(entry.blob_url)
        return True
    except Exception as exc:
        _LOG.error(
            "Failed to delete %s (%s): %s",
            entry.name,
            entry.blob_url,
            exc,
        )
        return False
