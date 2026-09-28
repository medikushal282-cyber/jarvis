"""Compatibility shim over the runtime event bus.

The ~100 ``await emit(...)`` call sites in ``app/graph/`` keep working
unchanged while the runtime rebuilds the transport underneath them. New code
should take an ``EventEmitter`` from ``app.runtime.events`` instead of
importing this module.

See docs/runtime/EVENTS.md section 3.
"""

from __future__ import annotations

import asyncio
import warnings
from typing import Optional

from app.runtime.events.bus import bus


async def emit(run_id: str, event_type: str, node: str = "", data: Optional[dict] = None) -> None:
    """Legacy async emit. Forwards to the runtime bus.

    Still a coroutine so existing ``await emit(...)`` call sites compile, but
    the publish itself is synchronous and non-blocking.
    """
    bus.publish(run_id, event_type, data, node=node)


def emit_nowait(run_id: str, event_type: str, node: str = "", data: Optional[dict] = None) -> None:
    """Sync variant, for code that cannot await."""
    bus.publish(run_id, event_type, data, node=node)


def get_queue(run_id: str) -> asyncio.Queue:
    """Deprecated. Returns a queue fed by a bus subscription.

    Kept so nothing breaks mid-migration; the SSE endpoint no longer uses it.
    Prefer ``bus.stream(run_id).subscribe(from_seq)``.
    """
    warnings.warn(
        "get_queue() is deprecated; use app.runtime.events.bus.stream(run_id).subscribe()",
        DeprecationWarning,
        stacklevel=2,
    )

    queue: asyncio.Queue = asyncio.Queue()
    stream = bus.stream(run_id)

    async def _pump() -> None:
        async for envelope in stream.subscribe(0):
            await queue.put(envelope)

    try:
        asyncio.get_running_loop().create_task(_pump())
    except RuntimeError:
        pass

    return queue


# Legacy attribute: some code inspected this dict directly.
event_bus = {}


__all__ = ["emit", "emit_nowait", "get_queue", "event_bus"]
