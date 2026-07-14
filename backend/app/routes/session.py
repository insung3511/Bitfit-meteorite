"""App-level login for the personal web app (distinct from Google OAuth).

``POST /session/login`` checks the shared ``APP_PASSWORD`` and, on success, sets
an ``HttpOnly`` signed session cookie. Every other router in the app requires that
cookie via :func:`app.session.require_session` (wired in ``main.py``), so this is
the only route (besides ``/health``) an unauthenticated visitor can reach.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from sqlmodel import Session, delete, select
from pydantic import BaseModel

from app.session import (
    SESSION_COOKIE_NAME,
    check_password,
    create_session_token,
    is_valid_token,
)

router = APIRouter(prefix="/session", tags=["session"])

_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days, matches session.py's token TTL.
_LOGIN_WINDOW = dt.timedelta(minutes=5)
_LOGIN_MAX_FAILURES = 5
_LOGIN_MAX_BACKOFF_SECONDS = 60 * 60


def _client_key(client_id: str) -> str:
    return hashlib.sha256(client_id.encode("utf-8")).hexdigest()


def _check_login_rate_limit(
    client_id: str, now: dt.datetime | None = None
) -> None:
    """Reject a client while its persistent progressive backoff is active."""
    from app.db import engine, init_db
    from app.models import LoginThrottle

    init_db()
    current = now or dt.datetime.utcnow()
    with Session(engine) as session:
        throttle = session.get(LoginThrottle, _client_key(client_id))
    if throttle and throttle.blocked_until and throttle.blocked_until > current:
        retry_after = max(
            1, math.ceil((throttle.blocked_until - current).total_seconds())
        )
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def _record_login_result(
    client_id: str, succeeded: bool, now: dt.datetime | None = None
) -> None:
    from app.db import engine, init_db
    from app.models import LoginThrottle

    init_db()
    key = _client_key(client_id)
    current = now or dt.datetime.utcnow()
    with Session(engine) as session:
        # A read/modify/write transaction can otherwise lose increments when two
        # failed requests arrive together. Acquire SQLite's write reservation
        # before reading so each request observes the preceding committed count.
        if engine.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")

        if succeeded:
            session.exec(delete(LoginThrottle).where(LoginThrottle.client_id == key))
            session.commit()
            return

        throttle = session.get(LoginThrottle, key)
        if throttle is None:
            throttle = LoginThrottle(
                client_id=key,
                failed_count=1,
                window_started_at=current,
            )
            session.add(throttle)
        elif current - throttle.window_started_at >= _LOGIN_WINDOW:
            # Keep the existing identity-tracked row. Replacing it with a new
            # object carrying the same primary key can attempt a duplicate INSERT.
            throttle.failed_count = 1
            throttle.window_started_at = current
            throttle.blocked_until = None
        else:
            throttle.failed_count += 1
        if throttle.failed_count >= _LOGIN_MAX_FAILURES:
            exponent = throttle.failed_count - _LOGIN_MAX_FAILURES
            backoff = min(60 * (2**exponent), _LOGIN_MAX_BACKOFF_SECONDS)
            throttle.blocked_until = current + dt.timedelta(seconds=backoff)
        session.commit()


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
def login(request: LoginRequest, response: Response, http_request: Request) -> dict[str, bool]:
    """Verify the app password and set the session cookie on success."""
    client_id = http_request.client.host if http_request.client else "unknown"
    _check_login_rate_limit(client_id)
    try:
        ok = check_password(request.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not ok:
        _record_login_result(client_id, succeeded=False)
        raise HTTPException(status_code=401, detail="Incorrect password.")

    _record_login_result(client_id, succeeded=True)
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
