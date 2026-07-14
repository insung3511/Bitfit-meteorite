from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import importlib
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException


def test_missing_session_secret_rejects_forge(monkeypatch):
    import app.session as session

    monkeypatch.setattr(session, "SESSION_SECRET", "")
    expiry = int(time.time()) + 3600
    signature = hmac.new(b"", str(expiry).encode(), hashlib.sha256).hexdigest()

    assert session.is_valid_token(f"{expiry}.{signature}") is False


def test_login_rate_limit_persists_and_success_clears(tmp_path, monkeypatch):
    db_path = tmp_path / "login-throttle.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import app.db as db

    importlib.reload(db)
    import app.routes.session as route

    now = dt.datetime(2024, 1, 1, 12, 0)
    for _ in range(route._LOGIN_MAX_FAILURES):
        route._record_login_result("127.0.0.1", succeeded=False, now=now)

    # Reloading the route does not erase the database-backed throttle.
    route = importlib.reload(route)
    with pytest.raises(HTTPException) as exc_info:
        route._check_login_rate_limit("127.0.0.1", now=now)
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "60"

    route._record_login_result("127.0.0.1", succeeded=True, now=now)
    route._check_login_rate_limit("127.0.0.1", now=now)


def test_expired_login_window_resets_existing_row(tmp_path, monkeypatch):
    db_path = tmp_path / "expired-login-throttle.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import app.db as db

    db = importlib.reload(db)
    import app.routes.session as route
    from app.models import LoginThrottle
    from sqlmodel import Session

    started = dt.datetime(2024, 1, 1, 12, 0)
    for _ in range(route._LOGIN_MAX_FAILURES):
        route._record_login_result("expired-client", succeeded=False, now=started)

    after_expiry = started + route._LOGIN_WINDOW
    route._record_login_result("expired-client", succeeded=False, now=after_expiry)

    with Session(db.engine) as session:
        throttle = session.get(LoginThrottle, route._client_key("expired-client"))
        assert throttle is not None
        assert throttle.failed_count == 1
        assert throttle.window_started_at == after_expiry
        assert throttle.blocked_until is None


def test_concurrent_login_failures_are_not_lost(tmp_path, monkeypatch):
    db_path = tmp_path / "concurrent-login-throttle.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import app.db as db

    db = importlib.reload(db)
    db.init_db()
    import app.routes.session as route
    from app.models import LoginThrottle
    from sqlmodel import Session

    now = dt.datetime(2024, 1, 1, 12, 0)
    failure_count = route._LOGIN_MAX_FAILURES + 3
    with ThreadPoolExecutor(max_workers=failure_count) as pool:
        list(
            pool.map(
                lambda _: route._record_login_result(
                    "concurrent-client", succeeded=False, now=now
                ),
                range(failure_count),
            )
        )

    with Session(db.engine) as session:
        throttle = session.get(LoginThrottle, route._client_key("concurrent-client"))
        assert throttle is not None
        assert throttle.failed_count == failure_count
        assert throttle.blocked_until == now + dt.timedelta(minutes=8)
