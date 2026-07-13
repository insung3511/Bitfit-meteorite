"""Read routes backing the dashboard UI (charts, anomalies, sleep coaching).

All four endpoints are thin read/serialize layers over data already computed
elsewhere:

* ``GET /dashboard/summary`` — the trailing per-day ``daily_summary`` rows for one
  metric, ordered by date. This is exactly what a line/area chart plots.
* ``GET /dashboard/metrics`` — the distinct ``metric_name`` values present in
  ``daily_metric``, so the frontend can offer what's actually available to chart
  instead of hardcoding a metric list.
* ``GET /dashboard/anomalies`` — a thin wrapper over
  :func:`app.llm_client.get_anomalies`, resolving ``since_date`` from a ``days``
  window so the anomaly logic stays defined in one place.
* ``GET /dashboard/raw`` — a bounded, serialized view over the high-resolution
  raw signal index for drill-down charts.
* ``POST /dashboard/sleep-coaching`` — runs :func:`app.llm_client.sleep_coaching_summary`
  (an LLM call). Because that can be slow and fails without ``ANTHROPIC_API_KEY``,
  the route catches everything and returns 200 with ``{"summary": None, "error": ...}``
  so the UI can show a friendly "coaching unavailable" state instead of a 500.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import engine
from app.llm_client import get_anomalies, sleep_coaching_summary
from app.models import DailyMetric, DailySummary
from app.raw_signal_import import query_raw_signals

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_MAX_RAW_LIMIT = 2_000


def _parse_raw_bound(value: str | None, *, end: bool = False) -> dt.datetime | None:
    """Parse a raw dashboard bound as ISO date/datetime.

    Date-only ``end`` values are treated as inclusive calendar days by converting
    them to the next midnight, matching ``query_raw_signals``' exclusive end
    bound without surprising dashboard callers.
    """
    if not value:
        return None
    raw = value.strip()
    try:
        if len(raw) == 10:
            day = dt.date.fromisoformat(raw)
            if end:
                day = day + dt.timedelta(days=1)
            return dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc)
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="start and end must be ISO dates or datetimes.",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _raw_value(row: dict[str, Any]) -> Any:
    if row.get("value_float") is not None:
        return row.get("value_float")
    if row.get("value_text") is not None:
        return row.get("value_text")
    return row.get("value_json")


def _iso_or_none(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _serialize_raw_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": row.get("record_fingerprint") or row.get("id"),
        "timestamp": _iso_or_none(row.get("timestamp")),
        "end_timestamp": _iso_or_none(row.get("end_timestamp")),
        "metric": row.get("metric_name"),
        "signal_type": row.get("signal_type"),
        "value": _raw_value(row),
        "unit": row.get("unit"),
        "source": row.get("source"),
        "source_kind": row.get("source_kind"),
        "source_file": row.get("source_file"),
    }


def _source_metadata(records: list[dict[str, Any]]) -> dict[str, Any]:
    sources = sorted({str(row["source"]) for row in records if row.get("source")})
    source_kinds = sorted(
        {str(row["source_kind"]) for row in records if row.get("source_kind")}
    )
    source_files = sorted(
        {str(row["source_file"]) for row in records if row.get("source_file")}
    )
    return {
        "sources": sources,
        "source_kinds": source_kinds,
        "source_files": source_files,
    }


@router.get("/summary")
def summary(
    metric: str = Query(..., description="Metric name to chart, e.g. 'steps'."),
    days: int = Query(30, gt=0, description="Trailing window size in days."),
) -> dict[str, Any]:
    """Return the trailing ``days`` of summary rows for one metric, date-ordered.

    Each row carries the rolling statistics a line chart plots (7-day and 30-day
    mean, 30-day stddev, delta vs. baseline). The window is anchored to the
    metric's newest available date, so historical Takeout exports remain visible.
    """
    with Session(engine) as session:
        latest = session.exec(
            select(func.max(DailySummary.date)).where(
                DailySummary.metric_name == metric
            )
        ).one()
        if latest is None:
            return {"metric": metric, "days": days, "count": 0, "points": []}
        since = latest - dt.timedelta(days=days - 1)
        rows = session.exec(
            select(DailySummary)
            .where(
                DailySummary.metric_name == metric,
                DailySummary.date >= since,
            )
            .order_by(DailySummary.date)
        ).all()

    return {
        "metric": metric,
        "days": days,
        "count": len(rows),
        "points": [
            {
                "date": row.date.isoformat(),
                "mean_7d": row.mean_7d,
                "mean_30d": row.mean_30d,
                "stddev_30d": row.stddev_30d,
                "delta_vs_baseline": row.delta_vs_baseline,
            }
            for row in rows
        ],
    }


@router.get("/metrics")
def metrics() -> dict[str, Any]:
    """Return the distinct metric names currently present in ``daily_metric``."""
    with Session(engine) as session:
        names = session.exec(
            select(DailyMetric.metric_name)
            .distinct()
            .order_by(DailyMetric.metric_name)
        ).all()

    return {"count": len(names), "metrics": list(names)}


@router.get("/raw")
def raw(
    metric: str | None = Query(
        None, description="Optional raw signal metric, e.g. 'heart_rate'."
    ),
    start: str | None = Query(None, description="Inclusive ISO date/datetime lower bound."),
    end: str | None = Query(None, description="ISO date/datetime upper bound."),
    limit: int = Query(
        500,
        ge=1,
        description=f"Maximum raw records to return, capped at {_MAX_RAW_LIMIT}.",
    ),
) -> dict[str, Any]:
    """Return bounded high-resolution raw records for dashboard drill-downs.

    The app-level router is mounted behind the shared session dependency in
    ``main.py``; this handler stays dependency-free so tests and direct imports
    remain compatible with that protected mounting pattern.
    """
    bounded_limit = min(limit, _MAX_RAW_LIMIT)
    start_dt = _parse_raw_bound(start)
    end_dt = _parse_raw_bound(end, end=True)
    if start_dt and end_dt and start_dt >= end_dt:
        raise HTTPException(status_code=422, detail="start must be before end.")

    rows = query_raw_signals(
        metric_name=metric,
        start=start_dt,
        end=end_dt,
        limit=bounded_limit + 1,
        engine=engine,
    )
    truncated = len(rows) > bounded_limit
    records = [_serialize_raw_record(row) for row in rows[:bounded_limit]]

    return {
        "metric": metric,
        "start": start,
        "end": end,
        "limit": bounded_limit,
        "count": len(records),
        "truncated": truncated,
        "records": records,
        "source_metadata": _source_metadata(records),
    }


@router.get("/anomalies")
def anomalies(
    days: int = Query(30, gt=0, description="Trailing window size in days."),
) -> dict[str, Any]:
    """Return metric-days deviating sharply from baseline within the window."""
    since = dt.date.today() - dt.timedelta(days=days)
    return get_anomalies(since_date=since.isoformat())


@router.post("/sleep-coaching")
def sleep_coaching() -> dict[str, Optional[str]]:
    """Run the LLM sleep-coaching summary, degrading gracefully on failure.

    Returns ``{"summary": <text>}`` on success. If the call fails (e.g. no
    ``ANTHROPIC_API_KEY`` configured), returns 200 with
    ``{"summary": None, "error": <message>}`` so the frontend can render a
    "coaching unavailable" state rather than crashing on a 500.
    """
    try:
        return {"summary": sleep_coaching_summary()}
    except Exception:  # graceful: surface as data, not an HTTP error
        # Don't leak raw exception detail (e.g. an Anthropic request ID) to the
        # browser — log it server-side and return a generic, actionable message.
        logger.exception("Sleep coaching request failed")
        return {
            "summary": None,
            "error": "Sleep coaching is unavailable right now. Check that "
            "ANTHROPIC_API_KEY is configured correctly and try again.",
        }
