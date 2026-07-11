"""Scheduled pull of health data from the Google Health API.

:func:`sync_once` is the unit of work the APScheduler background job (and the
manual ``POST /sync/run`` endpoint) invoke:

1. Ask :mod:`app.google_health_client` for records since the last sync.
2. Map them into :class:`app.models.DailyMetric` rows with
   ``source="google_health"``, skipping any ``(date, metric_name, source)`` that
   already exists (same idempotency pattern as ``takeout_import.py``).
3. Recompute rolling summaries via :func:`app.summarize.compute_daily_summaries`.

Because it runs unattended on a schedule, the whole thing is wrapped so *any*
failure — most commonly the ``RuntimeError`` from ``get_valid_access_token()``
when no Google account is connected yet, or an API/HTTP error — is caught and
returned as ``{"status": "error", "detail": ...}`` instead of crashing the
scheduler thread (or the request handler).
"""

from __future__ import annotations

import datetime as dt
import hashlib

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from sqlmodel import Session, delete, select

# How far back to pull when we have no prior google_health data to anchor on.
_DEFAULT_LOOKBACK_DAYS = 30


def _determine_since(session, DailyMetric) -> dt.datetime:
    """Pick the datetime to sync from: just after the latest synced day.

    Uses the most recent ``google_health`` ``DailyMetric`` date as the anchor (a
    small re-pull overlap is harmless because inserts are deduped). Falls back to
    a fixed lookback window on the very first sync.
    """
    latest_date = session.exec(
        select(DailyMetric.date)
        .where(DailyMetric.source == "google_health")
        .order_by(DailyMetric.date.desc())
    ).first()
    if latest_date is not None:
        return dt.datetime.combine(latest_date, dt.time.min)
    return dt.datetime.utcnow() - dt.timedelta(days=_DEFAULT_LOOKBACK_DAYS)


def sync_once() -> dict:
    """Pull recent Google Health data, persist it, and refresh summaries.

    Returns:
        On success: ``{"status": "ok", "rows_synced": N, "rows_skipped": M,
        "since": "<iso>"}``. On any failure: ``{"status": "error", "detail":
        "<message>"}`` — this never raises, so a scheduled run cannot take down
        the process.
    """
    # Imported lazily so a DATABASE_URL override set before the call is honoured
    # by app.db's module-level engine (mirrors takeout_import.py / summarize.py).
    from app.db import engine, init_db
    from app.google_health_client import fetch_recent_data
    from app.models import DailyMetric, SyncLease
    from app.summarize import compute_daily_summaries

    try:
        init_db()

        with Session(engine) as lock_session:
            acquired = lock_session.exec(
                sqlite_insert(SyncLease).values(id=1).on_conflict_do_nothing(
                    index_elements=["id"]
                )
            )
            lock_session.commit()
            if not acquired.rowcount:
                return {"status": "busy", "detail": "A sync is already running."}

        try:
            with Session(engine) as session:
                since = _determine_since(session, DailyMetric)
                records = fetch_recent_data(since)

                rows_synced = 0
                rows_skipped = 0
                for rec in records:
                    # A provider record can produce one row per sleep stage.
                    # Include the internal metric in its identity so they coexist.
                    provider_id = rec.get("provider_record_id")
                    if not provider_id:
                        provider_id = hashlib.sha256(
                            repr((rec["date"], rec["metric_name"], rec["value"])).encode()
                        ).hexdigest()
                    record_id = f"{provider_id}:{rec['metric_name']}"
                    statement = sqlite_insert(DailyMetric).values(
                        date=rec["date"], metric_name=rec["metric_name"],
                        value=rec["value"], unit=rec.get("unit"),
                        source="google_health", provider_record_id=record_id,
                        source_platform=rec.get("source_platform"),
                    )
                    result = session.exec(
                        statement.on_conflict_do_nothing(
                            index_elements=["source", "provider_record_id"]
                        )
                    )
                    if result.rowcount:
                        rows_synced += 1
                    else:
                        rows_skipped += 1

                session.commit()

            # Refresh rolling summaries so new points are reflected immediately.
            compute_daily_summaries()

            return {
                "status": "ok",
                "rows_synced": rows_synced,
                "rows_skipped": rows_skipped,
                "since": since.isoformat(),
            }
        finally:
            with Session(engine) as lock_session:
                lock_session.exec(delete(SyncLease).where(SyncLease.id == 1))
                lock_session.commit()
    except Exception as exc:  # unattended: never propagate — report and move on.
        return {"status": "error", "detail": str(exc)}
