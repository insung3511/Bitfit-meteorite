"""App-level login for the personal web app (distinct from Google OAuth).

``POST /session/login`` checks the shared ``APP_PASSWORD`` and, on success, sets
an ``HttpOnly`` signed session cookie. Every other router in the app requires that
cookie via :func:`app.session.require_session` (wired in ``main.py``), so this is
the only route (besides ``/health``) an unauthenticated visitor can reach.
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel

from app.session import (
    SESSION_COOKIE_NAME,
    check_password,
    create_session_token,
    is_valid_token,
)

router = APIRouter(prefix="/session", tags=["session"])

_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days, matches session.py's token TTL.


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
def login(request: LoginRequest, response: Response) -> dict[str, bool]:
    """Verify the app password and set the session cookie on success."""
    try:
        ok = check_password(request.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not ok:
        raise HTTPException(status_code=401, detail="Incorrect password.")

    token = create_session_token()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        # Not marked Secure: this app is designed for localhost / a personal LAN
        # over plain HTTP by default. Put it behind HTTPS for anything else and
        # add `secure=True` here.
    )
    return {"authenticated": True}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    """Clear the session cookie."""
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"authenticated": False}


@router.get("/me")
def me(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, bool]:
    """Report whether the current request carries a valid session cookie.

    Deliberately does NOT use :func:`app.session.require_session` (that would
    401 instead of answering) — the frontend calls this on every page load to
    decide whether to show the login screen, so it needs a plain 200 always.
    """
    return {"authenticated": is_valid_token(session)}
