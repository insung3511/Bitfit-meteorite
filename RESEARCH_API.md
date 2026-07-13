# Deep Research + Daily Check — frontend contract

Backend for **mode 2** (the "deep talk" report surface) is live as of `ebf7a57`.
Nothing in the frontend calls it yet. This is what it exposes.

All routes sit behind the session cookie, same as `/dashboard/*`. Use
`credentials: "include"`.

---

## Mode 2 — Deep research (slow, user-initiated)

A run takes **3–5 minutes** and 10–15 tool rounds. It is a job, not a request:
start it, poll it, then read the report.

### Start

```
POST /research/run
Body: { "question": "why is my sleep bad?" }   // optional; omit for open-ended baseline
->    { "job_id": "job_abc123", "status": "running" }
```

### Poll

```
GET /research/jobs/{job_id}
-> {
     "status": "running" | "complete" | "error" | "cancelled",
     "phase": "Analysing (round 7)",   // human-readable, safe to show verbatim
     "rounds_done": 7,
     "report_id": "rep_xyz" | null,    // set once complete
     "error": null
   }
```

Poll every ~3s. `phase` is written for display — it changes as the agent works,
which is what makes a 4-minute wait tolerable.

### Cancel

```
POST /research/jobs/{job_id}/cancel  -> { "status": "cancelled" }
```

Stops at the next tool round. No partial report is persisted.

### Read the report

```
GET /research/reports/{report_id}
-> {
     "narrative": "...",              // prose summary, <10k chars
     "analysis": {
       "observations":   [ { "statement": "...", "evidence_ids": ["ev_..."] } ],
       "hypotheses":     [ { "statement": "...", "confidence": "low|medium|high",
                             "evidence_ids": ["ev_..."] } ],
       "uncertainties":  [ { "statement": "...", "evidence_ids": [...] } ]
     },
     "evidence_refs": [ {
       "evidence_id": "ev_...",
       "metric": "hrv",
       "start_date": "2026-07-03", "end_date": "2026-07-10",
       "aggregation": "mean" | "raw" | "correlation" | "provenance",
       "record_ids": ["..."],         // the actual source rows
       "point_count": 7
     } ],
     "plan": { ... }                  // see below
   }
```

**This is the structure the report UI should be built on, not `narrative`.**

Each observation / hypothesis / uncertainty is a **separately sourced claim**.
Its `evidence_ids` join to `evidence_refs[]`, and each ref carries the metric,
the window, and the `record_ids` behind it. That is what makes a claim clickable:
click it → look up its refs → you have the exact metric + date range to chart, and
the record ids to highlight. This is the "click the claim, see the data" behavior.

Guarantees worth relying on:

- Every observation and every plan target has **at least one real evidence id**.
  The server mints evidence ids from actual tool results and discards any the
  model invents, so an ungrounded claim is dropped rather than shown as sourced.
- `uncertainties` may have **empty** `evidence_ids` — a caveat is not a data
  claim. Don't render them as unsourced errors.
- `hypotheses` are interpretation, not fact. They carry `confidence`. Render them
  visually distinct from observations — the whole design rests on that line.

A real run produced: 22 observations, 6 hypotheses, 6 uncertainties, 45 evidence
refs, 0 ungrounded.

### The plan

```
GET /research/plan/active
-> { "plan_id": "plan_...", "report_id": "rep_...", "horizon": "weekly"|"monthly",
     "plan": {
       "summary": "...",
       "confidence": "low|medium|high",
       "targets": [ {
         "metric": "resting_heart_rate",
         "direction": "increase" | "decrease" | "maintain",
         "current_value": 67.0,
         "target_value": 63.0,
         "unit": "bpm",
         "rationale": "...",
         "evidence_ids": ["ev_..."]
       } ],
       "experiments": [ { "statement": "...", "duration_days": 14,
                          "measured_by": ["hrv","sleep_score"] } ]
     } }
```

If deep research has never run: `{ "plan": null, "plan_id": null, "detail": "..." }`.
Handle that — it is the day-one state, not an error.

---

## Mode 1 — Daily check (cheap, automatic)

Written automatically after each successful `/sync/run`. **Served from storage —
a poll does not trigger a model call**, so it's safe to fetch on dashboard load.

```
GET /daily/check                       // defaults to yesterday
GET /daily/check?date=2026-07-11
GET /daily/check?refresh=true          // forces recompute — costs a model call
-> {
     "date": "2026-07-11",
     "plan_id": "plan_..." | null,
     "summary": "Slept 6h12m against your 7h30m target...",
     "adherence": [ {
       "metric": "steps",
       "target_value": 10000, "observed_value": 12000,
       "on_target": true | false | null,   // null = no reading that day
       "note": ""
     } ]
   }
```

`adherence` is computed **arithmetically in Python**, not narrated by the model —
the numbers are exact. The model only writes `summary`.

Daily check never re-plans. It measures the day against the standing plan and
defers all re-planning to deep research. If the two modes both reasoned freely
they'd contradict each other.

---

## Two things that will bite you

1. **Deep research takes minutes.** Don't build it as a request/response. Start →
   poll `phase` → read report. Show the phase; it's the only thing that makes the
   wait feel alive.

2. **`plan` is null until deep research has run once.** The daily check still
   works — it degrades to a plain baseline-deviation summary. Design the empty
   state first; it's what a new user sees.

---

## Not yet wired

`sync_once` writes `daily_metric` only — it never touches `raw_signal`. So cloud
sync does **not** grow the raw drill-down data; only a Takeout import does. The
Google Health API *can* serve raw points (`dataPoints.list`, no special access
tier), but that path isn't built. Don't promise "live raw data" in the UI yet.
