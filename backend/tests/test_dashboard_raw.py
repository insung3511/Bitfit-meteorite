"""Focused tests for the dashboard raw-signal endpoint."""

from __future__ import annotations


def _make_app():
    from fastapi import FastAPI

    from app.routes import dashboard as dashboard_routes

    app = FastAPI()
    app.include_router(dashboard_routes.router)
    return app


def test_dashboard_raw_returns_bounded_serialized_records(monkeypatch):
    from app.routes import dashboard as dashboard_routes

    calls = []

    def fake_query_raw_signals(metric_name=None, start=None, end=None, *, limit, engine=None):
        calls.append(
            {
                "metric_name": metric_name,
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "limit": limit,
                "engine": engine,
            }
        )
        return [
            {
                "id": 1,
                "record_fingerprint": "raw-1",
                "timestamp": "2024-03-15T00:01:00+00:00",
                "end_timestamp": "2024-03-15T00:02:00+00:00",
                "metric_name": "heart_rate",
                "signal_type": "sample",
                "value_float": 71.0,
                "value_text": None,
                "value_json": None,
                "unit": "bpm",
                "source": "google_fit_takeout",
                "source_kind": "raw_json",
                "source_file": "raw-heart.json",
            },
            {
                "id": 2,
                "record_fingerprint": "raw-2",
                "timestamp": "2024-03-15T00:02:00+00:00",
                "end_timestamp": "2024-03-15T00:03:00+00:00",
                "metric_name": "heart_rate",
                "signal_type": "sample",
                "value_float": 73.0,
                "unit": "bpm",
                "source": "google_fit_takeout",
                "source_kind": "raw_json",
                "source_file": "raw-heart.json",
            },
            {
                "id": 3,
                "record_fingerprint": "raw-3",
                "timestamp": "2024-03-15T00:03:00+00:00",
                "metric_name": "heart_rate",
                "signal_type": "sample",
                "value_float": 74.0,
                "unit": "bpm",
                "source": "google_fit_takeout",
                "source_kind": "raw_json",
                "source_file": "raw-heart.json",
            },
        ]

    monkeypatch.setattr(dashboard_routes, "query_raw_signals", fake_query_raw_signals)

    try:
        from fastapi.testclient import TestClient

        client = TestClient(_make_app())
        res = client.get(
            "/dashboard/raw?metric=heart_rate&start=2024-03-15&end=2024-03-15&limit=2"
        )
        assert res.status_code == 200
        body = res.json()
    except TypeError:
        body = dashboard_routes.raw(
            metric="heart_rate", start="2024-03-15", end="2024-03-15", limit=2
        )

    assert calls == [
        {
            "metric_name": "heart_rate",
            "start": "2024-03-15T00:00:00+00:00",
            "end": "2024-03-16T00:00:00+00:00",
            "limit": 3,
            "engine": dashboard_routes.engine,
        }
    ]
    assert body["metric"] == "heart_rate"
    assert body["limit"] == 2
    assert body["count"] == 2
    assert body["truncated"] is True
    assert body["records"] == [
        {
            "record_id": "raw-1",
            "timestamp": "2024-03-15T00:01:00+00:00",
            "end_timestamp": "2024-03-15T00:02:00+00:00",
            "metric": "heart_rate",
            "signal_type": "sample",
            "value": 71.0,
            "unit": "bpm",
            "source": "google_fit_takeout",
            "source_kind": "raw_json",
            "source_file": "raw-heart.json",
        },
        {
            "record_id": "raw-2",
            "timestamp": "2024-03-15T00:02:00+00:00",
            "end_timestamp": "2024-03-15T00:03:00+00:00",
            "metric": "heart_rate",
            "signal_type": "sample",
            "value": 73.0,
            "unit": "bpm",
            "source": "google_fit_takeout",
            "source_kind": "raw_json",
            "source_file": "raw-heart.json",
        },
    ]
    assert body["source_metadata"] == {
        "sources": ["google_fit_takeout"],
        "source_kinds": ["raw_json"],
        "source_files": ["raw-heart.json"],
    }


def test_dashboard_raw_caps_requested_limit(monkeypatch):
    from app.routes import dashboard as dashboard_routes

    seen = {}

    def fake_query_raw_signals(metric_name=None, start=None, end=None, *, limit, engine=None):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(dashboard_routes, "query_raw_signals", fake_query_raw_signals)

    body = dashboard_routes.raw(start=None, end=None, limit=999_999)

    assert seen["limit"] == dashboard_routes._MAX_RAW_LIMIT + 1
    assert body["limit"] == dashboard_routes._MAX_RAW_LIMIT
    assert body["count"] == 0
    assert body["truncated"] is False
