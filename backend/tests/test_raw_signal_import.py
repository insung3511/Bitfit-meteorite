import datetime as dt
import json

from sqlalchemy import create_engine, text

from app.raw_signal_import import import_raw_signals, query_raw_signals


def _engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'raw.db'}", connect_args={"check_same_thread": False})


def test_indexes_fit_json_idempotently(tmp_path):
    root = tmp_path / "모든 데이터"
    root.mkdir()
    (root / "raw_com.google.heart_rate.bpm.json").write_text(
        json.dumps(
            {
                "Data Source": "raw:com.google.heart_rate.bpm:watch",
                "Data Points": [
                    {
                        "dataTypeName": "com.google.heart_rate.bpm",
                        "startTimeNanos": 1480316400000000000,
                        "endTimeNanos": 1480316460000000000,
                        "fitValue": [{"value": {"fpVal": 76}}],
                    },
                    {
                        "dataTypeName": "com.google.heart_rate.bpm",
                        "startTimeNanos": 1480316460000000000,
                        "endTimeNanos": 1480316520000000000,
                        "fitValue": [{"value": {"fpVal": 82}}],
                    },
                ],
            }
        )
    )
    engine = _engine(tmp_path)

    first = import_raw_signals(str(tmp_path), engine=engine)
    second = import_raw_signals(str(tmp_path), engine=engine)

    assert first["status"] == "complete"
    assert first["points_inserted"] == 2
    assert second["points_inserted"] == 0
    assert second["files_skipped"] >= 1
    points = query_raw_signals("heart_rate", engine=engine)
    assert len(points) == 2
    assert points[0]["unit"] == "bpm"
    assert points[0]["source_kind"] == "raw_json"


def test_indexes_korean_interval_csv_sessions_and_tcx(tmp_path):
    interval = tmp_path / "일일 활동 측정항목"
    interval.mkdir()
    (interval / "2016-11-03.csv").write_text(
        "시작 시간,종료 시간,칼로리(kcal),거리(m),평균 심박수(bpm),걸음 수\n"
        "10:00:00.000-07:00,10:15:00.000-07:00,12.5,100,88,321\n",
        encoding="utf-8",
    )
    sessions = tmp_path / "모든 세션"
    sessions.mkdir()
    (sessions / "2016-11-03T10_00_00-07_00_WALKING.json").write_text(
        json.dumps(
            {
                "fitnessActivity": "walking",
                "startTime": "2016-11-03T17:00:00Z",
                "endTime": "2016-11-03T17:15:00Z",
                "duration": "900s",
                "segment": [],
                "aggregate": [{"metricName": "com.google.step_count.delta", "intValue": 321}],
            }
        )
    )
    (tmp_path / "walk.tcx").write_text(
        """<?xml version='1.0'?><TrainingCenterDatabase xmlns='urn:tcx'><Activities><Activity Sport='Walking'><Lap StartTime='2016-11-03T17:00:00Z'><Track><Trackpoint><Time>2016-11-03T17:00:00Z</Time><DistanceMeters>0</DistanceMeters><Position><LatitudeDegrees>37.5</LatitudeDegrees><LongitudeDegrees>127.1</LongitudeDegrees></Position></Trackpoint></Track><DistanceMeters>100</DistanceMeters><TotalTimeSeconds>60</TotalTimeSeconds><Calories>10</Calories></Lap></Activity></Activities></TrainingCenterDatabase>""",
        encoding="utf-8",
    )
    engine = _engine(tmp_path)

    report = import_raw_signals(str(tmp_path), engine=engine)

    assert report["status"] == "complete"
    assert report["points_inserted"] == 12
    assert query_raw_signals("steps_delta", engine=engine)
    assert query_raw_signals("activity_session", engine=engine)[0]["value_float"] == 900
    assert query_raw_signals("gps_latitude", engine=engine)[0]["value_float"] == 37.5
    assert query_raw_signals("distance", engine=engine)[0]["unit"] == "meters"


def test_rejects_oversized_file_and_keeps_batch_observable(tmp_path):
    path = tmp_path / "2016-11-03.csv"
    path.write_text("시작 시간,종료 시간,걸음 수\n" + ("10:00:00,10:15:00,1\n" * 10), encoding="utf-8")
    engine = _engine(tmp_path)

    report = import_raw_signals(str(tmp_path), engine=engine, max_file_bytes=20)

    assert report["status"] == "complete"
    assert report["files_errored"] == 1
    with engine.connect() as conn:
        row = conn.execute(text("select status, files_errored from raw_import_batch")).one()
    assert row[0] == "complete"
    assert row[1] == 1
