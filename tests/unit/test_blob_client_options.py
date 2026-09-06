"""Tests for VercelBlobStore option encoding — vercel_blob API contract."""

from __future__ import annotations

import vercel_blob

from podcast.blob.client import VercelBlobStore


def test_upload_sends_string_options(monkeypatch) -> None:
    """upload() passes header-safe string options to vercel_blob.put."""
    captured: dict[str, dict] = {}

    def _fake_put(path: str, data: bytes, options: dict, **kwargs):
        captured["options"] = options
        return {"url": "https://blob.test/ep.mp3"}

    monkeypatch.setattr(vercel_blob, "put", _fake_put)
    store = VercelBlobStore("tok")
    url = store.upload("ep.mp3", b"data", "audio/mpeg", 86400)
    assert url == "https://blob.test/ep.mp3"
    options = captured["options"]
    assert options["cacheControlMaxAge"] == "86400"
    assert options["addRandomSuffix"] == "false"
    assert options["allowOverwrite"] == "true"
    assert all(isinstance(v, str) for v in options.values())


def test_write_allows_overwrite_with_string_options(monkeypatch) -> None:
    """write() sets allowOverwrite so stable paths can be rewritten."""
    captured: dict[str, dict] = {}

    def _fake_put(path: str, data: bytes, options: dict, **kwargs):
        captured["options"] = options
        return {"url": "https://blob.test/manifest.json"}

    monkeypatch.setattr(vercel_blob, "put", _fake_put)
    store = VercelBlobStore("tok")
    store.write("manifest.json", b"{}", 60)
    options = captured["options"]
    assert options["allowOverwrite"] == "true"
    assert options["cacheControlMaxAge"] == "60"


def test_large_upload_uses_multipart(monkeypatch) -> None:
    """Payloads over the threshold upload with multipart enabled."""
    captured: dict[str, dict] = {}

    def _fake_put(path: str, data: bytes, options: dict, **kwargs):
        captured["kwargs"] = kwargs
        return {"url": "https://blob.test/big.mp3"}

    monkeypatch.setattr(vercel_blob, "put", _fake_put)
    store = VercelBlobStore("tok")
    store.upload("big.mp3", b"x" * (11 * 1024 * 1024), "audio/mpeg", 300)
    assert captured["kwargs"].get("multipart") is True


def test_small_upload_skips_multipart(monkeypatch) -> None:
    """Small payloads upload without multipart."""
    captured: dict[str, dict] = {}

    def _fake_put(path: str, data: bytes, options: dict, **kwargs):
        captured["kwargs"] = kwargs
        return {"url": "https://blob.test/small.mp3"}

    monkeypatch.setattr(vercel_blob, "put", _fake_put)
    store = VercelBlobStore("tok")
    store.upload("small.mp3", b"x", "audio/mpeg", 300)
    assert captured["kwargs"].get("multipart") is False
