import datetime as dt

from app.takeout_import import (
    _Accumulator,
    _drop_unrecorded_activity_days,
    _parse_google_fit_daily_csv,
    _parse_google_fit_sleep,
    _parse_weight,
    _spec_parser,
    _HRV_SPEC,
    _SLEEP_SCORE_SPEC,
    _Sample,
)


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


def _acc(value: float, agg: str = "sum") -> _Accumulator:
    accumulator = _Accumulator()
    accumulator.add(_Sample(dt.date(2026, 7, 13), "x", value, None, agg=agg))
    return accumulator


def test_weight_in_pounds_is_normalised_to_kg_via_bmi():
    # Fitbit exports weight in the account's display unit with no unit field.
    # 176.3lb at bmi 24.69 is a 1.80m person; read as kg it would imply 2.67m.
    samples = list(
        _parse_weight([{"date": "07/02/26", "weight": 176.3, "bmi": 24.69}], None)
    )

    assert len(samples) == 1
    assert samples[0].unit == "kg"
    assert round(samples[0].value, 1) == 80.0


def test_weight_already_in_kg_is_left_alone():
    samples = list(
        _parse_weight([{"date": "07/02/26", "weight": 80.0, "bmi": 24.69}], None)
    )

    assert round(samples[0].value, 1) == 80.0


def test_parses_fitbit_hrv_summary_csv(tmp_path):
    export = tmp_path / "Daily Heart Rate Variability Summary - 2026-07-05.csv"
    export.write_text(
        "timestamp,rmssd,nremhr,entropy\n2026-07-05T00:00:00,42.256,60.24,2.392\n",
        encoding="utf-8",
    )

    samples = list(_spec_parser(_HRV_SPEC)(str(export)))

    assert [(s.metric_name, s.value, s.unit) for s in samples] == [
        ("hrv", 42.256, "ms"),
        ("nrem_heart_rate", 60.24, "bpm"),
    ]
    assert all(s.date == dt.date(2026, 7, 5) for s in samples)


def test_sleep_score_csv_yields_score_and_resting_heart_rate(tmp_path):
    export = tmp_path / "sleep_score.csv"
    export.write_text(
        "sleep_log_entry_id,timestamp,overall_score,resting_heart_rate\n"
        "53009568837,2026-07-11T06:14:30Z,73,67\n",
        encoding="utf-8",
    )

    samples = list(_spec_parser(_SLEEP_SCORE_SPEC)(str(export)))

    assert [(s.metric_name, s.value) for s in samples] == [
        ("sleep_score", 73.0),
        ("resting_heart_rate", 67.0),
    ]


def test_drops_zero_filled_activity_padding_for_unrecorded_days():
    # Fitbit pads activity minutes to the end of the month: days with no steps,
    # no calories and a full 1440 sedentary minutes were never recorded.
    day = dt.date(2026, 7, 13)
    accumulators = {
        (day, "sedentary_minutes"): _acc(1440.0),
        (day, "very_active_minutes"): _acc(0.0),
        (day, "lightly_active_minutes"): _acc(0.0),
    }

    dropped = _drop_unrecorded_activity_days(accumulators)

    assert dropped == 3
    assert accumulators == {}


def test_keeps_a_genuinely_sedentary_day_that_has_recorded_evidence():
    day = dt.date(2026, 7, 13)
    accumulators = {
        (day, "steps"): _acc(412.0),
        (day, "sedentary_minutes"): _acc(1440.0),
        (day, "very_active_minutes"): _acc(0.0),
    }

    assert _drop_unrecorded_activity_days(accumulators) == 0
    assert (day, "sedentary_minutes") in accumulators
