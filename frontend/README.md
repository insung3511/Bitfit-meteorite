# Health Assistant — Frontend

Next.js (App Router) + TypeScript + Tailwind CSS frontend for the personal health
assistant. Talks to the FastAPI backend over REST.

## Prerequisites

- Node.js 18.18+ (Node 20+ recommended)
- The backend running at `http://localhost:8000` (see `../backend`)

## Setup

```bash
npm install
```

Optionally configure the backend URL. Defaults to `http://localhost:8000` if unset:

```bash
cp .env.local.example .env.local
# then edit NEXT_PUBLIC_API_BASE_URL if your backend runs elsewhere
```

## Run

```bash
npm run dev
```

Open http://localhost:3000. The home page shows a backend connectivity indicator
("Backend: connected" / "Backend: unreachable") by calling the backend's
`GET /health` endpoint.

## Build

```bash
npm run build
```

## Routes

- `/` — home + backend connectivity status
- `/chat` — Q&A over your health data (placeholder)
- `/dashboard` — trends, sleep coaching, anomaly flags (placeholder)
