# BitFit Meteorite User Guide

BitFit Meteorite is a local, single-user health-data assistant. It combines your
Fitbit-origin data from Google Health or a Fitbit Google Takeout export with a
dashboard and optional Claude-powered wellness chat.

## Before You Start

- Use this application only on your own trusted computer. It is intentionally
  configured for localhost, not LAN or public deployment.
- You need Python 3.10+, Node.js 18.18+ (Node 20+ recommended), and a Google
  Health OAuth client if you want live sync.
- The chat and sleep-coaching features require an Anthropic API key.

## Set Up the Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python scripts/generate_key.py
```

Edit `.env` and set these values:

- `APP_PASSWORD`: the password used to open the app.
- `SESSION_SECRET`: a random secret for the local login cookie.
- `TOKEN_ENCRYPTION_KEY`: the Fernet key printed by `generate_key.py`.
- `GOOGLE_HEALTH_CLIENT_ID`, `GOOGLE_HEALTH_CLIENT_SECRET`, and
  `GOOGLE_HEALTH_REDIRECT_URI`: required for live Google Health sync. The
  default redirect URI is `http://localhost:8000/auth/google/callback` and must
  be registered in Google Cloud.
- `ANTHROPIC_API_KEY`: optional, required only for Chat and Sleep Coaching.

Start the backend:

```bash
uvicorn app.main:app --reload
```

The first startup creates or migrates `health.db`. Existing local health data
is retained and derived dashboard summaries are rebuilt automatically.

## Set Up the Frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 and sign in with `APP_PASSWORD`. The home page shows
whether the backend is reachable.

## Add Health Data

### Live Google Health Sync

1. While signed in, open http://localhost:8000/auth/google/login.
2. Complete the Google consent screen and return to the callback page.
3. Wait for the first automatic sync, which starts about five minutes after the
   backend launches. Later syncs run every four hours by default. Use the
   Dashboard after the sync completes.

Google Health records sourced from Fitbit are preferred for analysis. Other
Google Health records are used only when Fitbit-origin records are unavailable.

### Fitbit Google Takeout Import

Use this when you want historical Fitbit data or do not yet have a live Google
Health connection:

```bash
cd backend
source .venv/bin/activate
python -m app.takeout_import /path/to/Takeout/Fitbit
```

For a Korean legacy Google Fit export, pass the localized folder instead:

```bash
python -m app.takeout_import "$HOME/Downloads/Takeout/피트니스"
```

The importer accepts the Fitbit folder from a Google Takeout archive. It is safe
to run again; already-imported daily records and raw signal points are not
duplicated. Daily Takeout rows fill only days without Google Health data, so the
canonical dashboard values are not averaged with live values. Interval CSV,
raw/derived JSON, session JSON, and TCX files are indexed separately for
high-resolution drill-down while the original files remain on disk.

## Use the App

- **Dashboard**: configure trend panels, date windows, chart types, baselines,
  evidence context, anomalies, and optional sleep coaching. Approved layout
  proposals create a new local workspace version and can be undone.
- **Chat**: ask questions about your imported or synced data. Responses expose
  bounded evidence references and may propose visual changes, but never apply
  them without approval. Responses are wellness guidance, not medical advice.
- **Log out**: use the navigation control when you are done on a shared device.

## Troubleshooting

- **Backend unreachable**: confirm `uvicorn app.main:app --reload` is running
  on port 8000 and that `NEXT_PUBLIC_API_BASE_URL` matches it.
- **Google callback rejected**: sign in again, start a fresh Google connection,
  and complete it within ten minutes. OAuth state is one-time use.
- **Sync reports busy**: another scheduled or manual sync is running; wait and
  try again.
- **Chat unavailable**: set a valid `ANTHROPIC_API_KEY` in `backend/.env` and
  restart the backend.
