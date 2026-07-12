"""One-off importer for Fitbit or legacy Google Fit data from Google Takeout.

Google Takeout exports Fitbit data as a tree of JSON files, typically under
``Takeout/Fitbit/Global Export Data/`` (plus category folders such as
``Sleep/`` and ``Physical Activity/`` in newer exports). Each metric is split
into per-day (occasionally per-month) files whose names encode the date, e.g.
``steps-2024-03-15.json`` or ``sleep-2024-03-15.json``.

This module walks such a directory, recognises the known file shapes, folds the
raw (often per-minute) samples down to one value per day, and writes them into
:class:`app.models.DailyMetric` with ``source="takeout"``.

Design notes / real-world tolerance:

* Takeout formats drift over time, so files are dispatched by *filename
  pattern* (regex on the base name) rather than a single rigid schema, and any
  file we do not recognise — or that fails to parse — is logged and skipped
  rather than aborting the whole import.
* ``value`` fields appear both as bare scalars (``"42"`` / ``42``) and as nested
  objects (``{"bpm": 76, "confidence": 3}``); the parsers cope with both.
* ``dateTime`` timestamps appear both as Fitbit's ``MM/DD/YY HH:MM:SS`` and as
  ISO ``YYYY-MM-DDThh:mm:ss``; :func:`_parse_datetime` handles either.

Idempotency: before inserting we query the existing ``(date, metric_name)`` keys
for ``source="takeout"`` and skip any that already exist, so re-running the
import over the same folder never duplicates rows. (No schema change is needed;
``models.py`` is left untouched.)

CLI::

    python -m app.takeout_import /path/to/Takeout/Fitbit
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from sqlmodel import Session, select

# Unit labels reused across parsers.
_UNIT_COUNT = "count"
_UNIT_BPM = "bpm"
_UNIT_MINUTES = "minutes"
_UNIT_KG = "kg"
_UNIT_PERCENT = "percent"
_UNIT_MS = "ms"

_DATE_IN_NAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _parse_datetime(raw: str) -> Optional[dt.date]:
    """Return the calendar date of a Fitbit timestamp, or ``None``.

    Handles Fitbit's ``MM/DD/YY HH:MM:SS`` form and ISO-8601 forms such as
    ``2024-03-15T23:10:00.000``.
    """
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%m/%d/%y %H:%M:%S", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    # ISO-8601 (optionally with a trailing 'Z').
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _date_from_filename(name: str) -> Optional[dt.date]:
    """Extract a ``YYYY-MM-DD`` date embedded in a filename, if present."""
    m = _DATE_IN_NAME.search(name)
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _as_float(value) -> Optional[float]:
    """Best-effort coercion of a JSON scalar to ``float``."""
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


@dataclass
class _Sample:
    """A single day/metric datum emitted by a parser before aggregation."""

    date: dt.date
    metric_name: str
    value: float
    unit: Optional[str]
    agg: str = "sum"  # "sum" or "mean"


# --------------------------------------------------------------------------- #
# Per-file parsers. Each takes the decoded JSON and yields _Sample objects.
# --------------------------------------------------------------------------- #
def _parse_steps(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """Per-minute step counts -> daily total. Entries: {dateTime, value}."""
    for entry in _iter_records(data):
        day = _parse_datetime(entry.get("dateTime", "")) or fallback
        val = _as_float(entry.get("value"))
        if day is not None and val is not None:
            yield _Sample(day, "steps", val, _UNIT_COUNT, agg="sum")


def _parse_resting_hr(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """Resting heart rate. value may be scalar or {"date","value","error"}."""
    for entry in _iter_records(data):
        day = _parse_datetime(entry.get("dateTime", "")) or fallback
        raw = entry.get("value")
        val = _as_float(raw["value"]) if isinstance(raw, dict) else _as_float(raw)
        if day is not None and val is not None and val > 0:
            yield _Sample(day, "resting_heart_rate", val, _UNIT_BPM, agg="mean")


_SLEEP_STAGE_METRIC = {
    "deep": "sleep_deep_minutes",
    "light": "sleep_light_minutes",
    "rem": "sleep_rem_minutes",
    "wake": "sleep_awake_minutes",
    "awake": "sleep_awake_minutes",  # classic (non-stages) sleep logs
}


def _parse_sleep(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """Sleep sessions -> per-stage minutes, summed across sessions per day."""
    for session in _iter_records(data):
        day = _parse_datetime(session.get("dateOfSleep", "")) or fallback
        if day is None:
            continue
        summary = (session.get("levels") or {}).get("summary") or {}
        for stage, stats in summary.items():
            metric = _SLEEP_STAGE_METRIC.get(str(stage).lower())
            if metric is None:
                continue
            minutes = (
                _as_float(stats.get("minutes"))
                if isinstance(stats, dict)
                else _as_float(stats)
            )
            if minutes is not None:
                yield _Sample(day, metric, minutes, _UNIT_MINUTES, agg="sum")


def _parse_weight(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """Body weight logs. Assumed to be kilograms (see README caveat)."""
    for entry in _iter_records(data):
        day = _parse_datetime(entry.get("date", "")) or _parse_datetime(
            entry.get("dateTime", "")
        ) or fallback
        val = _as_float(entry.get("weight"))
        if day is not None and val is not None:
            yield _Sample(day, "weight", val, _UNIT_KG, agg="mean")


def _parse_spo2(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """SpO2 readings -> daily average percentage."""
    for entry in _iter_records(data):
        day = (
            _parse_datetime(entry.get("dateTime", ""))
            or _parse_datetime(entry.get("timestamp", ""))
            or fallback
        )
        raw = entry.get("value")
        if isinstance(raw, dict):
            val = _as_float(raw.get("avg") or raw.get("value"))
        else:
            val = _as_float(raw)
        if day is not None and val is not None:
            yield _Sample(day, "spo2", val, _UNIT_PERCENT, agg="mean")


def _parse_hrv(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """Heart-rate variability daily summary -> RMSSD in milliseconds."""
    for entry in _iter_records(data):
        day = (
            _parse_datetime(entry.get("timestamp", ""))
            or _parse_datetime(entry.get("dateTime", ""))
            or fallback
        )
        raw = entry.get("value")
        if isinstance(raw, dict):
            val = _as_float(raw.get("dailyRmssd") or raw.get("rmssd"))
        else:
            val = _as_float(raw)
        if day is not None and val is not None:
            yield _Sample(day, "hrv", val, _UNIT_MS, agg="mean")


def _parse_azm(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """Active Zone Minutes -> daily total minutes."""
    for entry in _iter_records(data):
        day = (
            _parse_datetime(entry.get("dateTime", ""))
            or _parse_datetime(entry.get("date_time", ""))
            or fallback
        )
        raw = entry.get("value")
        if isinstance(raw, dict):
            # Sum the fat_burn/cardio/peak breakdown, or take a total if given.
            total = raw.get("active_zone_minutes")
            if total is None:
                total = sum(
                    v for v in (_as_float(x) for x in raw.values()) if v is not None
                )
            val = _as_float(total)
        else:
            val = _as_float(raw)
        if day is not None and val is not None:
            yield _Sample(day, "active_zone_minutes", val, _UNIT_MINUTES, agg="sum")


def _parse_google_fit_sleep(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """Parse a legacy Google Fit sleep session without inventing sleep stages."""
    if (
        not isinstance(data, dict)
        or str(data.get("fitnessActivity", "")).lower() != "sleep"
    ):
        return
    day = fallback or _parse_datetime(str(data.get("endTime", "")))
    duration = str(data.get("duration", ""))
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)s", duration)
    seconds = _as_float(match.group(1)) if match else None
    if day is not None and seconds is not None and seconds > 0:
        yield _Sample(day, "sleep_minutes", seconds / 60.0, _UNIT_MINUTES, agg="sum")


_CSV_ALIASES = {
    "date": ("date", "날짜"),
    "steps": ("steps", "step count", "걸음 수"),
    "weight": ("average weight(kg)", "avg weight(kg)", "평균 몸무게(kg)"),
}


def _csv_value(row: dict[str, str], names: tuple[str, ...]) -> Optional[float]:
    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        value = _as_float(normalized.get(name.lower()))
        if value is not None:
            return value
    return None


def _parse_google_fit_daily_csv(path: str) -> Iterable[_Sample]:
    """Parse the locale-dependent Google Fit daily aggregate CSV."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return
        normalized_headers = {
            header.strip().lower() for header in reader.fieldnames
        }
        date_headers = {name.lower() for name in _CSV_ALIASES["date"]}
        if normalized_headers.isdisjoint(date_headers):
            return
        for row in reader:
            normalized = {str(key).strip().lower(): value for key, value in row.items()}
            raw_date = next(
                (
                    normalized[name.lower()]
                    for name in _CSV_ALIASES["date"]
                    if normalized.get(name.lower())
                ),
                "",
            )
            day = _parse_datetime(raw_date)
            if day is None:
                continue
            steps = _csv_value(row, _CSV_ALIASES["steps"])
            if steps is not None:
                yield _Sample(day, "steps", steps, _UNIT_COUNT, agg="sum")
            weight = _csv_value(row, _CSV_ALIASES["weight"])
            if weight is not None:
                yield _Sample(day, "weight", weight, _UNIT_KG, agg="mean")


def _iter_records(data) -> Iterable[dict]:
    """Yield dict records from a Takeout payload (list, or {"..": [..]})."""
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
    elif isinstance(data, dict):
        # Some exports wrap the array under a single key.
        for value in data.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        yield item


# --------------------------------------------------------------------------- #
# Filename dispatch. Order matters: resting_heart_rate before heart_rate.
# --------------------------------------------------------------------------- #
_Parser = Callable[[object, Optional[dt.date]], Iterable[_Sample]]

_DISPATCH: list[tuple[re.Pattern, Optional[_Parser]]] = [
    (re.compile(r"resting[_-]?heart[_-]?rate"), _parse_resting_hr),
    (re.compile(r"heart[_-]?rate[_-]?variability|daily.*hrv|(^|[^a-z])hrv"), _parse_hrv),
    # Intraday heart-rate samples: recognised, but not one of our daily metrics.
    (re.compile(r"heart[_-]?rate"), None),
    (re.compile(r"steps"), _parse_steps),
    (re.compile(r"sleep"), _parse_sleep),
    (re.compile(r"weight"), _parse_weight),
    (re.compile(r"spo2|oxygen"), _parse_spo2),
    (re.compile(r"active[_-]?zone[_-]?minutes|(^|[^a-z])azm"), _parse_azm),
]


def _classify(basename: str) -> tuple[Optional[_Parser], bool]:
    """Return ``(parser, recognised)`` for a filename.

    ``recognised`` is ``True`` for known-but-unimported shapes (e.g. intraday
    heart rate) so they are not counted as errors.
    """
    name = basename.lower()
    for pattern, parser in _DISPATCH:
        if pattern.search(name):
            return parser, True
    return None, False


# --------------------------------------------------------------------------- #
# Aggregation + import
# --------------------------------------------------------------------------- #
@dataclass
class _Accumulator:
    total: float = 0.0
    n: int = 0
    unit: Optional[str] = None
    agg: str = "sum"

    def add(self, sample: _Sample) -> None:
        self.total += sample.value
        self.n += 1
        self.unit = sample.unit
        self.agg = sample.agg

    @property
    def value(self) -> float:
        if self.agg == "mean" and self.n:
            return self.total / self.n
        return self.total


@dataclass
class _Report:
    files_processed: int = 0
    files_skipped: int = 0
    files_errored: int = 0
    rows_inserted: dict = field(default_factory=lambda: defaultdict(int))
    rows_skipped_existing: int = 0
    skipped_files: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "files_processed": self.files_processed,
            "files_skipped": self.files_skipped,
            "files_errored": self.files_errored,
            "rows_inserted": dict(self.rows_inserted),
            "rows_inserted_total": sum(self.rows_inserted.values()),
            "rows_skipped_existing": self.rows_skipped_existing,
            "skipped_files": self.skipped_files,
            "errors": self.errors,
        }


def import_takeout(path: str) -> dict:
    """Import a Fitbit or legacy Google Fit Takeout export into ``DailyMetric``.

    Args:
        path: Directory containing the export (e.g. ``.../Takeout/Fitbit``).
            The tree is walked recursively for ``*.json`` files.

    Returns:
        A summary dict: files processed/skipped/errored, rows inserted per
        metric, rows skipped as already-present, and any per-file errors.
    """
    # Imported lazily so a DATABASE_URL override set before the call is honoured
    # by app.db's module-level engine.
    from app.db import engine, init_db
    from app.models import DailyMetric

    init_db()

    report = _Report()
    if not os.path.isdir(path):
        raise NotADirectoryError(f"Takeout path is not a directory: {path}")

    # (date, metric_name) -> _Accumulator
    accumulators: dict[tuple[dt.date, str], _Accumulator] = defaultdict(_Accumulator)

    for root, _dirs, files in os.walk(path):
        for filename in sorted(files):
            full = os.path.join(root, filename)
            if filename.lower().endswith(".csv"):
                try:
                    samples = list(_parse_google_fit_daily_csv(full))
                    if not samples:
                        report.files_skipped += 1
                        report.skipped_files.append(filename)
                        continue
                    for sample in samples:
                        accumulators[(sample.date, sample.metric_name)].add(sample)
                    report.files_processed += 1
                except (OSError, csv.Error, UnicodeError) as exc:
                    report.files_errored += 1
                    report.errors.append({"file": filename, "error": str(exc)})
                continue
            if not filename.lower().endswith(".json"):
                continue
            if re.search(r"_SLEEP\.json$", filename, re.IGNORECASE):
                parser, recognised = _parse_google_fit_sleep, True
            else:
                parser, recognised = _classify(filename)

            if not recognised:
                report.files_skipped += 1
                report.skipped_files.append(filename)
                continue
            if parser is None:
                # Recognised but intentionally not imported (e.g. intraday HR).
                report.files_processed += 1
                continue

            try:
                with open(full, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                report.files_errored += 1
                report.errors.append({"file": filename, "error": str(exc)})
                continue

            fallback = _date_from_filename(filename)
            try:
                for sample in parser(data, fallback):
                    accumulators[(sample.date, sample.metric_name)].add(sample)
            except Exception as exc:  # tolerate malformed real-world payloads
                report.files_errored += 1
                report.errors.append({"file": filename, "error": repr(exc)})
                continue
            report.files_processed += 1

    _persist(engine, DailyMetric, accumulators, report)

    # Recompute rolling summaries so a backfill immediately populates
    # DailySummary — cheap and idempotent, safe to run after every import.
    from app.summarize import compute_daily_summaries

    compute_daily_summaries()

    return report.as_dict()


def _persist(engine, DailyMetric, accumulators, report: _Report) -> None:
    """Insert accumulated rows, skipping any already present for this source."""
    if not accumulators:
        return

    with Session(engine) as session:
        existing = set(
            session.exec(
                select(DailyMetric.date, DailyMetric.metric_name).where(
                    DailyMetric.source == "takeout"
                )
            ).all()
        )

        for (day, metric_name), acc in sorted(
            accumulators.items(), key=lambda kv: (kv[0][0], kv[0][1])
        ):
            if (day, metric_name) in existing:
                report.rows_skipped_existing += 1
                continue
            session.add(
                DailyMetric(
                    date=day,
                    metric_name=metric_name,
                    value=acc.value,
                    unit=acc.unit,
                    source="takeout",
                    provider_record_id=f"takeout:{day.isoformat()}:{metric_name}",
                    source_platform="TAKEOUT",
                )
            )
            report.rows_inserted[metric_name] += 1
            existing.add((day, metric_name))

        session.commit()


def _format_summary(summary: dict) -> str:
    lines = [
        "Takeout import complete:",
        f"  files processed : {summary['files_processed']}",
        f"  files skipped   : {summary['files_skipped']} (unrecognised)",
        f"  files errored   : {summary['files_errored']}",
        f"  rows inserted   : {summary['rows_inserted_total']}",
        f"  rows already in : {summary['rows_skipped_existing']}",
    ]
    for metric, count in sorted(summary["rows_inserted"].items()):
        lines.append(f"      {metric:<24} {count}")
    if summary["errors"]:
        lines.append("  errors:")
        for err in summary["errors"]:
            lines.append(f"      {err['file']}: {err['error']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.takeout_import",
        description="Import a Fitbit or legacy Google Fit Takeout export into DailyMetric.",
    )
    parser.add_argument(
        "path",
        help="Path to the Fitbit or Fitness folder inside a Google Takeout export.",
    )
    args = parser.parse_args(argv)

    summary = import_takeout(args.path)
    print(_format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
