"""Signed session cookie create/validate using itsdangerous."""

from __future__ import annotations

import itsdangerous
from itsdangerous import URLSafeTimedSerializer

__all__ = ["create_session_cookie", "validate_session_cookie"]

_SALT = "session"
_MAX_AGE_SECONDS = 86400  # 24 hours


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    """Build a timed serializer for the given secret key.

    Args:
        secret_key: Application secret key from Settings.

    Returns:
        Configured URLSafeTimedSerializer instance.
    """
    return URLSafeTimedSerializer(secret_key, salt=_SALT)


def create_session_cookie(email: str, secret_key: str) -> str:
    """Create a signed session cookie value containing the user's email.

    Args:
        email: Authenticated user's email address.
        secret_key: Application secret key for signing.

    Returns:
        Signed cookie string suitable for setting as an HTTP cookie value.
    """
    return _serializer(secret_key).dumps({"email": email})


def validate_session_cookie(raw: str | None, secret_key: str) -> str | None:
    """Validate a signed session cookie and return the email it contains.

    All itsdangerous failure modes are caught; invalid cookies return None.

    Args:
        raw: Raw cookie value from the request, or None if absent.
        secret_key: Application secret key used to verify the signature.

    Returns:
        Email address if the cookie is valid and unexpired, else None.
    """
    if raw is None:
        return None
    try:
        data = _serializer(secret_key).loads(raw, max_age=_MAX_AGE_SECONDS)
        email = data.get("email") if isinstance(data, dict) else None
        return email if email else None
    except (
        itsdangerous.SignatureExpired,
        itsdangerous.BadSignature,
        itsdangerous.BadData,
    ):
        return None
