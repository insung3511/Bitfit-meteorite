"""SQLModel schema for the personal health assistant.

Three tables back the Phase 1 data pipeline:

* :class:`OAuthToken` — encrypted OAuth credentials for a data provider.
* :class:`DailyMetric` — flexible raw per-metric daily rows (steps, resting HR,
  sleep stages, HRV, SpO2, weight, active zone minutes, ...).
* :class:`DailySummary` — computed rolling statistics per metric per day.
"""

import datetime as dt
from typing import Optional

from sqlmodel import Field, SQLModel


class OAuthToken(SQLModel, table=True):
    """Stored OAuth credentials for a health-data provider.

    The refresh token is stored as an encrypted blob (Fernet) so it is never
    persisted in plaintext. The access token and its expiry are cached to avoid
    unnecessary refreshes.
    """

    __tablename__ = "oauth_token"

    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str = Field(index=True, description="e.g. 'google_health'")
    encrypted_refresh_token: bytes = Field(
        description="Fernet-encrypted refresh token blob"
    )
    access_token: Optional[str] = Field(default=None)
    access_token_expires_at: Optional[dt.datetime] = Field(default=None)
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    updated_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class DailyMetric(SQLModel, table=True):
    """A single raw metric observation for a given day.

    Modeled as a flexible key/value shape (``metric_name`` + ``value`` + ``unit``)
    rather than one column/table per metric, so new metrics can be ingested
    without a schema migration. Examples of ``metric_name``: ``steps``,
    ``resting_heart_rate``, ``sleep_light_minutes``, ``sleep_deep_minutes``,
    ``sleep_rem_minutes``, ``sleep_awake_minutes``, ``hrv``, ``spo2``,
    ``weight``, ``active_zone_minutes``.
    """

    __tablename__ = "daily_metric"

    id: Optional[int] = Field(default=None, primary_key=True)
    date: dt.date = Field(index=True)
    metric_name: str = Field(index=True)
    value: float
    unit: Optional[str] = Field(default=None)
    source: Optional[str] = Field(
        default=None, description="e.g. 'google_health', 'takeout'"
    )
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class DailySummary(SQLModel, table=True):
    """Computed rolling statistics for a metric on a given day.

    The dashboard and the LLM tool layer read from this table (not raw rows) to
    keep queries fast and cheap.
    """

    __tablename__ = "daily_summary"

    id: Optional[int] = Field(default=None, primary_key=True)
    date: dt.date = Field(index=True)
    metric_name: str = Field(index=True)
    mean_7d: Optional[float] = Field(default=None)
    mean_30d: Optional[float] = Field(default=None)
    stddev_30d: Optional[float] = Field(default=None)
    delta_vs_baseline: Optional[float] = Field(
        default=None, description="current value minus rolling baseline"
    )
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
