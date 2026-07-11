"""Lightweight cookie session auth for the personal web app.

This is a single-user app with no need for a user table or full auth system —
just a shared-secret gate so the app isn't wide open on the network. Logging in
with ``APP_PASSWORD`` sets a signed, expiring cookie; :func:`require_session` is
a FastAPI dependency applied to every route that shouldn't be reachable by an
unauthenticated visitor.

The cookie value is ``"<expiry_unix>.<hmac_hex>"`` where the HMAC (SHA-256, keyed
by ``SESSION_SECRET``) covers the expiry so the cookie can't be forged or extended
by a client that doesn't know the secret.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import Cookie, HTTPException

SESSION_COOKIE_NAME = "health_assistant_session"
_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days — a personal app, not a bank.

APP_PASSWORD = os.getenv("APP_PASSWORD", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")


def _sign(expiry: int) -> str:
    return hmac.new(
        SESSION_SECRET.encode(), str(expiry).encode(), hashlib.sha256
    ).hexdigest()


def create_session_token() -> str:
    """Create a signed, expiring session token for the login-success cookie."""
    if not SESSION_SECRET:
        raise RuntimeError(
            "SESSION_SECRET is not set. Generate one with "
            "`python scripts/generate_key.py` and add it to your .env file."
        )
    expiry = int(time.time()) + _SESSION_TTL_SECONDS
    return f"{expiry}.{_sign(expiry)}"


def is_valid_token(token: str | None) -> bool:
    """Check a session cookie value for validity (expiry + signature)."""
    if not token:
        return False
    try:
        expiry_str, signature = token.split(".", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False
    if expiry < int(time.time()):
        return False
    return hmac.compare_digest(signature, _sign(expiry))


def require_session(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> None:
    """FastAPI dependency: 401s unless a valid session cookie is present."""
    if not is_valid_token(session):
        raise HTTPException(status_code=401, detail="Not authenticated.")


def check_password(password: str) -> bool:
    """Constant-time comparison against ``APP_PASSWORD``."""
    if not APP_PASSWORD:
        raise RuntimeError(
            "APP_PASSWORD is not set. Add it to your .env file to enable login."
        )
    return hmac.compare_digest(password, APP_PASSWORD)
