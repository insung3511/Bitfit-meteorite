"""OAuth2 routes for connecting the Google Health account (backend only).

Flow:

1. Browser hits ``GET /auth/google/login`` → 307 redirect to Google's consent
   screen (the client secret never leaves the server).
2. Google redirects back to ``GET /auth/google/callback?code=...&state=...`` →
   the code is exchanged for tokens server-side and the refresh token is stored
   encrypted.

The CSRF ``state`` is stored as a one-time, expiring database record bound to
the initiating local session, so concurrent logins and restarts are safe.
"""

from __future__ import annotations

import datetime as dt
import hashlib

from fastapi import APIRouter, Cookie, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlmodel import Session, delete, select

from app import auth
from app.db import engine
from app.models import OAuthState
from app.session import SESSION_COOKIE_NAME

router = APIRouter(prefix="/auth/google", tags=["auth"])

_STATE_TTL = dt.timedelta(minutes=10)


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


@router.get("/login")
def login(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> RedirectResponse:
    """Redirect the browser to Google's OAuth2 consent screen."""
    url, state = auth.build_authorization_url()
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    now = dt.datetime.utcnow()
    with Session(engine) as db:
        db.exec(delete(OAuthState).where(OAuthState.expires_at <= now))
        db.add(
            OAuthState(
                state_hash=_state_hash(state),
                session_token=session_token,
                expires_at=now + _STATE_TTL,
            )
        )
        db.commit()
    return RedirectResponse(url)


@router.get("/callback")
def callback(
    code: str = Query(...),
    state: str = Query(...),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, str]:
    """Handle Google's redirect: verify state, exchange code, store tokens."""
    now = dt.datetime.utcnow()
    with Session(engine) as db:
        pending = db.exec(
            select(OAuthState).where(OAuthState.state_hash == _state_hash(state))
        ).first()
        if (
            pending is None
            or pending.expires_at <= now
            or pending.session_token != session_token
        ):
            raise HTTPException(status_code=400, detail="Invalid or expired state.")
        db.delete(pending)  # One-time use; commit before exchanging the code.
        db.commit()

    try:
        auth.exchange_code_for_tokens(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "connected", "provider": auth.PROVIDER}
