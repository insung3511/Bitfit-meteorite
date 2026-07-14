"""SQLModel schema for the personal health assistant.

The SQLModel tables back the Phase 1 data pipeline and versioned workspace:

* :class:`OAuthToken` — encrypted OAuth credentials for a data provider.
* :class:`DailyMetric` — flexible raw per-metric daily rows (steps, resting HR,
  sleep stages, HRV, SpO2, weight, active zone minutes, ...).
* :class:`DailySummary` — computed rolling statistics per metric per day.
"""

import datetime as dt
from typing import Optional

from sqlalchemy import UniqueConstraint
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


class OAuthState(SQLModel, table=True):
    """One-time Google OAuth CSRF state, bound to the initiating local session."""

    __tablename__ = "oauth_state"

    id: Optional[int] = Field(default=None, primary_key=True)
    state_hash: str = Field(index=True, unique=True)
    session_token: str
    expires_at: dt.datetime = Field(index=True)
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class SyncLease(SQLModel, table=True):
    """Singleton database lease preventing scheduler/manual sync overlap."""

    __tablename__ = "sync_lease"

    id: int = Field(default=1, primary_key=True)
    owner_id: str
    acquired_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class LoginThrottle(SQLModel, table=True):
    """Persistent failed-login state keyed by a hashed client address."""

    __tablename__ = "login_throttle"

    client_id: str = Field(primary_key=True)
    failed_count: int = Field(default=0)
    window_started_at: dt.datetime
    blocked_until: Optional[dt.datetime] = Field(default=None)


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
    __table_args__ = (
        UniqueConstraint("source", "provider_record_id", name="uq_daily_metric_source_record"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    date: dt.date = Field(index=True)
    metric_name: str = Field(index=True)
    value: float
    unit: Optional[str] = Field(default=None)
    source: Optional[str] = Field(
        default=None, description="e.g. 'google_health', 'takeout'"
    )
    # Stable provider identity makes repeated fetches idempotent without
    # collapsing distinct observations that happen on the same calendar day.
    provider_record_id: Optional[str] = Field(default=None, index=True)
    source_platform: Optional[str] = Field(default=None, index=True)
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)


class DailySummary(SQLModel, table=True):
    """Computed rolling statistics for a metric on a given day.

    The dashboard and the LLM tool layer read from this table (not raw rows) to
    keep queries fast and cheap.
    """

    __tablename__ = "daily_summary"
    __table_args__ = (
        UniqueConstraint("date", "metric_name", name="uq_daily_summary_date_metric"),
    )

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


class WorkspaceVersion(SQLModel, table=True):
    """Versioned dashboard workspace document for the single local user."""

    __tablename__ = "workspace_version"

    id: str = Field(primary_key=True)
    label: str
    document_json: str
    parent_id: Optional[str] = Field(default=None, index=True)
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow, index=True)


class ResearchJob(SQLModel, table=True):
    """A long-running deep-analysis run.

    Mirrors the ``raw_import_batch`` lifecycle: the row is the job's single
    source of truth, so a worker thread reports progress by updating it and
    cancellation works by flipping ``status`` and letting the worker notice
    between tool rounds.
    """

    __tablename__ = "research_job"

    id: str = Field(primary_key=True)
    status: str = Field(index=True, description="running | complete | error | cancelled")
    question: Optional[str] = Field(
        default=None, description="None means an open-ended baseline analysis."
    )
    phase: Optional[str] = Field(default=None, description="Human-readable progress.")
    rounds_done: int = Field(default=0)
    report_id: Optional[str] = Field(default=None, index=True)
    error: Optional[str] = Field(default=None)
    started_at: dt.datetime = Field(default_factory=dt.datetime.utcnow, index=True)
    finished_at: Optional[dt.datetime] = Field(default=None)


class ResearchReport(SQLModel, table=True):
    """The persisted output of a completed :class:`ResearchJob`."""

    __tablename__ = "research_report"

    id: str = Field(primary_key=True)
    job_id: str = Field(index=True)
    narrative: str
    analysis_json: str = Field(description="Serialized StructuredAnalysis.")
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow, index=True)


class HealthPlan(SQLModel, table=True):
    """A weekly/monthly plan derived from a research report.

    Plans are versioned, never mutated: superseding one writes a new row with
    ``parent_id`` set and clears ``is_active`` on the old. The daily check
    records which plan version it judged against, so history stays interpretable.
    """

    __tablename__ = "health_plan"

    id: str = Field(primary_key=True)
    report_id: str = Field(index=True)
    horizon: str = Field(description="weekly | monthly")
    plan_json: str = Field(description="Serialized HealthPlanSpec.")
    is_active: bool = Field(default=True, index=True)
    parent_id: Optional[str] = Field(default=None, index=True)
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow, index=True)


class DailyCheck(SQLModel, table=True):
    """One day's cheap readout of the data against the standing plan."""

    __tablename__ = "daily_check"
    __table_args__ = (
        UniqueConstraint("date", name="uq_daily_check_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    date: dt.date = Field(index=True)
    plan_id: Optional[str] = Field(default=None, index=True)
    summary: str
    result_json: str = Field(description="Serialized DailyCheckResult.")
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow)
