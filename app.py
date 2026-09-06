"""FastAPI entrypoint — routes only, no domain logic."""

from __future__ import annotations

import hmac
import logging
import os
from dataclasses import asdict

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from podcast.blob.protocol import BlobStore
from podcast.config import Settings
from podcast.deps import get_blob_store, get_drive_client, get_settings
from podcast.drive.client import DriveClient
from podcast.feed.builder import build_rss_xml
from podcast.sync.engine import (
    LockHeldError,
    _acquire_lock,
    _release_lock,
    run_sync,
)
from podcast.web.auth_routes import router as auth_router
from podcast.web.dashboard_routes import router as dashboard_router
from podcast.web.sync_routes import router as sync_router

_LOG = logging.getLogger(__name__)

app = FastAPI(title="Garmin Personal Podcasts", docs_url=None, redoc_url=None)

# Authlib's Starlette integration keeps transient OAuth state in
# request.session, which requires SessionMiddleware. The cookie name is
# deliberately distinct from our own "session" auth cookie, and the
# fallback secret only applies when SESSION_SECRET_KEY is unset (real
# requests fail earlier at Settings validation in that case).
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET_KEY", "dev-only-fallback-secret"),
    session_cookie="oauth_state_session",
    max_age=600,
    same_site="lax",
)

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(sync_router)


@app.get("/api/feed")
async def get_feed(
    request: Request,
    token: str | None = None,
    settings: Settings = Depends(get_settings),
    blob_store: BlobStore = Depends(get_blob_store),
) -> Response:
    """Serve the RSS feed — authenticated by query-string token.

    Args:
        request: Incoming FastAPI request.
        token: Secret token from the query string (None if absent).
        settings: Application settings (injected).
        blob_store: Blob storage (injected).

    Returns:
        RSS 2.0 XML response, or a 403 JSON error if the token is invalid.
    """
    if not token or not hmac.compare_digest(token, settings.feed_secret_token):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    entries = blob_store.read_manifest()
    xml = build_rss_xml(
        entries=entries,
        title=settings.podcast_title,
        feed_url=str(request.url),
        base_url=settings.podcast_base_url,
    )
    return Response(
        content=xml,
        media_type="application/rss+xml",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/cron/sync")
async def cron_sync(
    request: Request,
    settings: Settings = Depends(get_settings),
    blob_store: BlobStore = Depends(get_blob_store),
    drive_client: DriveClient = Depends(get_drive_client),
) -> JSONResponse:
    """Hourly cron endpoint — protected by Vercel cron schedule header.

    Returns 403 if the Vercel cron header is absent. Uses the same lock
    mechanism as the manual trigger to prevent concurrent runs.

    Args:
        request: Incoming FastAPI request.
        settings: Application settings (injected).
        blob_store: Blob storage (injected).
        drive_client: Drive API client (injected).

    Returns:
        JSON with sync result counts, 409 if locked, or 500 on error.
    """
    if not request.headers.get("x-vercel-cron-schedule"):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    lock_acquired = False
    try:
        _acquire_lock(blob_store)
        lock_acquired = True
        result = run_sync(settings, blob_store, drive_client)
        return JSONResponse(asdict(result))
    except LockHeldError:
        return JSONResponse({"status": "locked"}, status_code=409)
    except Exception as exc:
        _LOG.error("Cron sync failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)
    finally:
        if lock_acquired:
            _release_lock(blob_store)
