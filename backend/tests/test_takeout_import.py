import datetime as dt

from app.takeout_import import _parse_google_fit_daily_csv, _parse_google_fit_sleep


def test_parses_korean_google_fit_daily_csv(tmp_path):
    export = tmp_path / "daily.csv"
    export.write_text(
        "날짜,걸음 수,평균 몸무게(kg)\n"
        "2016-11-03,8817,77.69999694824219\n",
        encoding="utf-8",
    )

    samples = list(_parse_google_fit_daily_csv(str(export)))

    assert [(sample.metric_name, sample.value, sample.unit) for sample in samples] == [
        ("steps", 8817.0, "count"),
        ("weight", 77.69999694824219, "kg"),
    ]
    assert all(sample.date == dt.date(2016, 11, 3) for sample in samples)


def test_ignores_interval_csv_without_date_column(tmp_path):
    export = tmp_path / "2016-11-03.csv"
    export.write_text("시작 시간,종료 시간,걸음 수\n00:00,00:15,15\n", encoding="utf-8")

    assert list(_parse_google_fit_daily_csv(str(export))) == []


def test_parses_google_fit_sleep_session_as_total_minutes():
    samples = list(
        _parse_google_fit_sleep(
            {"fitnessActivity": "sleep", "duration": "28680s"},
            dt.date(2016, 12, 29),
        )
    )

    assert len(samples) == 1
    assert samples[0].metric_name == "sleep_minutes"
    assert samples[0].value == 478.0
    assert samples[0].unit == "minutes"
