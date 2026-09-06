"""FastAPI dependency — require_login() guards all dashboard routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from podcast.auth.session import validate_session_cookie
from podcast.config import Settings
from podcast.deps import get_settings

__all__ = ["parse_allowed_emails", "require_login"]


def require_login(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    """Validate the session cookie and return the authenticated email.

    Raises a 307 redirect to /auth/login if no valid session exists.
    Raises 403 if the email is not in the allowed list.

    Args:
        request: Incoming FastAPI request.
        settings: Application settings (injected).

    Returns:
        Authenticated user's email address.

    Raises:
        HTTPException: 307 redirect to login if unauthenticated; 403 if
            the email is not in the ALLOWED_EMAILS list.
    """
    email = validate_session_cookie(
        request.cookies.get("session"), settings.session_secret_key
    )
    if email is None:
        raise HTTPException(
            status_code=307,
            headers={"Location": "/auth/login"},
        )
    allowed = parse_allowed_emails(settings.allowed_emails)
    if email not in allowed:
        raise HTTPException(status_code=403, detail="Email not authorized")
    return email


def parse_allowed_emails(raw: str) -> set[str]:
    """Parse a comma-separated list of allowed emails.

    Args:
        raw: Comma-separated email string from settings.

    Returns:
        Set of stripped, lowercase email addresses.
    """
    return {e.strip().lower() for e in raw.split(",") if e.strip()}
