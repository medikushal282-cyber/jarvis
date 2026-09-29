"""Server-Sent Events framing.

The detail that matters: ``id:`` carries the event ``seq``, so a browser
reconnect sends ``Last-Event-ID`` and the stream resumes with no gap and no
duplicates. That single line is what stops "refresh during a run" from being a
bug.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.runtime.events import catalog
from app.runtime.events.bus import RunStream, bus

logger = logging.getLogger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # stop nginx buffering the stream
}


def frame(envelope: dict) -> str:
    """Render one event as an SSE frame."""
    seq = envelope.get("seq", 0)
    body = json.dumps(envelope, default=str)
    if seq:
        return f"id: {seq}\ndata: {body}\n\n"
    return f"data: {body}\n\n"


def resolve_from_seq(request: Request, explicit: Optional[int] = None) -> int:
    """Where to resume: explicit ``?from_seq=`` wins, else ``Last-Event-ID``."""
    if explicit is not None and explicit >= 0:
        return explicit
    raw = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
    if raw:
        try:
            return max(0, int(raw.strip()))
        except ValueError:
            pass
    return 0


async def stream_run(
    request: Request,
    run_id: str,
    from_seq: int = 0,
    *,
    close_on_terminal: bool = True,
) -> AsyncIterator[str]:
    """Yield SSE frames for one run until it ends or the client disconnects."""
    stream: RunStream = bus.stream(run_id)
    try:
        async for envelope in stream.subscribe(from_seq):
            if await request.is_disconnected():
                break
            yield frame(envelope)
            if close_on_terminal and catalog.is_terminal(envelope.get("event", "")):
                break
    except asyncio.CancelledError:  # client went away mid-flight
        raise
    except Exception:  # noqa: BLE001
        logger.exception("SSE stream failed for run %s", run_id)
        yield frame(
            {
                "seq": 0,
                "event": catalog.RUN_FAILED,
                "run_id": run_id,
                "node": "runtime",
                "data": {"message": "event stream error", "error_type": "StreamError"},
            }
        )


def sse_response(generator: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        generator, media_type="text/event-stream", headers=SSE_HEADERS
    )


__all__ = ["frame", "resolve_from_seq", "stream_run", "sse_response", "SSE_HEADERS"]
