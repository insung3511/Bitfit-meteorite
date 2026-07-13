"""Routes for deep-research mode and the daily check.

Deep research is slow by design (it can run for minutes), so ``POST /research/run``
returns immediately with a job id and the work continues on a background thread.
Clients poll ``GET /research/jobs/{id}`` for progress and read the finished report
from ``GET /research/reports/{id}``.

The report's ``evidence_refs`` carry the record ids behind each claim, which is
what lets a client link an assertion in the narrative back to the underlying rows.
"""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app import research
from app.daily_check import get_daily_check, run_daily_check
from app.db import engine
from app.models import ResearchJob

router = APIRouter(tags=["research"])


class ResearchRunRequest(BaseModel):
    question: Optional[str] = Field(
        default=None,
        max_length=2_000,
        description="Omit for an open-ended baseline analysis.",
    )


@router.post("/research/run")
def run_research(request: ResearchRunRequest | None = None) -> dict[str, Any]:
    """Start a deep-research run and return its job id immediately."""
    question = request.question if request else None
    job_id = research.create_job(question)

    # A daemon thread, not the shared APScheduler pool: a research run can take
    # minutes and must not occupy the slot the periodic sync job needs.
    thread = threading.Thread(
        target=research.run_job,
        args=(job_id,),
        name=f"research-{job_id}",
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id, "status": "running"}


@router.get("/research/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    """Poll a research job's progress."""
    with Session(engine) as session:
        job = session.get(ResearchJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown research job.")
    return {
        "job_id": job.id,
        "status": job.status,
        "phase": job.phase,
        "rounds_done": job.rounds_done,
        "question": job.question,
        "report_id": job.report_id,
        "error": job.error,
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.post("/research/jobs/{job_id}/cancel")
def cancel(job_id: str) -> dict[str, Any]:
    """Ask a running job to stop. It halts at the next tool round."""
    try:
        status = research.cancel_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown research job.") from None
    return {"job_id": job_id, "status": status}


@router.get("/research/reports/{report_id}")
def get_report(report_id: str) -> dict[str, Any]:
    """Read a finished report: narrative, structured analysis, evidence, plan."""
    report = research.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Unknown report.")
    return report


@router.get("/research/plan/active")
def active_plan() -> dict[str, Any]:
    """Return the standing plan, or a null plan if research has never run."""
    plan = research.get_active_plan()
    if plan is None:
        return {"plan": None, "plan_id": None, "detail": "No plan yet — run deep research."}
    return plan


@router.get("/daily/check")
def daily_check(
    date: str | None = Query(
        None, description="ISO date. Defaults to yesterday."
    ),
    refresh: bool = Query(
        False, description="Recompute instead of returning the stored readout."
    ),
) -> dict[str, Any]:
    """Return the day's readout against the standing plan.

    Served from storage by default — the readout is written after each sync, so a
    dashboard poll should not trigger a model call.
    """
    if date:
        try:
            day = dt.date.fromisoformat(date)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="date must be an ISO date (YYYY-MM-DD)."
            ) from None
    else:
        day = dt.date.today() - dt.timedelta(days=1)

    if not refresh:
        stored = get_daily_check(day)
        if stored is not None:
            return stored

    return run_daily_check(day)
