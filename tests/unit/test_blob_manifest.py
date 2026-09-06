"""Tests for manifest read/write with InMemoryBlobStore."""

from __future__ import annotations

import json

from tests.conftest import InMemoryBlobStore


def test_read_manifest_returns_empty_when_absent() -> None:
    """No manifest blob yields an empty list."""
    assert InMemoryBlobStore().read_manifest() == []


def test_write_then_read_manifest_roundtrips(
    sample_manifest_entry,
) -> None:
    """Written entries read back equal."""
    store = InMemoryBlobStore()
    store.write_manifest([sample_manifest_entry])
    assert store.read_manifest() == [sample_manifest_entry]


def test_read_manifest_with_malformed_json_returns_empty() -> None:
    """Garbage bytes yield an empty list."""
    store = InMemoryBlobStore()
    store.write("manifest.json", b"{not json", 60)
    assert store.read_manifest() == []


def test_read_manifest_with_missing_entries_key_returns_empty() -> None:
    """Object without entries key yields an empty list."""
    store = InMemoryBlobStore()
    store.write("manifest.json", json.dumps({"updated_at": "x"}).encode(), 60)
    assert store.read_manifest() == []


def test_write_manifest_includes_updated_at(
    sample_manifest_entry,
) -> None:
    """Written JSON contains an updated_at key."""
    store = InMemoryBlobStore()
    store.write_manifest([sample_manifest_entry])
    raw = store.read("manifest.json")
    assert raw is not None
    assert "updated_at" in json.loads(raw)


def test_manifest_entry_fields_survive_roundtrip(
    sample_manifest_entry,
) -> None:
    """All seven fields survive a write/read cycle exactly."""
    store = InMemoryBlobStore()
    store.write_manifest([sample_manifest_entry])
    (back,) = store.read_manifest()
    assert back == sample_manifest_entry
