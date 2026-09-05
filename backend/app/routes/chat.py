"""Chat SSE route — streams pipeline trace stages to the frontend in real time.

* POST /api/chat/session          -> {"session_id": "..."}  (start a conversation)
* POST /api/chat/stream           -> text/event-stream       (ask a question)
    body: { "q": "<question>", "session_id": "<optional>" }

When a ``session_id`` is supplied, the last few turns are passed to the generator as follow-up
context (short-term memory), so "what about credits?" / "and per bank?" resolve against the prior
query. The completed turn is recorded back into the session. Session state is in-memory
(single-process demo) behind a swappable interface.

Each pipeline stage is emitted as its own SSE event (intake, sql_generation, static_validation,
plan_inspection, reviewer_verdict, execution, answer_composition, clarification, completion).
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.services.ops.session_manager import get_session_manager
from app.services.pipeline.pipeline_factory import build_pipeline

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/session")
async def create_session():
    """Start a conversation; returns a session_id the FE sends with each question."""
    return {"session_id": get_session_manager().create()}


class ChatRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=1000, description="The user's question")
    session_id: str | None = Field(default=None, description="Conversation id for follow-ups")


@router.post("/stream")
async def chat_stream(body: ChatRequest):
    """Stream the pipeline's trace stages as SSE, with optional session follow-up context."""
    sessions = get_session_manager()
    history = sessions.history(body.session_id) if body.session_id else []
    pipeline, pool = build_pipeline()

    async def event_generator():
        final: dict | None = None
        try:
            async for evt in pipeline.run_stream(body.q, history=history):
                if evt["event"] == "completion":
                    final = evt["data"]
                yield {"event": evt["event"], "data": json.dumps(evt["data"], default=str)}
        finally:
            pool.close()
            # Record the turn for follow-up memory (only when a session was supplied).
            if body.session_id and final is not None:
                sessions.record_turn(
                    body.session_id,
                    question=body.q,
                    resolved_sql=final.get("resolved_sql"),
                    answer=final.get("answer_text"),
                    outcome=final.get("outcome", "unknown"),
                )

    return EventSourceResponse(event_generator())
