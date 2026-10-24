"""Verify Google Sign-In ID tokens.

The client (Expo app) signs in with Google and sends us the resulting ID token.
We verify its signature against Google's public keys and check the audience
matches one of our configured OAuth client IDs, then trust the claims inside.
"""

import logging

from flask import current_app
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from ..errors import ApiError

log = logging.getLogger(__name__)

_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# One transport/session reused across requests (fetches and caches Google's certs).
_request = google_requests.Request()


class GoogleIdentity:
    __slots__ = ("sub", "email", "email_verified", "name", "picture")

    def __init__(self, claims: dict):
        self.sub: str = claims["sub"]
        self.email: str | None = claims.get("email")
        self.email_verified: bool = bool(claims.get("email_verified"))
        self.name: str | None = claims.get("name")
        self.picture: str | None = claims.get("picture")


def verify_google_id_token(token: str) -> GoogleIdentity:
    client_ids = current_app.config["GOOGLE_CLIENT_IDS"]
    if not client_ids:
        raise ApiError(503, "GOOGLE_NOT_CONFIGURED", "Google Sign-In is not enabled on this server.")

    try:
        # Passing audience=None lets us accept any of our client IDs (Android/iOS/Web),
        # which we check explicitly below. Signature + expiry are always verified.
        claims = google_id_token.verify_oauth2_token(token, _request)
    except ValueError as e:
        log.warning("Google ID token rejected: %s", e)
        raise ApiError(401, "GOOGLE_TOKEN_INVALID", "Could not verify Google sign-in. Try again.")

    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise ApiError(401, "GOOGLE_TOKEN_INVALID", "Could not verify Google sign-in. Try again.")
    if claims.get("aud") not in client_ids:
        log.warning("Google ID token audience mismatch: %s", claims.get("aud"))
        raise ApiError(401, "GOOGLE_TOKEN_INVALID", "Could not verify Google sign-in. Try again.")
    if not claims.get("sub"):
        raise ApiError(401, "GOOGLE_TOKEN_INVALID", "Could not verify Google sign-in. Try again.")

    return GoogleIdentity(claims)
