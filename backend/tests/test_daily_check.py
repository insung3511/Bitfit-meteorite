from __future__ import annotations

import datetime as dt
import importlib


def test_observed_values_use_canonical_daily_aggregation(tmp_path, monkeypatch):
    db_path = tmp_path / "daily-check.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.db as db
    import app.models as models

    db = importlib.reload(db)
    db.init_db()

    from sqlmodel import Session

    day = dt.date(2024, 4, 1)
    with Session(db.engine) as session:
        session.add_all(
            [
                models.DailyMetric(
                    date=day,
                    metric_name="steps",
                    value=100,
                    unit="count",
                    source="google_health",
                    source_platform="FITBIT",
                    provider_record_id="one",
                ),
                models.DailyMetric(
                    date=day,
                    metric_name="steps",
                    value=200,
                    unit="count",
                    source="google_health",
                    source_platform="FITBIT",
                    provider_record_id="two",
                ),
                models.DailyMetric(
                    date=day,
                    metric_name="steps",
                    value=900,
                    unit="count",
                    source="takeout",
                    provider_record_id="fallback",
                ),
            ]
        )
        session.commit()

    import app.daily_check as daily_check

    daily_check = importlib.reload(daily_check)
    observed = daily_check._observed_values(day)
    assert observed["steps"]["value"] == 300
    assert observed["steps"]["unit"] == "count"
