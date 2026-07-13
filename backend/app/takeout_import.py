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
_UNIT_KCAL = "kcal"
_UNIT_KM = "km"
_UNIT_CELSIUS = "celsius"
_UNIT_SCORE = "score"
_UNIT_BREATHS = "breaths_per_min"
_UNIT_ML_KG_MIN = "ml/kg/min"

# Fitbit's Global Export Data reports body weight in pounds when the account is
# on US units (confirmed for this export: weight 176.3 with bmi 24.69 and
# height 1800mm solves to 80.0kg). The legacy Google Fit CSV reports kilograms.
# Everything is normalised to kg so the two eras share one axis.
_LB_TO_KG = 0.45359237

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


def _weight_to_kg(weight: float, bmi: Optional[float]) -> float:
    """Normalise a Fitbit weight log to kilograms.

    Fitbit exports ``weight`` in the account's display unit (pounds on US
    accounts, kilograms elsewhere) and gives no unit field. The paired ``bmi``
    disambiguates: since bmi = kg / m^2, treating the value as kilograms implies
    a height of sqrt(weight / bmi) metres. If that implied height is
    anatomically impossible (>2.2m) the value must be pounds.
    """
    if bmi and bmi > 0:
        implied_height_m = (weight / bmi) ** 0.5
        if implied_height_m > 2.2:
            return weight * _LB_TO_KG
    return weight


def _parse_weight(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """Body weight logs, normalised to kilograms via the paired BMI."""
    for entry in _iter_records(data):
        day = _parse_datetime(entry.get("date", "")) or _parse_datetime(
            entry.get("dateTime", "")
        ) or fallback
        val = _as_float(entry.get("weight"))
        if day is not None and val is not None:
            kg = _weight_to_kg(val, _as_float(entry.get("bmi")))
            yield _Sample(day, "weight", kg, _UNIT_KG, agg="mean")


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


def _scalar_parser(
    metric: str, unit: Optional[str], agg: str, *, scale: float = 1.0
) -> _Parser:
    """Build a parser for the ``[{dateTime, value}]`` shape Fitbit uses widely.

    ``scale`` converts the export's native unit (e.g. Fitbit logs distance in
    centimetres) into the unit we store.
    """

    def parse(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
        for entry in _iter_records(data):
            day = _parse_datetime(entry.get("dateTime", "")) or fallback
            val = _as_float(entry.get("value"))
            if day is not None and val is not None:
                yield _Sample(day, metric, val * scale, unit, agg=agg)

    return parse


def _parse_vo2_max(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """Demographic VO2 max -> daily cardio-fitness estimate."""
    for entry in _iter_records(data):
        day = _parse_datetime(entry.get("dateTime", "")) or fallback
        raw = entry.get("value")
        val = (
            _as_float(raw.get("filteredDemographicVO2Max") or raw.get("demographicVO2Max"))
            if isinstance(raw, dict)
            else _as_float(raw)
        )
        if day is not None and val is not None and val > 0:
            yield _Sample(day, "vo2_max", val, _UNIT_ML_KG_MIN, agg="mean")


_HR_ZONE_METRIC = {
    "BELOW_DEFAULT_ZONE_1": "hr_zone_below_minutes",
    "IN_DEFAULT_ZONE_1": "hr_zone_fat_burn_minutes",
    "IN_DEFAULT_ZONE_2": "hr_zone_cardio_minutes",
    "IN_DEFAULT_ZONE_3": "hr_zone_peak_minutes",
}


def _parse_hr_zones(data, fallback: Optional[dt.date]) -> Iterable[_Sample]:
    """Minutes spent in each Fitbit heart-rate zone, per day."""
    for entry in _iter_records(data):
        day = _parse_datetime(entry.get("dateTime", "")) or fallback
        raw = entry.get("value")
        zones = raw.get("valuesInZones") if isinstance(raw, dict) else None
        if day is None or not isinstance(zones, dict):
            continue
        for zone, minutes in zones.items():
            metric = _HR_ZONE_METRIC.get(str(zone))
            val = _as_float(minutes)
            if metric is not None and val is not None:
                yield _Sample(day, metric, val, _UNIT_MINUTES, agg="sum")


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


# --------------------------------------------------------------------------- #
# Fitbit CSV exports.
#
# The modern Fitbit/Google Health Takeout ships most daily metrics as CSV, not
# JSON — HRV, SpO2, AZM, temperature, sleep score and stress all arrive this way.
# Each file is a flat table with one timestamp column and one or more value
# columns, so they are described declaratively rather than as bespoke parsers.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _CsvField:
    aliases: tuple[str, ...]
    metric: str
    unit: Optional[str]
    agg: str = "mean"


@dataclass(frozen=True)
class _CsvSpec:
    date_aliases: tuple[str, ...]
    fields: tuple[_CsvField, ...]


def _parse_spec_csv(path: str, spec: _CsvSpec) -> Iterable[_Sample]:
    """Yield samples from a flat Fitbit CSV described by ``spec``."""
    fallback = _date_from_filename(os.path.basename(path))
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return
        headers = {str(name).strip().lower(): name for name in reader.fieldnames}
        date_key = next(
            (headers[alias] for alias in spec.date_aliases if alias in headers), None
        )
        for row in reader:
            day = _parse_datetime(str(row.get(date_key) or "")) if date_key else None
            if day is None:
                day = fallback
            if day is None:
                continue
            for field_spec in spec.fields:
                key = next(
                    (headers[alias] for alias in field_spec.aliases if alias in headers),
                    None,
                )
                if key is None:
                    continue
                value = _as_float(row.get(key))
                if value is None or value <= 0:
                    continue
                yield _Sample(
                    day, field_spec.metric, value, field_spec.unit, agg=field_spec.agg
                )


_HRV_SPEC = _CsvSpec(
    date_aliases=("timestamp",),
    fields=(
        _CsvField(("rmssd",), "hrv", _UNIT_MS),
        _CsvField(("nremhr",), "nrem_heart_rate", _UNIT_BPM),
    ),
)
_RESPIRATORY_SPEC = _CsvSpec(
    date_aliases=("timestamp",),
    fields=(_CsvField(("daily_respiratory_rate",), "respiratory_rate", _UNIT_BREATHS),),
)
_SPO2_SPEC = _CsvSpec(
    date_aliases=("timestamp",),
    fields=(_CsvField(("average_value",), "spo2", _UNIT_PERCENT),),
)
_AZM_SPEC = _CsvSpec(
    date_aliases=("date_time",),
    fields=(
        _CsvField(("total_minutes",), "active_zone_minutes", _UNIT_MINUTES, agg="sum"),
    ),
)
_TEMPERATURE_SPEC = _CsvSpec(
    date_aliases=("sleep_start",),
    fields=(_CsvField(("nightly_temperature",), "skin_temperature", _UNIT_CELSIUS),),
)
_SLEEP_SCORE_SPEC = _CsvSpec(
    date_aliases=("timestamp",),
    fields=(
        _CsvField(("overall_score",), "sleep_score", _UNIT_SCORE),
        _CsvField(("resting_heart_rate",), "resting_heart_rate", _UNIT_BPM),
    ),
)
_STRESS_SPEC = _CsvSpec(
    date_aliases=("date",),
    fields=(_CsvField(("stress_score",), "stress_score", _UNIT_SCORE),),
)

_CsvParser = Callable[[str], Iterable[_Sample]]


def _spec_parser(spec: _CsvSpec) -> _CsvParser:
    def parse(path: str) -> Iterable[_Sample]:
        return _parse_spec_csv(path, spec)

    return parse


# Order matters: the "daily" summaries must win over the intraday files that
# share a prefix (e.g. "Daily SpO2" vs "Minute SpO2").
_CSV_DISPATCH: list[tuple[re.Pattern, Optional[_CsvParser]]] = [
    (
        re.compile(r"heart[_ -]?rate[_ -]?variability[_ -]?summary|daily_heart_rate_variability"),
        _spec_parser(_HRV_SPEC),
    ),
    (
        re.compile(r"respiratory[_ -]?rate[_ -]?summary|daily_respiratory_rate"),
        _spec_parser(_RESPIRATORY_SPEC),
    ),
    (re.compile(r"^daily[_ -]?spo2|daily_oxygen_saturation"), _spec_parser(_SPO2_SPEC)),
    (re.compile(r"^active[_ -]?zone[_ -]?minutes"), _spec_parser(_AZM_SPEC)),
    (re.compile(r"^computed[_ -]?temperature"), _spec_parser(_TEMPERATURE_SPEC)),
    (re.compile(r"^sleep[_ -]?score"), _spec_parser(_SLEEP_SCORE_SPEC)),
    (re.compile(r"^stress[_ -]?score"), _spec_parser(_STRESS_SPEC)),
    # Recognised high-resolution/reference tables: indexed by raw_signal_import,
    # deliberately not folded into daily metrics here.
    (
        re.compile(
            r"^minute[_ -]?spo2|^device[_ -]?temperature|^heart[_ -]?rate[_ -]?notifications"
            r"|^glucose|readme|^daily[_ -]?readiness[_ -]?user[_ -]?properties"
        ),
        None,
    ),
]


def _classify_csv(basename: str) -> tuple[Optional[_CsvParser], bool]:
    """Return ``(parser, recognised)`` for a CSV filename."""
    name = basename.lower()
    for pattern, parser in _CSV_DISPATCH:
        if pattern.search(name):
            return parser, True
    return None, False


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
    (re.compile(r"time[_-]?in[_-]?heart[_-]?rate[_-]?zones?"), _parse_hr_zones),
    # Intraday heart-rate samples: recognised, but not one of our daily metrics.
    (re.compile(r"heart[_-]?rate"), None),
    (re.compile(r"steps"), _parse_steps),
    (re.compile(r"sleep"), _parse_sleep),
    (re.compile(r"weight"), _parse_weight),
    # Oxygen *variation* is a raw waveform, not an SpO2 reading — don't let it
    # fall through to the SpO2 parser below.
    (re.compile(r"estimated[_-]?oxygen[_-]?variation"), None),
    (re.compile(r"spo2|oxygen"), _parse_spo2),
    (re.compile(r"active[_-]?zone[_-]?minutes|(^|[^a-z])azm"), _parse_azm),
    (re.compile(r"demographic[_-]?vo2[_-]?max|(^|[^a-z])vo2"), _parse_vo2_max),
    (re.compile(r"^calories"), _scalar_parser("calories", _UNIT_KCAL, "sum")),
    # Fitbit logs distance in centimetres; store kilometres.
    (
        re.compile(r"^distance"),
        _scalar_parser("distance", _UNIT_KM, "sum", scale=1 / 100_000),
    ),
    (
        re.compile(r"very[_-]?active[_-]?minutes"),
        _scalar_parser("very_active_minutes", _UNIT_MINUTES, "sum"),
    ),
    (
        re.compile(r"moderately[_-]?active[_-]?minutes"),
        _scalar_parser("moderately_active_minutes", _UNIT_MINUTES, "sum"),
    ),
    (
        re.compile(r"lightly[_-]?active[_-]?minutes"),
        _scalar_parser("lightly_active_minutes", _UNIT_MINUTES, "sum"),
    ),
    (
        re.compile(r"sedentary[_-]?minutes"),
        _scalar_parser("sedentary_minutes", _UNIT_MINUTES, "sum"),
    ),
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
    rows_dropped_padding: int = 0
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
            "rows_dropped_padding": self.rows_dropped_padding,
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
                csv_parser, csv_recognised = _classify_csv(filename)
                if csv_recognised and csv_parser is None:
                    # Recognised but intentionally not folded into daily metrics
                    # (intraday tables, readmes, reference data).
                    report.files_processed += 1
                    continue
                try:
                    # Unrecognised names still get a shot at the legacy Google Fit
                    # daily aggregate, which is identified by its headers, not its
                    # filename (it is locale-dependent, e.g. "일일 활동 측정항목.csv").
                    samples = list(
                        csv_parser(full)
                        if csv_parser is not None
                        else _parse_google_fit_daily_csv(full)
                    )
                    if not samples:
                        report.files_skipped += 1
                        report.skipped_files.append(filename)
                        continue
                    for sample in samples:
                        accumulators[(sample.date, sample.metric_name)].add(sample)
                    report.files_processed += 1
                except (OSError, csv.Error, UnicodeError, ValueError) as exc:
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

    report.rows_dropped_padding = _drop_unrecorded_activity_days(accumulators)

    _persist(engine, DailyMetric, accumulators, report)

    # Recompute rolling summaries so a backfill immediately populates
    # DailySummary — cheap and idempotent, safe to run after every import.
    from app.summarize import compute_daily_summaries

    compute_daily_summaries()

    # Keep the established daily import as the compatibility path, then index
    # interval/session/track observations in the separate bounded raw store.
    # A raw-file error is reported without losing successfully imported daily
    # rows; callers can retry the raw pass independently.
    summary = report.as_dict()
    try:
        from app.raw_signal_import import import_raw_signals

        summary["raw_signals"] = import_raw_signals(path, engine=engine)
    except Exception as exc:  # pragma: no cover - defensive around optional index
        summary["raw_signals"] = {"status": "error", "errors": [{"error": str(exc)}]}
    return summary


# The activity-minute exports are zero-filled to the end of the current month,
# so an export taken mid-month yields trailing days of "0 active minutes, 1440
# sedentary minutes" for days the device never recorded (including days that have
# not happened yet). Left in, they read as real full-day-sedentary observations.
_ACTIVITY_FAMILY = (
    "very_active_minutes",
    "moderately_active_minutes",
    "lightly_active_minutes",
    "sedentary_minutes",
)
# Any of these existing for a day proves the device actually recorded it.
_RECORDED_EVIDENCE = ("steps", "calories", "distance")
_MINUTES_PER_DAY = 1440


def _drop_unrecorded_activity_days(accumulators: dict) -> int:
    """Remove zero-filled activity padding for days with no recorded evidence.

    A day is padding — not a genuinely sedentary day — when the device logged no
    steps, calories or distance for it *and* the activity minutes are the
    characteristic all-zero / full-day-sedentary fill.
    """
    days = {day for (day, _metric) in accumulators}
    dropped = 0
    for day in days:
        if any((day, metric) in accumulators for metric in _RECORDED_EVIDENCE):
            continue
        sedentary = accumulators.get((day, "sedentary_minutes"))
        if sedentary is None or sedentary.value < _MINUTES_PER_DAY:
            continue
        active = [
            accumulators[(day, metric)].value
            for metric in _ACTIVITY_FAMILY
            if metric != "sedentary_minutes" and (day, metric) in accumulators
        ]
        if any(value > 0 for value in active):
            continue
        for metric in _ACTIVITY_FAMILY:
            if accumulators.pop((day, metric), None) is not None:
                dropped += 1
    return dropped


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
        f"  padding dropped : {summary['rows_dropped_padding']} (unrecorded days)",
    ]
    for metric, count in sorted(summary["rows_inserted"].items()):
        lines.append(f"      {metric:<24} {count}")
    if summary["errors"]:
        lines.append("  errors:")
        for err in summary["errors"]:
            lines.append(f"      {err['file']}: {err['error']}")
    raw = summary.get("raw_signals")
    if raw:
        lines.extend(
            [
                "  raw signal index:",
                f"      status           {raw.get('status', 'unknown')}",
                f"      files processed  {raw.get('files_processed', 0)}",
                f"      points inserted  {raw.get('points_inserted', 0)}",
            ]
        )
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
