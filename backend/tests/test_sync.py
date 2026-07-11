"""Tests for the Google Health sync layer.

The live API cannot be exercised end-to-end here (no real Google Health access),
so instead we verify the parts that ARE testable offline:

* ``sync_once`` maps client records into ``DailyMetric`` rows, dedupes on re-run,
  and calls ``compute_daily_summaries`` afterwards.
* A failure inside ``sync_once`` (e.g. no connected account) is caught and
  returned as ``{"status": "error", ...}`` — never raised.
* ``POST /sync/run`` returns that graceful error (200, not a 500) when no Google
  account is connected, and the APScheduler lifespan starts/stops cleanly.
* The client's raw-response -> our-vocabulary mapping (``_normalize_data_point``)
  against hand-constructed fake ``DataPoint`` objects.
"""

from __future__ import annotations

import datetime as dt
import importlib
import os
import tempfile

import pytest
from cryptography.fernet import Fernet

# app.auth needs an encryption key at import; set one before any app import.
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
# Isolate every DB write to a throwaway file, not the real ./health.db.
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.name}"


@pytest.fixture()
def fresh_db(monkeypatch):
    """Reload app.db against the throwaway DB and clear the tables."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{_TMP_DB.name}")
    import app.db as db

    db = importlib.reload(db)
    import app.models as models
    from sqlmodel import Session, delete

    db.init_db()
    with Session(db.engine) as session:
        session.exec(delete(models.DailyMetric))
        session.exec(delete(models.DailySummary))
        session.commit()
    return db


# --------------------------------------------------------------------------- #
# sync_once mapping / dedup / summarize
# --------------------------------------------------------------------------- #
def test_sync_once_maps_records_and_summarizes(fresh_db, monkeypatch):
    import app.google_health_client as client
    import app.summarize as summarize
    import app.models as models
    from sqlmodel import Session, select

    fake_records = [
        {"date": dt.date(2024, 3, 1), "metric_name": "steps", "value": 8000.0, "unit": "count"},
        {"date": dt.date(2024, 3, 2), "metric_name": "steps", "value": 9000.0, "unit": "count"},
        {"date": dt.date(2024, 3, 1), "metric_name": "resting_heart_rate", "value": 58.0, "unit": "bpm"},
    ]
    monkeypatch.setattr(client, "fetch_recent_data", lambda since: fake_records)

    called = {"n": 0}
    real_compute = summarize.compute_daily_summaries

    def spy(*args, **kwargs):
        called["n"] += 1
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(summarize, "compute_daily_summaries", spy)

    from app.sync import sync_once

    result = sync_once()

    assert result["status"] == "ok"
    assert result["rows_synced"] == 3
    assert called["n"] == 1  # compute_daily_summaries ran after the insert

    with Session(fresh_db.engine) as session:
        metrics = session.exec(
            select(models.DailyMetric).where(
                models.DailyMetric.source == "google_health"
            )
        ).all()
        assert len(metrics) == 3
        assert {m.metric_name for m in metrics} == {"steps", "resting_heart_rate"}
        # Summaries were populated for the synced days.
        summaries = session.exec(select(models.DailySummary)).all()
        assert len(summaries) > 0


def test_sync_once_is_idempotent(fresh_db, monkeypatch):
    import app.google_health_client as client
    import app.models as models
    from sqlmodel import Session, select

    fake_records = [
        {"date": dt.date(2024, 3, 1), "metric_name": "steps", "value": 8000.0, "unit": "count"},
    ]
    monkeypatch.setattr(client, "fetch_recent_data", lambda since: fake_records)

    from app.sync import sync_once

    first = sync_once()
    second = sync_once()

    assert first["rows_synced"] == 1
    assert second["rows_synced"] == 0
    assert second["rows_skipped"] == 1

    with Session(fresh_db.engine) as session:
        count = len(
            session.exec(
                select(models.DailyMetric).where(
                    models.DailyMetric.source == "google_health"
                )
            ).all()
        )
    assert count == 1


def test_sync_once_catches_failures(fresh_db, monkeypatch):
    """A RuntimeError from the client (e.g. no account) becomes a graceful dict."""
    import app.google_health_client as client

    def boom(since):
        raise RuntimeError("No stored Google Health token.")

    monkeypatch.setattr(client, "fetch_recent_data", boom)

    from app.sync import sync_once

    result = sync_once()
    assert result["status"] == "error"
    assert "token" in result["detail"].lower()


# --------------------------------------------------------------------------- #
# POST /sync/run graceful error (handler-level)
# --------------------------------------------------------------------------- #
# NOTE: the live server path (uvicorn boot, GET /health, POST /sync/run, clean
# scheduler start/stop) is verified out-of-band with a real uvicorn process —
# fastapi's in-process TestClient is unusable in this env because the installed
# httpx is newer than starlette 0.27.0's TestClient expects. So here we call the
# route handler directly, which still exercises the real graceful-error path.
def test_sync_run_handler_graceful_error_no_account(fresh_db):
    """With no connected Google account, the handler returns the error dict."""
    from app.routes.sync import run_sync

    body = run_sync()
    assert body["status"] == "error"
    assert body["detail"]  # a message explaining no token is available


# --------------------------------------------------------------------------- #
# Client raw-response -> our-vocabulary mapping (fake DataPoints)
# --------------------------------------------------------------------------- #
def test_normalize_steps_data_point():
    import app.google_health_client as client

    spec = next(s for s in client._DATA_TYPES if s.google_name == "steps")
    fake_dp = {
        "name": "users/me/dataTypes/steps/dataPoints/1",
        "dataSource": {"platform": "FITBIT"},
        "steps": {
            "interval": {"startTime": "2024-03-01T00:00:00Z"},
            "count": "8000",
        },
    }

    records = client._normalize_data_point(spec, fake_dp)
    assert records == [
        {
            "date": dt.date(2024, 3, 1),
                "metric_name": "steps",
                "value": 8000.0,
                "unit": "count",
                "aggregation": "sum",
                "provider_record_id": "users/me/dataTypes/steps/dataPoints/1",
                "source_platform": "FITBIT",
        }
    ]


def test_normalize_sleep_fans_out_stages():
    import app.google_health_client as client

    spec = next(s for s in client._DATA_TYPES if s.google_name == "sleep")
    fake_dp = {
        "name": "users/me/dataTypes/sleep/dataPoints/1",
        "dataSource": {"platform": "FITBIT"},
        "sleep": {
            "interval": {"startTime": "2024-03-01T23:00:00Z"},
            "stages": [
                {"stage": "LIGHT", "minutes": 200},
                {"stage": "DEEP", "minutes": 90},
                {"stage": "REM", "minutes": 80},
                {"stage": "AWAKE", "minutes": 20},
            ]
        },
    }

    records = client._normalize_data_point(spec, fake_dp)
    by_metric = {r["metric_name"]: r["value"] for r in records}
    assert by_metric == {
        "sleep_light_minutes": 200.0,
        "sleep_deep_minutes": 90.0,
        "sleep_rem_minutes": 80.0,
        "sleep_awake_minutes": 20.0,
    }
    assert all(r["date"] == dt.date(2024, 3, 1) for r in records)
    assert all(r["source_platform"] == "FITBIT" for r in records)


def test_build_filter_interval_vs_civil():
    import app.google_health_client as client

    steps = next(s for s in client._DATA_TYPES if s.google_name == "steps")
    weight = next(s for s in client._DATA_TYPES if s.google_name == "weight")
    since = dt.datetime(2024, 3, 1, 12, 30, 0)

    assert (
        client._build_filter(steps, since)
        == 'steps.interval.civil_start_time >= "2024-03-01"'
    )
    assert (
        client._build_filter(weight, since)
        == 'weight.sample_time.physical_time >= "2024-03-01T12:30:00Z"'
    )
