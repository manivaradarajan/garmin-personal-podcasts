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

    total_bytes = sum(e.size_bytes for e in entries)
    quota_bytes = settings.blob_quota_mb * 1024 * 1024
    if quota_bytes:
        usage_pct = min(100, round(total_bytes / quota_bytes * 100, 1))
    else:
        usage_pct = 0

    is_syncing = is_sync_locked(blob_store)

    # Live Drive comparison so the dashboard shows pending changes
    # instead of silently stale state. Drive failures degrade to
    # last-synced state rather than a 500.
    try:
        drive_files = drive_client.list_audio_files()
        to_add, to_update, to_delete, _ = compute_diff(drive_files, entries)
        pending = {
            "add": len(to_add),
            "update": len(to_update),
            "delete": len(to_delete),
        }
        drive_ok = True
    except DriveListError:
        pending = {"add": 0, "update": 0, "delete": 0}
        drive_ok = False

    incompatible = [
        (entry.name, reason)
        for entry in entries
        if (reason := check_compatibility(entry)) is not None
    ]

    feed_url = (
        f"{settings.podcast_base_url}/api/feed"
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
