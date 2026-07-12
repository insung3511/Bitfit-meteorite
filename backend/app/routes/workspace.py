"""Authenticated, versioned dashboard workspace endpoints."""

from __future__ import annotations

import datetime as dt
import json
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import engine, init_db
from app.models import WorkspaceVersion

router = APIRouter(prefix="/workspace", tags=["workspace"])


class WorkspacePanel(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    metric: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    chart_type: str = Field(default="area", pattern="^(area|line|bar)$")
    range_days: int = Field(default=30, ge=1, le=3650)
    show_baseline: bool = True
    color: str = Field(default="var(--series-1)", max_length=80)


class WorkspaceVersionRequest(BaseModel):
    label: str = Field(default="Workspace revision", min_length=1, max_length=120)
    panels: list[WorkspacePanel] = Field(min_length=1, max_length=32)


def _serialize(version: WorkspaceVersion) -> dict[str, Any]:
    document = json.loads(version.document_json)
    return {
        "id": version.id,
        "label": version.label,
        "created_at": version.created_at.isoformat(),
        "parent_id": version.parent_id,
        "panels": document["panels"],
    }


def _latest(session: Session) -> WorkspaceVersion | None:
    return session.exec(
        select(WorkspaceVersion).order_by(WorkspaceVersion.created_at.desc())
    ).first()


@router.get("")
def get_workspace() -> dict[str, Any]:
    """Return the current workspace and its recent reversible history."""
    init_db()
    with Session(engine) as session:
        versions = session.exec(
            select(WorkspaceVersion).order_by(WorkspaceVersion.created_at.desc()).limit(13)
        ).all()
        if not versions:
            return {"active": None, "history": []}
        return {
            "active": _serialize(versions[0]),
            "history": [_serialize(version) for version in versions[1:]],
        }


@router.post("/versions", status_code=201)
def create_workspace_version(request: WorkspaceVersionRequest) -> dict[str, Any]:
    """Persist an approved workspace revision; callers must explicitly approve it."""
    init_db()
    with Session(engine) as session:
        parent = _latest(session)
        version = WorkspaceVersion(
            id=f"version-{time.time_ns()}-{secrets.token_hex(3)}",
            label=request.label,
            document_json=json.dumps(
                {"panels": [panel.model_dump() for panel in request.panels]},
                separators=(",", ":"),
            ),
            parent_id=parent.id if parent else None,
        )
        session.add(version)
        session.commit()
        session.refresh(version)
        return _serialize(version)


@router.post("/restore/{version_id}", status_code=201)
def restore_workspace_version(version_id: str) -> dict[str, Any]:
    """Create a new revision from an earlier one, preserving undo history."""
    init_db()
    with Session(engine) as session:
        source = session.get(WorkspaceVersion, version_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Workspace version not found.")
        parent = _latest(session)
        source_doc = json.loads(source.document_json)
        restored = WorkspaceVersion(
            id=f"version-{time.time_ns()}-{secrets.token_hex(3)}",
            label=f"Restored: {source.label}",
            document_json=json.dumps(source_doc, separators=(",", ":")),
            parent_id=parent.id if parent else None,
        )
        session.add(restored)
        session.commit()
        session.refresh(restored)
        return _serialize(restored)
