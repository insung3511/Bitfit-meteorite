"""Conversational Q&A route over the user's health data.

``POST /chat`` threads a user message plus the client-held conversation history
into :func:`app.llm_client.chat`, which runs the full Claude tool-use loop (real
SQL queries against the local health DB) and returns a grounded reply.

Conversation history is entirely client-held: this is a single-user personal app,
so there is no server-side session store. The frontend sends the full history back
on every request and this route just passes it through to ``llm_client.chat``.

The LLM call is slow (an API round-trip, possibly several tool round-trips) and can
fail — most commonly when ``ANTHROPIC_API_KEY`` is unset or the Anthropic API
errors. Those failures are caught and returned as a clean 503 with a JSON detail
message so the frontend can show a friendly error instead of an unhandled 500.
"""

from __future__ import annotations

import logging
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import llm_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """Incoming chat turn: the new message plus prior client-held history."""

    message: str
    conversation_history: Optional[list[dict[str, Any]]] = None


_MAX_HISTORY_MESSAGES = 24
_MAX_HISTORY_BYTES = 64_000


class ChatResponse(BaseModel):
    """The assistant reply plus the updated history to send back next turn."""

    reply: str
    conversation_history: list[dict[str, Any]]


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Answer one question over the user's health data via the tool-use loop."""
    if not request.message.strip() or len(request.message) > 8_000:
        raise HTTPException(status_code=422, detail="Message must be 1-8000 characters.")
    history = request.conversation_history or []
    if len(history) > _MAX_HISTORY_MESSAGES:
        raise HTTPException(status_code=422, detail="Conversation history is too long.")
    try:
        history_size = len(json.dumps(history, separators=(",", ":")).encode())
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Conversation history must be JSON data.") from exc
    if history_size > _MAX_HISTORY_BYTES:
        raise HTTPException(status_code=422, detail="Conversation history is too large.")
    try:
        result = llm_client.chat(request.message, history)
    except Exception as exc:  # LLM/config/network failure — keep it friendly.
        # The raw exception (e.g. an Anthropic 401) can carry request IDs and
        # other internal detail — log it server-side, never return it verbatim.
        logger.exception("Chat request failed")
        raise HTTPException(
            status_code=503,
            detail="Chat is unavailable right now. Check that ANTHROPIC_API_KEY "
            "is configured correctly and try again.",
        ) from exc

    return ChatResponse(
        reply=result["reply"],
        conversation_history=result["conversation_history"],
    )
