"""FastAPI dependencies — Settings, BlobStore, DriveClient providers."""

from __future__ import annotations

from fastapi import Depends

from podcast.auth.google_sa import build_drive_credentials
from podcast.blob.client import VercelBlobStore
from podcast.blob.protocol import BlobStore
from podcast.config import Settings
from podcast.drive.client import DriveClient

__all__ = ["get_blob_store", "get_drive_client", "get_settings"]


def get_settings() -> Settings:
    """Return application settings from the environment.

    Returns:
        Loaded Settings instance.
    """
    return Settings()


def get_blob_store(
    settings: Settings = Depends(get_settings),
) -> BlobStore:
    """Return the BlobStore backed by Vercel Blob.

    Args:
        settings: Application settings (injected).

    Returns:
        Configured VercelBlobStore.
    """
    return VercelBlobStore(settings.blob_read_write_token)


def get_drive_client(
    settings: Settings = Depends(get_settings),
) -> DriveClient:
    """Return an authenticated Drive client.

    Args:
        settings: Application settings (injected).

    Returns:
        DriveClient for the configured folder.
    """
    creds = build_drive_credentials(settings.google_sa_json_b64)
    return DriveClient(creds, settings.google_drive_folder_id)
