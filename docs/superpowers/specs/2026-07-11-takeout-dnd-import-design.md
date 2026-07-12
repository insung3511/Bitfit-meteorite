# Drag-and-drop Google Takeout import — Design

**Date:** 2026-07-11
**Status:** Approved (design), pending implementation plan

## Problem

The dashboard already tells users they can "import a Google Takeout export"
(`frontend/app/dashboard/page.tsx` empty state), and the backend already has a
complete, idempotent importer — `import_takeout(path)` in
`backend/app/takeout_import.py:394` — that walks a directory of Takeout
JSON/CSV files, folds them to daily metrics, recomputes summaries, and indexes
raw signals.

But there is **no way for a user to actually do this from the web app**. The
importer is reachable only via its CLI (`python -m app.takeout_import`) and the
scheduled Google Health sync. A user with a Google Takeout `.zip` on their
machine has no in-app path to load it.

## Goal

Let a user drag-and-drop their Google Takeout `.zip` onto the web app and have
their historical health data imported, with a clear report of what was
imported.

## Non-goals

- Live Google API / OAuth sync (that already exists via the scheduled job and
  `POST /sync/run`).
- Folder drag-and-drop or loose-file drop — the payload is a single `.zip`,
  exactly as Google Takeout delivers it.
- Background/async job processing with polling — the import runs synchronously
  in the request (see Approach).
- Changes to the importer's parsing logic or the data model.

## Approach

**No new dependencies; synchronous import.**

- **Frontend:** native HTML5 drag-and-drop (`onDrop` / `onDragOver` /
  `onDragLeave`) plus a hidden `<input type="file" accept=".zip">` click
  fallback. The repo's only runtime dependency beyond React/Next is `recharts`;
  a drag-and-drop library (e.g. react-dropzone) is unjustified for a single
  zone.
- **Backend:** a plain `POST` that unzips → imports → returns the summary. The
  importer is already run synchronously by the scheduler and is idempotent, so
  a synchronous request handler is the simplest correct design and is safe to
  retry.

**Rejected alternatives:**
- A drag-and-drop library — extra dependency for no benefit at this scale.
- A background job with status polling — unnecessary complexity for a
  single-user personal app; the import completes in-request.

## Components

### Backend — new upload endpoint

New route module `backend/app/routes/import_takeout.py`:

- `POST /import/takeout`, mounted in `backend/app/main.py` under the existing
  `Depends(require_session)` gate (same as every other protected router).
- Accepts `multipart/form-data` with a single `.zip` file via FastAPI
  `UploadFile`.
- Handler flow:
  1. Validate the upload is a zip (extension and/or `zipfile.is_zipfile`).
  2. Enforce a size cap (see Edge cases) before/while reading.
  3. Stream the upload into a `tempfile.TemporaryDirectory()`.
  4. `zipfile.extractall` into that dir, guarding against zip-slip
     (path-traversal) — reject any entry whose resolved path escapes the temp
     dir.
  5. Call the existing `import_takeout(temp_dir)`.
  6. Return its summary dict as JSON. Temp dir is auto-cleaned on scope exit.

The endpoint imports data into the existing `DailyMetric` store with
`source="takeout"` — no model or schema change.

### Frontend — new `/import` page

- New route `frontend/app/import/page.tsx` (client component).
- New **"Import"** link in the header nav in `frontend/app/layout.tsx`,
  alongside the existing Chat and Dashboard links.
- Dropzone: dashed-border box with a drag-active visual state (Tailwind),
  labelled "Drop your Google Takeout `.zip` here or click to browse". Clicking
  opens the hidden file input. Non-`.zip` drops are rejected with an inline
  message; the zone stays ready.
- On a valid drop/select: `POST` the file to `/import/takeout` as
  `multipart/form-data` with `credentials: "include"` (matching the dashboard's
  existing fetch pattern and `NEXT_PUBLIC_API_BASE_URL`). Show an
  uploading/importing state, then render the returned summary.
- Summary render: rows inserted per metric, total inserted, files
  skipped/errored, and the "already imported" (rows-skipped-existing) count.
- A short "How to export" helper: a link to Google Takeout and a note on which
  folder to select.

> **Next.js note:** this repo pins a Next.js version with breaking changes
> (`frontend/AGENTS.md`). The relevant guide under
> `node_modules/next/dist/docs/` must be read before writing the page/route.

## Data flow

```
User drops Takeout.zip on /import
  → POST /import/takeout   (multipart/form-data, session cookie)
    → validate zip + size cap
    → stream to temp dir
    → zipfile.extractall (zip-slip guarded)
    → import_takeout(temp_dir)
        parse → daily fold → idempotent insert (source="takeout")
        → recompute daily summaries → index raw signals
    → return summary JSON
    → temp dir auto-cleaned
  → UI renders per-metric import report
  → Dashboard /dashboard/metrics now returns the newly imported metrics
```

## Error handling & edge cases

| Case | Behaviour |
|------|-----------|
| Upload is not a zip | 400 with message; inline UI error; dropzone stays ready |
| Corrupt / unreadable zip | 400 with message |
| Zip-slip (entry escapes temp dir) | Reject the entry; do not extract outside temp dir |
| Oversized upload | Reject (400/413); cap configurable via env `MAX_UPLOAD_MB`, default 200 |
| Re-import of the same data | Importer skips existing `(date, metric)` rows; UI shows "already imported" count so a repeat is a clear no-op, not a failure |
| Partial parse failures | Still a success response; per-file errors surfaced in the summary (importer already tolerates malformed files) |

## Testing

**Backend (pytest, following `backend/tests/`):**
- Valid Takeout zip imports the expected daily rows.
- Non-zip upload → 400.
- Zip containing a path-traversal entry → entry rejected, nothing written
  outside the temp dir.
- Oversized upload → rejected.
- Re-uploading the same zip is idempotent (second import inserts 0 new rows,
  reports them as already-existing).

**Frontend (manual — no frontend test setup in the repo):**
- Drag-active visual state toggles on dragenter/dragleave.
- Valid zip uploads and the summary renders.
- Non-zip drop shows the inline error and does not upload.

## Files touched

- `backend/app/routes/import_takeout.py` — new route module.
- `backend/app/main.py` — mount the new router under `require_session`.
- `backend/tests/` — new endpoint tests.
- `frontend/app/import/page.tsx` — new import page + dropzone.
- `frontend/app/layout.tsx` — add "Import" nav link.

No changes to `takeout_import.py`, the data model, or the summarize/raw-signal
pipeline.
