"""Google OAuth2 web login flow using Authlib."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

__all__ = ["build_oauth_client"]

_GOOGLE_CONF_URL = (
    "https://accounts.google.com/.well-known/openid-configuration"
)


def build_oauth_client(client_id: str, client_secret: str) -> OAuth:
    """Construct and register the Google OAuth2 client.

    Args:
        client_id: Google OAuth2 application client ID.
        client_secret: Google OAuth2 application client secret.

    Returns:
        OAuth registry with 'google' client registered and server metadata
        loaded from the Google OpenID Connect discovery document.
    """
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=_GOOGLE_CONF_URL,
        client_kwargs={"scope": "openid email"},
    )
    return oauth
