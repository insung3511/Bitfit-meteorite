"""OAuth2 routes for connecting the Google Health account (backend only).

Flow:

1. Browser hits ``GET /auth/google/login`` → 307 redirect to Google's consent
   screen (the client secret never leaves the server).
2. Google redirects back to ``GET /auth/google/callback?code=...&state=...`` →
   the code is exchanged for tokens server-side and the refresh token is stored
   encrypted.

Because this is a single-user personal app, the CSRF ``state`` is held in a
module-level slot rather than a per-session store — there is only ever one
in-flight login at a time.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app import auth

router = APIRouter(prefix="/auth/google", tags=["auth"])

# Holds the CSRF state between /login and /callback for the single active flow.
_pending_state: str | None = None


@router.get("/login")
def login() -> RedirectResponse:
    """Redirect the browser to Google's OAuth2 consent screen."""
    global _pending_state
    url, state = auth.build_authorization_url()
    _pending_state = state
    return RedirectResponse(url)


@router.get("/callback")
def callback(
    code: str = Query(...),
    state: str = Query(...),
) -> dict[str, str]:
    """Handle Google's redirect: verify state, exchange code, store tokens."""
    global _pending_state
    if _pending_state is None or state != _pending_state:
        raise HTTPException(status_code=400, detail="Invalid or expired state.")
    _pending_state = None

    try:
        auth.exchange_code_for_tokens(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "connected", "provider": auth.PROVIDER}
