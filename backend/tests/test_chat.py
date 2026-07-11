"""Tests for the chat Q&A route.

The route just threads a message + client-held history into
``app.llm_client.chat`` and returns the result — so these tests monkeypatch that
function (no real ``ANTHROPIC_API_KEY`` required) and confirm:

* a normal call returns the expected JSON shape, and
* an exception raised inside ``llm_client.chat`` becomes a clean 503 error
  response, not an unhandled 500 crash.

We build a minimal FastAPI app that includes ONLY the chat router and drive it
with ``fastapi.testclient.TestClient``. If that client is unusable in this env
(the installed httpx is newer than the bundled starlette TestClient expects — see
test_sync.py), we fall back to exercising the route handler directly, which still
covers the same graceful-error path.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

# app.auth (imported transitively) needs an encryption key at import time.
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())


def _make_app():
    from fastapi import FastAPI

    from app.routes import chat as chat_routes

    app = FastAPI()
    app.include_router(chat_routes.router)
    return app


def test_chat_normal_call_returns_expected_shape(monkeypatch):
    from app import llm_client

    def fake_chat(message, conversation_history=None):
        assert message == "How did I sleep last week?"
        return {
            "reply": "You slept well.",
            "conversation_history": [
                {"role": "user", "content": message},
                {"role": "assistant", "content": [{"type": "text", "text": "You slept well."}]},
            ],
        }

    monkeypatch.setattr(llm_client, "chat", fake_chat)

    try:
        from fastapi.testclient import TestClient

        client = TestClient(_make_app())
        res = client.post(
            "/chat", json={"message": "How did I sleep last week?", "conversation_history": None}
        )
        assert res.status_code == 200
        body = res.json()
    except TypeError:
        # httpx/starlette TestClient mismatch in this env — call the handler directly.
        from app.routes.chat import ChatRequest, chat

        body = chat(ChatRequest(message="How did I sleep last week?")).model_dump()

    assert body["reply"] == "You slept well."
    assert isinstance(body["conversation_history"], list)
    assert len(body["conversation_history"]) == 2


def test_chat_exception_becomes_clean_503(monkeypatch):
    from app import llm_client

    def boom(message, conversation_history=None):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(llm_client, "chat", boom)

    try:
        from fastapi.testclient import TestClient

        client = TestClient(_make_app(), raise_server_exceptions=False)
        res = client.post("/chat", json={"message": "hi", "conversation_history": None})
        assert res.status_code == 503
        detail = res.json()["detail"]
    except TypeError:
        # Fall back to the handler directly; assert it raises a 503 HTTPException.
        from fastapi import HTTPException
        import pytest

        from app.routes.chat import ChatRequest, chat

        with pytest.raises(HTTPException) as excinfo:
            chat(ChatRequest(message="hi"))
        assert excinfo.value.status_code == 503
        detail = excinfo.value.detail

    assert "unavailable" in detail.lower()
    assert "ANTHROPIC_API_KEY" in detail
