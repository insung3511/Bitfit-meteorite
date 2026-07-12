"""FastAPI application entrypoint for the personal health assistant backend."""

from __future__ import annotations

import datetime as dt
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routes import auth as auth_routes
from app.routes import chat as chat_routes
from app.routes import dashboard as dashboard_routes
from app.routes import import_takeout as import_takeout_routes
from app.routes import session as session_routes
from app.routes import sync as sync_routes
from app.routes import workspace as workspace_routes
from app.session import require_session
from app.sync import sync_once

# Local Next.js dev server.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# How often the background job pulls from the Google Health API. Read from the
# environment so it's a config change, not a code change; defaults to 4 hours.
SYNC_INTERVAL_HOURS = float(os.getenv("SYNC_INTERVAL_HOURS", "4"))
# Delay the first tick a few minutes so a sync never blocks server boot.
_FIRST_RUN_DELAY = dt.timedelta(minutes=5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup and run the background sync scheduler."""
    init_db()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        sync_once,
        trigger="interval",
        hours=SYNC_INTERVAL_HOURS,
        # First run a few minutes out (not at boot) so startup never blocks on a
        # network sync; thereafter every SYNC_INTERVAL_HOURS.
        next_run_time=dt.datetime.now() + _FIRST_RUN_DELAY,
        id="google_health_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="BitFit Meteorite — Health Assistant API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session login stays open (it's how you get a session in the first place);
# every other router requires a valid session cookie — this is a personal app
# with no user accounts, so a single shared-secret gate is all it needs.
app.include_router(session_routes.router)

_protected = [Depends(require_session)]
app.include_router(auth_routes.router, dependencies=_protected)
app.include_router(sync_routes.router, dependencies=_protected)
app.include_router(import_takeout_routes.router, dependencies=_protected)
app.include_router(chat_routes.router, dependencies=_protected)
app.include_router(dashboard_routes.router, dependencies=_protected)
app.include_router(workspace_routes.router, dependencies=_protected)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the frontend and deployment checks. Unauthenticated
    on purpose — it must work before the user has ever logged in."""
    return {"status": "ok"}
