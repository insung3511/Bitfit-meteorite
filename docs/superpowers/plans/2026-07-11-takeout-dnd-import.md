# Drag-and-drop Google Takeout Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user drag-and-drop their Google Takeout `.zip` onto a new `/import` page and have their historical health data imported, with a summary of what was imported.

**Architecture:** A new `/import` page uses native HTML5 drag-and-drop to POST a `.zip` (multipart) to a new session-gated `POST /import/takeout` endpoint. The endpoint safely extracts the zip to a temp dir (zip-slip guarded, size-capped) and calls the existing, idempotent `import_takeout(directory)`. The core extract-and-import logic is a pure function (`import_takeout_zip(bytes) -> dict`) so it is fully unit-testable without HTTP, multipart, or session plumbing.

**Tech Stack:** Backend — FastAPI, SQLModel, pytest, `python-multipart` (new). Frontend — Next.js 16 (App Router, client component), React 19, Tailwind 4. No new frontend dependencies.

## Global Constraints

- Backend routes are mounted under `Depends(require_session)` in `backend/app/main.py` — the new router MUST be added to the protected list, not exposed unauthenticated.
- Do NOT modify `backend/app/takeout_import.py`, the data model, or the summarize/raw-signal pipeline. Reuse `import_takeout(path)` as-is.
- Upload size cap is configurable via env `MAX_UPLOAD_MB`, default `200`.
- Frontend copy for the zone: "Drop your Google Takeout `.zip` here or click to browse".
- Frontend fetches use `credentials: "include"` and base URL `process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"` (match `frontend/app/dashboard/page.tsx`).
- **Next.js is a pinned breaking-change version** (`frontend/AGENTS.md`): read the relevant guide under `node_modules/next/dist/docs/` before writing the page.
- Backend commands run from the `backend/` directory; frontend commands from `frontend/`.

---

### Task 1: Core zip extract-and-import helper

The pure logic: validate a `.zip` byte payload, safely extract it, and run the existing importer. No FastAPI, no multipart, no session — so it is tested directly with crafted zip bytes.

**Files:**
- Create: `backend/app/routes/import_takeout.py`
- Test: `backend/tests/test_import_takeout_route.py`

**Interfaces:**
- Consumes: `app.takeout_import.import_takeout(path: str) -> dict` (existing).
- Produces:
  - `import_takeout_zip(data: bytes) -> dict` — extracts a Takeout `.zip` and returns the importer summary dict. Raises `ValueError` for empty / oversized / non-zip / zip-slip payloads.
  - `MAX_UPLOAD_MB: float` — module-level env-driven cap.
  - `_safe_extract(zf: zipfile.ZipFile, dest: str) -> None` — internal, raises `ValueError` on unsafe member paths.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_import_takeout_route.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_import_takeout_route.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routes.import_takeout'` (or ImportError on `import_takeout_zip`).

- [ ] **Step 3: Write the helper module**

Create `backend/app/routes/import_takeout.py`:

```python
"""Upload endpoint for importing a Google Takeout ``.zip`` into DailyMetric.

The heavy lifting lives in :func:`app.takeout_import.import_takeout`, which
walks a *directory*. This module accepts an uploaded ``.zip``, safely extracts
it to a temporary directory, and hands that directory to the existing importer.

Security: extraction is guarded against zip-slip (members whose paths escape the
extraction root) and against oversized uploads (``MAX_UPLOAD_MB``). The core
logic is the pure function :func:`import_takeout_zip`, which the route wraps.
"""

from __future__ import annotations

import io
import os
import tempfile
import zipfile

from fastapi import APIRouter, HTTPException, UploadFile

router = APIRouter(prefix="/import", tags=["import"])

# Max accepted upload size; a config change, not a code change. Default 200 MB.
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "200"))


def _safe_extract(zf: zipfile.ZipFile, dest: str) -> None:
    """Extract every member of ``zf`` into ``dest``, rejecting zip-slip paths.

    A member whose resolved path is not inside ``dest`` (via ``..`` segments or
    an absolute path) raises :class:`ValueError` before anything is written.
    """
    dest_root = os.path.realpath(dest)
    for member in zf.namelist():
        target = os.path.realpath(os.path.join(dest, member))
        if target != dest_root and not target.startswith(dest_root + os.sep):
            raise ValueError(f"Unsafe path in zip: {member}")
    zf.extractall(dest)


def import_takeout_zip(data: bytes) -> dict:
    """Extract a Takeout ``.zip`` payload and run the daily-metric importer.

    Args:
        data: Raw bytes of an uploaded ``.zip`` file.

    Returns:
        The summary dict from :func:`app.takeout_import.import_takeout`.

    Raises:
        ValueError: the payload is empty, larger than ``MAX_UPLOAD_MB``, not a
            valid zip, or contains an unsafe (path-traversal) member.
    """
    if not data:
        raise ValueError("Empty upload.")
    max_bytes = int(MAX_UPLOAD_MB * 1024 * 1024)
    if len(data) > max_bytes:
        raise ValueError(f"Upload exceeds {MAX_UPLOAD_MB:.0f} MB limit.")

    buffer = io.BytesIO(data)
    if not zipfile.is_zipfile(buffer):
        raise ValueError("Upload is not a valid .zip file.")
    buffer.seek(0)

    # Imported lazily so a DATABASE_URL override set before the call is honoured
    # by app.db's module-level engine (same contract as import_takeout).
    from app.takeout_import import import_takeout

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(buffer) as zf:
            _safe_extract(zf, tmp)
        return import_takeout(tmp)


@router.post("/takeout")
async def upload_takeout(file: UploadFile) -> dict:
    """Import a Google Takeout ``.zip`` uploaded via the web UI.

    Returns the importer's summary dict on success; a bad upload (not a zip,
    too large, unsafe) returns a 400 with an explanatory message.
    """
    data = await file.read()
    try:
        return import_takeout_zip(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_import_takeout_route.py -v`
Expected: PASS (6 passed). If `test_imports_daily_csv_from_zip` fails on row count, confirm the CSV header uses a recognised date/steps alias — `Date`/`Steps` are in `_CSV_ALIASES` in `takeout_import.py`.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/routes/import_takeout.py tests/test_import_takeout_route.py
git commit -m "feat(import): add safe Takeout .zip extract-and-import helper

Constraint: reuse existing import_takeout(dir); no importer changes
Constraint: guard zip-slip and cap upload size (MAX_UPLOAD_MB, default 200)
Confidence: high
Scope-risk: narrow"
```

---

### Task 2: Wire the upload route into the app

Mount the new router under the session gate and add the `python-multipart` dependency FastAPI needs for `UploadFile`.

**Files:**
- Modify: `backend/pyproject.toml` (add `python-multipart` to `dependencies`)
- Modify: `backend/app/main.py` (import + include the router under `require_session`)
- Test: `backend/tests/test_import_takeout_route.py` (add a route-wiring test)

**Interfaces:**
- Consumes: `app.routes.import_takeout.router` (Task 1), `app.session.require_session` (existing).
- Produces: mounted `POST /import/takeout`, session-protected.

- [ ] **Step 1: Add the failing route-wiring test**

Append to `backend/tests/test_import_takeout_route.py`:

```python
def test_route_is_registered_under_session_gate():
    """The router is mounted at /import/takeout and behind require_session."""
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/import/takeout" in paths
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_import_takeout_route.py::test_route_is_registered_under_session_gate -v`
Expected: FAIL — `/import/takeout` not in the app's routes (router not yet mounted). It may also fail at import with `RuntimeError: Form data requires "python-multipart"` — Step 3 fixes both.

- [ ] **Step 3a: Add the python-multipart dependency**

In `backend/pyproject.toml`, add `"python-multipart"` to the `dependencies` list (alphabetical-ish, next to the other core libs):

```toml
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "sqlmodel",
    "python-dotenv",
    "python-multipart",
    "cryptography",
    "apscheduler",
    "anthropic",
    "httpx",
    "authlib",
]
```

Then install it into the active environment:

Run: `cd backend && python -m pip install python-multipart`
Expected: "Successfully installed python-multipart-…".

- [ ] **Step 3b: Mount the router in main.py**

In `backend/app/main.py`, add the import alongside the other route imports (after `from app.routes import dashboard as dashboard_routes`):

```python
from app.routes import import_takeout as import_takeout_routes
```

And include it in the protected block, next to the other `app.include_router(..., dependencies=_protected)` calls (e.g. right after the `sync_routes` line):

```python
app.include_router(import_takeout_routes.router, dependencies=_protected)
```

- [ ] **Step 4: Run the full test file to verify it passes**

Run: `cd backend && python -m pytest tests/test_import_takeout_route.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Run the whole backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests pass (no import-time failures from the new router or dependency).

- [ ] **Step 6: Commit**

```bash
cd backend
git add pyproject.toml app/main.py tests/test_import_takeout_route.py
git commit -m "feat(import): mount POST /import/takeout under session gate

Adds python-multipart (required by FastAPI UploadFile).

Constraint: endpoint must sit behind require_session like every other route
Confidence: high
Scope-risk: narrow"
```

---

### Task 3: `/import` page with drag-and-drop zone + nav link

The user-facing page: a native drag-and-drop `.zip` zone that uploads to `/import/takeout` and renders the summary, plus an "Import" link in the header.

**Files:**
- Create: `frontend/app/import/page.tsx`
- Modify: `frontend/app/layout.tsx` (add the "Import" nav link)

**Interfaces:**
- Consumes: `POST /import/takeout` (Task 2) — multipart field name `file`; response is the importer summary dict `{ rows_inserted: Record<string, number>, rows_inserted_total, rows_skipped_existing, files_processed, files_skipped, files_errored, errors }`, or `{ detail: string }` with a non-2xx status on rejection.
- Produces: a `/import` route reachable from the header nav.

- [ ] **Step 0: Read the Next.js guide first**

Per `frontend/AGENTS.md`, this is a pinned breaking-change Next.js. Before writing the page, skim the App Router client-component guide:

Run: `ls frontend/node_modules/next/dist/docs/` and read the routing/client-component page relevant to a `"use client"` route. Confirm `"use client"` + `export default function Page()` in `app/<route>/page.tsx` is still the correct shape; adjust the code below only if the guide says otherwise.

- [ ] **Step 1: Add the "Import" nav link**

In `frontend/app/layout.tsx`, inside the `<div className="flex gap-4 text-sm">` block, add an Import link after the Dashboard link:

```tsx
<Link href="/import" className="hover:underline">
  Import
</Link>
```

- [ ] **Step 2: Create the import page**

Create `frontend/app/import/page.tsx`:

```tsx
"use client";

import { useRef, useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type ImportSummary = {
  rows_inserted: Record<string, number>;
  rows_inserted_total: number;
  rows_skipped_existing: number;
  files_processed: number;
  files_skipped: number;
  files_errored: number;
  errors: { file: string; error: string }[];
};

type State =
  | { status: "idle" }
  | { status: "uploading" }
  | { status: "done"; summary: ImportSummary }
  | { status: "error"; message: string };

export default function ImportPage() {
  const [state, setState] = useState<State>({ status: "idle" });
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setState({
        status: "error",
        message: "Please drop a Google Takeout .zip file.",
      });
      return;
    }
    setState({ status: "uploading" });
    const body = new FormData();
    body.append("file", file);
    try {
      const res = await fetch(`${API_BASE_URL}/import/takeout`, {
        method: "POST",
        credentials: "include",
        body,
      });
      if (!res.ok) {
        const detail = await res
          .json()
          .then((b) => (b as { detail?: string }).detail)
          .catch(() => null);
        setState({
          status: "error",
          message: detail ?? `Import failed (${res.status}).`,
        });
        return;
      }
      const summary = (await res.json()) as ImportSummary;
      setState({ status: "done", summary });
    } catch {
      setState({
        status: "error",
        message: `Could not reach the backend at ${API_BASE_URL}.`,
      });
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void upload(file);
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold">Import health data</h1>
        <p className="mt-1 max-w-2xl text-sm text-black/60 dark:text-white/60">
          Drop your Google Takeout export to load your historical Fitbit /
          Google Fit data. Re-importing the same export is safe — existing days
          are skipped.
        </p>
      </div>

      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
        className={`flex min-h-52 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragActive
            ? "border-black/60 bg-black/5 dark:border-white/60 dark:bg-white/10"
            : "border-black/20 dark:border-white/25"
        }`}
      >
        <p className="text-sm font-medium">
          Drop your Google Takeout .zip here or click to browse
        </p>
        <p className="mt-2 text-xs text-black/45 dark:text-white/45">
          {state.status === "uploading"
            ? "Importing… this can take a moment for large exports."
            : "Export at takeout.google.com → select Fitbit, then upload the .zip."}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".zip"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
            e.target.value = "";
          }}
        />
      </div>

      {state.status === "error" && (
        <div
          role="alert"
          className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-700 dark:text-red-300"
        >
          {state.message}
        </div>
      )}

      {state.status === "done" && (
        <section className="rounded-xl border border-black/10 p-4 dark:border-white/15">
          <h2 className="mb-3 text-sm font-medium">Import complete</h2>
          <ul className="space-y-1 text-sm">
            <li>
              Rows imported: <strong>{state.summary.rows_inserted_total}</strong>
            </li>
            <li>
              Already imported (skipped): {state.summary.rows_skipped_existing}
            </li>
            <li>
              Files: {state.summary.files_processed} processed,{" "}
              {state.summary.files_skipped} skipped, {state.summary.files_errored}{" "}
              errored
            </li>
          </ul>
          {Object.keys(state.summary.rows_inserted).length > 0 && (
            <div className="mt-3">
              <div className="text-[11px] uppercase tracking-wide text-black/40 dark:text-white/40">
                By metric
              </div>
              <ul className="mt-1 grid grid-cols-2 gap-x-6 text-sm">
                {Object.entries(state.summary.rows_inserted).map(
                  ([metric, count]) => (
                    <li key={metric} className="flex justify-between">
                      <span>{metric}</span>
                      <span className="font-mono">{count}</span>
                    </li>
                  ),
                )}
              </ul>
            </div>
          )}
          <a
            href="/dashboard"
            className="mt-4 inline-block rounded-md bg-black px-3 py-1.5 text-xs font-medium text-white dark:bg-white dark:text-black"
          >
            View dashboard
          </a>
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify it builds / lints**

Run: `cd frontend && npm run lint`
Expected: no errors for `app/import/page.tsx` or `app/layout.tsx`.

- [ ] **Step 4: Manual verification**

Start backend (`cd backend && uvicorn app.main:app --reload`) and frontend (`cd frontend && npm run dev`), log in, then visit `/import`:
1. Header shows the **Import** link; it routes to `/import`.
2. Dragging a file over the zone toggles the active border/background; dragging away clears it.
3. Dropping (or browsing to) a **non-`.zip`** shows the inline "Please drop a Google Takeout .zip file." error and does not upload.
4. Dropping a real Takeout `.zip` shows "Importing…", then the summary (rows imported, per-metric counts).
5. Re-dropping the same `.zip` shows rows imported `0` and a non-zero "Already imported (skipped)" count.
6. `/dashboard` now shows charts for the imported metrics.

- [ ] **Step 5: Commit**

```bash
cd /Users/bahk_insung/Documents/Github/bitfit_meteorite
git add frontend/app/import/page.tsx frontend/app/layout.tsx
git commit -m "feat(import): add /import drag-and-drop page and nav link

Native HTML5 drag-and-drop uploads a Takeout .zip to POST /import/takeout
and renders the import summary. No new frontend dependencies.

Constraint: pinned breaking-change Next.js — followed node_modules/next/dist/docs
Confidence: high
Scope-risk: narrow
Not-tested: browser drag-and-drop covered by manual verification only"
```

---

## Self-Review

**Spec coverage:**
- New `/import` page + dropzone + nav link → Task 3. ✅
- `POST /import/takeout` endpoint, session-gated → Tasks 1–2. ✅
- Unzip to temp dir, call existing `import_takeout`, return summary → Task 1. ✅
- Zip-slip guard → Task 1 (`_safe_extract` + `test_rejects_zip_slip`). ✅
- Size cap via `MAX_UPLOAD_MB` (default 200) → Task 1 (`test_rejects_oversized_upload`). ✅
- Non-zip / corrupt → 400 → Task 1 (`ValueError`) + Task 2 route maps to `HTTPException(400)`. ✅
- Idempotent re-import + "already imported" count in UI → Task 1 (`test_reimport_is_idempotent`) + Task 3 summary render. ✅
- No changes to importer / model / pipeline → honoured across all tasks. ✅
- `python-multipart` dependency (discovered missing) → Task 2. ✅

**Placeholder scan:** No TBD/TODO; every code and command step is complete. ✅

**Type consistency:** `import_takeout_zip(data: bytes) -> dict` and `MAX_UPLOAD_MB` are defined in Task 1 and consumed unchanged in Task 2. The frontend `ImportSummary` fields match `report.as_dict()` keys in `backend/app/takeout_import.py` (`rows_inserted`, `rows_inserted_total`, `rows_skipped_existing`, `files_processed/skipped/errored`, `errors`). ✅
