"""Tests for sync lock acquire/release with InMemoryBlobStore."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from podcast.sync.engine import (
    LockHeldError,
    _acquire_lock,
    _release_lock,
    is_sync_locked,
)
from tests.conftest import InMemoryBlobStore


def _fresh_lock() -> bytes:
    """Return a lock timestamp 10 seconds old."""
    stamp = datetime.now(UTC) - timedelta(seconds=10)
    return stamp.isoformat().encode()


def _stale_lock() -> bytes:
    """Return a lock timestamp 6 minutes old."""
    stamp = datetime.now(UTC) - timedelta(minutes=6)
    return stamp.isoformat().encode()


def test_acquire_when_no_lock_succeeds() -> None:
    """No existing lock writes one and returns."""
    store = InMemoryBlobStore()
    _acquire_lock(store)
    assert is_sync_locked(store) is True


def test_acquire_when_fresh_lock_raises_lock_held_error() -> None:
    """Ten-second-old lock raises LockHeldError."""
    store = InMemoryBlobStore()
    store.write("sync.lock", _fresh_lock(), 0)
    with pytest.raises(LockHeldError):
        _acquire_lock(store)


def test_acquire_when_stale_lock_overwrites() -> None:
    """Six-minute-old lock is overwritten without error."""
    store = InMemoryBlobStore()
    store.write("sync.lock", _stale_lock(), 0)
    _acquire_lock(store)
    assert is_sync_locked(store) is True


def test_acquire_when_corrupt_lock_overwrites() -> None:
    """Non-ISO bytes are treated as absent and overwritten."""
    store = InMemoryBlobStore()
    store.write("sync.lock", b"garbage", 0)
    _acquire_lock(store)
    assert is_sync_locked(store) is True


def test_release_lock_swallows_exceptions() -> None:
    """Broken write backend does not raise on release."""

    class _Broken(InMemoryBlobStore):
        def write(self, path: str, data: bytes, cache: int) -> None:
            raise RuntimeError("boom")

    _release_lock(_Broken())


def test_is_sync_locked_false_after_release() -> None:
    """Released (stale) lock reports not locked."""
    store = InMemoryBlobStore()
    _acquire_lock(store)
    _release_lock(store)
    assert is_sync_locked(store) is False


def test_is_sync_locked_false_when_absent() -> None:
    """Missing lock blob reports not locked."""
    assert is_sync_locked(InMemoryBlobStore()) is False
