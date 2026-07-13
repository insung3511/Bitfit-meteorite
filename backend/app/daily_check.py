"""Daily-check mode: the cheap lane, run after each cloud sync.

Deliberately *not* a second analyst. Deep research owns interpretation and owns
the plan; this compares one day's numbers against the standing plan and the
rolling baseline, and says whether the day was on track. It never re-plans — if
the two modes were both allowed to reason freely they would contradict each
other, and the user would have no way to tell which to believe.

That constraint is why this is a single bounded LLM call with pre-fetched data
rather than a tool loop: there is nothing here worth eight rounds of tool use.

Degrades on purpose: with no active plan (deep research has never run) it falls
back to a plain baseline-deviation summary, so cloud sync is useful on day one.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Optional

from sqlmodel import Session, select

from app.ai_schemas import DailyCheckResult, PlanAdherence
from app.db import engine
from app.models import DailyCheck, DailyMetric, DailySummary

logger = logging.getLogger(__name__)

_MAX_TOKENS = 1_024

_SYSTEM_PROMPT = (
    "You write a single short daily health readout for one user, comparing one "
    "day's measurements against their standing wellness plan and their own "
    "rolling baseline.\n\n"
    "Every number you mention must come from the data supplied in the message. "
    "Never invent or recall figures. You are not a medical professional: report "
    "what changed, do not diagnose.\n\n"
    "Do NOT propose a new plan, revise targets, or give broad lifestyle advice — "
    "a separate deep-research process owns the plan. Your job is only to say how "
    "this day measured up and what stands out. Two or three sentences.\n\n"
    "If there is no plan, just summarise how the day compares to the baseline."
)


def _observed_values(day: dt.date) -> dict[str, dict[str, Any]]:
    """Read one day's actual values and their rolling baseline context."""
    with Session(engine) as session:
        metrics = session.exec(
            select(DailyMetric).where(DailyMetric.date == day)
        ).all()
        summaries = session.exec(
            select(DailySummary).where(DailySummary.date == day)
        ).all()

    by_metric: dict[str, dict[str, Any]] = {}
    for row in metrics:
        by_metric.setdefault(row.metric_name, {})["value"] = row.value
        by_metric[row.metric_name]["unit"] = row.unit
    for row in summaries:
        entry = by_metric.setdefault(row.metric_name, {})
        entry["mean_7d"] = row.mean_7d
        entry["mean_30d"] = row.mean_30d
        entry["delta_vs_baseline"] = row.delta_vs_baseline
    return by_metric


def _adherence(
    targets: list[Any], observed: dict[str, dict[str, Any]]
) -> list[PlanAdherence]:
    """Score each plan target against the day, arithmetically — not by the model.

    Adherence is a comparison of two numbers. Computing it here keeps it exact and
    keeps the model's job to narration only.
    """
    rows: list[PlanAdherence] = []
    for target in targets:
        entry = observed.get(target.metric) or {}
        value = entry.get("value")
        on_target: bool | None = None
        if value is not None and target.target_value is not None:
            if target.direction == "increase":
                on_target = value >= target.target_value
            elif target.direction == "decrease":
                on_target = value <= target.target_value
            else:
                on_target = True
        rows.append(
            PlanAdherence(
                metric=target.metric,
                target_value=target.target_value,
                observed_value=value,
                on_target=on_target,
                note="" if value is not None else "No reading for this day.",
            )
        )
    return rows


def run_daily_check(day: dt.date | None = None) -> dict[str, Any]:
    """Produce (and persist) the readout for ``day``, defaulting to yesterday."""
    from app.llm_client import MODEL, _get_client
    from app.research import active_plan_spec

    day = day or (dt.date.today() - dt.timedelta(days=1))
    observed = _observed_values(day)

    active = active_plan_spec()
    plan_id, spec = active if active else (None, None)
    adherence = _adherence(spec.targets, observed) if spec else []

    payload = {
        "date": day.isoformat(),
        "observed": observed,
        "plan": spec.model_dump(mode="json") if spec else None,
        "adherence": [row.model_dump(mode="json") for row in adherence],
    }

    if not observed:
        summary = f"No health data was recorded for {day.isoformat()}."
    else:
        client = _get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Here is my data for {day.isoformat()}, my standing plan "
                        "(may be null), and the pre-computed adherence for each "
                        "plan target. Write my daily readout.\n\n"
                        f"{json.dumps(payload, indent=2, default=str)}"
                    ),
                }
            ],
        )
        summary = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

    result = DailyCheckResult(
        date=day,
        plan_id=plan_id,
        summary=summary or "No readout was produced.",
        adherence=adherence,
    )

    with Session(engine) as session:
        existing = session.exec(
            select(DailyCheck).where(DailyCheck.date == day)
        ).first()
        if existing is None:
            existing = DailyCheck(date=day, plan_id=plan_id, summary=result.summary,
                                  result_json=result.model_dump_json())
        else:
            existing.plan_id = plan_id
            existing.summary = result.summary
            existing.result_json = result.model_dump_json()
        session.add(existing)
        session.commit()

    return result.model_dump(mode="json")


def get_daily_check(day: dt.date) -> Optional[dict[str, Any]]:
    """Return a previously persisted readout, without calling the model."""
    with Session(engine) as session:
        row = session.exec(select(DailyCheck).where(DailyCheck.date == day)).first()
    if row is None:
        return None
    return json.loads(row.result_json)


def run_after_sync() -> None:
    """Hook for the scheduled sync. Never raises — a failed readout must not
    take down the sync job or the scheduler thread."""
    try:
        run_daily_check()
    except Exception:
        logger.exception("Daily check failed after sync")
