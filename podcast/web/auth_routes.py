"""Auth routes — Google OAuth2 login / callback / logout."""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path

import itsdangerous
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer

from podcast.auth.google_oauth import build_oauth_client
from podcast.auth.session import create_session_cookie
from podcast.config import Settings
from podcast.deps import get_settings

__all__ = ["router"]

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
_STATE_MAX_AGE = 300  # 5 minutes
_STATE_SALT = "oauth_state"


def _state_serializer(secret_key: str) -> URLSafeTimedSerializer:
    """Build a short-lived state serializer for CSRF protection.

    Args:
        secret_key: Application secret key.

    Returns:
        Configured URLSafeTimedSerializer.
    """
    return URLSafeTimedSerializer(secret_key, salt=_STATE_SALT)


@router.get("/auth/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Render the login page with a Google sign-in button.

    The middleware redirects unauthenticated users here. The page presents
    a single 'Sign in with Google' button that initiates the OAuth2 flow
    via GET /auth/google.

    Args:
        request: Incoming FastAPI request.

    Returns:
        Rendered login HTML page.
    """
    return _templates.TemplateResponse(request, "login.html")


@router.get("/auth/google")
async def login_google(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Initiate the Google OAuth2 authorization flow.

    Generates a CSRF state token, stores it in a signed short-lived cookie,
    then redirects to Google's authorization endpoint.

    Args:
        request: Incoming FastAPI request.
        settings: Application settings (injected).

    Returns:
        Redirect to Google's OAuth2 authorization endpoint.
    """
    state = secrets.token_urlsafe(32)
    signed_state = _state_serializer(settings.session_secret_key).dumps(state)

    oauth = build_oauth_client(
        settings.google_oauth_client_id,
        settings.google_oauth_client_secret,
    )
    # Built from config, not the request: behind vercel dev (or any
    # proxy) request.url_for() sees the internal address
    # (e.g. 127.0.0.1:<random-port>), which can never match the URI
    # registered in the Google console.
    redirect_uri = f"{settings.podcast_base_url.rstrip('/')}/auth/callback"
    google_redirect = await oauth.google.authorize_redirect(
        request, redirect_uri, state=state
    )
    response = RedirectResponse(url=google_redirect.headers["location"])
    response.set_cookie(
        "oauth_state",
        signed_state,
        max_age=_STATE_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return response


@router.get("/auth/callback", name="auth_callback", response_model=None)
async def auth_callback(
    request: Request,
    state: str = "",
    settings: Settings = Depends(get_settings),
) -> RedirectResponse | HTMLResponse:
    """Handle the Google OAuth2 authorization callback.

    Validates the CSRF state, exchanges the code for an ID token, checks the
    email against the allowlist, and issues a signed session cookie.

    Args:
        request: Incoming FastAPI request.
        state: OAuth2 state parameter from the query string.
        settings: Application settings (injected).

    Returns:
        Redirect to dashboard on success, or an error HTML response.
    """
    raw_state_cookie = request.cookies.get("oauth_state")

    if not _validate_state(
        raw_state_cookie, state, settings.session_secret_key
    ):
        return HTMLResponse("Invalid state — possible CSRF", status_code=400)

    oauth = build_oauth_client(
        settings.google_oauth_client_id,
        settings.google_oauth_client_secret,
    )
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        return HTMLResponse("OAuth2 token exchange failed", status_code=400)

    userinfo = token.get("userinfo") or {}
    email: str = (userinfo.get("email") or "").lower()

    allowed = {
        e.strip().lower()
        for e in settings.allowed_emails.split(",")
        if e.strip()
    }
    if email not in allowed:
        return HTMLResponse("Not authorized", status_code=403)

    session_value = create_session_cookie(email, settings.session_secret_key)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        "session",
        session_value,
        max_age=86400,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    response.delete_cookie("oauth_state")
    return response


@router.get("/auth/logout")
async def logout() -> RedirectResponse:
    """Clear the session cookie and redirect to the login page.

    Returns:
        Redirect to /auth/login with session cookie cleared.
    """
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("session")
    return response


# ---


def _validate_state(
    raw_cookie: str | None,
    query_state: str,
    secret_key: str,
) -> bool:
    """Validate the OAuth2 CSRF state parameter.

    Args:
        raw_cookie: Signed state value from the oauth_state cookie.
        query_state: State value from the OAuth2 callback query string.
        secret_key: Application secret key for verifying the signature.

    Returns:
        True if the state is valid and unexpired; False otherwise.
    """
    if not raw_cookie or not query_state:
        return False
    try:
        cookie_state = _state_serializer(secret_key).loads(
            raw_cookie, max_age=_STATE_MAX_AGE
        )
    except (
        itsdangerous.SignatureExpired,
        itsdangerous.BadSignature,
        itsdangerous.BadData,
    ):
        return False

    return hmac.compare_digest(query_state, cookie_state)
