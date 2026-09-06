"""Page rendering tests — login and dashboard HTML routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import app
from podcast.auth.session import create_session_cookie
from podcast.deps import get_blob_store, get_settings
from tests.integration.helpers import make_settings, make_store


def _client(settings, store, authed: bool = False) -> TestClient:
    """Build a TestClient with overrides, optionally with a session."""
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_blob_store] = lambda: store
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
