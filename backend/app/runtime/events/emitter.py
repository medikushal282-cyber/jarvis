"""The ``emit`` everyone else calls.

Synchronous, thread-safe, and incapable of raising. Nikunj's brain, Lohith's
tools and Kushal's memory layer all receive one of these; none of them know
that an event bus, a queue or SSE exists.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.runtime.events.bus import bus

logger = logging.getLogger(__name__)


class RunEmitter:
    """An ``EventEmitter`` bound to one run (and optionally one node).

    ``event_bus`` defaults to the process-wide bus; tests inject their own so
    runs stay isolated from each other.
    """

    __slots__ = ("run_id", "node", "_bus", "_stream")

    def __init__(self, run_id: str, node: str = "", event_bus=None):
        self.run_id = run_id
        self.node = node
        self._bus = event_bus if event_bus is not None else bus
        self._stream = None

    def emit(self, event: str, data: Optional[dict] = None, *, node: str = "") -> None:
        try:
            if self._stream is None:
                self._stream = self._bus.stream(self.run_id)
            self._stream.publish(event, data, node=node or self.node)
        except Exception:  # noqa: BLE001 - telemetry must never break a run
            logger.exception("emit failed: run=%s event=%s", self.run_id, event)

    # Callable sugar: emit("tool_started", {...})
    __call__ = emit

    def scoped(self, node: str) -> "RunEmitter":
        return RunEmitter(self.run_id, node, self._bus)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RunEmitter run={self.run_id} node={self.node or '-'}>"


def get_emitter(run_id: str, node: str = "", event_bus=None) -> RunEmitter:
    return RunEmitter(run_id, node, event_bus)


def emit_sync(run_id: str, event: str, data: Optional[dict] = None, *, node: str = "") -> None:
    """One-shot emit without holding an emitter."""
    RunEmitter(run_id).emit(event, data, node=node)


class NullEmitter:
    """Drops everything. For tests and for code paths with no run context."""

    __slots__ = ("events",)

    def __init__(self) -> None:
        self.events: list = []

    def emit(self, event: str, data: Optional[dict] = None, *, node: str = "") -> None:
        self.events.append({"event": event, "data": data or {}, "node": node})

    __call__ = emit

    def scoped(self, node: str) -> "NullEmitter":
        return self


__all__ = ["RunEmitter", "NullEmitter", "get_emitter", "emit_sync"]
