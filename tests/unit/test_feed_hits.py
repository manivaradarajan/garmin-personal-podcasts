"""Tests for the feed hit log — InMemoryBlobStore, no I/O."""

from __future__ import annotations

import json

from podcast.feed.hits import read_feed_hits, record_feed_hit
from tests.conftest import InMemoryBlobStore


def test_read_hits_empty_when_absent() -> None:
    """No hits blob yields an empty list."""
    assert read_feed_hits(InMemoryBlobStore()) == []


def test_record_then_read_roundtrips() -> None:
    """Recorded hit reads back with timestamp, UA, and status."""
    store = InMemoryBlobStore()
    record_feed_hit(store, "PlayRun/1.0", 200)
    (hit,) = read_feed_hits(store)
    assert hit.user_agent == "PlayRun/1.0" and hit.status == 200
    assert hit.timestamp.endswith("Z")


def test_missing_user_agent_recorded_as_dash() -> None:
    """None User-Agent is stored as a dash, not null."""
    store = InMemoryBlobStore()
    record_feed_hit(store, None, 403)
    (hit,) = read_feed_hits(store)
    assert hit.user_agent == "-" and hit.status == 403


def test_user_agent_is_truncated() -> None:
    """Overlong User-Agent values are capped."""
    store = InMemoryBlobStore()
    record_feed_hit(store, "x" * 500, 200)
    (hit,) = read_feed_hits(store)
    assert len(hit.user_agent) <= 120


def test_hits_capped_at_fifty() -> None:
    """Only the newest 50 hits are retained."""
    store = InMemoryBlobStore()
    for i in range(55):
        record_feed_hit(store, f"ua-{i}", 200)
    hits = read_feed_hits(store)
    assert len(hits) == 50
    assert hits[0].user_agent == "ua-5"
    assert hits[-1].user_agent == "ua-54"


def test_malformed_hits_blob_returns_empty() -> None:
    """Garbage bytes yield an empty list, not an exception."""
    store = InMemoryBlobStore()
    store.write("feed-hits.json", b"{nope", 60)
    assert read_feed_hits(store) == []


def test_record_failure_never_raises() -> None:
    """Broken backend does not propagate out of record."""

    class _Broken(InMemoryBlobStore):
        def write(self, path: str, data: bytes, cache: int) -> None:
            raise RuntimeError("boom")

        def read(self, path: str, use_cache: bool = True):
            raise RuntimeError("boom")

    record_feed_hit(_Broken(), "ua", 200)


def test_token_never_stored() -> None:
    """Raw blob content must not contain a token value."""
    store = InMemoryBlobStore()
    record_feed_hit(store, "ua", 200)
    raw = store.read("feed-hits.json")
    assert raw is not None
    assert "token" not in json.loads(raw)["entries"][0]
