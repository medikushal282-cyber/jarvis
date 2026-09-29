"""Event sinks. A sink is the boundary between the loop and whoever is watching.

The contract (see :class:`brain.contracts.EventSink`) is that a sink must not raise on a
healthy path and must not block the loop beyond the run budget. The reason is asymmetric
cost: a trace is *diagnostic*, while a run is *the work*. A broken websocket or a full disk
must not destroy a run that was otherwise going to succeed, so every sink here swallows its
own failures rather than propagating them -- and the emitter records the failure so it is
still visible rather than silently lost.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TextIO

from brain.contracts import BrainEvent

__all__ = ["MemorySink", "JsonlSink", "StdoutSink", "MultiSink"]


class MemorySink:
    """Collects events in memory. Used by tests, the benchmark, and trace rendering.

    The replay API (:meth:`since`, :meth:`tail`) exists because a consumer that reconnects
    must be able to resume from a sequence number rather than replaying a whole run -- which
    is exactly what the HTTP surface in the contracts promises for SSE.
    """

    def __init__(self) -> None:
        self._events: list[BrainEvent] = []
        #: Set when an emit failed, so a caller can surface it instead of losing it.
        self.dropped: int = 0

    def emit(self, event: BrainEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> tuple[BrainEvent, ...]:
        return tuple(self._events)

    def since(self, seq: int) -> list[BrainEvent]:
        """Events with ``seq`` strictly greater than ``seq``, in order."""
        return [e for e in self._events if e.seq > seq]

    def tail(self, n: int) -> list[BrainEvent]:
        return self._events[-n:] if n > 0 else []

    def of_type(self, *types: str) -> list[BrainEvent]:
        wanted = set(types)
        return [e for e in self._events if e.type in wanted]

    def __iter__(self) -> Iterator[BrainEvent]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)


class JsonlSink:
    """Appends one JSON object per line. This is what an SSE relay tails.

    JSONL rather than a single JSON array so that a reader can tail the file while it is being
    written and a truncated final line is recoverable rather than corrupting the whole file.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.dropped = 0
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            # A sink that cannot create its directory is degraded, not fatal; emit() will
            # record the drops.
            self.dropped += 1

    def emit(self, event: BrainEvent) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(event.to_json())
                fh.write("\n")
        except OSError:
            self.dropped += 1


class StdoutSink:
    """Prints events for a human watching a terminal run.

    Deliberately compact and single-line: this is for live debugging, and a multi-line dump
    per event makes a running trace unreadable. ``compact=False`` prints the full payload.
    """

    def __init__(self, stream: TextIO | None = None, *, compact: bool = True) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self.compact = compact
        self.dropped = 0

    def emit(self, event: BrainEvent) -> None:
        try:
            if self.compact:
                state = f"{str(event.state):<9}" if event.state else " " * 9
                self.stream.write(f"{event.seq:>4} {state} {event.type}\n")
            else:
                self.stream.write(json.dumps(event.to_dict(), indent=2, default=str) + "\n")
            self.stream.flush()
        except (OSError, ValueError):
            self.dropped += 1


class MultiSink:
    """Fan-out. One failing child never prevents the others from receiving the event."""

    def __init__(self, *sinks: Any) -> None:
        self.sinks = sinks
        self.dropped = 0

    def emit(self, event: BrainEvent) -> None:
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception:
                # A sink is never allowed to break a run. Swallow and count; the emitter
                # surfaces the count on the next error.raised.
                self.dropped += 1


def build(settings: dict[str, Any], *, root: Path | None = None, impl: str | None = None) -> Any:
    """Factory for the 'events' provider.

    ``impl`` (from config or the registry override) selects the sink:
    * ``memory`` (default) -- in-process, for tests and the trace viewer.
    * ``stdout`` -- compact live debugging; ``compact=false`` for the full payload.
    * ``jsonl`` -- appends to a file; ``sink_path`` in settings gives the path.
    * ``multi`` -- fan-out; names the children via ``sinks`` (a list of impl names).
    """
    chosen = impl or str(settings.get("impl", "memory"))
    if chosen == "stdout":
        return StdoutSink(compact=bool(settings.get("compact", True)))
    if chosen == "jsonl":
        from pathlib import Path as _Path
        sink_path = settings.get("sink_path", ".brain/state/events.jsonl")
        resolved = (_Path(root) / str(sink_path)) if root else _Path(str(sink_path))
        return JsonlSink(resolved)
    # Default: memory sink.
    return MemorySink()

