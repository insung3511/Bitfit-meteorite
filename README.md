# BitFit Meteorite

BitFit Meteorite is a local, single-user health assistant for Fitbit and Google
Health data. It imports or synchronizes wearable metrics, builds canonical daily
summaries, displays trends and anomalies, and optionally uses Claude to answer
questions about your own health history.

The application is intended to run on one trusted computer. It is not currently
designed for public hosting or multiple users.

## What This Repository Implements

- Google OAuth 2.0 connection to the Google Health API
- Scheduled and manual health-data synchronization
- Historical Fitbit import from Google Takeout
- Source-aware reconciliation that prefers Fitbit-origin Google Health records
- Rolling 7-day and 30-day health summaries and anomaly detection
- A dashboard for health trends, anomalies, and sleep coaching
- Claude tool-use chat grounded in SQL queries over your stored data
- Password-protected, local-only access with encrypted OAuth token storage
- Forward-only SQLite migrations that preserve existing local data

## Architecture

```text
Google Health API ─┐
                   ├─> FastAPI backend ─> SQLite ─> summaries/anomalies
Google Takeout ────┘          │                         │
                              ├─> Claude tool calls     │
                              └─> REST API <─ Next.js frontend
```

The backend preserves provider provenance. For overlapping metric-days, it uses
Fitbit-origin Google Health data first, other Google Health data second, and
Takeout data as the historical fallback. Sources are not averaged together.

## Repository Layout

```text
backend/                 FastAPI, SQLModel, sync, imports, summaries, and chat
  app/                   Application code and API routes
  tests/                 Backend regression tests and synthetic fixtures
  USER_GUIDE.md          Detailed setup and operating guide
frontend/                Next.js, React, TypeScript, Tailwind, and Recharts UI
```

## Prerequisites

- Python 3.10 or newer
- Node.js 18.18 or newer; Node.js 20+ is recommended
- npm
- Optional: Google Health OAuth credentials for live synchronization
- Optional: an Anthropic API key for Chat and Sleep Coaching

## Quick Start

### 1. Configure and run the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python scripts/generate_key.py
```

Edit `backend/.env` and configure at least:

```env
APP_PASSWORD=choose-a-local-password
SESSION_SECRET=replace-with-a-long-random-secret
TOKEN_ENCRYPTION_KEY=replace-with-the-generated-fernet-key
```

For live synchronization, also configure:

```env
GOOGLE_HEALTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_HEALTH_CLIENT_SECRET=your-client-secret
GOOGLE_HEALTH_REDIRECT_URI=http://localhost:8000/auth/google/callback
```

For AI chat and sleep coaching, add:

```env
ANTHROPIC_API_KEY=your-anthropic-api-key
```

Start the API:

```bash
uvicorn app.main:app --reload
```

The backend is available at http://localhost:8000. Its first startup creates or
migrates `backend/health.db`.

### 2. Configure and run the frontend

Open another terminal:

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open http://localhost:3000 and sign in with the `APP_PASSWORD` configured in the
backend.

## Add Health Data

### Google Health

After signing in, open http://localhost:8000/auth/google/login and complete the
Google consent flow. The first scheduled sync runs about five minutes after the
backend starts; later syncs run every four hours by default.

The redirect URI must exactly match the URI registered for your Google OAuth
client.

### Fitbit Google Takeout

You can use a Fitbit export instead of, or alongside, live synchronization:

```bash
cd backend
source .venv/bin/activate
python -m app.takeout_import /path/to/Takeout/Fitbit
```

The importer is idempotent, so importing the same export again does not create
duplicate daily records.

## Use the Application

- `/` shows backend connectivity.
- `/dashboard` shows available health trends, anomalies, and sleep coaching.
- `/chat` answers questions using your stored health data.
- The navigation logout button clears the local session.

AI-generated responses provide general wellness information, not medical advice.

## Verification

Run backend tests:

```bash
cd backend
source .venv/bin/activate
pytest -q
```

Run frontend checks:

```bash
cd frontend
npm run lint
npx tsc --noEmit
npm run build
```

The production frontend build downloads Geist fonts through `next/font`, so it
requires network access to Google Fonts during the build.

## Documentation

- [User guide](backend/USER_GUIDE.md)
- [Backend reference](backend/README.md)
- [Frontend reference](frontend/README.md)

Keep `.env`, `health.db`, OAuth credentials, encryption keys, and API keys out of
version control.
