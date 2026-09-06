"""Dashboard routes — GET / (main dashboard view)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from podcast.blob.protocol import BlobStore
from podcast.config import Settings
from podcast.deps import get_blob_store, get_settings
from podcast.sync.engine import is_sync_locked
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

    feed_url = (
        f"{settings.podcast_base_url}/api/feed"
        f"?token={settings.feed_secret_token}"
    )

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
            "feed_url": feed_url,
            "podcast_title": settings.podcast_title,
            "flash": flash,
        },
    )
