"""FastAPI entrypoint — routes only, no domain logic."""

from __future__ import annotations

import hmac
import logging
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from podcast.blob.protocol import BlobStore
from podcast.config import Settings
from podcast.deps import get_blob_store, get_drive_client, get_settings
from podcast.drive.client import DriveClient
from podcast.feed.builder import build_rss_xml
from podcast.feed.hits import record_feed_hit
from podcast.models import ManifestEntry
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
_COVER_PATH = Path(__file__).parent / "podcast" / "web" / "static" / "cover.png"

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


@app.get("/cover.png", response_class=FileResponse)
async def get_cover() -> FileResponse:
    """Serve the podcast cover artwork (immutable static asset).

    Returns:
        PNG cover image with long-lived caching.
    """
    return FileResponse(
        path=_COVER_PATH,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.api_route("/api/feed", methods=["GET", "HEAD"])
async def get_feed(
    request: Request,
    token: str | None = None,
    settings: Settings = Depends(get_settings),
    blob_store: BlobStore = Depends(get_blob_store),
) -> Response:
    """Serve the RSS feed — authenticated by query-string token.

    Supports HEAD (headers only, same metadata as GET) and conditional
    GET via ETag/If-None-Match so pollers can check cheaply.

    Args:
        request: Incoming FastAPI request.
        token: Secret token from the query string (None if absent).
        settings: Application settings (injected).
        blob_store: Blob storage (injected).

    Returns:
        RSS 2.0 XML response, empty HEAD/304 responses with matching
        headers, or a 403 JSON error if the token is invalid.
    """
    user_agent = request.headers.get("user-agent")
    if not token or not hmac.compare_digest(token, settings.feed_secret_token):
        record_feed_hit(blob_store, user_agent, 403)
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    entries = blob_store.read_manifest()
    # Built from config, not the request: behind Vercel the request URL
    # carries the deployment-specific hostname, which never matches the
    # canonical document location validators compare against.
    feed_url = (
        f"{settings.podcast_base_url}/api/feed"
        f"?token={settings.feed_secret_token}"
    )
    xml = build_rss_xml(
        entries=entries,
        title=settings.podcast_title,
        feed_url=feed_url,
        base_url=settings.podcast_base_url,
        description=settings.podcast_description,
    )
    body = xml.encode("utf-8")
    etag = f'"{_sha256_hex(body)}"'
    headers = {
        "Cache-Control": "no-store",
        "Content-Length": str(len(body)),
        "ETag": etag,
        "Last-Modified": _feed_last_modified(entries),
    }
    record_feed_hit(blob_store, user_agent, 200)
    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            media_type="application/rss+xml",
            headers=headers,
        )
    if request.method == "HEAD":
        return Response(
            content=b"",
            media_type="application/rss+xml",
            headers=headers,
        )
    return Response(
        content=xml,
        media_type="application/rss+xml",
        headers=headers,
    )


def _sha256_hex(data: bytes) -> str:
    """Return the hex SHA-256 digest of bytes.

    Args:
        data: Bytes to hash.

    Returns:
        Lowercase hex digest string.
    """
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _feed_last_modified(entries: list[ManifestEntry]) -> str:
    """Return the feed Last-Modified date from the newest entry.

    Args:
        entries: Manifest entries in the feed.

    Returns:
        RFC 2822 date of the newest episode, or now when empty.
    """
    from podcast.feed.builder import _iso_to_rfc2822, _rfc2822_now

    if not entries:
        return _rfc2822_now()
    newest = max(entries, key=lambda e: e.published_at)
    return _iso_to_rfc2822(newest.published_at)


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
