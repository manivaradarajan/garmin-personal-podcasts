"""Tests for email allowlist parsing and OAuth state — pure."""

from __future__ import annotations

from podcast.web.auth_routes import _validate_state
from podcast.web.middleware import parse_allowed_emails


def test_single_email_parsed() -> None:
    """Single email yields a one-element set."""
    assert parse_allowed_emails("a@b.com") == {"a@b.com"}


def test_multiple_emails_parsed() -> None:
    """Comma-separated pair yields both addresses."""
    assert parse_allowed_emails("a@b.com, c@d.com") == {
        "a@b.com",
        "c@d.com",
    }


def test_whitespace_stripped() -> None:
    """Surrounding whitespace is stripped."""
    assert parse_allowed_emails("  a@b.com  ") == {"a@b.com"}


def test_uppercase_normalized() -> None:
    """Uppercase addresses are lowercased."""
    assert parse_allowed_emails("A@B.COM") == {"a@b.com"}


def test_empty_string_returns_empty_set() -> None:
    """Empty string yields an empty set."""
    assert parse_allowed_emails("") == set()


def _signed_state(state: str, key: str) -> str:
    """Sign a state value with the oauth_state serializer."""
    from podcast.web.auth_routes import _state_serializer

    return _state_serializer(key).dumps(state)


def test_valid_state_returns_true(secret_key: str) -> None:
    """Matching signed cookie and query state validates."""
    signed = _signed_state("abc", secret_key)
    assert _validate_state(signed, "abc", secret_key) is True


def test_mismatched_state_returns_false(secret_key: str) -> None:
    """Signed state A with query state B fails."""
    signed = _signed_state("aaa", secret_key)
    assert _validate_state(signed, "bbb", secret_key) is False


def test_missing_cookie_returns_false(secret_key: str) -> None:
    """None cookie fails validation."""
    assert _validate_state(None, "abc", secret_key) is False


def test_tampered_cookie_returns_false(secret_key: str) -> None:
    """Tampering the signature segment fails validation."""
    signed = _signed_state("abc", secret_key)
    head, dot, tail = signed.rpartition(".")
    first = tail[0]
    bad = head + dot + ("g" if first == "A" else "A") + tail[1:]
    assert _validate_state(bad, "abc", secret_key) is False
