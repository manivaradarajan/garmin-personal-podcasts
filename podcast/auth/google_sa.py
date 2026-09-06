"""Google Service Account credentials for Drive API access."""

from __future__ import annotations

import base64
import json

from google.oauth2 import service_account

__all__ = ["build_drive_credentials"]

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def build_drive_credentials(
    sa_json_b64: str,
) -> service_account.Credentials:
    """Decode base64 Service Account JSON into Drive credentials.

    Args:
        sa_json_b64: Base64-encoded Service Account JSON key string.

    Returns:
        Scoped service account credentials for the Drive API.

    Raises:
        ValueError: If the base64 string cannot be decoded or parsed as JSON.
    """
    try:
        raw = base64.b64decode(sa_json_b64)
    except Exception as exc:
        raise ValueError("GOOGLE_SA_JSON_B64 is not valid base64") from exc

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = "Decoded GOOGLE_SA_JSON_B64 is not valid JSON"
        raise ValueError(msg) from exc

    return service_account.Credentials.from_service_account_info(
        info, scopes=_DRIVE_SCOPES
    )
