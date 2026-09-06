"""Google Drive client — list and stream audio files."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from podcast.models import DriveFile

__all__ = ["DriveClient", "DriveListError"]

_LOG = logging.getLogger(__name__)

_AUDIO_MIME_TYPES = (
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "audio/wav",
    "audio/flac",
    "audio/aac",
    "audio/x-m4a",
)
_PAGE_SIZE = 100
_LIST_FIELDS = "nextPageToken,files(id,name,mimeType,size,md5Checksum)"


class DriveListError(Exception):
    """Raised when a Drive file-listing page request fails."""


class DriveClient:
    """Client for listing and streaming audio files from a Drive folder.

    Args:
        credentials: Authenticated Google service account credentials.
        folder_id: Drive folder ID to list audio files from.
    """

    def __init__(
        self,
        credentials: service_account.Credentials,
        folder_id: str,
    ) -> None:
        """Initialise the Drive API service.

        Args:
            credentials: Authenticated Google service account credentials.
            folder_id: Drive folder ID to list audio files from.
        """
        self._folder_id = folder_id
        self._service = build("drive", "v3", credentials=credentials)

    def list_audio_files(self) -> list[DriveFile]:
        """List all audio files in the configured folder.

        Pages through the full listing; raises DriveListError on any page
        failure so the caller can abort the sync rather than proceed with a
        partial result.

        Returns:
            All audio files found in the folder.

        Raises:
            DriveListError: If any Drive API page request fails.
        """
        query = (
            f"'{self._folder_id}' in parents"
            " and trashed = false"
            " and ("
            + " or ".join(f"mimeType = '{m}'" for m in _AUDIO_MIME_TYPES)
            + ")"
        )
        files: list[DriveFile] = []
        page_token: str | None = None

        while True:
            try:
                response = self._fetch_page(query, page_token)
            except Exception as exc:
                raise DriveListError(f"Drive listing failed: {exc}") from exc

            for item in response.get("files", []):
                drive_file = _parse_drive_item(item)
                if drive_file is not None:
                    files.append(drive_file)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return files

    def stream_file(self, file_id: str) -> Iterator[bytes]:
        """Stream audio file content from Drive in chunks.

        Args:
            file_id: Drive file ID to download.

        Yields:
            Chunks of file content as bytes.

        Raises:
            Exception: If the download request fails.
        """
        import io

        request = self._service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request, chunksize=1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buffer.seek(0)
        while True:
            chunk = buffer.read(1024 * 1024)
            if not chunk:
                break
            yield chunk

    def _fetch_page(self, query: str, page_token: str | None) -> dict[str, Any]:
        """Execute one Drive files.list page request.

        Args:
            query: Drive query string.
            page_token: Pagination token from previous page, or None for first.

        Returns:
            Raw Drive API response dict.
        """
        kwargs: dict[str, Any] = {
            "q": query,
            "pageSize": _PAGE_SIZE,
            "fields": _LIST_FIELDS,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        return self._service.files().list(**kwargs).execute()


# ---


def _parse_drive_item(item: dict[str, Any]) -> DriveFile | None:
    """Convert a raw Drive API item dict to a DriveFile.

    Returns None and logs a warning if required fields are missing.

    Args:
        item: Raw item dict from Drive API response.

    Returns:
        Parsed DriveFile, or None if required fields are absent.
    """
    file_id = item.get("id")
    name = item.get("name")
    mime_type = item.get("mimeType")
    md5 = item.get("md5Checksum")
    size_str = item.get("size")

    if not all([file_id, name, mime_type, md5, size_str]):
        _LOG.warning("Skipping Drive item with missing fields: %s", item)
        return None

    try:
        size_bytes = int(size_str)
    except TypeError, ValueError:
        _LOG.warning("Skipping Drive item with invalid size: %s", item)
        return None

    return DriveFile(
        id=file_id,
        name=name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        md5=md5,
    )
