"""Rolling summary computation for the health assistant.

Recomputes :class:`app.models.DailySummary` rows from the raw
:class:`app.models.DailyMetric` table. The dashboard and the LLM tool layer read
from ``DailySummary`` (not the raw rows) so their queries stay fast and cheap.

For every ``(metric_name, date)`` that has at least one ``DailyMetric`` row we
compute, over trailing calendar-day windows ending on (and including) that date:

* ``mean_7d``  — mean of the per-day values across the trailing 7 days.
* ``mean_30d`` — mean of the per-day values across the trailing 30 days.
* ``stddev_30d`` — *sample* standard deviation (Bessel's correction) of the
  per-day values across the trailing 30 days. ``None`` when the window holds
  fewer than two values (sample stddev is undefined for n < 2).
* ``delta_vs_baseline`` — that date's own value minus ``mean_30d``.

"That date's value" collapses multiple rows for the same ``(date, metric_name)``
— e.g. one from ``takeout`` and one from ``google_health`` — into their mean, so
each calendar day contributes a single value to every window.

Idempotency: the target rows are upserted keyed on ``(date, metric_name)`` using
the same query-then-update-or-insert pattern ``takeout_import.py`` uses (there is
no unique constraint on ``daily_summary``), so this is safe to re-run after every
sync/import.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

_WINDOW_7D = 7
_WINDOW_30D = 30


_SUM_METRICS = {
    "steps",
    "active_zone_minutes",
    "sleep_light_minutes",
    "sleep_deep_minutes",
    "sleep_rem_minutes",
    "sleep_awake_minutes",
}


def _per_day_values(rows) -> dict[str, dict[dt.date, float]]:
    """Select a canonical source then aggregate its records for each day.

    Fitbit-origin Google Health records win; reconciled Google Health records
    are next; Takeout/legacy data is historical fallback. Sources never mix in a
    canonical value, preventing a sync and a backfill from fabricating averages.
    """
    buckets: dict[tuple[str, dt.date], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for metric_name, day, value, source, platform in rows:
        if source == "google_health" and platform == "FITBIT":
            tier = "fitbit"
        elif source == "google_health":
            tier = "google_health"
        else:
            tier = "fallback"
        buckets[(metric_name, day)][tier].append(value)

    canonical: dict[str, dict[dt.date, float]] = defaultdict(dict)
    for (metric_name, day), tiers in buckets.items():
        values = tiers.get("fitbit") or tiers.get("google_health") or tiers["fallback"]
        canonical[metric_name][day] = (
            sum(values) if metric_name in _SUM_METRICS else statistics.fmean(values)
        )
    return dict(canonical)


def _window_stats(
    day: dt.date, by_day: dict[dt.date, float]
) -> tuple[float, float, float | None, float]:
    """Compute ``(mean_7d, mean_30d, stddev_30d, delta_vs_baseline)`` for ``day``.

    ``by_day`` maps every date that has a value for this metric to that date's
    per-day value. Windows are trailing calendar-day ranges ending on ``day``.
    """
    start_7d = day - dt.timedelta(days=_WINDOW_7D - 1)
    start_30d = day - dt.timedelta(days=_WINDOW_30D - 1)

    window_7d = [v for d, v in by_day.items() if start_7d <= d <= day]
    window_30d = [v for d, v in by_day.items() if start_30d <= d <= day]

    mean_7d = statistics.fmean(window_7d)
    mean_30d = statistics.fmean(window_30d)
    # Sample stddev (Bessel's correction); undefined for a single observation.
    stddev_30d = statistics.stdev(window_30d) if len(window_30d) >= 2 else None
    delta_vs_baseline = by_day[day] - mean_30d
    return mean_7d, mean_30d, stddev_30d, delta_vs_baseline


def compute_daily_summaries(metric_names: list[str] | None = None) -> dict:
    """Recompute ``DailySummary`` rows from ``DailyMetric``.

    Args:
        metric_names: Optional subset of metric names to (re)compute. When
            ``None`` (the default) every metric present in ``DailyMetric`` is
            processed.

    Returns:
        A summary dict: ``metrics`` processed, ``rows_upserted`` (inserted +
        updated), ``rows_inserted``, and ``rows_updated``.
    """
    # Imported lazily so a DATABASE_URL override set before the call is honoured
    # by app.db's module-level engine (mirrors takeout_import.py).
    from app.db import engine, init_db
    from app.models import DailyMetric, DailySummary

    init_db()

    rows_inserted = 0
    rows_updated = 0

    with Session(engine) as session:
        statement = select(
            DailyMetric.metric_name,
            DailyMetric.date,
            DailyMetric.value,
            DailyMetric.source,
            DailyMetric.source_platform,
        )
        if metric_names:
            statement = statement.where(DailyMetric.metric_name.in_(metric_names))
        raw_rows = list(session.exec(statement).all())

        by_metric = _per_day_values(raw_rows)

        # Counts are diagnostic only; writes below are DB-native atomic upserts.
        existing_stmt = select(DailySummary)
        if metric_names:
            existing_stmt = existing_stmt.where(
                DailySummary.metric_name.in_(metric_names)
            )
        existing: dict[tuple[dt.date, str], DailySummary] = {
            (row.date, row.metric_name): row
            for row in session.exec(existing_stmt).all()
        }

        for metric_name, day_values in by_metric.items():
            for day in sorted(day_values):
                mean_7d, mean_30d, stddev_30d, delta = _window_stats(
                    day, day_values
                )
                summary = existing.get((day, metric_name))
                if summary is None:
                    rows_inserted += 1
                else:
                    rows_updated += 1
                statement = sqlite_insert(DailySummary).values(
                    date=day,
                    metric_name=metric_name,
                    mean_7d=mean_7d,
                    mean_30d=mean_30d,
                    stddev_30d=stddev_30d,
                    delta_vs_baseline=delta,
                )
                session.exec(
                    statement.on_conflict_do_update(
                        index_elements=["date", "metric_name"],
                        set_={
                            "mean_7d": statement.excluded.mean_7d,
                            "mean_30d": statement.excluded.mean_30d,
                            "stddev_30d": statement.excluded.stddev_30d,
                            "delta_vs_baseline": statement.excluded.delta_vs_baseline,
                        },
                    )
                )

        session.commit()

    return {
        "metrics": sorted(by_metric.keys()),
        "rows_upserted": rows_inserted + rows_updated,
        "rows_inserted": rows_inserted,
        "rows_updated": rows_updated,
    }
