"""SQLite engine setup for the health assistant backend.

The database URL is read from the ``DATABASE_URL`` env var and defaults to a
local SQLite file (``./health.db``). Tables are created from the SQLModel
metadata on startup via :func:`init_db`.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./health.db")

# ``check_same_thread`` must be disabled for SQLite when used across FastAPI's
# threadpool and the APScheduler sync job.
connect_args = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def init_db() -> None:
    """Create all tables defined on the SQLModel metadata."""
    # Import models so their tables are registered on SQLModel.metadata before
    # create_all runs.
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    from app.migrations import migrate

    migrate(engine)
