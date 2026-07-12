# Personal Health Evidence Workspace

This document is the durable continuation plan for the private, local-first
health dashboard. The runtime copy is also kept at
`.omx/plans/personal-health-evidence-workspace.md` for OMX agents.

## Product Decisions

- One private user; local SQLite remains the source of truth.
- Initial sources are Google Health/Fit OAuth and Google Takeout.
- Keep daily, session, interval, and sensor-level signals queryable.
- Keep original Takeout files outside the relational database; index normalized
  points locally with file and record provenance.
- AI can inspect bounded evidence and propose chart/workspace changes, but it
  cannot mutate the workspace directly. Approved changes are versioned and
  reversible.
- Separate measured observations, calculations, hypotheses, and uncertainty;
  the assistant must not diagnose or prescribe treatment.

## Implemented Lanes

### Raw signal ingestion

`backend/app/raw_signal_import.py` indexes raw/derived Fit JSON, Korean interval
CSV, session JSON, and TCX tracks into separate SQLite tables. Imports are
SHA-256 checkpointed, idempotent, resumable per file, transactionally persisted,
size-limited, cancellable, and query-bounded. `takeout_import.py` runs this
index after preserving the existing daily import contract.

### AI evidence protocol

`backend/app/ai_schemas.py` defines typed evidence references, structured
observations/hypotheses, bounded workspace context, and proposal-only reversible
actions. `llm_client.py` exposes bounded daily, correlation, provenance, and
raw-signal tools, generates server-owned evidence IDs, filters model-invented
evidence references, and preserves the legacy plain-text chat response.

### Versioned workspace and UI

`backend/app/routes/workspace.py` and `WorkspaceVersion` persist approved
workspace revisions and restore operations. The dashboard has configurable
panels, chart modes, date windows, baselines, local history/undo, evidence
context, and an approval bridge for assistant proposals. Chat renders evidence
references and stores approved proposals for the dashboard to apply.

## Verification

- Backend: `python -m pytest -q` -> 30 passed (only existing dependency
  deprecation warnings).
- Frontend: `npm run lint`, `npx tsc --noEmit`, and `npm run build` -> passed.
  Local system font stacks replace build-time Google font fetching so builds do
  not require network access.
- Real Korean Takeout in a disposable SQLite database: 715 files processed,
  35,060 raw points inserted, 0 errors. Re-import: 0 new points and 719 files
  skipped by their completed hashes.
- Python compilation and `git diff --check` pass.

## Follow-up

Run a browser-level smoke test against the local dev servers covering panel
focus, raw drill-down, evidence display, proposal approval, undo/restore, and
historical dates. Do not commit private Takeout files or the local database.

## Safe Continuation Order

1. Read this file and the existing tests before changing contracts.
2. Keep raw files outside the database and preserve import idempotency.
3. Keep AI actions proposal-only and approval-gated; add a regression test for
   every new action type.
4. Run backend tests, frontend lint/typecheck/build, and `git diff --check`.
