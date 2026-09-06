"""Tests for Service Account credential builder — pure."""

from __future__ import annotations

import base64

import pytest

from podcast.auth.google_sa import build_drive_credentials


def test_invalid_base64_raises_value_error() -> None:
    """Non-base64 input raises ValueError mentioning base64."""
    with pytest.raises(ValueError, match="base64"):
        build_drive_credentials("not-base64!!")


def test_valid_b64_invalid_json_raises_value_error() -> None:
    """Base64 of non-JSON raises ValueError mentioning JSON."""
    raw = base64.b64encode(b"not json").decode()
    with pytest.raises(ValueError, match="JSON"):
        build_drive_credentials(raw)


def test_valid_b64_empty_json_raises() -> None:
    """Base64 of {} raises from the Google library (not silent)."""
    raw = base64.b64encode(b"{}").decode()
    with pytest.raises(Exception):
        build_drive_credentials(raw)
