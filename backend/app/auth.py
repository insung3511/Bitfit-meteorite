"""Google Health API OAuth2 (Authorization Code) flow — backend only.

The client secret and the encrypted refresh token never leave the server. The
browser only ever sees the authorization URL (redirect) and, on the way back,
the short-lived ``code`` — which is immediately exchanged here for tokens.

Endpoints and scopes are confirmed against the Google Health API docs
(migrated from the legacy Fitbit Web API, 2026):

* Setup / data access: https://developers.google.com/health/setup
* Migration + scopes:  https://developers.google.com/health/migration

Google Health uses standard Google OAuth 2.0, so the authorization and token
endpoints are the generic Google endpoints; only the scope strings are
Health-API specific.
"""

from __future__ import annotations

import datetime as dt
import os

from authlib.integrations.httpx_client import OAuth2Client
from cryptography.fernet import Fernet
from sqlmodel import Session, select

from app.db import engine
from app.models import OAuthToken

# --- OAuth endpoints (standard Google OAuth 2.0) ---------------------------
# Confirmed via developers.google.com/health/setup and /health/migration.
GOOGLE_HEALTH_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_HEALTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# --- Scopes (Google Health API) --------------------------------------------
# Health API scopes follow https://www.googleapis.com/auth/googlehealth.{scope}
# and are all "Restricted" (require Google's privacy/security review). These
# three read-only bundles cover the metrics this app ingests: steps / active
# zone minutes (activity_and_fitness), resting HR / HRV / SpO2 / weight
# (health_metrics_and_measurements), and sleep stages (sleep).
GOOGLE_HEALTH_SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
]
SCOPE_STRING = " ".join(GOOGLE_HEALTH_SCOPES)

PROVIDER = "google_health"

# Refresh a little before the real expiry to avoid racing the clock.
_EXPIRY_SKEW = dt.timedelta(seconds=60)

# --- Environment -----------------------------------------------------------
CLIENT_ID = os.getenv("GOOGLE_HEALTH_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_HEALTH_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv(
    "GOOGLE_HEALTH_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
)

# --- Token encryption ------------------------------------------------------
# Built once at import time from TOKEN_ENCRYPTION_KEY (a Fernet key). Generate
# one with ``python scripts/generate_key.py`` and put it in ``.env``.
_TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")
if not _TOKEN_ENCRYPTION_KEY:
    raise RuntimeError(
        "TOKEN_ENCRYPTION_KEY is not set. Generate one with "
        "`python scripts/generate_key.py` and add it to your .env file."
    )
fernet = Fernet(_TOKEN_ENCRYPTION_KEY.encode())


def encrypt_token(plaintext: str) -> bytes:
    """Encrypt a token string into a Fernet blob for storage at rest."""
    return fernet.encrypt(plaintext.encode())


def decrypt_token(blob: bytes) -> str:
    """Decrypt a Fernet blob back into the token string."""
    return fernet.decrypt(blob).decode()


def _oauth_client() -> OAuth2Client:
    """An authlib OAuth2 client configured for the Google Health API."""
    return OAuth2Client(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scope=SCOPE_STRING,
        redirect_uri=REDIRECT_URI,
        token_endpoint=GOOGLE_HEALTH_TOKEN_ENDPOINT,
    )


def build_authorization_url() -> tuple[str, str]:
    """Build the Google authorization URL and its CSRF ``state``.

    ``access_type=offline`` + ``prompt=consent`` force Google to issue a refresh
    token (and to re-issue one on every re-consent), which the backend needs to
    keep syncing without the user present.
    """
    client = _oauth_client()
    uri, state = client.create_authorization_url(
        GOOGLE_HEALTH_AUTH_ENDPOINT,
        access_type="offline",
        prompt="consent",
    )
    return uri, state


def _expires_at(token: dict) -> dt.datetime | None:
    """Derive an absolute UTC expiry from an authlib token dict."""
    expires_at = token.get("expires_at")
    if expires_at is not None:
        return dt.datetime.utcfromtimestamp(int(expires_at))
    expires_in = token.get("expires_in")
    if expires_in is not None:
        return dt.datetime.utcnow() + dt.timedelta(seconds=int(expires_in))
    return None


def exchange_code_for_tokens(code: str) -> OAuthToken:
    """Exchange an authorization ``code`` for tokens and persist them.

    Upserts the single ``google_health`` row (a personal single-user app only
    ever has one row per provider). The refresh token is encrypted before it
    touches the database.
    """
    client = _oauth_client()
    token = client.fetch_token(
        GOOGLE_HEALTH_TOKEN_ENDPOINT,
        grant_type="authorization_code",
        code=code,
    )

    refresh_token = token.get("refresh_token")
    if not refresh_token:
        # Without access_type=offline + prompt=consent Google omits it; without
        # a refresh token the backend cannot sync unattended.
        raise ValueError(
            "Google did not return a refresh token. Ensure access_type=offline "
            "and prompt=consent are sent, and that the user re-consented."
        )

    now = dt.datetime.utcnow()
    with Session(engine) as session:
        row = session.exec(
            select(OAuthToken).where(OAuthToken.provider == PROVIDER)
        ).first()
        if row is None:
            row = OAuthToken(
                provider=PROVIDER,
                encrypted_refresh_token=encrypt_token(refresh_token),
            )
        else:
            row.encrypted_refresh_token = encrypt_token(refresh_token)
        row.access_token = token.get("access_token")
        row.access_token_expires_at = _expires_at(token)
        row.updated_at = now
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def get_valid_access_token() -> str:
    """Return a currently-valid Google Health access token.

    Returns the cached access token while it is still fresh; otherwise refreshes
    it using the stored refresh token, persists the new access token (and the
    refresh token too, since Google may rotate it), and returns the new one.
    This is the entry point the sync job calls before hitting the Health API.
    """
    now = dt.datetime.utcnow()
    with Session(engine) as session:
        row = session.exec(
            select(OAuthToken).where(OAuthToken.provider == PROVIDER)
        ).first()
        if row is None:
            raise RuntimeError(
                "No stored Google Health token. Complete the OAuth flow at "
                "/auth/google/login first."
            )

        if (
            row.access_token
            and row.access_token_expires_at
            and row.access_token_expires_at - _EXPIRY_SKEW > now
        ):
            return row.access_token

        client = _oauth_client()
        new_token = client.refresh_token(
            GOOGLE_HEALTH_TOKEN_ENDPOINT,
            refresh_token=decrypt_token(row.encrypted_refresh_token),
        )

        access_token = new_token.get("access_token")
        if not access_token:
            raise RuntimeError("Token refresh did not return an access token.")

        # Google may rotate the refresh token on refresh — always overwrite both.
        rotated_refresh = new_token.get("refresh_token")
        if rotated_refresh:
            row.encrypted_refresh_token = encrypt_token(rotated_refresh)
        row.access_token = access_token
        row.access_token_expires_at = _expires_at(new_token)
        row.updated_at = dt.datetime.utcnow()
        session.add(row)
        session.commit()
        return access_token
