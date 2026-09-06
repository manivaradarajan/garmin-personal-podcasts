"""Application configuration — all environment variables typed here."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings"]


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables.

    All secrets and configuration are declared here. No other module
    reads environment variables directly.
    """

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Vercel injects its own vars (VERCEL_OIDC_TOKEN, ...) into the
        # runtime environment; reject nothing we don't recognize.
        extra="ignore",
    )

    # Google Drive Service Account
    google_sa_json_b64: str
    google_drive_folder_id: str

    # Vercel Blob
    blob_read_write_token: str
    blob_quota_mb: int = 500

    # RSS feed auth
    feed_secret_token: str

    # Podcast metadata
    podcast_title: str = "My Garmin Podcasts"
    podcast_base_url: str = "http://localhost:3000"

    # Google OAuth (web dashboard login)
    google_oauth_client_id: str
    google_oauth_client_secret: str
    allowed_emails: str  # Comma-separated list

    # Session signing
    session_secret_key: str
