import importlib

import pytest


@pytest.fixture()
def workspace_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workspace.db'}")
    import app.db as db

    importlib.reload(db)
    from app.routes import workspace as workspace_routes
    yield workspace_routes
    importlib.reload(db)


def _panels():
    return [
        {
            "id": "panel-steps",
            "metric": "steps",
            "title": "Steps",
            "chart_type": "area",
            "range_days": 30,
            "show_baseline": True,
            "color": "var(--series-1)",
        }
    ]


def test_workspace_version_and_restore(workspace_client):
    assert workspace_client.get_workspace() == {
        "active": None,
        "history": [],
    }

    created = workspace_client.create_workspace_version(
        workspace_client.WorkspaceVersionRequest(label="Overview", panels=_panels())
    )
    version = created
    assert version["panels"][0]["metric"] == "steps"

    changed = _panels()
    changed[0]["metric"] = "sleep_minutes"
    workspace_client.create_workspace_version(
        workspace_client.WorkspaceVersionRequest(label="Sleep focus", panels=changed)
    )
    restored = workspace_client.restore_workspace_version(version["id"])
    assert restored["panels"][0]["metric"] == "steps"
    current = workspace_client.get_workspace()
    assert current["active"]["panels"][0]["metric"] == "steps"
    assert len(current["history"]) == 2


def test_workspace_rejects_invalid_panel(workspace_client):
    with pytest.raises(Exception):
        workspace_client.create_workspace_version(
            workspace_client.WorkspaceVersionRequest(
                label="Bad",
                panels=[
                    {
                        "id": "x",
                        "metric": "steps",
                        "title": "x",
                        "chart_type": "scatter",
                    }
                ],
            )
        )
