"""Dashboard routes — GET / (main dashboard view)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from podcast.blob.protocol import BlobStore
from podcast.compat import check_compatibility
from podcast.config import Settings
from podcast.deps import get_blob_store, get_drive_client, get_settings
from podcast.drive.client import DriveClient, DriveListError
from podcast.feed.hits import read_feed_hits
from podcast.models import ManifestEntry
from podcast.sync.engine import compute_diff, is_sync_locked
from podcast.web.middleware import require_login

__all__ = ["router"]

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    flash: str = "",
    email: str = Depends(require_login),
    settings: Settings = Depends(get_settings),
    blob_store: BlobStore = Depends(get_blob_store),
    drive_client: DriveClient = Depends(get_drive_client),
) -> HTMLResponse:
    """Render the main dashboard page.

    Shows the file list, storage usage bar, feed URL, sync status, and
    audio players for each synced episode.

    Args:
        request: Incoming FastAPI request.
        flash: Optional status message passed via query string.
        email: Authenticated user's email (injected by require_login).
        settings: Application settings (injected).
        blob_store: Blob storage (injected).
        drive_client: Drive API client (injected).

    Returns:
        Rendered dashboard HTML response.
    """
    entries = blob_store.read_manifest()
    total_bytes, quota_bytes, usage_pct = _storage_usage(
        entries, settings.blob_quota_mb
    )
    is_syncing = is_sync_locked(blob_store)
    pending, drive_ok = _pending_changes(drive_client, entries)
    incompatible = _incompatible_entries(entries)
    feed_url = (
        f"{settings.podcast_base_url}/api/podcast"
        f"?token={settings.feed_secret_token}"
    )

    # Newest first, capped for display. Reads may lag writes by ~a
    # minute due to Blob edge caching (see LESSONS.md).
    feed_hits = read_feed_hits(blob_store)[-10:][::-1]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "email": email,
            "entries": entries,
            "total_bytes": total_bytes,
            "quota_bytes": quota_bytes,
            "usage_pct": usage_pct,
            "is_syncing": is_syncing,
            "pending": pending,
            "drive_ok": drive_ok,
            "incompatible": incompatible,
            "feed_hits": feed_hits,
            "feed_url": feed_url,
            "podcast_title": settings.podcast_title,
            "flash": flash,
        },
    )


def _storage_usage(
    entries: list[ManifestEntry], quota_mb: int
) -> tuple[int, int, float]:
    """Compute storage totals and usage percentage.

    Args:
        entries: Manifest entries representing synced files.
        quota_mb: Blob storage quota in megabytes.

    Returns:
        Tuple of (total bytes, quota bytes, usage percent capped at 100).
    """
    total_bytes = sum(e.size_bytes for e in entries)
    quota_bytes = quota_mb * 1024 * 1024
    if quota_bytes:
        usage_pct = min(100, round(total_bytes / quota_bytes * 100, 1))
    else:
        usage_pct = 0
    return total_bytes, quota_bytes, usage_pct


def _pending_changes(
    drive_client: DriveClient, entries: list[ManifestEntry]
) -> tuple[dict[str, int], bool]:
    """Compare live Drive state against the manifest.

    Drive failures degrade to last-synced state rather than raising.

    Args:
        drive_client: Drive API client.
        entries: Current manifest entries.

    Returns:
        Tuple of (pending add/update/delete counts, drive reachable).
    """
    try:
        drive_files = drive_client.list_audio_files()
    except DriveListError:
        return {"add": 0, "update": 0, "delete": 0}, False
    to_add, to_update, to_delete, _ = compute_diff(drive_files, entries)
    return (
        {
            "add": len(to_add),
            "update": len(to_update),
            "delete": len(to_delete),
        },
        True,
    )


def _incompatible_entries(
    entries: list[ManifestEntry],
) -> list[tuple[str, str]]:
    """List entries unlikely to play on a Garmin watch.

    Args:
        entries: Manifest entries representing synced files.

    Returns:
        List of (filename, reason) pairs for incompatible entries.
    """
    return [
        (entry.name, reason)
        for entry in entries
        if (reason := check_compatibility(entry)) is not None
    ]
