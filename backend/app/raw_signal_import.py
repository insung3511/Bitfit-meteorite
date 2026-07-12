"""Bounded, idempotent indexer for Google Fit Takeout signal data.

The legacy importer deliberately reduces Takeout files to one row per day.  This
module keeps the interval/session/track observations in a separate local SQLite
index so exploratory charts can use the original resolution without changing the
daily ``DailyMetric`` contract.  Files are checkpointed by SHA-256 and each point
has a stable file/record fingerprint, making interrupted or repeated imports safe.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

from sqlalchemy import text

SCHEMA_VERSION = 1
DEFAULT_MAX_FILE_BYTES = 32 * 1024 * 1024
DEFAULT_BATCH_SIZE = 500


def _get_engine(engine=None):
    if engine is not None:
        return engine
    from app.db import engine as app_engine

    return app_engine


def ensure_raw_signal_schema(engine=None) -> None:
    """Create the raw index tables without requiring a SQLModel migration."""
    engine = _get_engine(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw_import_batch (
                id VARCHAR PRIMARY KEY,
                source VARCHAR NOT NULL,
                root_path VARCHAR NOT NULL,
                schema_version INTEGER NOT NULL,
                status VARCHAR NOT NULL,
                started_at DATETIME NOT NULL,
                finished_at DATETIME,
                files_seen INTEGER NOT NULL DEFAULT 0,
                files_processed INTEGER NOT NULL DEFAULT 0,
                files_skipped INTEGER NOT NULL DEFAULT 0,
                files_errored INTEGER NOT NULL DEFAULT 0,
                points_inserted INTEGER NOT NULL DEFAULT 0,
                points_skipped INTEGER NOT NULL DEFAULT 0,
                error_json TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw_import_file (
                file_hash VARCHAR PRIMARY KEY,
                source_file VARCHAR NOT NULL,
                source_kind VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                import_batch_id VARCHAR NOT NULL,
                points_inserted INTEGER NOT NULL DEFAULT 0,
                points_skipped INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                first_seen_at DATETIME NOT NULL,
                completed_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw_signal (
                id INTEGER PRIMARY KEY,
                source VARCHAR NOT NULL,
                provider VARCHAR NOT NULL,
                signal_type VARCHAR NOT NULL,
                metric_name VARCHAR NOT NULL,
                timestamp DATETIME NOT NULL,
                end_timestamp DATETIME,
                value_float FLOAT,
                value_text VARCHAR,
                value_json TEXT,
                unit VARCHAR,
                data_source VARCHAR,
                origin_data_source VARCHAR,
                source_kind VARCHAR NOT NULL,
                source_file VARCHAR NOT NULL,
                source_record_index INTEGER NOT NULL,
                source_value_index INTEGER NOT NULL DEFAULT 0,
                file_hash VARCHAR NOT NULL,
                import_batch_id VARCHAR NOT NULL,
                metadata_json TEXT,
                created_at DATETIME NOT NULL,
                record_fingerprint VARCHAR NOT NULL UNIQUE
            )
        """))
        for statement in (
            "CREATE INDEX IF NOT EXISTS ix_raw_signal_metric_time ON raw_signal (metric_name, timestamp)",
            "CREATE INDEX IF NOT EXISTS ix_raw_signal_type_time ON raw_signal (signal_type, timestamp)",
            "CREATE INDEX IF NOT EXISTS ix_raw_signal_source_file ON raw_signal (file_hash)",
            "CREATE INDEX IF NOT EXISTS ix_raw_import_file_status ON raw_import_file (status)",
        ):
            conn.execute(text(statement))


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _timestamp(value: Any) -> Optional[dt.datetime]:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # Google Fit exports timestamps as Unix nanoseconds.
            number = int(value)
            if abs(number) > 10_000_000_000_000:
                sec, nanos = divmod(number, 1_000_000_000)
                return dt.datetime.fromtimestamp(sec, tz=dt.timezone.utc).replace(
                    microsecond=nanos // 1000
                )
            return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
        raw = str(value).strip().replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _duration_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    raw = str(value).strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)s", raw, re.I)
    if match:
        return _number(match.group(1))
    match = re.fullmatch(
        r"P(?:([0-9]+)D)?(?:T(?:([0-9]+)H)?(?:([0-9]+)M)?(?:([0-9]+(?:\.[0-9]+)?)S)?)?",
        raw,
        re.I,
    )
    if match:
        days, hours, minutes, seconds = (_number(part) or 0 for part in match.groups())
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
    return _number(value)


def _json(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


@dataclass
class RawSignalPoint:
    timestamp: dt.datetime
    end_timestamp: Optional[dt.datetime]
    metric_name: str
    signal_type: str
    value_float: Optional[float] = None
    value_text: Optional[str] = None
    value_json: Optional[str] = None
    unit: Optional[str] = None
    data_source: Optional[str] = None
    origin_data_source: Optional[str] = None
    source_kind: str = "unknown"
    source_record_index: int = 0
    source_value_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FileResult:
    kind: str
    points: Iterable[RawSignalPoint]


_TYPE_MAP: dict[str, tuple[str, str, Optional[str]]] = {
    "com.google.step_count.delta": ("steps_delta", "steps_delta", "count"),
    "com.google.step_count.cumulative": ("steps_cumulative", "steps_cumulative", "count"),
    "com.google.heart_rate.bpm": ("heart_rate", "heart_rate", "bpm"),
    "com.google.distance.delta": ("distance", "distance", "meters"),
    "com.google.speed": ("speed", "speed", "m/s"),
    "com.google.calories.expended": ("calories", "calories", "kcal"),
    "com.google.weight": ("weight", "weight", "kg"),
    "com.google.sleep.segment": ("sleep_stage", "sleep_stage", "stage"),
    "com.google.activity.segment": ("activity_type", "activity_type", "activity"),
    "com.google.location.sample": ("location", "location", "coordinate"),
    "com.google.sensor.events": ("sensor_event", "sensor_event", "event"),
}


def metric_for_type(data_type: str) -> tuple[str, Optional[str]]:
    """Return a stable metric and unit for a Google Fit data type."""
    known = _TYPE_MAP.get(data_type)
    if known:
        return known[0], known[2]
    value = data_type.removeprefix("com.google.")
    metric = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unknown"
    return metric, None


def _fit_values(point: dict[str, Any]) -> Iterator[tuple[int, Optional[float], Optional[str], Optional[str]]]:
    values = point.get("fitValue") or point.get("value") or []
    if isinstance(values, dict):
        values = [values]
    if not isinstance(values, list):
        values = [values]
    keys = ("fpVal", "doubleVal", "floatVal", "intVal", "longVal", "boolVal", "stringVal")
    for index, item in enumerate(values):
        obj = item.get("value", item) if isinstance(item, dict) else item
        if isinstance(obj, dict):
            for key in keys:
                if key not in obj:
                    continue
                raw = obj[key]
                number = _number(raw)
                if number is not None:
                    yield index, number, None, None
                elif raw is not None:
                    yield index, None, str(raw), _json(obj)
                break
            else:
                yield index, None, None, _json(obj)
        else:
            number = _number(obj)
            yield index, number, None if number is not None else str(obj), None


def _fit_points(data: dict[str, Any], source_kind: str) -> Iterator[RawSignalPoint]:
    data_source = str(data.get("Data Source") or data.get("dataSource") or "")
    records = data.get("Data Points") or data.get("dataPoints") or []
    if not isinstance(records, list):
        return
    for record_index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        data_type = str(record.get("dataTypeName") or "unknown")
        metric, unit = metric_for_type(data_type)
        start = _timestamp(record.get("startTimeNanos") or record.get("startTime"))
        end = _timestamp(record.get("endTimeNanos") or record.get("endTime")) or start
        if start is None:
            continue
        metadata = {
            "modified_time_millis": record.get("modifiedTimeMillis"),
            "raw_timestamp_nanos": record.get("rawTimestampNanos"),
        }
        origin = record.get("originDataSourceId")
        for value_index, number, text_value, json_value in _fit_values(record):
            yield RawSignalPoint(
                timestamp=start,
                end_timestamp=end,
                metric_name=metric,
                signal_type=data_type,
                value_float=number,
                value_text=text_value,
                value_json=json_value,
                unit=unit,
                data_source=data_source or None,
                origin_data_source=str(origin) if origin else None,
                source_kind=source_kind,
                source_record_index=record_index,
                source_value_index=value_index,
                metadata=metadata,
            )


def _parse_session(data: dict[str, Any]) -> Iterator[RawSignalPoint]:
    activity = str(data.get("fitnessActivity") or "unknown").lower()
    start = _timestamp(data.get("startTime"))
    end = _timestamp(data.get("endTime")) or start
    duration = _duration_seconds(data.get("duration"))
    if start is None:
        return
    session_metric = "sleep_session" if activity == "sleep" else "activity_session"
    yield RawSignalPoint(
        timestamp=start,
        end_timestamp=end,
        metric_name=session_metric,
        signal_type="session",
        value_float=duration,
        value_text=activity,
        unit="seconds",
        source_kind="session",
        source_record_index=0,
        metadata={"segment_count": len(data.get("segment") or []), "aggregate": data.get("aggregate") or []},
    )
    for index, segment in enumerate(data.get("segment") or []):
        if not isinstance(segment, dict):
            continue
        segment_start = _timestamp(segment.get("startTime")) or start
        segment_end = _timestamp(segment.get("endTime")) or segment_start
        segment_duration = (segment_end - segment_start).total_seconds() if segment_end else None
        segment_activity = str(segment.get("fitnessActivity") or activity).lower()
        yield RawSignalPoint(
            timestamp=segment_start,
            end_timestamp=segment_end,
            metric_name="sleep_segment" if segment_activity == "sleep" else "activity_segment",
            signal_type="session_segment",
            value_float=segment_duration,
            value_text=segment_activity,
            unit="seconds",
            source_kind="session_segment",
            source_record_index=index + 1,
        )
    for index, aggregate in enumerate(data.get("aggregate") or []):
        if not isinstance(aggregate, dict):
            continue
        data_type = str(aggregate.get("metricName") or "session_metric")
        metric, unit = metric_for_type(data_type)
        number = _number(aggregate.get("floatValue"))
        if number is None:
            number = _number(aggregate.get("intValue"))
        if number is None:
            continue
        yield RawSignalPoint(
            timestamp=start,
            end_timestamp=end,
            metric_name=metric,
            signal_type=data_type,
            value_float=number,
            unit=unit,
            source_kind="session_aggregate",
            source_record_index=1000 + index,
            metadata={"session_activity": activity},
        )


_CSV_FIELDS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("걸음 수", "steps", "step count"), "steps_delta", "count"),
    (("칼로리(kcal)", "calories (kcal)", "calories"), "calories", "kcal"),
    (("거리(m)", "distance (m)", "distance"), "distance", "meters"),
    (("평균 심박수(bpm)", "average heart rate (bpm)", "average heart rate"), "heart_rate", "bpm"),
    (("최대 심박수(bpm)", "maximum heart rate (bpm)", "maximum heart rate"), "heart_rate_max", "bpm"),
    (("최소 심박수(bpm)", "minimum heart rate (bpm)", "minimum heart rate"), "heart_rate_min", "bpm"),
    (("평균 속도(m/s)", "average speed (m/s)", "average speed"), "speed", "m/s"),
    (("最高速",), "speed_max", "m/s"),
    (("평균 몸무게(kg)", "average weight(kg)", "weight"), "weight", "kg"),
)


def _date_from_name(name: str) -> Optional[dt.date]:
    match = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})", name)
    if not match:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _csv_time(value: str, day: dt.date) -> Optional[dt.datetime]:
    raw = (value or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})(?:\.\d+)?([+-]\d{2}:\d{2})?$", raw)
    if not match:
        return None
    hour, minute, second = (int(match.group(index)) for index in (1, 2, 3))
    if hour == 24:
        hour = 0
        day = day + dt.timedelta(days=1)
    offset = match.group(4)
    tz = dt.timezone(dt.timedelta(hours=int(offset[1:3]), minutes=int(offset[4:]))) if offset else dt.timezone.utc
    if offset and offset.startswith("-"):
        tz = dt.timezone(-dt.timedelta(hours=int(offset[1:3]), minutes=int(offset[4:])))
    try:
        return dt.datetime.combine(day, dt.time(hour, minute, second), tzinfo=tz).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def _parse_interval_csv(path: str) -> Iterator[RawSignalPoint]:
    day = _date_from_name(os.path.basename(path))
    if day is None:
        return
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = {str(name).strip().lower(): name for name in (reader.fieldnames or [])}
        start_key = headers.get("시작 시간") or headers.get("start time")
        end_key = headers.get("종료 시간") or headers.get("end time")
        if not start_key or not end_key:
            return
        for row_index, row in enumerate(reader):
            start = _csv_time(str(row.get(start_key) or ""), day)
            end = _csv_time(str(row.get(end_key) or ""), day)
            if start is None:
                continue
            for field_index, (aliases, metric, unit) in enumerate(_CSV_FIELDS):
                key = next((headers.get(alias.lower()) for alias in aliases if headers.get(alias.lower())), None)
                if not key:
                    continue
                number = _number(row.get(key))
                if number is None:
                    continue
                yield RawSignalPoint(
                    timestamp=start,
                    end_timestamp=end or start,
                    metric_name=metric,
                    signal_type="google_fit_interval",
                    value_float=number,
                    unit=unit,
                    data_source="google_fit_takeout:interval_csv",
                    source_kind="interval_csv",
                    source_record_index=row_index,
                    source_value_index=field_index,
                )


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_tcx(path: str) -> Iterator[RawSignalPoint]:
    track_index = 0
    lap_index = 0
    try:
        context = ET.iterparse(path, events=("end",))
        for _event, element in context:
            tag = _local_tag(element.tag)
            if tag == "Trackpoint":
                values = {_local_tag(child.tag): (child.text or "").strip() for child in element.iter() if child is not element and child.text}
                timestamp = _timestamp(values.get("Time"))
                if timestamp is not None:
                    for value_index, (metric, key, unit) in enumerate((("track_distance", "DistanceMeters", "meters"), ("elevation", "AltitudeMeters", "meters"), ("heart_rate", "Value", "bpm"))):
                        number = _number(values.get(key))
                        if number is not None:
                            yield RawSignalPoint(timestamp, timestamp, metric, "tcx_trackpoint", value_float=number, unit=unit, source_kind="tcx_trackpoint", source_record_index=track_index, source_value_index=value_index)
                    for value_index, (metric, key) in enumerate((("gps_latitude", "LatitudeDegrees"), ("gps_longitude", "LongitudeDegrees")), start=3):
                        number = _number(values.get(key))
                        if number is not None:
                            yield RawSignalPoint(timestamp, timestamp, metric, "tcx_trackpoint", value_float=number, unit="degrees", source_kind="tcx_trackpoint", source_record_index=track_index, source_value_index=value_index)
                track_index += 1
                element.clear()
            elif tag == "Lap":
                lap_index += 1
                values = {_local_tag(child.tag): (child.text or "").strip() for child in element.iter() if child is not element and child.text}
                start = _timestamp(element.attrib.get("StartTime")) or _timestamp(values.get("Id"))
                if start is not None:
                    duration = _number(values.get("TotalTimeSeconds"))
                    end = start + dt.timedelta(seconds=duration) if duration is not None else start
                    for value_index, (metric, key, unit) in enumerate((("activity_distance", "DistanceMeters", "meters"), ("activity_duration", "TotalTimeSeconds", "seconds"), ("activity_calories", "Calories", "kcal"))):
                        number = _number(values.get(key))
                        if number is not None:
                            yield RawSignalPoint(start, end, metric, "tcx_lap", value_float=number, unit=unit, value_text=values.get("Intensity"), source_kind="tcx_lap", source_record_index=1_000_000 + lap_index, source_value_index=value_index)
                element.clear()
    except ET.ParseError:
        raise


def _sha256(path: str, max_bytes: int) -> str:
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"file exceeds {max_bytes} byte limit")
            digest.update(chunk)
    return digest.hexdigest()


def _file_result(path: str) -> Optional[_FileResult]:
    suffix = Path(path).suffix.lower()
    if suffix == ".tcx":
        return _FileResult("tcx", _parse_tcx(path))
    if suffix == ".csv":
        return _FileResult("interval_csv", _parse_interval_csv(path))
    if suffix != ".json":
        return None
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict) and data.get("fitnessActivity"):
        return _FileResult("session", _parse_session(data))
    if isinstance(data, dict) and ("Data Points" in data or "dataPoints" in data):
        source = str(data.get("Data Source") or "").lower()
        kind = "derived_json" if source.startswith("derived:") or Path(path).name.lower().startswith("derived_") else "raw_json"
        return _FileResult(kind, _fit_points(data, kind))
    return None


class _Cancelled(Exception):
    pass


def _insert_points(engine, points: Iterable[RawSignalPoint], *, file_hash: str, source_file: str, batch_id: str, source: str, provider: str, batch_size: int) -> tuple[int, int]:
    inserted = skipped = 0
    created = _now()
    with engine.begin() as conn:
        rows: list[dict[str, Any]] = []
        for point in points:
            fingerprint = hashlib.sha256(f"{file_hash}:{point.source_record_index}:{point.source_value_index}".encode()).hexdigest()
            rows.append({
                "source": source, "provider": provider, "signal_type": point.signal_type, "metric_name": point.metric_name,
                "timestamp": point.timestamp.isoformat(), "end_timestamp": point.end_timestamp.isoformat() if point.end_timestamp else None,
                "value_float": point.value_float, "value_text": point.value_text, "value_json": point.value_json, "unit": point.unit,
                "data_source": point.data_source, "origin_data_source": point.origin_data_source, "source_kind": point.source_kind,
                "source_file": source_file, "source_record_index": point.source_record_index, "source_value_index": point.source_value_index,
                "file_hash": file_hash, "import_batch_id": batch_id, "metadata_json": _json(point.metadata), "created_at": created,
                "record_fingerprint": fingerprint,
            })
            if len(rows) >= batch_size:
                result = conn.execute(text("""INSERT OR IGNORE INTO raw_signal
                    (source, provider, signal_type, metric_name, timestamp, end_timestamp, value_float, value_text, value_json, unit,
                     data_source, origin_data_source, source_kind, source_file, source_record_index, source_value_index, file_hash,
                     import_batch_id, metadata_json, created_at, record_fingerprint)
                    VALUES (:source,:provider,:signal_type,:metric_name,:timestamp,:end_timestamp,:value_float,:value_text,:value_json,:unit,
                            :data_source,:origin_data_source,:source_kind,:source_file,:source_record_index,:source_value_index,:file_hash,
                            :import_batch_id,:metadata_json,:created_at,:record_fingerprint)"""), rows)
                inserted += max(result.rowcount or 0, 0)
                skipped += len(rows) - max(result.rowcount or 0, 0)
                rows.clear()
        if rows:
            result = conn.execute(text("""INSERT OR IGNORE INTO raw_signal
                (source, provider, signal_type, metric_name, timestamp, end_timestamp, value_float, value_text, value_json, unit,
                 data_source, origin_data_source, source_kind, source_file, source_record_index, source_value_index, file_hash,
                 import_batch_id, metadata_json, created_at, record_fingerprint)
                VALUES (:source,:provider,:signal_type,:metric_name,:timestamp,:end_timestamp,:value_float,:value_text,:value_json,:unit,
                        :data_source,:origin_data_source,:source_kind,:source_file,:source_record_index,:source_value_index,:file_hash,
                        :import_batch_id,:metadata_json,:created_at,:record_fingerprint)"""), rows)
            inserted += max(result.rowcount or 0, 0)
            skipped += len(rows) - max(result.rowcount or 0, 0)
    return inserted, skipped


def import_raw_signals(path: str, engine=None, *, cancel_check: Optional[Callable[[], bool]] = None, max_files: Optional[int] = None, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, batch_size: int = DEFAULT_BATCH_SIZE) -> dict[str, Any]:
    """Index raw/derived JSON, interval CSV, sessions, and TCX files.

    Each file is committed independently. A later invocation skips completed
    file hashes, so a killed import resumes at the next file. ``cancel_check``
    is called between files and can be used by an API job runner.
    """
    engine = _get_engine(engine)
    ensure_raw_signal_schema(engine)
    if not os.path.isdir(path):
        raise NotADirectoryError(f"Takeout path is not a directory: {path}")
    root = os.path.abspath(path)
    batch_id = str(uuid.uuid4())
    started = _now()
    report: dict[str, Any] = {"batch_id": batch_id, "status": "running", "files_seen": 0, "files_processed": 0, "files_skipped": 0, "files_errored": 0, "points_inserted": 0, "points_skipped": 0, "errors": []}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO raw_import_batch (id,source,root_path,schema_version,status,started_at) VALUES (:id,:source,:root,:version,:status,:started)"), {"id": batch_id, "source": "google_fit_takeout", "root": root, "version": SCHEMA_VERSION, "status": "running", "started": started})
    try:
        files = [os.path.join(folder, name) for folder, _dirs, names in os.walk(root) for name in sorted(names) if not name.startswith(".")]
        for full_path in files:
            if max_files is not None and report["files_processed"] + report["files_errored"] >= max_files:
                break
            report["files_seen"] += 1
            if cancel_check and cancel_check():
                raise _Cancelled()
            try:
                if Path(full_path).suffix.lower() not in {".json", ".csv", ".tcx"}:
                    report["files_skipped"] += 1
                    continue
                file_hash = _sha256(full_path, max_file_bytes)
                source_file = os.path.relpath(full_path, root)
                with engine.connect() as conn:
                    existing = conn.execute(text("SELECT status FROM raw_import_file WHERE file_hash=:hash"), {"hash": file_hash}).scalar()
                if existing == "completed":
                    report["files_skipped"] += 1
                    continue
                # Do not decode a file until its byte limit and checkpoint have
                # been checked. This keeps malformed/oversized JSON bounded too.
                result = _file_result(full_path)
                if result is None:
                    report["files_skipped"] += 1
                    continue
                with engine.begin() as conn:
                    conn.execute(text("""INSERT INTO raw_import_file (file_hash,source_file,source_kind,status,import_batch_id,first_seen_at)
                        VALUES (:hash,:file,:kind,'running',:batch,:now)
                        ON CONFLICT(file_hash) DO UPDATE SET source_file=excluded.source_file, source_kind=excluded.source_kind, status='running', import_batch_id=excluded.import_batch_id, error=NULL"""), {"hash": file_hash, "file": source_file, "kind": result.kind, "batch": batch_id, "now": _now()})
                inserted, skipped = _insert_points(engine, result.points, file_hash=file_hash, source_file=source_file, batch_id=batch_id, source="google_fit_takeout", provider="google_fit", batch_size=batch_size)
                with engine.begin() as conn:
                    conn.execute(text("UPDATE raw_import_file SET status='completed',points_inserted=:inserted,points_skipped=:skipped,completed_at=:now WHERE file_hash=:hash"), {"inserted": inserted, "skipped": skipped, "now": _now(), "hash": file_hash})
                report["files_processed"] += 1
                report["points_inserted"] += inserted
                report["points_skipped"] += skipped
            except _Cancelled:
                raise
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError, csv.Error, ET.ParseError) as exc:
                report["files_errored"] += 1
                report["errors"].append({"file": os.path.relpath(full_path, root), "error": str(exc)})
                try:
                    file_hash = _sha256(full_path, max_file_bytes)
                    with engine.begin() as conn:
                        conn.execute(text("UPDATE raw_import_file SET status='error',error=:error WHERE file_hash=:hash"), {"error": str(exc), "hash": file_hash})
                except Exception:
                    pass
        report["status"] = "complete"
    except _Cancelled:
        report["status"] = "cancelled"
    finally:
        with engine.begin() as conn:
            conn.execute(text("""UPDATE raw_import_batch SET status=:status,finished_at=:finished,files_seen=:seen,files_processed=:processed,files_skipped=:skipped,files_errored=:errored,points_inserted=:inserted,points_skipped=:point_skipped,error_json=:errors WHERE id=:id"""), {"status": report["status"], "finished": _now(), "seen": report["files_seen"], "processed": report["files_processed"], "skipped": report["files_skipped"], "errored": report["files_errored"], "inserted": report["points_inserted"], "point_skipped": report["points_skipped"], "errors": _json(report["errors"]), "id": batch_id})
    return report


def query_raw_signals(metric_name: Optional[str] = None, start: Optional[dt.datetime] = None, end: Optional[dt.datetime] = None, *, limit: int = 10_000, engine=None) -> list[dict[str, Any]]:
    """Read a bounded set of indexed points for chart/AI query layers."""
    engine = _get_engine(engine)
    ensure_raw_signal_schema(engine)
    limit = max(1, min(int(limit), 100_000))
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if metric_name:
        clauses.append("metric_name = :metric")
        params["metric"] = metric_name
    if start:
        clauses.append("timestamp >= :start")
        params["start"] = start.isoformat()
    if end:
        clauses.append("timestamp < :end")
        params["end"] = end.isoformat()
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT * FROM raw_signal{where} ORDER BY timestamp LIMIT :limit"), params).mappings().all()
    return [dict(row) for row in rows]
