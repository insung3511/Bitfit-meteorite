# BitFit Meteorite — Backend

FastAPI + SQLModel backend for the personal health assistant (Fitbit/Google
Health data + Claude): Google Health OAuth + sync, a Google Takeout backfill
importer, a separate high-resolution raw-signal index, rolling summary/anomaly
computation, a versioned workspace API, and a Claude tool-use layer for chat Q&A
and sleep coaching over your own data.

## Requirements

- Python 3.10+

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .          # installs deps from pyproject.toml
cp .env.example .env      # then fill in the values
```

### Generate the token encryption key

The stored OAuth refresh token is encrypted at rest with a Fernet key. Generate
one **once** and paste it into `.env` as `TOKEN_ENCRYPTION_KEY`:

```bash
python scripts/generate_key.py
# copy the printed value into TOKEN_ENCRYPTION_KEY in .env
```

Keep this key secret and stable — rotating it invalidates the stored token and
you would have to re-connect the Google account.

### App login

This is a personal single-user app with no accounts system, so it's gated by
one shared password rather than a login system. Set two values in `.env`:

- `APP_PASSWORD` — the password you'll use to log in.
- `SESSION_SECRET` — signs the login cookie. Generate one the same way as the
  encryption key (`python scripts/generate_key.py` — any random string works
  here, this is just a convenient source):

Every route except `GET /health` and `POST /session/login` requires a valid
session cookie (`app/session.py`, wired in `main.py` via
`dependencies=[Depends(require_session)]` on each router). The frontend's
`/login` page calls `POST /session/login`; the cookie is `HttpOnly` and lasts
30 days. `POST /session/logout` clears it.

## Connect Google Health (OAuth2)

The OAuth2 Authorization Code flow runs entirely on the backend — the client
secret never reaches the browser. Set `GOOGLE_HEALTH_CLIENT_ID`,
`GOOGLE_HEALTH_CLIENT_SECRET`, and `GOOGLE_HEALTH_REDIRECT_URI` in `.env` (the
redirect URI must also be registered on your Google Cloud OAuth client), then:

1. Open http://localhost:8000/auth/google/login in a browser. You are redirected
   to Google's consent screen (`access_type=offline` + `prompt=consent` so a
   refresh token is issued).
2. After consenting, Google redirects back to `/auth/google/callback`, which
   exchanges the code for tokens and stores the encrypted refresh token.

The sync job obtains a fresh access token via `app.auth.get_valid_access_token()`,
which auto-refreshes (and re-stores a rotated refresh token) when the cached one
expires.

## Run

```bash
uvicorn app.main:app --reload
```

The API starts on http://localhost:8000. Verify it is up:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

CORS is enabled for the local Next.js dev server (http://localhost:3000).

## Backfill historical data from Google Takeout

Before live sync is connected (or to import years of history at once), you can
bulk-load a Fitbit export obtained through
[Google Takeout](https://takeout.google.com/). Request the **Fitbit** product,
download and unzip the archive — you get a `Takeout/Fitbit/` tree of per-day JSON
files (`steps-YYYY-MM-DD.json`, `sleep-YYYY-MM-DD.json`,
`resting_heart_rate-YYYY-MM-DD.json`, `weight-*.json`, etc.).

Run the importer against that folder:

```bash
python -m app.takeout_import /path/to/Takeout/Fitbit
```

It walks the tree recursively, folds each metric down to one value per day, and
inserts provenance-tagged rows into `daily_metric` with `source="takeout"`. It
prints a summary of files processed/skipped and rows inserted per metric.

Notes:

- **Idempotent** — re-running over the same export never duplicates rows. Each
  imported daily record has a stable provider identity.
- **Canonical data** — when Google Health has Fitbit-origin data for a day it is
  used for dashboard and chat analysis; other Google Health data is the next
  fallback, followed by Takeout. Sources are never averaged together.
- **Metrics imported**: `steps`, `resting_heart_rate`,
  `sleep_{light,deep,rem,awake}_minutes`, `spo2`, `hrv`, `weight`,
  `active_zone_minutes`. Intraday heart-rate files are recognised but not
  written to `daily_metric` (there is no daily metric for them); the separate
  raw index handles high-resolution Fit JSON, interval CSV, session JSON, and
  TCX points with provenance. Unrecognised files (e.g. `Profile.json`) are
  skipped and listed in the summary.
- **Weight unit**: Takeout weight logs do not record the unit, so values are
  stored as `kg`. If your Fitbit account is set to pounds, convert first or
  adjust `_UNIT_KG` in `app/takeout_import.py`.
- **Target a different database** with the `DATABASE_URL` env var, e.g.
  `DATABASE_URL=sqlite:///./scratch.db python -m app.takeout_import ...` to try
  it without touching `health.db`.

A small synthetic export lives in `tests/fixtures/takeout_sample/` for testing
the parser without a real Takeout archive.

## Sync, summaries, and chat

- The scheduler (APScheduler, `app/sync.py`) pulls from the Google Health API
  every `SYNC_INTERVAL_HOURS` (default 4) and recomputes rolling summaries.
  Trigger a sync manually with `POST /sync/run` — it always returns 200,
  including `{"status": "error", ...}` if no account is connected yet.
- `app/summarize.py` recomputes `daily_summary` (7d/30d mean, 30d stddev, delta
  vs. baseline) from `daily_metric`; both the sync job and the Takeout importer
  call it automatically.
- `app/llm_client.py` is the Claude tool-use layer: `POST /chat` answers
  questions over your real data (via bounded daily, correlation, provenance,
  and raw-signal tools, not a raw data dump in the prompt); `POST
  /dashboard/sleep-coaching` runs a focused sleep summary. Both need
  `ANTHROPIC_API_KEY` set and degrade gracefully (a clean error, not a crash) if
  it's missing or invalid.
- `GET /dashboard/summary`, `/dashboard/metrics`, `/dashboard/anomalies` back
  the frontend's charts and anomaly list.
- `GET /workspace`, `POST /workspace/versions`, and `POST
  /workspace/restore/{version_id}` persist approved, reversible workspace
  revisions.

## Layout

- `app/main.py` — FastAPI app, CORS, table creation, scheduler lifecycle, router wiring + auth gate.
- `app/db.py` — SQLite engine setup; `DATABASE_URL` env var (default `./health.db`).
- `app/migrations.py` — forward-only local SQLite migration that preserves legacy
  raw records and rebuilds derived summaries.
- `app/models.py` — SQLModel schema: OAuth/session records, daily metrics,
  summaries, and `WorkspaceVersion`.
- `app/session.py` + `app/routes/session.py` — app-level password login (`/session/login|logout|me`), session cookie.
- `app/auth.py` + `app/routes/auth.py` — Google Health OAuth2 flow, Fernet token encryption, `get_valid_access_token()`.
- `app/google_health_client.py` — Google Health API HTTP client (data-point fetch, pagination, retry/backoff).
- `app/sync.py` + `app/routes/sync.py` — scheduled + manual (`POST /sync/run`) sync from Google Health into `daily_metric`.
- `app/summarize.py` — rolling summary computation (`daily_summary`).
- `app/takeout_import.py` — one-off Google Takeout (Fitbit) backfill importer (`python -m app.takeout_import <path>`).
- `app/raw_signal_import.py` — resumable local index for raw/derived Fit JSON,
  interval CSV, sessions, and TCX track points.
- `app/llm_client.py` + `app/routes/chat.py` — Claude tool-use chat Q&A over your data.
- `app/routes/dashboard.py` — chart/anomaly/sleep-coaching read routes.
- `app/routes/workspace.py` — authenticated version/restore endpoints for the
  analytical workspace.
- `scripts/generate_key.py` — one-off random-key generator for `TOKEN_ENCRYPTION_KEY` / `SESSION_SECRET`.
- `.env.example` — documented environment variables.
- `tests/` — pytest suite covering summarize, sync, Takeout/raw imports, chat,
  workspace versions, and AI evidence/action contracts.
