"""Chat SSE route — streams pipeline trace stages to the frontend in real time.

GET/POST /api/chat/stream?q=...  ->  text/event-stream

Each pipeline stage is emitted as its own SSE event (intake, sql_generation, static_validation,
reviewer_verdict, execution, answer_composition, clarification, completion), so the FE can render
the assistant "thinking" live and drive intermediate/filler speech at stage boundaries. The final
``completion`` event carries the full answer payload (answer text, chart, breakdown, SQL, verdict).

Uses Strands agents under the hood via the pipeline; the per-stage generator is
``SimplePipeline.run_stream()``.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.services.pipeline.pipeline_factory import build_pipeline

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=1000, description="The user's question")


@router.post("/stream")
async def chat_stream(body: ChatRequest):
    """Stream the pipeline's trace stages for the question as Server-Sent Events.

    POST (not GET): the question goes in the JSON body, so long/special-character questions are
    clean and not exposed in URLs or caches. The FE consumes the SSE stream via a fetch() reader
    (e.g. @microsoft/fetch-event-source), since the native EventSource API is GET-only.
    """
    pipeline, pool = build_pipeline()

    async def event_generator():
        try:
            async for evt in pipeline.run_stream(body.q):
                yield {"event": evt["event"], "data": json.dumps(evt["data"], default=str)}
        finally:
            pool.close()

    return EventSourceResponse(event_generator())
