"""Page rendering tests — login and dashboard HTML routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import app
from podcast.auth.session import create_session_cookie
from podcast.deps import get_blob_store, get_drive_client, get_settings
from podcast.drive.client import DriveListError
from podcast.models import DriveFile
from tests.integration.helpers import make_settings, make_store


class _StubDrive:
    """Drive stub returning canned files for dashboard tests."""

    def __init__(self, files: list[DriveFile] | None = None) -> None:
        """Store canned files (defaults to empty listing)."""
        self._files = files or []

    def list_audio_files(self) -> list[DriveFile]:
        """Return canned files."""
        return list(self._files)


def _client(settings, store, authed: bool = False, drive=None) -> TestClient:
    """Build a TestClient with overrides, optionally with a session."""
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_blob_store] = lambda: store
    app.dependency_overrides[get_drive_client] = lambda: drive or _StubDrive()
    client = TestClient(app, raise_server_exceptions=False)
    if authed:
        cookie = create_session_cookie("a@b.com", settings.session_secret_key)
        client.cookies.set("session", cookie)
    return client


def test_login_page_renders() -> None:
    """GET /auth/login returns 200 with the sign-in button."""
    client = _client(make_settings(), make_store())
    try:
        resp = client.get("/auth/login")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "Sign in with Google" in resp.text


def test_dashboard_renders_when_authed(sample_manifest_entry) -> None:
    """GET / with a valid session returns 200 with feed content."""
    settings = make_settings()
    store = make_store()
    store.write_manifest([sample_manifest_entry])
    client = _client(settings, store, authed=True)
    try:
        resp = client.get("/")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "ep1.mp3" in resp.text
    assert "a@b.com" in resp.text
    assert "May not play on Garmin" not in resp.text


def test_dashboard_alerts_on_incompatible_format() -> None:
    """GET / with an OGG entry shows the Garmin compat alert."""
    from podcast.models import ManifestEntry

    settings = make_settings()
    store = make_store()
    store.write_manifest(
        [
            ManifestEntry(
                drive_file_id="fid-ogg",
                drive_md5="md5",
                blob_url="https://blob.test/ep.ogg",
                name="talk.ogg",
                size_bytes=100,
                mime_type="audio/ogg",
                published_at="2026-09-05T12:00:00Z",
            )
        ]
    )
    client = _client(settings, store, authed=True)
    try:
        resp = client.get("/")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "May not play on Garmin 970" in resp.text
    assert "talk.ogg" in resp.text


def test_dashboard_redirects_when_anonymous() -> None:
    """GET / without a session redirects toward login."""
    client = _client(make_settings(), make_store())
    try:
        resp = client.get("/", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 307
    assert resp.headers["location"] == "/auth/login"


def test_flash_banner_has_dismiss_link() -> None:
    """Flash banner renders with a link clearing the query param."""
    settings = make_settings()
    client = _client(settings, make_store(), authed=True)
    try:
        resp = client.get("/", params={"flash": "Sync failed"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert 'href="/" ' in resp.text or 'href="/"' in resp.text
    assert "flash-close" in resp.text


def test_session_middleware_installed_with_distinct_cookie() -> None:
    """Authlib needs request.session; its cookie must not clash."""
    from starlette.middleware.sessions import SessionMiddleware

    found = [
        m.kwargs.get("session_cookie")
        for m in app.user_middleware
        if m.cls is SessionMiddleware
    ]
    assert len(found) == 1
    assert found[0] not in (None, "session", "oauth_state")


def test_login_google_uses_configured_base_url(monkeypatch) -> None:
    """Redirect URI sent to Google comes from config, not the request.

    Behind vercel dev the request sees an internal 127.0.0.1:port
    address, which Google can never accept.
    """
    from fastapi.responses import RedirectResponse

    captured: dict[str, str] = {}

    class _FakeGoogle:
        async def authorize_redirect(
            self, request, redirect_uri: str, state: str = ""
        ) -> RedirectResponse:
            captured["redirect_uri"] = redirect_uri
            return RedirectResponse(
                url="https://accounts.google.com/o/oauth2/auth?x=1"
            )

    class _FakeOAuth:
        google = _FakeGoogle()

    monkeypatch.setattr(
        "podcast.web.auth_routes.build_oauth_client",
        lambda *args: _FakeOAuth(),
    )
    settings = make_settings(podcast_base_url="http://localhost:4000")
    client = _client(settings, make_store())
    try:
        resp = client.get("/auth/google", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 307
    assert captured["redirect_uri"] == "http://localhost:4000/auth/callback"


def test_dashboard_shows_up_to_date_when_no_changes(
    sample_manifest_entry,
) -> None:
    """Matching Drive and manifest render the up-to-date status."""
    from podcast.models import DriveFile as _DriveFile

    settings = make_settings()
    store = make_store()
    store.write_manifest([sample_manifest_entry])
    drive = _StubDrive(
        [
            _DriveFile(
                id="drive-id-1",
                name="ep1.mp3",
                mime_type="audio/mpeg",
                size_bytes=1_000_000,
                md5="abc123",
            )
        ]
    )
    client = _client(settings, store, authed=True, drive=drive)
    try:
        resp = client.get("/")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "Up to date with Google Drive" in resp.text


def test_dashboard_shows_pending_counts(sample_manifest_entry) -> None:
    """Extra Drive file renders pending new-file status."""
    settings = make_settings()
    store = make_store()
    store.write_manifest([sample_manifest_entry])
    drive = _StubDrive(
        [
            DriveFile(
                id="drive-id-1",
                name="ep1.mp3",
                mime_type="audio/mpeg",
                size_bytes=1_000_000,
                md5="abc123",
            ),
            DriveFile(
                id="drive-id-2",
                name="ep2.mp3",
                mime_type="audio/mpeg",
                size_bytes=2_000_000,
                md5="def456",
            ),
        ]
    )
    client = _client(settings, store, authed=True, drive=drive)
    try:
        resp = client.get("/")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "1 new" in resp.text


def test_dashboard_degrades_when_drive_unreachable(
    sample_manifest_entry,
) -> None:
    """Drive failure still renders the dashboard with a warning."""

    class _BrokenDrive:
        def list_audio_files(self):
            raise DriveListError("down")

    settings = make_settings()
    store = make_store()
    store.write_manifest([sample_manifest_entry])
    client = _client(settings, store, authed=True, drive=_BrokenDrive())
    try:
        resp = client.get("/")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "Couldn" in resp.text
    assert "ep1.mp3" in resp.text


def test_dashboard_shows_id3_badge_for_tagged_files() -> None:
    """Tagged entries render the ID3 badge; untagged ones do not."""
    from dataclasses import replace

    from podcast.models import ManifestEntry

    settings = make_settings()
    store = make_store()
    tagged_entry = ManifestEntry(
        drive_file_id="fid-tagged",
        drive_md5="md5",
        blob_url="https://blob.test/tagged.mp3",
        name="tagged.mp3",
        size_bytes=100,
        mime_type="audio/mpeg",
        published_at="2026-09-05T12:00:00Z",
        tagged=True,
    )
    plain_entry = replace(
        tagged_entry, drive_file_id="fid-plain", name="plain.mp3", tagged=False
    )
    store.write_manifest([tagged_entry, plain_entry])
    client = _client(settings, store, authed=True)
    try:
        resp = client.get("/")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "🏷 ID3" in resp.text
    assert resp.text.count('<span class="tag-badge"') == 1


def test_dashboard_shows_recorded_feed_hits() -> None:
    """Pre-recorded feed hits render in the fetches table."""
    from podcast.feed.hits import record_feed_hit

    settings = make_settings()
    store = make_store()
    record_feed_hit(store, "PlayRun/1.0", 200)
    client = _client(settings, store, authed=True)
    try:
        resp = client.get("/")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "PlayRun/1.0" in resp.text
