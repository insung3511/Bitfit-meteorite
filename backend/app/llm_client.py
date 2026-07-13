"""Claude tool-use layer for the personal health assistant.

This module is the key differentiator called out in the project plan: instead of
stuffing raw time-series into the prompt (which LLMs reason over poorly), it gives
Claude *tools* that run real SQL queries against the local health database and
returns only the numbers Claude asks for. Claude then grounds its answers in those
tool results.

Public surface:

* :func:`query_health_data`, :func:`get_daily_summary`, :func:`get_anomalies` —
  plain Python functions, each backed by a real SQLModel query. They are also the
  execution backends for the three Claude tools.
* :data:`TOOL_SCHEMAS` — Anthropic Messages-API ``input_schema`` tool definitions.
* :func:`chat` — the full tool-use loop for conversational Q&A over the data.
* :func:`sleep_coaching_summary` — a specialized view that runs a fixed multi-tool
  query sequence and asks Claude for a focused sleep-coaching writeup.

Config is env-driven and swappable (per the plan): ``ANTHROPIC_API_KEY`` and
``ANTHROPIC_MODEL``. The Anthropic client is constructed lazily so importing this
module (and running the tool functions directly) never requires an API key.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
from typing import Any, Callable, Optional

import anthropic
from sqlalchemy import func, text
from sqlmodel import Session, select

from app.db import engine
from app.ai_schemas import (
    ChatResult,
    EvidenceReference,
    StructuredAnalysis,
    WorkspaceActionProposal,
    WorkspaceActionType,
    WorkspaceContext,
)
from app.models import DailyMetric, DailySummary

# --- Configuration (swappable via .env, not code) --------------------------------

# Model name is read from the environment. If unset, fall back to the model the
# project documents in .env.example. Swapping models is a config change.
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

# Max tokens for a single assistant turn. Well under the streaming threshold, so a
# plain (non-streaming) request is fine.
_MAX_TOKENS = 2048
_MAX_TOOL_ROUNDS = 8

# Must match StructuredAnalysis.narrative's own max_length. A model reply that is
# truncated mid-JSON falls back to the raw text, which can exceed it.
_MAX_NARRATIVE_CHARS = 16_000

# Anomaly threshold: a metric-day is anomalous when its deviation from baseline
# exceeds this many rolling-30-day standard deviations.
_ANOMALY_SIGMA = 2.0

# Keep model context bounded even when a user imports years of daily data.  The
# count in a result remains the full match count; raw series are sampled before
# they are sent to Claude or the browser.
_MAX_QUERY_DAYS = 3_660
_MAX_RAW_POINTS = 2_000
_MAX_PROVENANCE_ROWS = 1_000

_ALLOWED_AGGREGATIONS = ("mean", "min", "max", "raw")

SYSTEM_PROMPT = (
    "You are a personal wellness coach for a single user, helping them understand "
    "their own wearable health data (sleep stages, resting heart rate, HRV, steps, "
    "activity, SpO2, weight, and related metrics). You are NOT a licensed medical "
    "professional and you must not diagnose conditions or prescribe treatment.\n\n"
    "Ground every factual claim about the user's data in the results of the provided "
    "tools. Never invent, estimate, or recall specific numbers from memory — if you "
    "state a value, trend, average, or anomaly, it must come from a tool call you "
    "made in this conversation. If the tools return no data for what the user asked, "
    "say so plainly rather than guessing.\n\n"
    "Always call list_available_metrics before you query any metric. Which metrics "
    "exist depends on the user's devices and imports — never assume a metric is "
    "present or absent, and never guess a metric name. Metrics you have not seen "
    "before are still real data worth analysing.\n\n"
    "When you give concrete suggestions (sleep, exercise, recovery, habits), keep them "
    "practical and encouraging, and explicitly note that they are general wellness "
    "guidance, not medical advice, and that the user should consult a qualified "
    "healthcare professional for medical concerns or before making significant "
    "changes.\n\n"
    "Your final answer is a normal, readable response. When you have tool evidence, "
    "append a machine-readable block exactly between the markers "
    "<!-- BITFIT_ANALYSIS_JSON and -->. The JSON object may contain narrative, "
    "observations, hypotheses, uncertainties, evidence_refs, and workspace_actions. "
    "Each observation must reference evidence_ids. Hypotheses must be labelled as "
    "hypotheses and include confidence. Workspace actions are proposals only: never "
    "claim that a chart or layout changed, and always leave requires_approval=true "
    "and reversible=true. If you cannot produce valid JSON, omit the block; the "
    "server will still return your plain-text answer and the tool evidence."
)


# --- Date helpers ----------------------------------------------------------------


def _parse_date(value: str | dt.date) -> dt.date:
    """Parse an ISO ``YYYY-MM-DD`` string (or pass through a ``date``)."""
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(value)


def _summary_to_dict(row: DailySummary) -> dict[str, Any]:
    """Serialize a :class:`DailySummary` row to a JSON-friendly dict."""
    return {
        "date": row.date.isoformat(),
        "metric_name": row.metric_name,
        "mean_7d": row.mean_7d,
        "mean_30d": row.mean_30d,
        "stddev_30d": row.stddev_30d,
        "delta_vs_baseline": row.delta_vs_baseline,
    }


def _fetch_metric_rows(
    metric: str,
    start: dt.date,
    end: dt.date,
    *,
    limit: int | None = None,
) -> list[DailyMetric]:
    """Read ordered daily rows for one metric.

    The helper centralizes the bounded date-window check used by every read-only
    analytical tool.  ``limit`` is applied after ordering so callers can make an
    explicit provenance request without accidentally scanning an unbounded set.
    """
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    if (end - start).days + 1 > _MAX_QUERY_DAYS:
        raise ValueError(f"date range cannot exceed {_MAX_QUERY_DAYS} days")

    statement = (
        select(DailyMetric)
        .where(
            DailyMetric.metric_name == metric,
            DailyMetric.date >= start,
            DailyMetric.date <= end,
        )
        .order_by(DailyMetric.date, DailyMetric.id)
    )
    if limit is not None:
        statement = statement.limit(limit)

    with Session(engine) as session:
        return list(session.exec(statement).all())


def _bounded_rows(
    rows: list[DailyMetric], max_points: int = _MAX_RAW_POINTS
) -> tuple[list[DailyMetric], bool]:
    """Downsample ordered rows while preserving the first and last point."""
    if len(rows) <= max_points:
        return rows, False
    step = math.ceil(len(rows) / max_points)
    sampled = rows[::step]
    if sampled[-1] is not rows[-1]:
        if len(sampled) >= max_points:
            sampled = sampled[: max_points - 1]
        sampled.append(rows[-1])
    return sampled[:max_points], True


# --- Tool backends (real SQLModel queries) ---------------------------------------


def query_health_data(
    metric: str,
    start_date: str,
    end_date: str,
    aggregation: str = "mean",
) -> dict[str, Any]:
    """Query raw daily observations for one metric over a date range.

    Reads per-day values from ``daily_metric`` (the ``daily_summary`` table only
    stores rolling statistics, so it is not granular enough to aggregate over an
    arbitrary window). Returns an aggregate or the raw series.

    Args:
        metric: Metric name, e.g. ``"resting_heart_rate"``, ``"sleep_deep_minutes"``.
        start_date: Inclusive start, ISO ``YYYY-MM-DD``.
        end_date: Inclusive end, ISO ``YYYY-MM-DD``.
        aggregation: One of ``"mean"``, ``"min"``, ``"max"``, ``"raw"``.

    Returns:
        A JSON-serializable dict with the requested aggregation (or the raw
        series) plus the observation count and the resolved date range.
    """
    if aggregation not in _ALLOWED_AGGREGATIONS:
        return {
            "error": (
                f"Unknown aggregation {aggregation!r}. "
                f"Expected one of {list(_ALLOWED_AGGREGATIONS)}."
            )
        }

    start = _parse_date(start_date)
    end = _parse_date(end_date)
    rows = _fetch_metric_rows(metric, start, end)

    values = [r.value for r in rows]
    record_ids = [
        str(row.provider_record_id or row.id)
        for row in rows
        if row.provider_record_id is not None or row.id is not None
    ]
    result: dict[str, Any] = {
        "metric": metric,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "aggregation": aggregation,
        "count": len(values),
        "record_ids": record_ids[:_MAX_RAW_POINTS],
        "record_ids_truncated": len(record_ids) > _MAX_RAW_POINTS,
        "sources": sorted({row.source for row in rows if row.source}),
    }

    if aggregation == "raw":
        bounded, downsampled = _bounded_rows(rows)
        result["series"] = [
            {"date": r.date.isoformat(), "value": r.value} for r in bounded
        ]
        result["downsampled"] = downsampled
        result["returned_count"] = len(bounded)
        return result

    if not values:
        result["result"] = None
        return result

    if aggregation == "mean":
        result["result"] = sum(values) / len(values)
    elif aggregation == "min":
        result["result"] = min(values)
    elif aggregation == "max":
        result["result"] = max(values)
    return result


def get_daily_summary(date: str) -> dict[str, Any]:
    """Return all metrics' computed summary rows for a single day.

    Reads from ``daily_summary`` (rolling 7/30-day mean, 30-day stddev, and delta
    vs. baseline per metric).

    Args:
        date: The day to snapshot, ISO ``YYYY-MM-DD``.

    Returns:
        A dict with the date and a list of per-metric summary rows for that day.
    """
    day = _parse_date(date)
    with Session(engine) as session:
        rows = session.exec(
            select(DailySummary)
            .where(DailySummary.date == day)
            .order_by(DailySummary.metric_name)
        ).all()

    return {
        "date": day.isoformat(),
        "count": len(rows),
        "summaries": [_summary_to_dict(r) for r in rows],
    }


def get_anomalies(since_date: str) -> dict[str, Any]:
    """Return metric-days that deviate sharply from their rolling baseline.

    A row is flagged when ``abs(delta_vs_baseline) > 2 * stddev_30d`` (there is no
    stored ``is_anomaly`` column — it is computed here). Rows with a null delta or
    null/zero-context stddev are skipped rather than assumed anomalous.

    Args:
        since_date: Inclusive lower bound on the date, ISO ``YYYY-MM-DD``.

    Returns:
        A dict with the threshold used and a list of flagged summary rows, each
        annotated with the sigma multiple by which it exceeded baseline.
    """
    since = _parse_date(since_date)
    with Session(engine) as session:
        rows = session.exec(
            select(DailySummary)
            .where(DailySummary.date >= since)
            .order_by(DailySummary.date, DailySummary.metric_name)
            .limit(_MAX_RAW_POINTS + 1)
        ).all()

    truncated = len(rows) > _MAX_RAW_POINTS
    rows = rows[:_MAX_RAW_POINTS]

    anomalies: list[dict[str, Any]] = []
    for row in rows:
        delta = row.delta_vs_baseline
        stddev = row.stddev_30d
        if delta is None or stddev is None:
            continue
        threshold = _ANOMALY_SIGMA * stddev
        if abs(delta) > threshold:
            entry = _summary_to_dict(row)
            # How many standard deviations from baseline (None if stddev == 0).
            entry["sigma"] = abs(delta) / stddev if stddev else None
            anomalies.append(entry)

    return {
        "since_date": since.isoformat(),
        "threshold_sigma": _ANOMALY_SIGMA,
        "count": len(anomalies),
        "truncated": truncated,
        "anomalies": anomalies,
    }


def correlate_health_signals(
    metric_a: str,
    metric_b: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Compute a bounded Pearson correlation for two daily metric signals.

    Rows are aligned by calendar day and duplicate records on a day are averaged
    before calculating the coefficient.  A correlation is descriptive only; the
    agent must not present it as causation.
    """
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    rows_a = _fetch_metric_rows(metric_a, start, end)
    rows_b = _fetch_metric_rows(metric_b, start, end)

    by_day_a: dict[dt.date, list[float]] = {}
    by_day_b: dict[dt.date, list[float]] = {}
    for row in rows_a:
        by_day_a.setdefault(row.date, []).append(row.value)
    for row in rows_b:
        by_day_b.setdefault(row.date, []).append(row.value)

    pairs = [
        {
            "date": day.isoformat(),
            "value_a": sum(by_day_a[day]) / len(by_day_a[day]),
            "value_b": sum(by_day_b[day]) / len(by_day_b[day]),
        }
        for day in sorted(set(by_day_a) & set(by_day_b))
    ]
    bounded_pairs = pairs
    downsampled = False
    if len(pairs) > _MAX_RAW_POINTS:
        step = math.ceil(len(pairs) / _MAX_RAW_POINTS)
        bounded_pairs = pairs[::step]
        if bounded_pairs[-1]["date"] != pairs[-1]["date"]:
            bounded_pairs.append(pairs[-1])
        bounded_pairs = bounded_pairs[:_MAX_RAW_POINTS]
        downsampled = True

    xs = [pair["value_a"] for pair in pairs]
    ys = [pair["value_b"] for pair in pairs]
    correlation: float | None = None
    if len(xs) >= 2:
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denominator_x = sum((x - mean_x) ** 2 for x in xs)
        denominator_y = sum((y - mean_y) ** 2 for y in ys)
        denominator = math.sqrt(denominator_x * denominator_y)
        if denominator:
            correlation = numerator / denominator

    record_ids = [
        str(row.provider_record_id or row.id)
        for row in [*rows_a, *rows_b]
        if row.provider_record_id is not None or row.id is not None
    ]
    return {
        "metric_a": metric_a,
        "metric_b": metric_b,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "count": len(pairs),
        "correlation": correlation,
        "pairs": bounded_pairs,
        "returned_count": len(bounded_pairs),
        "downsampled": downsampled,
        "record_ids": record_ids[:_MAX_RAW_POINTS],
        "sources": sorted(
            {
                row.source
                for row in [*rows_a, *rows_b]
                if row.source
            }
        ),
    }


def get_data_provenance(
    metric: str,
    start_date: str,
    end_date: str,
    limit: int = 200,
    record_id: str | None = None,
) -> dict[str, Any]:
    """Return source/device identity for bounded metric observations."""
    if limit <= 0 or limit > _MAX_PROVENANCE_ROWS:
        return {
            "error": f"limit must be between 1 and {_MAX_PROVENANCE_ROWS}"
        }
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    # A targeted provider/local ID may occur after the first page; resolve the
    # full bounded date window before applying the caller's result limit.
    rows = _fetch_metric_rows(metric, start, end, limit=None if record_id else limit)
    if record_id is not None:
        rows = [
            row
            for row in rows
            if str(row.id) == record_id or row.provider_record_id == record_id
        ]

    records = [
        {
            "record_id": str(row.id) if row.id is not None else None,
            "provider_record_id": row.provider_record_id,
            "date": row.date.isoformat(),
            "metric": row.metric_name,
            "value": row.value,
            "unit": row.unit,
            "source": row.source,
            "source_platform": row.source_platform,
        }
        for row in rows
    ]
    return {
        "metric": metric,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "aggregation": "provenance",
        "count": len(records),
        "records": records,
        "record_ids": [
            str(row.provider_record_id or row.id)
            for row in rows
            if row.provider_record_id is not None or row.id is not None
        ],
    }


def query_raw_health_signals(
    metric_name: str,
    start_date: str,
    end_date: str,
    limit: int = 500,
) -> dict[str, Any]:
    """Read high-resolution Takeout points through the bounded raw-signal index."""
    if limit <= 0 or limit > _MAX_RAW_POINTS:
        return {"error": f"limit must be between 1 and {_MAX_RAW_POINTS}"}
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start > end:
        return {"error": "start_date must be on or before end_date"}
    if (end - start).days + 1 > _MAX_QUERY_DAYS:
        return {"error": f"date range cannot exceed {_MAX_QUERY_DAYS} days"}
    # Keep the raw index query exclusive of the following calendar day.
    start_dt = dt.datetime.combine(start, dt.time.min, tzinfo=dt.timezone.utc)
    end_dt = dt.datetime.combine(
        end + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc
    )
    from app.raw_signal_import import query_raw_signals

    rows = query_raw_signals(
        metric_name=metric_name,
        start=start_dt,
        end=end_dt,
        limit=limit + 1,
    )
    truncated = len(rows) > limit
    rows = rows[:limit]
    records = [
        {
            "record_id": row.get("record_fingerprint") or row.get("id"),
            "timestamp": row.get("timestamp"),
            "end_timestamp": row.get("end_timestamp"),
            "metric": row.get("metric_name"),
            "signal_type": row.get("signal_type"),
            "value": row.get("value_float")
            if row.get("value_float") is not None
            else row.get("value_text") or row.get("value_json"),
            "unit": row.get("unit"),
            "source": row.get("source"),
            "source_kind": row.get("source_kind"),
            "source_file": row.get("source_file"),
        }
        for row in rows
    ]
    return {
        "metric": metric_name,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "aggregation": "raw",
        "count": len(records),
        "records": records,
        "record_ids": [str(row["record_id"]) for row in records if row["record_id"]],
        "sources": sorted({str(row["source"]) for row in records if row["source"]}),
        "truncated": truncated,
    }


def list_available_metrics() -> dict[str, Any]:
    """List every metric actually present in the database, with its coverage.

    The agent must call this before assuming a metric exists. Hardcoding metric
    names in a tool description is how the agent went blind to two thirds of the
    imported metrics; the catalogue lives in the data, not in a prompt.
    """
    with Session(engine) as session:
        rows = session.exec(
            select(
                DailyMetric.metric_name,
                DailyMetric.unit,
                func.count(DailyMetric.id),
                func.min(DailyMetric.date),
                func.max(DailyMetric.date),
            )
            .group_by(DailyMetric.metric_name, DailyMetric.unit)
            .order_by(DailyMetric.metric_name)
        ).all()

    metrics = [
        {
            "metric": name,
            "unit": unit,
            "count": count,
            "first_date": first.isoformat() if first else None,
            "last_date": last.isoformat() if last else None,
        }
        for name, unit, count, first, last in rows
    ]
    return {"count": len(metrics), "metrics": metrics}


def list_raw_signal_types(metric: str) -> dict[str, Any]:
    """Report which high-resolution signals back a daily metric, if any.

    The daily rollup layer and the raw index use different vocabularies (a chart
    says ``steps``; the indexed points are ``steps_delta``). This resolves the
    daily name to the raw names ``query_raw_health_signals`` will actually match,
    and reports how many points exist, so the agent knows whether a drill-down is
    possible before attempting one.
    """
    from app.raw_signal_import import ensure_raw_signal_schema, resolve_raw_metric_names

    names = resolve_raw_metric_names(metric)
    ensure_raw_signal_schema(engine)
    placeholders = ", ".join(f":m{index}" for index in range(len(names)))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT metric_name, signal_type, COUNT(*) AS n, "
                "MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts "
                f"FROM raw_signal WHERE metric_name IN ({placeholders}) "
                "GROUP BY metric_name, signal_type ORDER BY n DESC"
            ),
            {f"m{index}": name for index, name in enumerate(names)},
        ).all()

    signals = [
        {
            "raw_metric": row[0],
            "signal_type": row[1],
            "count": row[2],
            "first_timestamp": row[3],
            "last_timestamp": row[4],
        }
        for row in rows
    ]
    return {
        "metric": metric,
        "raw_metric_names": list(names),
        "has_raw_data": bool(signals),
        "signals": signals,
    }


def accept_health_plan(**plan: Any) -> dict[str, Any]:
    """Acknowledge a submitted deep-research plan.

    The plan is not persisted from here. ``app.research`` reads it back out of the
    tool-call history and re-validates it against the evidence the server actually
    minted, so a plan can never be stored just because the model asserted it. This
    backend exists so the tool call resolves cleanly and the model can finish its
    turn.
    """
    targets = plan.get("targets") or []
    return {
        "accepted": True,
        "target_count": len(targets),
        "note": (
            "Plan received. Targets citing evidence IDs that were not returned by "
            "a tool in this run will be discarded before the plan is saved."
        ),
    }


def accept_analysis(**analysis: Any) -> dict[str, Any]:
    """Acknowledge submitted structured findings.

    Like :func:`accept_health_plan`, this does not persist anything: the caller
    re-reads the submission from the tool-call history and re-grounds every claim
    against the evidence the server actually minted.
    """
    counts = {
        key: len(analysis.get(key) or [])
        for key in ("observations", "hypotheses", "uncertainties")
    }
    return {
        "accepted": True,
        **counts,
        "note": (
            "Findings received. Any claim citing an evidence ID that no tool in "
            "this run returned will be dropped before the report is saved."
        ),
    }


def propose_workspace_action(
    action_type: str,
    panel_id: str | None = None,
    payload: dict[str, Any] | None = None,
    rationale: str = "",
) -> dict[str, Any]:
    """Return an approval-gated workspace proposal without applying it."""
    try:
        normalized_type = WorkspaceActionType(action_type)
    except ValueError:
        return {
            "error": (
                f"Unknown action_type {action_type!r}. Expected one of "
                f"{[item.value for item in WorkspaceActionType]}"
            )
        }

    normalized_payload = payload or {}
    action_key = json.dumps(
        {
            "action_type": normalized_type.value,
            "panel_id": panel_id,
            "payload": normalized_payload,
            "rationale": rationale,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    action_id = "act_" + hashlib.sha256(action_key.encode()).hexdigest()[:20]
    try:
        proposal = WorkspaceActionProposal(
            action_id=action_id,
            action_type=normalized_type,
            panel_id=panel_id,
            payload=normalized_payload,
            rationale=rationale,
        )
    except Exception as exc:
        return {"error": f"Invalid workspace action: {exc}"}

    return {
        "proposal": proposal.model_dump(mode="json"),
        "applied": False,
        "requires_approval": True,
        "reversible": True,
    }


# --- Anthropic tool schemas + dispatch -------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_available_metrics",
        "description": (
            "List every metric that actually exists in the user's database, with "
            "its unit, observation count, and date coverage. Call this FIRST, "
            "before any other data tool. Do not assume a metric exists or guess "
            "its name — the set of metrics depends on which devices and exports "
            "the user has imported, and it changes over time."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_raw_signal_types",
        "description": (
            "Check whether a daily metric has high-resolution data underneath it "
            "and what the raw signals are called. Call this before "
            "query_raw_health_signals: the daily name and the raw name differ "
            "(daily 'steps' is stored raw as 'steps_delta'), and some daily "
            "metrics are derived with no raw form at all."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "description": "The daily metric name to resolve, e.g. 'steps'.",
                },
            },
            "required": ["metric"],
        },
    },
    {
        "name": "query_health_data",
        "description": (
            "Query the user's historical health data for a single metric over a "
            "date range, returning an aggregate (mean/min/max) or the raw daily "
            "series. Use this for questions about levels, trends, or comparisons "
            "over a time window. Get valid metric names from list_available_metrics "
            "— never guess them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "description": "The metric name to query, e.g. 'resting_heart_rate'.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Inclusive start date, ISO format YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Inclusive end date, ISO format YYYY-MM-DD.",
                },
                "aggregation": {
                    "type": "string",
                    "enum": ["mean", "min", "max", "raw"],
                    "description": (
                        "How to aggregate the daily values in the range. Use 'raw' "
                        "to get the per-day series. Large results are downsampled "
                        "server-side and report the full match count."
                    ),
                },
            },
            "required": ["metric", "start_date", "end_date", "aggregation"],
        },
    },
    {
        "name": "get_daily_summary",
        "description": (
            "Get all metrics' computed summary statistics (rolling 7-day and 30-day "
            "mean, 30-day standard deviation, and delta vs. baseline) for one "
            "specific day. Use this for a single-day snapshot across every metric."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The day to snapshot, ISO format YYYY-MM-DD.",
                },
            },
            "required": ["date"],
        },
    },
    {
        "name": "get_anomalies",
        "description": (
            "Find metric-days since a given date where the value deviated sharply "
            "from its rolling 30-day baseline (more than 2 standard deviations). "
            "Use this to surface unusual readings the user should be aware of."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "since_date": {
                    "type": "string",
                    "description": "Inclusive lower-bound date, ISO format YYYY-MM-DD.",
                },
            },
            "required": ["since_date"],
        },
    },
    {
        "name": "correlate_health_signals",
        "description": (
            "Align two daily health metrics over a bounded date range and compute "
            "their descriptive Pearson correlation. This is association, not "
            "causation. Use it when the user asks whether two signals move together."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_a": {"type": "string", "description": "First metric name."},
                "metric_b": {"type": "string", "description": "Second metric name."},
                "start_date": {
                    "type": "string",
                    "description": "Inclusive start date, ISO format YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Inclusive end date, ISO format YYYY-MM-DD.",
                },
            },
            "required": ["metric_a", "metric_b", "start_date", "end_date"],
        },
    },
    {
        "name": "get_data_provenance",
        "description": (
            "Look up the source, device platform, and provider record identity for "
            "bounded observations. Use this when the user asks where a displayed "
            "point came from or when comparing imported and live data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "Metric name."},
                "start_date": {
                    "type": "string",
                    "description": "Inclusive start date, ISO format YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Inclusive end date, ISO format YYYY-MM-DD.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_PROVENANCE_ROWS,
                    "default": 200,
                },
                "record_id": {
                    "type": ["string", "null"],
                    "description": "Optional local or provider record identity.",
                },
            },
            "required": ["metric", "start_date", "end_date"],
        },
    },
    {
        "name": "query_raw_health_signals",
        "description": (
            "Query high-resolution interval, session, sample, or track points "
            "imported from Takeout. Results are bounded and include source-file "
            "provenance; use this for drill-downs below the daily chart level. "
            "Call list_raw_signal_types first to confirm the metric has raw data. "
            "Accepts either a daily metric name ('steps') or a raw signal name "
            "('steps_delta') — daily names are resolved for you."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Daily metric or raw signal name, e.g. 'steps' or 'heart_rate'.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Inclusive start date, ISO format YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Inclusive end date, ISO format YYYY-MM-DD.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_RAW_POINTS,
                    "default": _MAX_RAW_POINTS,
                },
            },
            "required": ["metric_name", "start_date", "end_date"],
        },
    },
    {
        "name": "propose_workspace_action",
        "description": (
            "Propose a reversible visual-workspace action. This tool NEVER changes "
            "the workspace: the user must approve the returned proposal. Supported "
            "actions are focus_panel, set_date_range, add_chart, remove_chart, "
            "add_overlay, annotate, propose_layout_patch, and save_analysis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": [item.value for item in WorkspaceActionType],
                },
                "panel_id": {
                    "type": ["string", "null"],
                    "description": "Stable panel identifier when the action targets one panel.",
                },
                "payload": {
                    "type": "object",
                    "description": "Action-specific patch or chart payload.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Short explanation grounded in the evidence.",
                },
            },
            "required": ["action_type", "payload", "rationale"],
        },
    },
]

# Maps each tool name to its Python backend.
_TOOL_FUNCTIONS = {
    "list_available_metrics": list_available_metrics,
    "list_raw_signal_types": list_raw_signal_types,
    "query_health_data": query_health_data,
    "get_daily_summary": get_daily_summary,
    "get_anomalies": get_anomalies,
    "correlate_health_signals": correlate_health_signals,
    "get_data_provenance": get_data_provenance,
    "query_raw_health_signals": query_raw_health_signals,
    "propose_workspace_action": propose_workspace_action,
    "propose_health_plan": accept_health_plan,
    "submit_analysis": accept_analysis,
}


_EVIDENCE_TOOLS = {
    "query_health_data",
    "get_daily_summary",
    "get_anomalies",
    "correlate_health_signals",
    "get_data_provenance",
    "query_raw_health_signals",
}


def _evidence_for_tool(
    name: str,
    tool_input: dict[str, Any],
    result: dict[str, Any],
) -> EvidenceReference | None:
    """Build a deterministic evidence reference for a successful read tool."""
    if name not in _EVIDENCE_TOOLS or "error" in result:
        return None
    identity = json.dumps(
        {"tool": name, "input": tool_input, "result": {
            "metric": result.get("metric"),
            "metric_a": result.get("metric_a"),
            "metric_b": result.get("metric_b"),
            "start_date": result.get("start_date") or result.get("since_date"),
            "end_date": result.get("end_date"),
            "aggregation": result.get("aggregation"),
            "count": result.get("count"),
        }},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    evidence_id = "ev_" + hashlib.sha256(identity.encode()).hexdigest()[:20]
    start_date = result.get("start_date") or result.get("since_date")
    end_date = result.get("end_date") or start_date
    aggregation = result.get("aggregation")
    if name == "correlate_health_signals":
        aggregation = "correlation"
    elif name == "get_data_provenance":
        aggregation = "provenance"
    return EvidenceReference(
        evidence_id=evidence_id,
        metric=result.get("metric"),
        start_date=start_date,
        end_date=end_date,
        aggregation=aggregation,
        panel_id=tool_input.get("panel_id"),
        source=(result.get("sources") or [None])[0],
        record_ids=[str(item) for item in result.get("record_ids", [])][:2_000],
        point_count=result.get("count"),
        query=tool_input,
    )


# The model reasons over shapes and magnitudes, not over thousands of rows — and
# every tool result is resent on every subsequent round, so anything unbounded
# here compounds until the request exceeds the context window. These caps decide
# what Claude *sees*; the full evidence (including every record id) is collected
# server-side and returned to the client untouched.
_MODEL_SAMPLE_ROWS = 25
_MODEL_RECORD_IDS = 20

# Keys whose payloads are large and are summarised before Claude sees them.
_BULK_KEYS = ("records", "series", "pairs")


def _model_projection(result: dict[str, Any]) -> dict[str, Any]:
    """Bound a tool result to what is useful to the model.

    Long row sets are replaced by descriptive statistics plus a small evenly
    spaced sample. The untruncated ``count`` is always preserved, so the model
    still knows how much data stands behind the numbers it is given.
    """
    projected = {
        key: value
        for key, value in result.items()
        if key not in _BULK_KEYS and key != "evidence_refs"
    }

    record_ids = result.get("record_ids")
    if isinstance(record_ids, list) and len(record_ids) > _MODEL_RECORD_IDS:
        projected["record_ids"] = record_ids[:_MODEL_RECORD_IDS]
        projected["record_ids_omitted"] = len(record_ids) - _MODEL_RECORD_IDS

    for key in _BULK_KEYS:
        rows = result.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        values = [
            row.get("value")
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("value"), (int, float))
        ]
        if values:
            projected[f"{key}_stats"] = {
                "n": len(values),
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
            }
        if len(rows) <= _MODEL_SAMPLE_ROWS:
            projected[key] = rows
            continue
        step = math.ceil(len(rows) / _MODEL_SAMPLE_ROWS)
        sample = rows[::step][: _MODEL_SAMPLE_ROWS - 1] + [rows[-1]]
        projected[key] = sample
        projected[f"{key}_sampled"] = True
        projected[f"{key}_total"] = len(rows)
    return projected


def _dispatch_tool(
    name: str,
    tool_input: dict[str, Any],
    evidence_sink: list[EvidenceReference] | None = None,
    action_sink: list[WorkspaceActionProposal] | None = None,
) -> dict[str, Any]:
    """Execute a tool by name with Claude-provided input; never raises.

    Returns the *model-facing* projection of the result. Full evidence and any
    workspace proposal are appended to the sinks instead of being round-tripped
    through the conversation, which keeps the transcript bounded no matter how
    much data a tool touched.
    """
    func = _TOOL_FUNCTIONS.get(name)
    if func is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = func(**tool_input)
        evidence = _evidence_for_tool(name, tool_input, result)
        if evidence is not None:
            if evidence_sink is not None:
                evidence_sink.append(evidence)
            result = dict(result)
            result["evidence_id"] = evidence.evidence_id
        if action_sink is not None and isinstance(result.get("proposal"), dict):
            try:
                action_sink.append(
                    WorkspaceActionProposal.model_validate(result["proposal"])
                )
            except Exception:
                pass
        return _model_projection(result)
    except Exception as exc:  # surface the error to Claude as a tool result
        return {"error": f"{type(exc).__name__}: {exc}"}


# --- Anthropic client (lazy) + tool-use loop -------------------------------------

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    """Construct (once) and return the Anthropic client.

    Reads ``ANTHROPIC_API_KEY`` from the environment. Construction is lazy so that
    importing this module and calling the tool functions directly never requires a
    key.
    """
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _build_system_prompt(workspace_context: WorkspaceContext | None = None) -> str:
    """Add bounded visible-workspace context without changing the base policy."""
    if workspace_context is None:
        return SYSTEM_PROMPT
    context = json.dumps(
        workspace_context.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "The following is trusted, read-only context about the panels currently "
        "visible to the user. Use stable panel IDs in any proposal; do not infer "
        "measurements from this context:\n"
        f"<workspace_context>{context}</workspace_context>"
    )


class AgentCancelled(Exception):
    """Raised when a caller's ``cancel_check`` asks the tool loop to stop."""


def _run_agent(
    messages: list[dict[str, Any]],
    workspace_context: WorkspaceContext | None = None,
    *,
    max_tokens: int = _MAX_TOKENS,
    max_rounds: int = _MAX_TOOL_ROUNDS,
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    on_round: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    evidence_sink: list[EvidenceReference] | None = None,
    action_sink: list[WorkspaceActionProposal] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Drive the full tool-use loop until Claude returns a final text answer.

    ``messages`` is mutated/extended in place with assistant turns (serialized to
    plain dicts so the history stays JSON-serializable for session persistence) and
    tool-result turns. Returns the final assistant text and the updated history.

    The budget and tool set are parameters so a long-running deep-research run can
    use a much larger loop than an interactive chat turn without forking this
    function. ``cancel_check`` is polled between rounds (same contract as
    ``raw_signal_import.import_raw_signals``) so a cancelled job stops promptly.
    """
    client = _get_client()
    active_tools = TOOL_SCHEMAS if tools is None else tools

    for round_index in range(max_rounds + 1):
        if cancel_check is not None and cancel_check():
            raise AgentCancelled()
        if on_round is not None:
            on_round(round_index)
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system or _build_system_prompt(workspace_context),
            tools=active_tools,
            messages=messages,
        )

        # Persist the assistant turn as plain dicts (keeps history serializable).
        assistant_content = [
            block.model_dump(exclude_none=True) for block in response.content
        ]
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason != "tool_use":
            break

        # Execute every tool_use block and return all results in one user turn.
        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "tool_use":
                result = _dispatch_tool(
                    block.name, dict(block.input), evidence_sink, action_sink
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                        "is_error": "error" in result,
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    else:
        raise RuntimeError(
            f"The assistant exceeded the maximum number of tool rounds ({max_rounds})."
        )

    final_text = "".join(
        block.get("text", "")
        for block in messages[-1]["content"]
        if block.get("type") == "text"
    )
    return final_text, messages


def _extract_tool_metadata(
    messages: list[dict[str, Any]],
) -> tuple[list[EvidenceReference], list[WorkspaceActionProposal]]:
    """Recover evidence/proposals from serialized tool-result history."""
    evidence_by_id: dict[str, EvidenceReference] = {}
    actions_by_id: dict[str, WorkspaceActionProposal] = {}
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            raw = block.get("content")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (TypeError, ValueError):
                    continue
            if not isinstance(raw, dict):
                continue
            for item in raw.get("evidence_refs", []):
                try:
                    evidence = EvidenceReference.model_validate(item)
                except Exception:
                    continue
                evidence_by_id[evidence.evidence_id] = evidence
            proposal_data = raw.get("proposal")
            if proposal_data:
                try:
                    proposal = WorkspaceActionProposal.model_validate(proposal_data)
                except Exception:
                    continue
                actions_by_id[proposal.action_id] = proposal
    return list(evidence_by_id.values()), list(actions_by_id.values())


_ANALYSIS_MARKER_RE = re.compile(
    r"<!--\s*BITFIT_ANALYSIS_JSON\s*(.*?)\s*-->",
    re.IGNORECASE | re.DOTALL,
)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)


def _analysis_payload_from_text(text: str) -> tuple[str, dict[str, Any] | None]:
    """Strip the optional machine-readable block and parse its JSON payload."""
    marker_match = _ANALYSIS_MARKER_RE.search(text)
    if marker_match:
        candidate = marker_match.group(1).strip()
        clean_text = _ANALYSIS_MARKER_RE.sub("", text).strip()
    else:
        fence_match = _JSON_FENCE_RE.search(text)
        candidate = fence_match.group(1).strip() if fence_match else ""
        clean_text = _JSON_FENCE_RE.sub("", text).strip() if fence_match else text.strip()
        if not candidate and text.lstrip().startswith("{"):
            candidate = text.strip()
            clean_text = ""

    if not candidate:
        return clean_text, None
    try:
        payload = json.loads(candidate)
    except (TypeError, ValueError):
        return clean_text, None
    return clean_text, payload if isinstance(payload, dict) else None


def _normalise_action_payload(raw: Any) -> dict[str, Any] | None:
    """Fill safe defaults for model-proposed actions before Pydantic validation."""
    if not isinstance(raw, dict):
        return None
    value = dict(raw)
    value.setdefault("status", "proposed")
    value["requires_approval"] = True
    value["reversible"] = True
    if not value.get("action_id"):
        identity = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        value["action_id"] = "act_" + hashlib.sha256(identity.encode()).hexdigest()[:20]
    return value


def _structured_analysis(
    reply_text: str,
    messages: list[dict[str, Any]],
    collected_evidence: list[EvidenceReference] | None = None,
    collected_actions: list[WorkspaceActionProposal] | None = None,
) -> tuple[str, StructuredAnalysis, list[EvidenceReference], list[WorkspaceActionProposal]]:
    """Parse structured output while accepting legacy plain-text model replies.

    Evidence is taken from the live collection when the caller ran the tool loop
    (the transcript no longer carries it — see :func:`_model_projection`), and
    falls back to parsing the history so a persisted legacy conversation still
    resolves.
    """
    if collected_evidence is None and collected_actions is None:
        evidence_refs, tool_actions = _extract_tool_metadata(messages)
    else:
        evidence_refs = list(collected_evidence or [])
        tool_actions = list(collected_actions or [])
    evidence_ids = {item.evidence_id for item in evidence_refs}
    clean_text, payload = _analysis_payload_from_text(reply_text)
    fallback_narrative = (clean_text or reply_text or "No analysis was returned.").strip()
    # A reply truncated mid-JSON leaves the marker block unparseable and the whole
    # raw text lands here, which can exceed the schema's own limit. Clamp rather
    # than raise: a long narrative is a degraded answer, not a failed run.
    if len(fallback_narrative) > _MAX_NARRATIVE_CHARS:
        fallback_narrative = (
            fallback_narrative[:_MAX_NARRATIVE_CHARS - 3].rstrip() + "..."
        )
    parsed_actions: list[WorkspaceActionProposal] = []
    if payload:
        for raw_action in payload.get("workspace_actions", []):
            normalized = _normalise_action_payload(raw_action)
            if normalized is None:
                continue
            try:
                parsed_actions.append(WorkspaceActionProposal.model_validate(normalized))
            except Exception:
                continue

    actions_by_id = {item.action_id: item for item in tool_actions}
    actions_by_id.update({item.action_id: item for item in parsed_actions})
    actions = list(actions_by_id.values())

    # Never trust evidence IDs invented in the final text.  The only IDs exposed
    # to clients are references produced by the server-side read tools.
    if payload:
        payload = dict(payload)
        payload["narrative"] = payload.get("narrative") or clean_text or reply_text
        payload["evidence_refs"] = [item.model_dump(mode="json") for item in evidence_refs]
        payload["workspace_actions"] = [item.model_dump(mode="json") for item in actions]
        for field in ("observations", "hypotheses", "uncertainties"):
            values = []
            for item in payload.get(field, []):
                if not isinstance(item, dict):
                    continue
                item = dict(item)
                item["evidence_ids"] = [
                    evidence_id
                    for evidence_id in item.get("evidence_ids", [])
                    if evidence_id in evidence_ids
                ]
                values.append(item)
            payload[field] = values
        try:
            analysis = StructuredAnalysis.model_validate(payload)
        except Exception:
            analysis = StructuredAnalysis(
                narrative=fallback_narrative,
                evidence_refs=evidence_refs,
                workspace_actions=actions,
            )
    else:
        analysis = StructuredAnalysis(
            narrative=fallback_narrative,
            evidence_refs=evidence_refs,
            workspace_actions=actions,
        )
    return clean_text or analysis.narrative, analysis, evidence_refs, actions


def chat(
    user_message: str,
    conversation_history: Optional[list[dict[str, Any]]] = None,
    workspace_context: WorkspaceContext | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Answer a natural-language question over the user's health data.

    Implements the full Claude tool-use loop: the message and tool definitions are
    sent to Claude; whenever Claude responds with ``tool_use`` blocks, the matching
    Python query runs and the results are sent back as ``tool_result`` blocks; this
    repeats until Claude produces a final text answer.

    Args:
        user_message: The user's question.
        conversation_history: Prior messages (as returned here) to continue a
            session. ``None`` starts fresh.

    Returns:
        ``{"reply": <final text>, "conversation_history": <updated messages>}``.
        The history is JSON-serializable so a FastAPI chat route can persist it.
    """
    messages: list[dict[str, Any]] = list(conversation_history or [])
    if workspace_context is not None and not isinstance(workspace_context, WorkspaceContext):
        workspace_context = WorkspaceContext.model_validate(workspace_context)
    messages.append({"role": "user", "content": user_message})
    evidence_sink: list[EvidenceReference] = []
    action_sink: list[WorkspaceActionProposal] = []
    reply, history = _run_agent(
        messages,
        workspace_context=workspace_context,
        evidence_sink=evidence_sink,
        action_sink=action_sink,
    )
    clean_reply, analysis, evidence_refs, actions = _structured_analysis(
        reply, history, evidence_sink, action_sink
    )
    result = ChatResult(
        reply=clean_reply,
        conversation_history=history,
        analysis=analysis,
        evidence_refs=evidence_refs,
        workspace_actions=actions,
    )
    return result.model_dump(mode="json", exclude_none=True)


def sleep_coaching_summary() -> str:
    """Produce a focused sleep-coaching writeup grounded in recent data.

    A specialized view over the same tools (not a separate system): it runs a fixed
    multi-tool query sequence — recent sleep-stage minutes plus correlated resting
    heart rate and activity, and any recent anomalies — pre-fetches that data via
    the tool backends, then asks Claude to write a sleep-coaching summary. Claude
    may still call the tools for any follow-up detail it needs.

    Returns:
        The sleep-coaching writeup as text.
    """
    today = dt.date.today()
    window_start = (today - dt.timedelta(days=30)).isoformat()
    window_end = today.isoformat()

    # Fixed multi-tool sequence: recent sleep stages + correlated HR/activity.
    prefetched = {
        "window": {"start_date": window_start, "end_date": window_end},
        "sleep_deep_minutes_mean": query_health_data(
            "sleep_deep_minutes", window_start, window_end, "mean"
        ),
        "sleep_rem_minutes_mean": query_health_data(
            "sleep_rem_minutes", window_start, window_end, "mean"
        ),
        "sleep_light_minutes_mean": query_health_data(
            "sleep_light_minutes", window_start, window_end, "mean"
        ),
        "sleep_awake_minutes_mean": query_health_data(
            "sleep_awake_minutes", window_start, window_end, "mean"
        ),
        "resting_heart_rate_mean": query_health_data(
            "resting_heart_rate", window_start, window_end, "mean"
        ),
        "active_zone_minutes_mean": query_health_data(
            "active_zone_minutes", window_start, window_end, "mean"
        ),
        "recent_anomalies": get_anomalies(window_start),
    }

    user_message = (
        "Please write a focused sleep-coaching summary for me based on roughly the "
        f"last 30 days ({window_start} to {window_end}).\n\n"
        "I've already pulled the relevant figures from my data below (all values "
        "come from real tool queries). Interpret my sleep-stage balance, relate it "
        "to my resting heart rate and activity, call out anything notable in the "
        "anomalies, and give me a few concrete, encouraging suggestions to improve "
        "my sleep. If you need any additional numbers, use the tools.\n\n"
        "Pre-fetched data (JSON):\n"
        f"{json.dumps(prefetched, indent=2)}"
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    reply, history = _run_agent(messages)
    clean_reply, _analysis, _evidence, _actions = _structured_analysis(reply, history)
    return clean_reply
