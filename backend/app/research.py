"""Deep-research mode: a long-running, cancellable analysis over the user's data.

This is the slow lane. Where :func:`app.llm_client.chat` answers one question in
a bounded interactive turn, a research run is given a much larger tool budget and
is expected to sweep the whole metric catalogue, drill into the raw signal index,
correlate, and finish by proposing a weekly or monthly plan.

Three properties matter and are enforced here rather than trusted to the model:

* **Grounding.** The plan is returned through the ``propose_health_plan`` tool, so
  it arrives as a validated :class:`app.ai_schemas.HealthPlanSpec` instead of prose
  scraped out of the final message. Every target must cite evidence IDs that were
  minted by a real read tool (see :func:`app.llm_client._evidence_for_tool`); IDs
  the model invents are stripped, and a target left with none is rejected.
* **Cancellability.** The job row is the single source of truth. Cancelling flips
  ``status`` and the worker notices between tool rounds — the same contract
  ``import_raw_signals`` uses.
* **Durability.** Progress is written to ``research_job`` as it happens, so a
  frontend can poll a run that takes minutes.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from typing import Any, Optional

from sqlmodel import Session, select

from app.ai_schemas import HealthPlanSpec, PlanTarget, StructuredAnalysis
from app.db import engine
from app.models import HealthPlan, ResearchJob, ResearchReport

logger = logging.getLogger(__name__)

# Deep research needs far more room than an interactive turn: it sweeps every
# metric, drills into raw signals, and correlates before it plans. The final turn
# also carries a long report *and* the structured analysis block, so a tight
# output cap truncates it mid-JSON and the block becomes unparseable.
_DEEP_MAX_TOKENS = 16_384
_DEEP_MAX_ROUNDS = 40

_TERMINAL_STATUSES = {"complete", "error", "cancelled"}

RESEARCH_SYSTEM_SUFFIX = (
    "\n\nYou are running in DEEP RESEARCH mode. Take your time and be thorough.\n\n"
    "Work in this order:\n"
    "1. Call list_available_metrics to discover what data actually exists. Analyse "
    "every metric that has meaningful coverage — not only the ones you recognise.\n"
    "2. For metrics with high-resolution data (check list_raw_signal_types), drill "
    "into the raw signals rather than settling for the daily rollup.\n"
    "3. Look for relationships between signals with correlate_health_signals, and "
    "for outliers with get_anomalies. Correlation is not causation — say so.\n"
    "4. Call submit_analysis exactly once with your structured findings. This is "
    "required, not optional: the report renders each observation, hypothesis and "
    "uncertainty as its own sourced claim that links back to the underlying "
    "records. Findings left only in your prose cannot be linked to evidence and "
    "are invisible to the UI. Do not use a JSON block in your message — use the "
    "tool.\n"
    "5. Call propose_health_plan exactly once.\n"
    "6. Then write your final message: a readable report, under 10000 characters. "
    "It is a summary for a human, not the data structure — that is what the two "
    "tools above are for.\n\n"
    "The plan must be built only from what you measured. Every target and every "
    "experiment must cite the evidence_ids returned by the tools you actually "
    "called. A target you cannot ground in evidence will be discarded by the "
    "server, so do not guess. Where the data is thin or absent, say so in the "
    "uncertainties rather than filling the gap with generic advice.\n\n"
    "This is wellness guidance derived from the user's own measurements. It is not "
    "a diagnosis and not a prescription."
)

def _claim_items(description: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Schema for a list of evidence-carrying claims."""
    properties: dict[str, Any] = {
        "statement": {"type": "string"},
        "evidence_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Evidence IDs returned by tool calls in this run.",
        },
        **(extra or {}),
    }
    return {
        "type": "array",
        "description": description,
        "items": {
            "type": "object",
            "properties": properties,
            "required": ["statement", "evidence_ids"],
        },
    }


# The structured analysis arrives as a tool call, not as a JSON block appended to
# the prose. Asking the model to append a marker block works only when it feels
# like it — in practice it writes the report and forgets — and a report with no
# structured claims cannot be rendered as clickable, evidence-linked findings.
SUBMIT_ANALYSIS_TOOL: dict[str, Any] = {
    "name": "submit_analysis",
    "description": (
        "Submit your structured findings. Call this exactly once, immediately "
        "before propose_health_plan. Each observation, hypothesis and uncertainty "
        "is rendered in the report as an individually sourced claim, so every one "
        "must carry the evidence_ids of the tool results it rests on. Split your "
        "findings into one entry per claim rather than one long paragraph."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "observations": _claim_items(
                "What the data measurably shows. Facts, not interpretation."
            ),
            "hypotheses": _claim_items(
                "Possible explanations. Interpretation, clearly labelled as such.",
                {"confidence": {"type": "string", "enum": ["low", "medium", "high"]}},
            ),
            "uncertainties": _claim_items(
                "Limits on the above: thin coverage, gaps, confounds, short windows."
            ),
        },
        "required": ["observations", "uncertainties"],
    },
}

PROPOSE_PLAN_TOOL: dict[str, Any] = {
    "name": "propose_health_plan",
    "description": (
        "Submit the final weekly or monthly plan. Call this exactly once, at the "
        "very end, after you have gathered your evidence. Every target and "
        "experiment must cite evidence_ids returned by earlier tool calls in this "
        "run — invented IDs are rejected by the server."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "horizon": {"type": "string", "enum": ["weekly", "monthly"]},
            "summary": {
                "type": "string",
                "description": "What the plan is steering toward, and why, in plain language.",
            },
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "targets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string"},
                        "direction": {
                            "type": "string",
                            "enum": ["increase", "decrease", "maintain"],
                        },
                        "current_value": {"type": ["number", "null"]},
                        "target_value": {"type": ["number", "null"]},
                        "unit": {"type": ["string", "null"]},
                        "rationale": {"type": "string"},
                        "evidence_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Evidence IDs from tool results in this run.",
                        },
                    },
                    "required": ["metric", "direction", "rationale", "evidence_ids"],
                },
            },
            "experiments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string"},
                        "duration_days": {"type": "integer", "minimum": 1, "maximum": 365},
                        "measured_by": {"type": "array", "items": {"type": "string"}},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["statement", "duration_days", "measured_by"],
                },
            },
        },
        "required": ["horizon", "summary", "targets"],
    },
}


def _last_tool_input(messages: list[dict[str, Any]], tool_name: str) -> Optional[dict[str, Any]]:
    """Return the input of the last call to ``tool_name``, if it was called."""
    found: dict[str, Any] | None = None
    for message in messages:
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("name") == tool_name:
                found = block.get("input") or {}
    return found


def _ground(items: Any, valid_evidence_ids: set[str], *, require: bool) -> list[dict[str, Any]]:
    """Filter claim evidence to IDs the server actually minted.

    ``require`` drops any claim left with no real evidence — an ungrounded claim
    presented as sourced is worse than one that was never made.
    """
    grounded: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        ids = [
            evidence_id
            for evidence_id in item.get("evidence_ids") or []
            if evidence_id in valid_evidence_ids
        ]
        if require and not ids:
            logger.warning("Dropping ungrounded claim: %r", str(item.get("statement"))[:80])
            continue
        grounded.append({**item, "evidence_ids": ids})
    return grounded


def _analysis_from_tool_history(
    messages: list[dict[str, Any]],
    valid_evidence_ids: set[str],
) -> Optional[dict[str, Any]]:
    """Recover the structured findings from the ``submit_analysis`` call."""
    raw = _last_tool_input(messages, "submit_analysis")
    if raw is None:
        return None
    return {
        "observations": _ground(raw.get("observations"), valid_evidence_ids, require=True),
        "hypotheses": _ground(raw.get("hypotheses"), valid_evidence_ids, require=True),
        "uncertainties": _ground(raw.get("uncertainties"), valid_evidence_ids, require=False),
    }


def _plan_from_tool_history(
    messages: list[dict[str, Any]],
    valid_evidence_ids: set[str],
) -> Optional[HealthPlanSpec]:
    """Recover the plan from the ``propose_health_plan`` call, evidence-filtered.

    The plan is read from the model's *tool input* rather than its prose, so it is
    a validated structure by construction. Evidence IDs are then intersected with
    the IDs the server actually minted: a target that cites nothing real is
    dropped, because an ungrounded target is exactly the failure mode the whole
    evidence system exists to prevent.
    """
    raw_plan: dict[str, Any] | None = None
    for message in messages:
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("name") == "propose_health_plan":
                raw_plan = block.get("input") or {}

    if raw_plan is None:
        return None

    targets: list[dict[str, Any]] = []
    for item in raw_plan.get("targets") or []:
        if not isinstance(item, dict):
            continue
        grounded = [
            evidence_id
            for evidence_id in item.get("evidence_ids") or []
            if evidence_id in valid_evidence_ids
        ]
        if not grounded:
            logger.warning(
                "Discarding ungrounded plan target for %r: no evidence survived.",
                item.get("metric"),
            )
            continue
        targets.append({**item, "evidence_ids": grounded})

    experiments: list[dict[str, Any]] = []
    for item in raw_plan.get("experiments") or []:
        if not isinstance(item, dict):
            continue
        experiments.append(
            {
                **item,
                "evidence_ids": [
                    evidence_id
                    for evidence_id in item.get("evidence_ids") or []
                    if evidence_id in valid_evidence_ids
                ],
            }
        )

    try:
        return HealthPlanSpec.model_validate(
            {**raw_plan, "targets": targets, "experiments": experiments}
        )
    except Exception:
        logger.exception("Model returned a plan that failed validation")
        return None


def _job_status(job_id: str) -> Optional[str]:
    with Session(engine) as session:
        job = session.get(ResearchJob, job_id)
        return job.status if job else None


def _update_job(job_id: str, **fields: Any) -> None:
    with Session(engine) as session:
        job = session.get(ResearchJob, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        session.add(job)
        session.commit()


def create_job(question: str | None = None) -> str:
    """Register a research job in ``running`` state and return its id."""
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    with Session(engine) as session:
        session.add(
            ResearchJob(
                id=job_id,
                status="running",
                question=question,
                phase="Queued",
            )
        )
        session.commit()
    return job_id


def cancel_job(job_id: str) -> str:
    """Ask a running job to stop. The worker notices between tool rounds."""
    with Session(engine) as session:
        job = session.get(ResearchJob, job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status in _TERMINAL_STATUSES:
            return job.status
        job.status = "cancelled"
        job.phase = "Cancelling"
        session.add(job)
        session.commit()
        return job.status


def _activate_plan(session: Session, plan: HealthPlan) -> None:
    """Make ``plan`` the standing plan, superseding any previous active one.

    Plans are never mutated — the old row stays, deactivated, so a daily check
    written against it remains interpretable.
    """
    previous = session.exec(
        select(HealthPlan).where(HealthPlan.is_active == True)  # noqa: E712
    ).all()
    for old in previous:
        old.is_active = False
        session.add(old)
        plan.parent_id = old.id
    session.add(plan)


def run_job(job_id: str) -> None:
    """Execute a research job to completion. Never raises — failures are recorded.

    This runs on a worker thread, so an escaping exception would be lost; every
    outcome is written back to the job row instead.
    """
    # Imported lazily: the module-level import would be circular via llm_client's
    # own imports, and it keeps this module importable without an API key.
    from app.ai_schemas import EvidenceReference, WorkspaceActionProposal
    from app.llm_client import (
        AgentCancelled,
        SYSTEM_PROMPT,
        TOOL_SCHEMAS,
        _run_agent,
        _structured_analysis,
    )

    with Session(engine) as session:
        job = session.get(ResearchJob, job_id)
        if job is None or job.status != "running":
            return
        question = job.question

    def cancelled() -> bool:
        return _job_status(job_id) == "cancelled"

    def on_round(round_index: int) -> None:
        _update_job(
            job_id,
            rounds_done=round_index,
            phase=f"Analysing (round {round_index + 1})",
        )

    if question:
        user_message = (
            f"{question}\n\n"
            "Research this thoroughly against my data, then propose a plan."
        )
    else:
        user_message = (
            "Run a full baseline analysis of my health data. Survey every metric "
            "I have, drill into the high-resolution signals, look for "
            "relationships and outliers, then propose a plan for me."
        )

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    evidence_sink: list[EvidenceReference] = []
    action_sink: list[WorkspaceActionProposal] = []

    try:
        reply, history = _run_agent(
            messages,
            max_tokens=_DEEP_MAX_TOKENS,
            max_rounds=_DEEP_MAX_ROUNDS,
            system=SYSTEM_PROMPT + RESEARCH_SYSTEM_SUFFIX,
            tools=[*TOOL_SCHEMAS, SUBMIT_ANALYSIS_TOOL, PROPOSE_PLAN_TOOL],
            on_round=on_round,
            cancel_check=cancelled,
            evidence_sink=evidence_sink,
            action_sink=action_sink,
        )
    except AgentCancelled:
        _update_job(
            job_id,
            status="cancelled",
            phase="Cancelled",
            finished_at=dt.datetime.utcnow(),
        )
        return
    except Exception as exc:
        logger.exception("Research job %s failed", job_id)
        _update_job(
            job_id,
            status="error",
            phase="Failed",
            error=f"{type(exc).__name__}: {exc}",
            finished_at=dt.datetime.utcnow(),
        )
        return

    _update_job(job_id, phase="Writing report")

    # Persisting is fallible too (a truncated reply can produce output the schema
    # rejects). Without this guard a failure here escapes the worker thread and
    # leaves the job stuck in 'running' forever, with no report and no error.
    try:
        narrative, analysis, _evidence_refs, _actions = _structured_analysis(
            reply, history, evidence_sink, action_sink
        )
        valid_ids = {item.evidence_id for item in evidence_sink}

        # Prefer the findings the model submitted as a tool call. They are what a
        # report renders as sourced, clickable claims; the marker-block parsing in
        # _structured_analysis is only a fallback for models that ignore the tool.
        submitted = _analysis_from_tool_history(history, valid_ids)
        if submitted:
            analysis = StructuredAnalysis.model_validate(
                {
                    "narrative": analysis.narrative,
                    "evidence_refs": [item.model_dump(mode="json") for item in evidence_sink],
                    "workspace_actions": [item.model_dump(mode="json") for item in action_sink],
                    **submitted,
                }
            )

        plan = _plan_from_tool_history(history, valid_ids)

        report_id = f"rep_{uuid.uuid4().hex[:16]}"
        with Session(engine) as session:
            session.add(
                ResearchReport(
                    id=report_id,
                    job_id=job_id,
                    narrative=narrative,
                    analysis_json=analysis.model_dump_json(),
                )
            )
            if plan is not None and plan.targets:
                _activate_plan(
                    session,
                    HealthPlan(
                        id=f"plan_{uuid.uuid4().hex[:16]}",
                        report_id=report_id,
                        horizon=plan.horizon,
                        plan_json=plan.model_dump_json(),
                    ),
                )
            session.commit()
    except Exception as exc:
        logger.exception("Research job %s produced an unusable report", job_id)
        _update_job(
            job_id,
            status="error",
            phase="Failed writing report",
            error=f"{type(exc).__name__}: {exc}",
            finished_at=dt.datetime.utcnow(),
        )
        return

    _update_job(
        job_id,
        status="complete",
        phase="Complete",
        report_id=report_id,
        finished_at=dt.datetime.utcnow(),
    )


def get_report(report_id: str) -> Optional[dict[str, Any]]:
    """Return a persisted report with its plan, ready to serialize."""
    with Session(engine) as session:
        report = session.get(ResearchReport, report_id)
        if report is None:
            return None
        plan = session.exec(
            select(HealthPlan).where(HealthPlan.report_id == report_id)
        ).first()

    analysis = StructuredAnalysis.model_validate_json(report.analysis_json)
    return {
        "report_id": report.id,
        "job_id": report.job_id,
        "created_at": report.created_at.isoformat(),
        "narrative": report.narrative,
        "analysis": analysis.model_dump(mode="json"),
        "evidence_refs": [item.model_dump(mode="json") for item in analysis.evidence_refs],
        "plan": json.loads(plan.plan_json) if plan else None,
        "plan_id": plan.id if plan else None,
    }


def get_active_plan() -> Optional[dict[str, Any]]:
    """Return the standing plan, or ``None`` if deep research has never run."""
    with Session(engine) as session:
        plan = session.exec(
            select(HealthPlan)
            .where(HealthPlan.is_active == True)  # noqa: E712
            .order_by(HealthPlan.created_at.desc())
        ).first()
        if plan is None:
            return None

    return {
        "plan_id": plan.id,
        "report_id": plan.report_id,
        "horizon": plan.horizon,
        "created_at": plan.created_at.isoformat(),
        "plan": json.loads(plan.plan_json),
    }


def active_plan_spec() -> Optional[tuple[str, HealthPlanSpec]]:
    """Return ``(plan_id, spec)`` for the standing plan, for the daily check."""
    active = get_active_plan()
    if active is None:
        return None
    return active["plan_id"], HealthPlanSpec.model_validate(active["plan"])


def plan_targets(spec: HealthPlanSpec) -> list[PlanTarget]:
    return list(spec.targets)
