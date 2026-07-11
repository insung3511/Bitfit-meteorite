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
import json
import os
from typing import Any, Optional

import anthropic
from sqlmodel import Session, select

from app.db import engine
from app.models import DailyMetric, DailySummary

# --- Configuration (swappable via .env, not code) --------------------------------

# Model name is read from the environment. If unset, fall back to the model the
# project documents in .env.example. Swapping models is a config change.
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

# Max tokens for a single assistant turn. Well under the streaming threshold, so a
# plain (non-streaming) request is fine.
_MAX_TOKENS = 2048

# Anomaly threshold: a metric-day is anomalous when its deviation from baseline
# exceeds this many rolling-30-day standard deviations.
_ANOMALY_SIGMA = 2.0

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
    "When you give concrete suggestions (sleep, exercise, recovery, habits), keep them "
    "practical and encouraging, and explicitly note that they are general wellness "
    "guidance, not medical advice, and that the user should consult a qualified "
    "healthcare professional for medical concerns or before making significant "
    "changes."
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

    with Session(engine) as session:
        rows = session.exec(
            select(DailyMetric)
            .where(
                DailyMetric.metric_name == metric,
                DailyMetric.date >= start,
                DailyMetric.date <= end,
            )
            .order_by(DailyMetric.date)
        ).all()

    values = [r.value for r in rows]
    result: dict[str, Any] = {
        "metric": metric,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "aggregation": aggregation,
        "count": len(values),
    }

    if aggregation == "raw":
        result["series"] = [
            {"date": r.date.isoformat(), "value": r.value} for r in rows
        ]
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
        ).all()

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
        "anomalies": anomalies,
    }


# --- Anthropic tool schemas + dispatch -------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "query_health_data",
        "description": (
            "Query the user's historical health data for a single metric over a "
            "date range, returning an aggregate (mean/min/max) or the raw daily "
            "series. Use this for questions about levels, trends, or comparisons "
            "over a time window. Common metric names: steps, resting_heart_rate, "
            "hrv, spo2, weight, active_zone_minutes, sleep_deep_minutes, "
            "sleep_rem_minutes, sleep_light_minutes, sleep_awake_minutes."
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
                        "to get the full per-day series."
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
]

# Maps each tool name to its Python backend.
_TOOL_FUNCTIONS = {
    "query_health_data": query_health_data,
    "get_daily_summary": get_daily_summary,
    "get_anomalies": get_anomalies,
}


def _dispatch_tool(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool by name with Claude-provided input; never raises."""
    func = _TOOL_FUNCTIONS.get(name)
    if func is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return func(**tool_input)
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


def _run_agent(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Drive the full tool-use loop until Claude returns a final text answer.

    ``messages`` is mutated/extended in place with assistant turns (serialized to
    plain dicts so the history stays JSON-serializable for session persistence) and
    tool-result turns. Returns the final assistant text and the updated history.
    """
    client = _get_client()

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
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
                result = _dispatch_tool(block.name, dict(block.input))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                        "is_error": "error" in result,
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    final_text = "".join(
        block.get("text", "")
        for block in messages[-1]["content"]
        if block.get("type") == "text"
    )
    return final_text, messages


def chat(
    user_message: str,
    conversation_history: Optional[list[dict[str, Any]]] = None,
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
    messages.append({"role": "user", "content": user_message})
    reply, history = _run_agent(messages)
    return {"reply": reply, "conversation_history": history}


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
    reply, _ = _run_agent(messages)
    return reply
