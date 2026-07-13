"""Focused tests for the structured AI/evidence/workspace protocol."""

from __future__ import annotations

import json

import pytest


def test_workspace_proposal_is_reversible_and_not_applied():
    from app.llm_client import propose_workspace_action

    result = propose_workspace_action(
        "focus_panel",
        panel_id="sleep-trend",
        payload={"date": "2016-12-30"},
        rationale="Focus the chart referenced by the sleep evidence.",
    )

    assert result["applied"] is False
    assert result["requires_approval"] is True
    assert result["reversible"] is True
    assert result["proposal"]["status"] == "proposed"
    assert result["proposal"]["action_id"].startswith("act_")


def test_workspace_proposal_rejects_panel_action_without_panel_id():
    from app.ai_schemas import WorkspaceActionProposal

    with pytest.raises(ValueError, match="requires panel_id"):
        WorkspaceActionProposal(
            action_id="act_missing_panel",
            action_type="focus_panel",
            payload={},
            rationale="Focus a panel.",
        )


def test_dispatch_attaches_deterministic_evidence_reference(monkeypatch):
    from app import llm_client

    def fake_query(**kwargs):
        return {
            "metric": kwargs["metric"],
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "aggregation": kwargs["aggregation"],
            "count": 2,
            "record_ids": ["takeout-1", "takeout-2"],
            "sources": ["takeout"],
        }

    monkeypatch.setitem(llm_client._TOOL_FUNCTIONS, "query_health_data", fake_query)
    tool_input = {
        "metric": "steps",
        "start_date": "2016-12-01",
        "end_date": "2016-12-02",
        "aggregation": "mean",
    }

    # Evidence is collected server-side rather than echoed back to the model: the
    # full reference (with every record id) would otherwise be resent on every
    # subsequent tool round and blow the context window.
    sink: list = []
    first = llm_client._dispatch_tool("query_health_data", tool_input, sink)
    second = llm_client._dispatch_tool("query_health_data", tool_input, sink)

    assert first["evidence_id"] == second["evidence_id"]
    assert "evidence_refs" not in first
    evidence = sink[0]
    assert evidence.evidence_id == first["evidence_id"]
    assert evidence.metric == "steps"
    assert evidence.record_ids == ["takeout-1", "takeout-2"]
    assert evidence.source == "takeout"


def test_raw_signal_tool_returns_bounded_provenance(monkeypatch):
    from app import llm_client
    import app.raw_signal_import as raw_signal_import

    monkeypatch.setattr(
        raw_signal_import,
        "query_raw_signals",
        lambda **kwargs: [
            {
                "id": 1,
                "record_fingerprint": "raw-1",
                "timestamp": "2016-12-01T10:00:00+00:00",
                "end_timestamp": "2016-12-01T10:01:00+00:00",
                "metric_name": "heart_rate",
                "signal_type": "heart_rate",
                "value_float": 62.0,
                "value_text": None,
                "value_json": None,
                "unit": "bpm",
                "source": "google_fit_takeout",
                "source_kind": "fit_json",
                "source_file": "raw.json",
            }
        ],
    )

    sink: list = []
    result = llm_client._dispatch_tool(
        "query_raw_health_signals",
        {
            "metric_name": "heart_rate",
            "start_date": "2016-12-01",
            "end_date": "2016-12-01",
            "limit": 10,
        },
        sink,
    )

    assert result["records"][0]["value"] == 62.0
    assert result["record_ids"] == ["raw-1"]
    assert sink[0].source == "google_fit_takeout"


def test_structured_analysis_filters_untrusted_evidence_ids():
    from app import llm_client
    from app.ai_schemas import EvidenceReference

    evidence = EvidenceReference(
        evidence_id="ev_real_123",
        metric="steps",
        start_date="2016-12-01",
        end_date="2016-12-02",
        aggregation="mean",
    ).model_dump(mode="json")
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": json.dumps({"evidence_refs": [evidence]}),
                }
            ],
        }
    ]
    reply = (
        "The trend is stable.\n"
        "<!-- BITFIT_ANALYSIS_JSON\n"
        '{"narrative":"The trend is stable.","observations":[{'
        '"statement":"Observed steps are stable.","evidence_ids":["ev_real_123",'
        '"ev_invented"]}],"hypotheses":[],"uncertainties":[],"workspace_actions":[]}'
        "\n-->"
    )

    clean, analysis, refs, actions = llm_client._structured_analysis(reply, messages)

    assert clean == "The trend is stable."
    assert [ref.evidence_id for ref in refs] == ["ev_real_123"]
    assert analysis.observations[0].evidence_ids == ["ev_real_123"]
    assert actions == []


def test_chat_keeps_legacy_reply_and_history_fields(monkeypatch):
    from app import llm_client

    monkeypatch.setattr(
        llm_client,
        "_run_agent",
        lambda messages, workspace_context=None, **kwargs: ("No matching data.", messages),
    )

    result = llm_client.chat("What happened?")

    assert result["reply"] == "No matching data."
    assert result["conversation_history"][-1] == {
        "role": "user",
        "content": "What happened?",
    }
    assert result["analysis"]["narrative"] == "No matching data."
    assert result["evidence_refs"] == []
    assert result["workspace_actions"] == []


def test_chat_route_serializes_additive_protocol_fields(monkeypatch):
    from app import llm_client
    from app.ai_schemas import EvidenceReference, WorkspaceActionProposal
    from app.routes.chat import ChatRequest, chat

    evidence = EvidenceReference(evidence_id="ev_route_1", metric="steps")
    proposal = WorkspaceActionProposal(
        action_id="act_route_1",
        action_type="set_date_range",
        payload={"range_days": 30},
        rationale="Keep the selected chart in view.",
    )
    monkeypatch.setattr(
        llm_client,
        "chat",
        lambda message, history: {
            "reply": "Done.",
            "conversation_history": [{"role": "user", "content": message}],
            "analysis": {
                "narrative": "Done.",
                "evidence_refs": [evidence.model_dump(mode="json")],
                "workspace_actions": [proposal.model_dump(mode="json")],
            },
            "evidence_refs": [evidence.model_dump(mode="json")],
            "workspace_actions": [proposal.model_dump(mode="json")],
        },
    )

    response = chat(ChatRequest(message="Show my chart."))

    assert response.reply == "Done."
    assert response.evidence_refs[0].evidence_id == "ev_route_1"
    assert response.workspace_actions[0].requires_approval is True


def test_tool_schema_exposes_read_and_proposal_tools():
    from app.llm_client import TOOL_SCHEMAS

    names = {schema["name"] for schema in TOOL_SCHEMAS}
    assert {
        "query_health_data",
        "get_daily_summary",
        "get_anomalies",
        "correlate_health_signals",
        "get_data_provenance",
        "propose_workspace_action",
    } <= names
    proposal_schema = next(
        schema for schema in TOOL_SCHEMAS if schema["name"] == "propose_workspace_action"
    )
    assert proposal_schema["input_schema"]["properties"]["action_type"]["enum"]


def test_research_drops_ungrounded_claims():
    """Claims citing evidence the server never minted must not survive."""
    from app.research import _analysis_from_tool_history, _plan_from_tool_history

    history = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "submit_analysis",
                    "input": {
                        "observations": [
                            {"statement": "Real claim.", "evidence_ids": ["ev_real"]},
                            {"statement": "Invented claim.", "evidence_ids": ["ev_fake"]},
                            {"statement": "Unsourced claim.", "evidence_ids": []},
                        ],
                        "uncertainties": [
                            {"statement": "Thin coverage.", "evidence_ids": ["ev_fake"]},
                        ],
                    },
                },
                {
                    "type": "tool_use",
                    "name": "propose_health_plan",
                    "input": {
                        "horizon": "weekly",
                        "summary": "Plan.",
                        "targets": [
                            {
                                "metric": "steps",
                                "direction": "increase",
                                "rationale": "Grounded.",
                                "evidence_ids": ["ev_real", "ev_fake"],
                            },
                            {
                                "metric": "hrv",
                                "direction": "increase",
                                "rationale": "Ungrounded.",
                                "evidence_ids": ["ev_fake"],
                            },
                        ],
                    },
                },
            ],
        }
    ]
    valid = {"ev_real"}

    analysis = _analysis_from_tool_history(history, valid)
    assert [o["statement"] for o in analysis["observations"]] == ["Real claim."]
    # Uncertainties are kept even unsourced — a caveat is not a data claim.
    assert len(analysis["uncertainties"]) == 1
    assert analysis["uncertainties"][0]["evidence_ids"] == []

    plan = _plan_from_tool_history(history, valid)
    assert [t.metric for t in plan.targets] == ["steps"]
    assert plan.targets[0].evidence_ids == ["ev_real"]


def test_model_projection_bounds_bulk_rows_but_keeps_the_count():
    """Claude must never receive thousands of rows: they are resent every round."""
    from app import llm_client

    result = {
        "metric": "heart_rate",
        "count": 5_000,
        "records": [{"value": float(i)} for i in range(5_000)],
        "record_ids": [f"r{i}" for i in range(5_000)],
    }
    projected = llm_client._model_projection(result)

    assert projected["count"] == 5_000
    assert len(projected["records"]) <= llm_client._MODEL_SAMPLE_ROWS
    assert len(projected["record_ids"]) == llm_client._MODEL_RECORD_IDS
    assert projected["records_total"] == 5_000
    assert projected["records_stats"]["min"] == 0.0
    assert projected["records_stats"]["max"] == 4_999.0


def test_daily_check_adherence_is_arithmetic_not_narrated():
    """Adherence is a numeric comparison; the model only narrates it."""
    from app.ai_schemas import PlanTarget
    from app.daily_check import _adherence

    targets = [
        PlanTarget(metric="steps", direction="increase", target_value=10_000, rationale="x"),
        PlanTarget(metric="resting_heart_rate", direction="decrease", target_value=63, rationale="x"),
        PlanTarget(metric="spo2", direction="increase", target_value=97, rationale="x"),
    ]
    observed = {
        "steps": {"value": 12_000.0},
        "resting_heart_rate": {"value": 70.0},
    }

    rows = {row.metric: row for row in _adherence(targets, observed)}

    assert rows["steps"].on_target is True
    assert rows["resting_heart_rate"].on_target is False
    assert rows["spo2"].on_target is None
    assert "No reading" in rows["spo2"].note
