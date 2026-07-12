"""Regression tests for dashboard chart window alignment."""

from __future__ import annotations

import datetime as dt

from sqlmodel import Session, SQLModel, create_engine

from app.models import DailySummary


def test_summary_uses_shared_latest_date(monkeypatch, tmp_path):
    """A stale metric must not render a different historical 30-day axis."""
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard.db'}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            DailySummary(
                date=dt.date(2025, 12, 19),
                metric_name="sleep_minutes",
                mean_7d=450,
            )
        )
        session.add(
            DailySummary(
                date=dt.date(2026, 7, 12),
                metric_name="steps",
                mean_7d=9000,
            )
        )
        session.commit()

    from app.routes import dashboard

    monkeypatch.setattr(dashboard, "engine", engine)

    assert dashboard.summary(metric="sleep_minutes", days=30)["points"] == []
    steps = dashboard.summary(metric="steps", days=30)["points"]
    assert [point["date"] for point in steps] == ["2026-07-12"]
