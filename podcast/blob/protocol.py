"""BlobStore typing.Protocol — defines the storage interface."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from podcast.models import ManifestEntry

__all__ = ["BlobStore"]


@runtime_checkable
class BlobStore(Protocol):
    """Interface for Blob storage operations.

    All consuming modules depend on this protocol, not on the concrete
    implementation, so swapping the backend requires changing only one file.
    """

    def upload(
        self,
        path: str,
        data: bytes | Iterator[bytes],
        mime_type: str,
        cache_max_age: int,
    ) -> str:
        """Upload data to Blob storage and return the public URL.

        Args:
            path: Destination path / filename within the store.
            data: File content as bytes or a bytes iterator.
            mime_type: Declared MIME type (implementations may guess
                from the path extension instead).
            cache_max_age: Cache-Control max-age in seconds.

        Returns:
            Public URL of the uploaded object.
        """
        ...

    def delete(self, url: str) -> None:
        """Delete a Blob object by its public URL.

        Args:
            url: Public URL of the object to delete.
        """
        ...

    def read(self, path: str, use_cache: bool = True) -> bytes | None:
        """Read a Blob object by path.

        Args:
            path: Path / filename within the store.
            use_cache: If False, bypass CDN cache.

        Returns:
            Object content as bytes, or None if the object does not exist.
        """
        ...

    def write(self, path: str, data: bytes, cache_max_age: int) -> None:
        """Write bytes to a Blob path (creates or overwrites).

        Args:
            path: Destination path / filename within the store.
            data: Content to write.
            cache_max_age: Cache-Control max-age in seconds.
        """
        ...

    def read_manifest(self) -> list[ManifestEntry]:
        """Read and deserialise the manifest from Blob storage.

        Returns:
            List of ManifestEntry records, or an empty list if absent.
        """
        ...

    def write_manifest(self, entries: list[ManifestEntry]) -> None:
        """Serialise and write the manifest to Blob storage.

        Args:
            entries: Current list of synced file entries.
        """
        ...
