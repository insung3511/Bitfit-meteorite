"""Verify compute_daily_summaries against hand-calculated expected values.

Seeds a scratch SQLite DB (via a ``DATABASE_URL`` override) with 45 consecutive
days of a constant ``steps`` metric plus one deliberate spike, then checks the
computed rolling statistics for a normal day, the spike day, and a multi-source
day against numbers worked out by hand in the comments below.
"""

from __future__ import annotations

import datetime as dt
import importlib
import os

import pytest

# Metric under test and the synthetic pattern.
_METRIC = "steps"
_BASE_VALUE = 1000.0
_SPIKE_VALUE = 5000.0

_START = dt.date(2024, 1, 1)
_DAYS = 45  # 2024-01-01 .. 2024-02-14
_SPIKE_DAY = dt.date(2024, 2, 10)
_NORMAL_DAY = dt.date(2024, 2, 5)  # 30d window is entirely pre-spike
_MULTI_SOURCE_DAY = dt.date(2024, 1, 2)  # excluded from both check-day windows


@pytest.fixture()
def seeded_db(tmp_path, monkeypatch):
    """Point app.db at a fresh scratch SQLite file and seed synthetic rows."""
    db_path = tmp_path / "summarize_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    # Import (or reload) app.db AFTER the env override so its module-level engine
    # binds to the scratch DB rather than the default ./health.db.
    import app.db as db

    db = importlib.reload(db)
    import app.models as models

    db.init_db()

    from sqlmodel import Session

    with Session(db.engine) as session:
        for i in range(_DAYS):
            day = _START + dt.timedelta(days=i)
            value = _SPIKE_VALUE if day == _SPIKE_DAY else _BASE_VALUE
            session.add(
                models.DailyMetric(
                    date=day,
                    metric_name=_METRIC,
                    value=value,
                    unit="count",
                    source="takeout",
                )
            )
        # Second source on the multi-source day: takeout=1000 + google_health=3000
        # must collapse to a per-day value of 2000 before windowing.
        session.add(
            models.DailyMetric(
                date=_MULTI_SOURCE_DAY,
                metric_name=_METRIC,
                value=3000.0,
                unit="count",
                source="google_health",
            )
        )
        session.commit()

    yield db

    # Reload once more so later tests / imports don't see the scratch engine.
    importlib.reload(db)


def _summary_for(db, day: dt.date):
    from sqlmodel import Session, select
    import app.models as models

    with Session(db.engine) as session:
        return session.exec(
            select(models.DailySummary).where(
                models.DailySummary.date == day,
                models.DailySummary.metric_name == _METRIC,
            )
        ).first()


def test_normal_day(seeded_db):
    """A day whose whole 30d window is the constant baseline: flat stats."""
    from app.summarize import compute_daily_summaries

    compute_daily_summaries()
    row = _summary_for(seeded_db, _NORMAL_DAY)

    assert row is not None
    # All values in both windows are 1000 -> means 1000, stddev 0, delta 0.
    assert row.mean_7d == pytest.approx(1000.0)
    assert row.mean_30d == pytest.approx(1000.0)
    assert row.stddev_30d == pytest.approx(0.0)
    assert row.delta_vs_baseline == pytest.approx(0.0)


def test_spike_day(seeded_db):
    """The spike day: 29x1000 + 1x5000 in the 30d window, 6x1000+5000 in 7d."""
    from app.summarize import compute_daily_summaries

    compute_daily_summaries()
    row = _summary_for(seeded_db, _SPIKE_DAY)

    assert row is not None
    # mean_7d  = (6*1000 + 5000) / 7  = 11000 / 7 = 1571.428571...
    assert row.mean_7d == pytest.approx(11000.0 / 7)
    # mean_30d = (29*1000 + 5000) / 30 = 34000 / 30 = 1133.333333...
    assert row.mean_30d == pytest.approx(34000.0 / 30)
    # Sample variance = 139_200_000 / 261 = 533333.333...; stddev = 730.29674...
    assert row.stddev_30d == pytest.approx((139_200_000 / 261) ** 0.5)
    # delta = 5000 - 34000/30 = 3866.666667
    assert row.delta_vs_baseline == pytest.approx(5000.0 - 34000.0 / 30)


def test_multi_source_day_collapses_to_mean(seeded_db):
    """Two sources on one day average before windowing (1000+3000 -> 2000)."""
    from app.summarize import compute_daily_summaries

    compute_daily_summaries()
    row = _summary_for(seeded_db, _MULTI_SOURCE_DAY)

    assert row is not None
    # Only 2024-01-01 (1000) and 2024-01-02 (2000) fall in either window.
    # mean = 1500; delta = own value (2000) - 1500 = 500 proves the collapse.
    assert row.mean_7d == pytest.approx(1500.0)
    assert row.mean_30d == pytest.approx(1500.0)
    assert row.delta_vs_baseline == pytest.approx(500.0)


def test_idempotent_rerun(seeded_db):
    """Re-running updates in place: same row count, values unchanged."""
    from sqlmodel import Session, select
    import app.models as models
    from app.summarize import compute_daily_summaries

    first = compute_daily_summaries()
    second = compute_daily_summaries()

    assert second["rows_inserted"] == 0
    assert second["rows_updated"] == first["rows_upserted"]

    with Session(seeded_db.engine) as session:
        count = len(session.exec(select(models.DailySummary)).all())
    # One summary row per distinct date (45), no duplicates after re-run.
    assert count == _DAYS
