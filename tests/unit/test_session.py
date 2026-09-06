"""Tests for session cookie create/validate — pure."""

from __future__ import annotations

from podcast.auth.session import (
    create_session_cookie,
    validate_session_cookie,
)


def test_create_and_validate_roundtrip(secret_key: str) -> None:
    """Cookie created with email A validates back to email A."""
    raw = create_session_cookie("a@b.com", secret_key)
    assert validate_session_cookie(raw, secret_key) == "a@b.com"


def test_validate_wrong_key_returns_none(secret_key: str) -> None:
    """Cookie signed with key A fails validation with key B."""
    raw = create_session_cookie("a@b.com", secret_key)
    assert validate_session_cookie(raw, "other-key") is None


def test_validate_none_cookie_returns_none(secret_key: str) -> None:
    """None cookie returns None without raising."""
    assert validate_session_cookie(None, secret_key) is None


def test_validate_garbage_string_returns_none(secret_key: str) -> None:
    """Random string returns None."""
    assert validate_session_cookie("not-a-cookie", secret_key) is None


def _tamper(raw: str) -> str:
    """Tamper a signed token so verification must fail.

    Flips high bits of the first signature character. Tampering the
    last character is unreliable: trailing base64 bits can be padding,
    leaving the decoded bytes unchanged.
    """
    head, dot, tail = raw.rpartition(".")
    first = tail[0]
    replacement = "g" if first == "A" else "A"
    return head + dot + replacement + tail[1:]


def test_validate_tampered_cookie_returns_none(secret_key: str) -> None:
    """Tampering the signature invalidates the cookie."""
    raw = create_session_cookie("a@b.com", secret_key)
    assert validate_session_cookie(_tamper(raw), secret_key) is None


def test_validate_missing_email_key_returns_none(secret_key: str) -> None:
    """Payload without email field returns None instead of raising."""
    from podcast.auth.session import _serializer

    raw = _serializer(secret_key).dumps({"nope": 1})
    assert validate_session_cookie(raw, secret_key) is None


def test_validate_empty_dict_returns_none(secret_key: str) -> None:
    """Empty dict payload returns None instead of raising."""
    from podcast.auth.session import _serializer

    raw = _serializer(secret_key).dumps({})
    assert validate_session_cookie(raw, secret_key) is None


def test_create_returns_string(secret_key: str) -> None:
    """Create returns a non-empty string."""
    raw = create_session_cookie("a@b.com", secret_key)
    assert isinstance(raw, str) and len(raw) > 0
