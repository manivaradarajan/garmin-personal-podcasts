"""Sync trigger route — POST /api/sync/trigger."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from podcast.blob.protocol import BlobStore
from podcast.config import Settings
from podcast.deps import get_blob_store, get_drive_client, get_settings
from podcast.drive.client import DriveClient
from podcast.sync.engine import (
    LockHeldError,
    _acquire_lock,
    _release_lock,
    run_sync,
)
from podcast.web.middleware import require_login

__all__ = ["router"]

_LOG = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/sync/trigger")
async def trigger_sync(
    request: Request,
    email: str = Depends(require_login),
    settings: Settings = Depends(get_settings),
    blob_store: BlobStore = Depends(get_blob_store),
    drive_client: DriveClient = Depends(get_drive_client),
) -> RedirectResponse:
    """Manually trigger a sync run from the dashboard.

    Acquires the sync lock, runs sync, then releases the lock. Redirects
    back to the dashboard with a flash message indicating success or failure.
    The lock is always released if it was acquired, even on unexpected errors.

    Args:
        request: Incoming FastAPI request.
        email: Authenticated user's email (injected by require_login).
        settings: Application settings (injected).
        blob_store: Blob storage (injected).
        drive_client: Drive API client (injected).

    Returns:
        Redirect to / with a flash query parameter indicating the result.
    """
    lock_acquired = False
    try:
        _acquire_lock(blob_store)
        lock_acquired = True
        result = run_sync(settings, blob_store, drive_client)
        flash = (
            f"Sync complete — added {result.added}, "
            f"updated {result.updated}, deleted {result.deleted}, "
            f"errors {result.errors}"
        )
        target = f"/?flash={_encode_flash(flash)}"
        return RedirectResponse(url=target, status_code=302)
    except LockHeldError:
        flash = "Sync already in progress"
        target = f"/?flash={_encode_flash(flash)}"
        return RedirectResponse(url=target, status_code=302)
    except Exception as exc:
        _LOG.error("Sync trigger failed: %s", exc)
        flash = "Sync failed — check logs"
        target = f"/?flash={_encode_flash(flash)}"
        return RedirectResponse(url=target, status_code=302)
    finally:
        if lock_acquired:
            _release_lock(blob_store)


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
