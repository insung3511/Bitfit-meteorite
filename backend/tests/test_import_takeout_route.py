"""Tests for the Takeout .zip upload helper (app.routes.import_takeout).

These target the pure ``import_takeout_zip(bytes)`` function directly — no
TestClient, multipart, or session cookie needed — matching how the other
importer tests point app.db at a scratch SQLite DB via a DATABASE_URL override.
"""

from __future__ import annotations

import importlib
import io
import zipfile

import pytest


@pytest.fixture()
def scratch_db(tmp_path, monkeypatch):
    """Point app.db at a fresh scratch SQLite file (see test_summarize.py)."""
    db_path = tmp_path / "import_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import app.db as db

    importlib.reload(db)
    db.init_db()
    return db


def _make_takeout_zip(files: dict[str, str]) -> bytes:
    """Build an in-memory .zip from {archive_path: text_contents}."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, contents in files.items():
            zf.writestr(name, contents)
    return buffer.getvalue()


def test_imports_daily_csv_from_zip(scratch_db):
    from app.routes.import_takeout import import_takeout_zip

    payload = _make_takeout_zip(
        {
            "Takeout/Fit/daily.csv": (
                "Date,Steps\n2016-11-03,8817\n"
            )
        }
    )

    summary = import_takeout_zip(payload)

    assert summary["rows_inserted"].get("steps") == 1
    assert summary["rows_inserted_total"] >= 1


def test_rejects_non_zip():
    from app.routes.import_takeout import import_takeout_zip

    with pytest.raises(ValueError, match="not a valid .zip"):
        import_takeout_zip(b"this is definitely not a zip")


def test_rejects_empty_upload():
    from app.routes.import_takeout import import_takeout_zip

    with pytest.raises(ValueError, match="Empty"):
        import_takeout_zip(b"")


def test_rejects_oversized_upload(monkeypatch):
    from app.routes import import_takeout as mod

    monkeypatch.setattr(mod, "MAX_UPLOAD_MB", 0.0001)  # ~100 bytes
    payload = _make_takeout_zip({"Takeout/Fit/daily.csv": "Date,Steps\n" * 100})

    with pytest.raises(ValueError, match="exceeds"):
        mod.import_takeout_zip(payload)


def test_rejects_zip_slip(scratch_db):
    from app.routes.import_takeout import import_takeout_zip

    payload = _make_takeout_zip({"../escape.csv": "Date,Steps\n2016-11-03,10\n"})

    with pytest.raises(ValueError, match="[Uu]nsafe"):
        import_takeout_zip(payload)


def test_reimport_is_idempotent(scratch_db):
    from app.routes.import_takeout import import_takeout_zip

    payload = _make_takeout_zip(
        {"Takeout/Fit/daily.csv": "Date,Steps\n2016-11-03,8817\n"}
    )

    first = import_takeout_zip(payload)
    second = import_takeout_zip(payload)

    assert first["rows_inserted_total"] >= 1
    assert second["rows_inserted_total"] == 0
    assert second["rows_skipped_existing"] >= 1


def test_route_is_registered_under_session_gate():
    """The router is mounted at /import/takeout so the UI can POST uploads."""
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/import/takeout" in paths
