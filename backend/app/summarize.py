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

from sqlmodel import Session, select

_WINDOW_7D = 7
_WINDOW_30D = 30


def _per_day_values(
    rows: list[tuple[dt.date, float]]
) -> dict[str, dict[dt.date, float]]:
    """Group raw ``(metric_name, date, value)`` rows into per-day means.

    Returns ``{metric_name: {date: mean_value}}`` where ``mean_value`` collapses
    all rows sharing that ``(metric_name, date)`` (across sources) to their mean.
    """
    # metric_name -> date -> [values]
    buckets: dict[str, dict[dt.date, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for metric_name, day, value in rows:
        buckets[metric_name][day].append(value)

    collapsed: dict[str, dict[dt.date, float]] = {}
    for metric_name, by_day in buckets.items():
        collapsed[metric_name] = {
            day: statistics.fmean(values) for day, values in by_day.items()
        }
    return collapsed


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
            DailyMetric.metric_name, DailyMetric.date, DailyMetric.value
        )
        if metric_names:
            statement = statement.where(DailyMetric.metric_name.in_(metric_names))
        raw_rows = list(session.exec(statement).all())

        by_metric = _per_day_values(raw_rows)

        # Preload existing summaries for the metrics we're touching so each
        # (date, metric_name) is an update-or-insert without a per-row query.
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
                    summary = DailySummary(date=day, metric_name=metric_name)
                    rows_inserted += 1
                else:
                    rows_updated += 1
                summary.mean_7d = mean_7d
                summary.mean_30d = mean_30d
                summary.stddev_30d = stddev_30d
                summary.delta_vs_baseline = delta
                session.add(summary)

        session.commit()

    return {
        "metrics": sorted(by_metric.keys()),
        "rows_upserted": rows_inserted + rows_updated,
        "rows_inserted": rows_inserted,
        "rows_updated": rows_updated,
    }
