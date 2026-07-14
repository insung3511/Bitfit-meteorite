"""Thin HTTP client for the Google Health API (reads a user's health data).

The Google Health API (2025/2026) consolidated the legacy Fitbit Web API's 100+
endpoints into a single REST resource that returns per-``dataType`` *data points*:

    GET https://health.googleapis.com/v4/{parent=users/*/dataTypes/*}/dataPoints

Confirmed against the live docs (July 2026):

* Endpoint + list method:
  https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/list
* Endpoints overview:      https://developers.google.com/health/endpoints
* Data type catalogue:     https://developers.google.com/health/data-types

What IS documented and used below:

* Base URL ``https://health.googleapis.com/v4`` and the ``dataPoints`` path,
  with ``parent = users/me/dataTypes/{dataType}`` (``dataType`` in kebab-case).
* Standard Google OAuth 2.0 bearer auth (``Authorization: Bearer <token>``).
* Query params ``pageSize``, ``pageToken`` (response ``nextPageToken``), and an
  AIP-160 ``filter`` for time-range selection, e.g.
  ``steps.interval.start_time >= "2023-11-24T00:00:00Z"``.
* The data type names for the metrics this app ingests (see ``_DATA_TYPES``).
* Response envelope ``{"dataPoints": [...], "nextPageToken": "..."}``.

The normalizer follows the documented nested ``DataPoint`` shape and isolates
the per-data-type payload keys in ``_DATA_TYPES`` so future provider additions
remain small, contract-testable changes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Iterable, Optional

import httpx

from app.auth import get_valid_access_token

BASE_URL = "https://health.googleapis.com/v4"
# Single-user personal app: the authenticated user is always "me".
USER_ID = "me"

# Retry/backoff for rate limiting (429) and transient 5xx.
_MAX_RETRIES = 4
_BACKOFF_BASE_SECONDS = 1.0
_PAGE_SIZE = 1000
_REQUEST_TIMEOUT = 30.0


@dataclass(frozen=True)
class _DataTypeSpec:
    """How to fetch and label one Google Health data type.

    Attributes:
        google_name: The data type name in kebab-case, used in the URL path
            (e.g. ``daily-resting-heart-rate``).
        time_field: The AIP-160 filter field used to bound the request by time
            (per docs: interval types use ``interval.start_time`` with RFC3339;
            sample/daily types use ``sample_time.civil_time`` with a date).
        civil: True when ``time_field`` expects a civil ``YYYY-MM-DD`` value
            rather than an RFC3339 timestamp.
        metric_name: Our internal metric vocabulary name, or ``None`` for
            ``sleep`` (which fans out into several stage metrics on parse).
        unit: Unit label stored on the resulting ``DailyMetric`` rows.
    """

    google_name: str
    time_field: str
    civil: bool
    metric_name: Optional[str]
    unit: Optional[str]
    aggregation: str
    payload_key: str


# Maps our metric vocabulary onto the documented Google Health data type names
# (https://developers.google.com/health/data-types). ``sleep`` fans out into the
# four stage metrics during normalization, so it has no single metric_name.
_DATA_TYPES: list[_DataTypeSpec] = [
    _DataTypeSpec("steps", "interval.civil_start_time", True, "steps", "count", "sum", "steps"),
    _DataTypeSpec(
        # Unlike the other sample types this one has no `sampleTime` — its
        # payload carries a flat civil `date` (confirmed live against the API).
        "daily-resting-heart-rate",
        "date",
        True,
        "resting_heart_rate",
        "bpm",
        "mean",
        "dailyRestingHeartRate",
    ),
    _DataTypeSpec(
        "heart-rate-variability",
        "sample_time.physical_time",
        False,
        "hrv",
        "ms",
        "mean",
        "heartRateVariability",
    ),
    _DataTypeSpec(
        "oxygen-saturation",
        "sample_time.physical_time",
        False,
        "spo2",
        "percent",
        "mean",
        "oxygenSaturation",
    ),
    _DataTypeSpec("weight", "sample_time.physical_time", False, "weight", "kg", "mean", "weight"),
    _DataTypeSpec(
        "active-zone-minutes",
        "interval.civil_start_time",
        True,
        "active_zone_minutes",
        "minutes",
        "sum",
        "activeZoneMinutes",
    ),
    _DataTypeSpec("sleep", "interval.civil_end_time", True, None, "minutes", "sum", "sleep"),
]

# Google sleep-stage type -> our per-stage metric name.
_SLEEP_STAGE_METRIC = {
    "LIGHT": "sleep_light_minutes",
    "DEEP": "sleep_deep_minutes",
    "REM": "sleep_rem_minutes",
    "AWAKE": "sleep_awake_minutes",
    "WAKE": "sleep_awake_minutes",
}


def fetch_recent_data(since: dt.datetime) -> list[dict]:
    """Fetch health data points recorded since ``since`` from the Google Health API.

    Args:
        since: Lower bound (UTC) for the time-range filter on each data type.

    Returns:
        A list of normalized records, each a dict with keys ``date`` (``dt.date``),
        ``metric_name`` (our vocabulary), ``value`` (``float``) and ``unit``.
        Multiple records for the same ``(date, metric_name)`` are fine — the sync
        layer collapses/dedupes them.

    Raises:
        RuntimeError: Propagated from ``get_valid_access_token()`` when no Google
            account is connected. ``httpx.HTTPError`` on unrecoverable HTTP errors.
    """
    token = get_valid_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    records: list[dict] = []
    with httpx.Client(base_url=BASE_URL, timeout=_REQUEST_TIMEOUT) as client:
        for spec in _DATA_TYPES:
            for data_point in _iter_data_points(client, headers, spec, since):
                records.extend(_normalize_data_point(spec, data_point))
    return records


def _build_filter(spec: _DataTypeSpec, since: dt.datetime) -> str:
    """Build the AIP-160 time-range filter string for a data type.

    Per the docs, interval types filter on ``<type>.interval.start_time`` with an
    RFC3339 timestamp; sample/daily types filter on
    ``<type>.sample_time.civil_time`` with a ``YYYY-MM-DD`` date.

    The ``<type>`` prefix must be the data type's snake_case name (confirmed
    live against the API — camelCase and kebab-case are both rejected with
    ``INVALID_DATA_POINT_FILTER_DATA_TYPE_RESTRICTION``).
    """
    snake = spec.google_name.replace("-", "_")
    if spec.civil:
        bound = since.date().isoformat()
    else:
        bound = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f'{snake}.{spec.time_field} >= "{bound}"'


def _iter_data_points(
    client: httpx.Client,
    headers: dict,
    spec: _DataTypeSpec,
    since: dt.datetime,
) -> Iterable[dict]:
    """Yield raw ``DataPoint`` dicts for one data type, following pagination."""
    path = f"/users/{USER_ID}/dataTypes/{spec.google_name}/dataPoints"
    params = {"pageSize": _PAGE_SIZE, "filter": _build_filter(spec, since)}

    while True:
        payload = _request_with_retry(client, path, params, headers)
        for data_point in payload.get("dataPoints", []) or []:
            if isinstance(data_point, dict):
                yield data_point
        next_token = payload.get("nextPageToken")
        if not next_token:
            return
        params = {**params, "pageToken": next_token}


def _request_with_retry(
    client: httpx.Client,
    path: str,
    params: dict,
    headers: dict,
) -> dict:
    """GET ``path`` with exponential backoff on 429 (and transient 5xx).

    Honours a ``Retry-After`` header when present; otherwise backs off
    exponentially. Raises ``httpx.HTTPStatusError`` on non-retryable failures or
    once retries are exhausted.
    """
    last_exc: Optional[httpx.HTTPStatusError] = None
    for attempt in range(_MAX_RETRIES):
        response = client.get(path, params=params, headers=headers)
        if response.status_code == 429 or response.status_code >= 500:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = _BACKOFF_BASE_SECONDS * (2**attempt)
            else:
                delay = _BACKOFF_BASE_SECONDS * (2**attempt)
            last_exc = httpx.HTTPStatusError(
                f"Retryable status {response.status_code}",
                request=response.request,
                response=response,
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(delay)
                continue
            raise last_exc
        response.raise_for_status()
        return response.json()
    # Unreachable in practice, but keeps type checkers happy.
    assert last_exc is not None
    raise last_exc


def _normalize_data_point(spec: _DataTypeSpec, data_point: dict) -> list[dict]:
    """Turn one documented Google ``DataPoint`` into normalized records."""
    payload = data_point.get(spec.payload_key)
    if not isinstance(payload, dict):
        return []
    metadata = _record_metadata(data_point)
    if spec.google_name == "sleep":
        return _normalize_sleep(payload, metadata)

    day = _extract_date(payload)
    value = _extract_value(payload)
    if day is None or value is None or spec.metric_name is None:
        return []
    return [
        {
            "date": day,
            "metric_name": spec.metric_name,
            "value": value,
            "unit": spec.unit,
            "aggregation": spec.aggregation,
            **metadata,
        }
    ]


def _normalize_sleep(payload: dict, metadata: dict[str, str]) -> list[dict]:
    """Fan a sleep session out into per-stage minute totals (best-effort).

    Best-effort shape (see the TODO in ``_normalize_data_point``): a sleep data
    point is assumed to carry stage segments, each with a stage type and a
    duration, under a ``sleep``/``stages``/``segments`` container. Unknown shapes
    yield nothing rather than guessing wrong.
    """
    day = _extract_date(payload)
    if day is None:
        return []

    container = payload
    segments = None
    if isinstance(container, dict):
        segments = (
            container.get("stages")
            or container.get("segments")
            or container.get("stageSegments")
        )
    if not isinstance(segments, list):
        return []

    minutes_by_metric: dict[str, float] = {}
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        stage = str(seg.get("stage") or seg.get("type") or "").upper()
        metric = _SLEEP_STAGE_METRIC.get(stage)
        minutes = _segment_minutes(seg)
        if metric is None or minutes is None:
            continue
        minutes_by_metric[metric] = minutes_by_metric.get(metric, 0.0) + minutes

    return [
        {
            "date": day,
            "metric_name": metric,
            "value": minutes,
            "unit": "minutes",
            "aggregation": "sum",
            **metadata,
        }
        for metric, minutes in minutes_by_metric.items()
    ]


def _record_metadata(data_point: dict) -> dict[str, str]:
    """Return stable provider identity and platform for a data point."""
    record_id = data_point.get("name")
    if not isinstance(record_id, str) or not record_id:
        encoded = json.dumps(data_point, sort_keys=True, separators=(",", ":")).encode()
        record_id = "sha256:" + hashlib.sha256(encoded).hexdigest()
    source = data_point.get("dataSource")
    platform = source.get("platform") if isinstance(source, dict) else None
    return {"provider_record_id": record_id, "source_platform": str(platform or "GOOGLE_HEALTH")}


def _extract_date(data_point: dict) -> Optional[dt.date]:
    """Best-effort calendar date of a data point (see TODO)."""
    date_field = data_point.get("date")
    if isinstance(date_field, dict):
        year, month, day = date_field.get("year"), date_field.get("month"), date_field.get("day")
        if year and month and day:
            return dt.date(year, month, day)
    for key in ("startTime", "endTime", "sampleTime", "time"):
        parsed = _parse_ts(data_point.get(key))
        if parsed is not None:
            return parsed
    interval = data_point.get("interval")
    if isinstance(interval, dict):
        for key in ("startTime", "endTime"):
            parsed = _parse_ts(interval.get(key))
            if parsed is not None:
                return parsed
    sample_time = data_point.get("sampleTime")
    if isinstance(sample_time, dict):
        # The live payload nests the actual timestamp under sampleTime.physicalTime
        # (a string) or sampleTime.civilTime.date (a {year,month,day} dict) — the
        # sampleTime dict itself is never a parseable timestamp.
        parsed = _parse_ts(sample_time.get("physicalTime"))
        if parsed is not None:
            return parsed
        civil_time = sample_time.get("civilTime")
        if isinstance(civil_time, dict):
            civil_date = civil_time.get("date")
            if isinstance(civil_date, dict):
                year, month, day = (
                    civil_date.get("year"),
                    civil_date.get("month"),
                    civil_date.get("day"),
                )
                if year and month and day:
                    return dt.date(year, month, day)
    return None


def _extract_value(data_point: dict) -> Optional[float]:
    """Best-effort numeric value of a scalar data point (see TODO)."""
    # weightGrams is reported in grams; every other unit below is used as-is.
    weight_grams = _as_float(data_point.get("weightGrams"))
    if weight_grams is not None:
        return weight_grams / 1000.0
    for key in (
        "value",
        "count",
        "bpm",
        "beatsPerMinute",
        "weight",
        "percentage",
        "milliseconds",
        "rootMeanSquareOfSuccessiveDifferencesMilliseconds",
        "minutes",
        "activeZoneMinutes",
        "fpVal",
        "intVal",
    ):
        val = _as_float(data_point.get(key))
        if val is not None:
            return val
    value = data_point.get("value")
    if isinstance(value, dict):
        for key in ("fpVal", "intVal", "value", "count"):
            val = _as_float(value.get(key))
            if val is not None:
                return val
    return None


def _segment_minutes(seg: dict) -> Optional[float]:
    """Best-effort duration-in-minutes of a sleep stage segment (see TODO)."""
    minutes = _as_float(seg.get("minutes"))
    if minutes is not None:
        return minutes
    seconds = _as_float(seg.get("durationSeconds") or seg.get("seconds"))
    if seconds is not None:
        return seconds / 60.0
    start = _parse_dt(seg.get("startTime"))
    end = _parse_dt(seg.get("endTime"))
    if start is not None and end is not None:
        return max(0.0, (end - start).total_seconds() / 60.0)
    return None


def _parse_ts(raw) -> Optional[dt.date]:
    """Parse an RFC3339 timestamp or civil date string into a ``date``."""
    parsed = _parse_dt(raw)
    if parsed is not None:
        return parsed.date()
    if isinstance(raw, str):
        try:
            return dt.date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return None
    return None


def _parse_dt(raw) -> Optional[dt.datetime]:
    """Parse an RFC3339 timestamp string into a ``datetime`` (or ``None``)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return dt.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_float(value) -> Optional[float]:
    """Coerce a JSON scalar to ``float`` (mirrors takeout_import._as_float)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None
