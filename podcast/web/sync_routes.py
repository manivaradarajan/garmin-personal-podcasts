"""Sync trigger route — POST /api/sync/trigger, GET /api/sync/status.

The trigger starts the sync in a background thread and redirects
immediately so the browser never spins on multi-minute uploads. The
dashboard polls the status endpoint and reloads when the run finishes.
Serverless note: a background thread may be frozen if the platform
reclaims the function — the Blob lock TTL plus incremental manifest
commits make that safe; cron remains the reliable production path.
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, RedirectResponse

from podcast.blob.protocol import BlobStore
from podcast.config import Settings
from podcast.deps import get_blob_store, get_drive_client, get_settings
from podcast.drive.client import DriveClient
from podcast.sync.engine import (
    LockHeldError,
    _acquire_lock,
    _release_lock,
    is_sync_locked,
    run_sync,
)
from podcast.web.middleware import require_login

__all__ = ["router"]

_LOG = logging.getLogger(__name__)
router = APIRouter()

_STARTED_FLASH = "Sync started — this page will refresh when done"

_state_lock = threading.Lock()
_last_summary: str | None = None
_last_error: str | None = None


def _run_in_background(
    settings: Settings,
    blob_store: BlobStore,
    drive_client: DriveClient,
) -> None:
    """Execute a sync run, recording its outcome for the status endpoint.

    Args:
        settings: Application settings.
        blob_store: Blob storage implementation.
        drive_client: Drive API client.
    """
    global _last_summary, _last_error
    try:
        result = run_sync(settings, blob_store, drive_client)
        summary = (
            f"Sync complete — added {result.added}, "
            f"updated {result.updated}, deleted {result.deleted}, "
            f"errors {result.errors}"
        )
        with _state_lock:
            _last_summary = summary
            _last_error = None
    except Exception as exc:
        _LOG.error("Background sync failed: %s", exc)
        with _state_lock:
            _last_summary = None
            _last_error = "Sync failed — check logs"
    finally:
        _release_lock(blob_store)


@router.post("/api/sync/trigger")
async def trigger_sync(
    email: str = Depends(require_login),
    settings: Settings = Depends(get_settings),
    blob_store: BlobStore = Depends(get_blob_store),
    drive_client: DriveClient = Depends(get_drive_client),
) -> RedirectResponse:
    """Start a sync run in the background and redirect immediately.

    Acquires the Blob lock synchronously (so a second trigger sees it
    as in-progress), then hands the run to a daemon thread.

    Args:
        email: Authenticated user's email (injected by require_login).
        settings: Application settings (injected).
        blob_store: Blob storage (injected).
        drive_client: Drive API client (injected).

    Returns:
        Redirect to / with a flash query parameter indicating the result.
    """
    global _last_summary, _last_error
    try:
        _acquire_lock(blob_store)
    except LockHeldError:
        flash = "Sync already in progress"
        target = f"/?flash={_encode_flash(flash)}"
        return RedirectResponse(url=target, status_code=302)
    with _state_lock:
        _last_summary = None
        _last_error = None
    thread = threading.Thread(
        target=_run_in_background,
        args=(settings, blob_store, drive_client),
        daemon=True,
    )
    thread.start()
    target = f"/?flash={_encode_flash(_STARTED_FLASH)}"
    return RedirectResponse(url=target, status_code=302)


@router.get("/api/sync/status")
async def sync_status(
    email: str = Depends(require_login),
    blob_store: BlobStore = Depends(get_blob_store),
) -> JSONResponse:
    """Report whether a sync is running and its last outcome.

    Args:
        email: Authenticated user's email (injected by require_login).
        blob_store: Blob storage (injected).

    Returns:
        JSON with running flag and, when finished, a flash summary.
    """
    running = is_sync_locked(blob_store)
    with _state_lock:
        summary = _last_summary
        error = _last_error
    if running:
        return JSONResponse({"running": True})
    if error is not None:
        return JSONResponse({"running": False, "flash": error})
    if summary is not None:
        return JSONResponse({"running": False, "flash": summary})
    return JSONResponse({"running": False})


# ---


def _encode_flash(message: str) -> str:
    """URL-encode a flash message for passing in a query string.

    Args:
        message: Flash message text.

    Returns:
        URL-encoded string safe for query string inclusion.
    """
    from urllib.parse import quote

    return quote(message)
