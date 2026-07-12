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
* ``POST /dashboard/sleep-coaching`` — runs :func:`app.llm_client.sleep_coaching_summary`
  (an LLM call). Because that can be slow and fails without ``ANTHROPIC_API_KEY``,
  the route catches everything and returns 200 with ``{"summary": None, "error": ...}``
  so the UI can show a friendly "coaching unavailable" state instead of a 500.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

from fastapi import APIRouter, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import engine
from app.llm_client import get_anomalies, sleep_coaching_summary
from app.models import DailyMetric, DailySummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(
    metric: str = Query(..., description="Metric name to chart, e.g. 'steps'."),
    days: int = Query(30, gt=0, description="Trailing window size in days."),
) -> dict[str, Any]:
    """Return the trailing ``days`` of summary rows for one metric, date-ordered.

    Each row carries the rolling statistics a line chart plots (7-day and 30-day
    mean, 30-day stddev, delta vs. baseline). Every metric uses the same window,
    anchored to the newest summary date in the database, so dashboard panels
    have comparable time axes.
    """
    with Session(engine) as session:
        latest = session.exec(select(func.max(DailySummary.date))).one()
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
