"""Vercel Blob implementation of BlobStore."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime

import httpx
import vercel_blob

from podcast.models import ManifestEntry

__all__ = ["VercelBlobStore"]

_LOG = logging.getLogger(__name__)
_MANIFEST_PATH = "manifest.json"
_MANIFEST_CACHE_MAX_AGE = 60  # seconds


class VercelBlobStore:
    """BlobStore backed by Vercel Blob storage.

    Args:
        token: Vercel Blob read-write token.
    """

    def __init__(self, token: str) -> None:
        """Initialise the store with the given token.

        Args:
            token: Vercel Blob read-write token.
        """
        self._token = token

    def upload(
        self,
        path: str,
        data: bytes | Iterator[bytes],
        mime_type: str,
        cache_max_age: int,
    ) -> str:
        """Upload data to Vercel Blob and return the public URL.

        Uploads overwrite in place at a stable path (no random suffix)
        so enclosure URLs never change across re-uploads — downstream
        clients cache episode URLs aggressively. PUTs are atomic, so
        readers see the old or new object, never a mix.

        Args:
            path: Destination path within the store (stable per file).
            data: File content as bytes or a bytes iterator.
            mime_type: MIME type of the uploaded content.
            cache_max_age: Cache-Control max-age in seconds.

        Returns:
            Public URL of the uploaded object.
        """
        if isinstance(data, Iterator):
            data = b"".join(data)

        # vercel_blob >= 0.4 sends options as HTTP headers: all values
        # must be strings. contentType is not honored (MIME is guessed
        # from the path extension); the canonical type lives in the
        # manifest entry written by the sync engine.
        result = vercel_blob.put(
            path,
            data,
            {
                "token": self._token,
                "cacheControlMaxAge": str(cache_max_age),
                "access": "public",
                "addRandomSuffix": "false",
                "allowOverwrite": "true",
            },
        )
        return result["url"]

    def delete(self, url: str) -> None:
        """Delete a Blob object by its public URL.

        Args:
            url: Public URL of the object to delete.
        """
        vercel_blob.delete(url, {"token": self._token})

    def read(self, path: str, use_cache: bool = True) -> bytes | None:
        """Read a Blob object by path.

        Uses vercel_blob.list to resolve the path to a URL, then fetches
        the content via HTTP. Returns None if no blob with the given path
        prefix is found.

        Args:
            path: Path / filename within the store.
            use_cache: If False, adds a cache-busting query parameter.

        Returns:
            Object content as bytes, or None if the object does not exist.
        """
        url = self._resolve_url(path)
        if url is None:
            return None

        if use_cache:
            params: dict[str, str] = {}
        else:
            params = {"_cb": str(int(datetime.now(UTC).timestamp()))}
        try:
            response = httpx.get(url, params=params, follow_redirects=True)
        except httpx.RequestError as exc:
            _LOG.warning("Failed to fetch blob %s: %s", path, exc)
            return None
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content

    def write(self, path: str, data: bytes, cache_max_age: int) -> None:
        """Write bytes to a Blob path (creates or overwrites).

        Uses addRandomSuffix=False so the blob URL is stable across writes.
        Repeated calls to write() with the same path overwrite the existing
        content at the same URL.

        Args:
            path: Destination filename within the store.
            data: Content to write.
            cache_max_age: Cache-Control max-age in seconds.
        """
        vercel_blob.put(
            path,
            data,
            {
                "token": self._token,
                "cacheControlMaxAge": str(cache_max_age),
                "access": "public",
                "addRandomSuffix": "false",
                "allowOverwrite": "true",
            },
        )

    def read_manifest(self) -> list[ManifestEntry]:
        """Read and deserialise the manifest from Blob storage.

        Returns:
            List of ManifestEntry records, or an empty list if absent.
        """
        raw = self.read(_MANIFEST_PATH, use_cache=False)
        if raw is None:
            return []
        try:
            payload = json.loads(raw)
            return [ManifestEntry(**e) for e in payload.get("entries", [])]
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            _LOG.error("Failed to parse manifest: %s", exc)
            return []

    def write_manifest(self, entries: list[ManifestEntry]) -> None:
        """Serialise and write the manifest to Blob storage.

        Args:
            entries: Current list of synced file entries.
        """
        payload = {
            "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entries": [asdict(e) for e in entries],
        }
        self.write(
            _MANIFEST_PATH,
            json.dumps(payload, indent=2).encode(),
            _MANIFEST_CACHE_MAX_AGE,
        )

    # ---

    def _resolve_url(self, path: str) -> str | None:
        """Find the public URL for a blob by its path prefix.

        Args:
            path: Exact pathname to look up via vercel_blob.list.

        Returns:
            Public URL of the first matching blob, or None if not found.
        """
        try:
            result = vercel_blob.list(
                {"prefix": path, "token": self._token, "limit": 1}
            )
            blobs = result.get("blobs", [])
            if blobs:
                return blobs[0]["url"]
            return None
        except Exception as exc:
            _LOG.warning("Failed to list blob %s: %s", path, exc)
            return None
