"""Typed contracts shared by the health-data agent and the workspace UI.

The chat endpoint predates the visual workspace and returns a plain-text reply
plus an opaque Anthropic conversation history.  These models are the additive
protocol used by newer clients: every data-backed claim can point to an
``EvidenceReference`` and any visual change is represented as a reversible,
approval-gated ``WorkspaceActionProposal``.  Nothing in this module performs a
workspace mutation.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _ProtocolModel(BaseModel):
    """Base model for tolerant wire contracts.

    AI output is untrusted input.  Ignoring unknown fields lets the protocol
    evolve without making a response fail validation, while the fields we do
    expose remain strictly typed.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class EvidencePoint(_ProtocolModel):
    """A bounded point shown or referenced by an analysis."""

    date: dt.date | None = None
    timestamp: dt.datetime | None = None
    value: float | None = None
    unit: str | None = None
    record_id: str | None = None


class EvidenceReference(_ProtocolModel):
    """Stable reference to a query result and its source records.

    ``evidence_id`` is deterministic for a tool call, so the frontend can use
    it to highlight the same evidence even when a chat response is replayed.
    ``query`` contains only the bounded query parameters, never credentials or
    raw files.
    """

    evidence_id: str = Field(min_length=3, max_length=128)
    metric: str | None = Field(default=None, min_length=1, max_length=128)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    aggregation: Literal["mean", "min", "max", "raw", "correlation", "provenance"] | None = None
    panel_id: str | None = Field(default=None, min_length=1, max_length=128)
    source: str | None = Field(default=None, max_length=128)
    record_ids: list[str] = Field(default_factory=list, max_length=2_000)
    point_count: int | None = Field(default=None, ge=0)
    query: dict[str, Any] = Field(default_factory=dict)


class AnalysisObservation(_ProtocolModel):
    """A measured or computed statement supported by evidence."""

    statement: str = Field(min_length=1, max_length=4_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)


class AnalysisHypothesis(_ProtocolModel):
    """A clearly-labelled interpretation, never a medical diagnosis."""

    statement: str = Field(min_length=1, max_length=4_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    confidence: Literal["low", "medium", "high"] = "low"


class AnalysisUncertainty(_ProtocolModel):
    """A data-quality or interpretation limitation attached to an answer."""

    statement: str = Field(min_length=1, max_length=4_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)


class WorkspaceActionType(str, Enum):
    """Actions an agent may propose for the visual workspace."""

    FOCUS_PANEL = "focus_panel"
    SET_DATE_RANGE = "set_date_range"
    ADD_CHART = "add_chart"
    REMOVE_CHART = "remove_chart"
    ADD_OVERLAY = "add_overlay"
    ANNOTATE = "annotate"
    PROPOSE_LAYOUT_PATCH = "propose_layout_patch"
    SAVE_ANALYSIS = "save_analysis"


class WorkspacePatchOperation(_ProtocolModel):
    """One JSON-patch-like, reversible workspace operation."""

    op: Literal["add", "remove", "replace", "focus", "annotate", "overlay", "set_range"]
    path: str = Field(pattern=r"^/[A-Za-z0-9_./:-]{1,255}$")
    value: Any = None


class WorkspacePatch(_ProtocolModel):
    """A proposed workspace version change; it is not persisted by the agent."""

    operations: list[WorkspacePatchOperation] = Field(default_factory=list, max_length=32)
    base_version: str | None = Field(default=None, max_length=128)
    summary: str | None = Field(default=None, max_length=1_000)


class ChartSpec(_ProtocolModel):
    """Minimal chart description used in an ``add_chart`` proposal."""

    panel_id: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=128)
    chart_type: Literal["line", "area", "bar", "scatter", "heatmap", "sleep_timeline", "table"] = "line"
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    aggregation: Literal["mean", "min", "max", "raw"] = "raw"
    overlays: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def date_order(self) -> "ChartSpec":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class WorkspaceActionProposal(_ProtocolModel):
    """A reversible action that always requires explicit user approval."""

    action_id: str = Field(min_length=3, max_length=128)
    action_type: WorkspaceActionType
    panel_id: str | None = Field(default=None, min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(default="", max_length=2_000)
    status: Literal["proposed", "approved", "rejected"] = "proposed"
    requires_approval: Literal[True] = True
    reversible: Literal[True] = True

    @model_validator(mode="after")
    def validate_action_payload(self) -> "WorkspaceActionProposal":
        # The agent can only suggest actions.  API routes may later create a
        # separate approved event, but an AI response cannot mark itself done.
        if self.status != "proposed":
            raise ValueError("AI workspace actions must remain proposed until approved")
        if self.action_type in {
            WorkspaceActionType.FOCUS_PANEL,
            WorkspaceActionType.REMOVE_CHART,
            WorkspaceActionType.ADD_OVERLAY,
            WorkspaceActionType.ANNOTATE,
        } and not self.panel_id:
            raise ValueError(f"{self.action_type.value} requires panel_id")
        if self.action_type == WorkspaceActionType.ADD_CHART:
            # Validate the nested chart when supplied, but keep payload open for
            # forward-compatible chart options.
            if "chart" in self.payload:
                ChartSpec.model_validate(self.payload["chart"])
        if self.action_type == WorkspaceActionType.PROPOSE_LAYOUT_PATCH:
            if "patch" in self.payload:
                WorkspacePatch.model_validate(self.payload["patch"])
        return self


class WorkspaceContext(_ProtocolModel):
    """The bounded visible context sent with a chat turn."""

    active_panel_id: str | None = Field(default=None, max_length=128)
    visible_panel_ids: list[str] = Field(default_factory=list, max_length=64)
    workspace_version: str | None = Field(default=None, max_length=128)
    start_date: dt.date | None = None
    end_date: dt.date | None = None

    @model_validator(mode="after")
    def date_order(self) -> "WorkspaceContext":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class StructuredAnalysis(_ProtocolModel):
    """Structured companion to the legacy plain-text chat reply."""

    narrative: str = Field(min_length=1, max_length=16_000)
    observations: list[AnalysisObservation] = Field(default_factory=list, max_length=64)
    hypotheses: list[AnalysisHypothesis] = Field(default_factory=list, max_length=32)
    uncertainties: list[AnalysisUncertainty] = Field(default_factory=list, max_length=32)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list, max_length=128)
    workspace_actions: list[WorkspaceActionProposal] = Field(default_factory=list, max_length=32)


class ChatResult(_ProtocolModel):
    """Wire response returned by :func:`app.llm_client.chat`."""

    reply: str
    conversation_history: list[dict[str, Any]]
    analysis: StructuredAnalysis | None = None
    evidence_refs: list[EvidenceReference] = Field(default_factory=list, max_length=128)
    workspace_actions: list[WorkspaceActionProposal] = Field(default_factory=list, max_length=32)


__all__ = [
    "AnalysisHypothesis",
    "AnalysisObservation",
    "AnalysisUncertainty",
    "ChartSpec",
    "ChatResult",
    "EvidencePoint",
    "EvidenceReference",
    "StructuredAnalysis",
    "WorkspaceActionProposal",
    "WorkspaceActionType",
    "WorkspaceContext",
    "WorkspacePatch",
    "WorkspacePatchOperation",
]
