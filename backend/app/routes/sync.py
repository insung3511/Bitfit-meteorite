"""Manual trigger for the Google Health sync job.

``POST /sync/run`` runs :func:`app.sync.sync_once` synchronously and returns its
result dict. Useful for testing without waiting for the scheduled interval, and
as the backend for a future "sync now" button in the UI.

``sync_once`` already catches its own failures and returns
``{"status": "error", ...}``, so this endpoint returns 200 with that body rather
than surfacing a 500 when (for example) no Google account is connected yet.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.sync import sync_once

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/run")
def run_sync() -> dict:
    """Run one sync cycle now and return its summary (or graceful error)."""
    return sync_once()
