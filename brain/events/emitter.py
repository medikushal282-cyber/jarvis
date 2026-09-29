"""The event emitter: assigns sequence numbers and hands events to a sink.

Two ordering guarantees, both of which the trace's usefulness depends on:

1. **Causal order, not just timestamp order.** The event reaches the sink *before* the loop
   advances. A timestamp alone would not survive a frozen clock or a coarse clock resolution,
   and would leave a consumer guessing whether a state transition was recorded before or after
   the work it describes.
2. **Monotonic sequence.** ``seq`` starts at 0 and increments by exactly one per event, never
   reused. A consumer detects a dropped event by a gap rather than by a missing timestamp,
   which is what makes the SSE ``since_seq`` reconnect in the contracts implementable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from brain.contracts import EVENT_SCHEMA_VERSION, BrainEvent, Clock, EventSink, IdFactory, State
from brain.errors import BrainError, ContractError


class EventEmitter:
    """Builds, validates and dispatches run events."""

    def __init__(
        self,
        sink: EventSink,
        run_id: str,
        clock: Clock,
        ids: IdFactory,
        *,
        schema: dict[str, Any] | None = None,
        validate: bool = False,
        validator: Callable[[dict[str, Any], dict[str, Any]], list[str]] | None = None,
    ) -> None:
        self._sink = sink
        self._run_id = run_id
        self._clock = clock
        self._ids = ids
        self._schema = schema
        self._validate = validate
        self._validator = validator
        self._seq = 0
        self._events: list[BrainEvent] = []
        self.dropped = 0

    # ------------------------------------------------------------------ emitting

    def emit(
        self,
        type: str,
        data: dict[str, Any],
        *,
        state: State | None = None,
        step_id: str | None = None,
    ) -> BrainEvent:
        """Construct, validate, record and dispatch one event."""
        event = BrainEvent(
            schema_version=EVENT_SCHEMA_VERSION,
            event_id=self._ids.new("evt"),
            run_id=self._run_id,
            seq=self._seq,
            ts=self._clock.now(),
            type=type,
            data=data,
            state=state,
            step_id=step_id,
        )
        if self._validate:
            self._check(event)
        self._seq += 1
        self._events.append(event)
        self._dispatch(event)
        return event

    def emit_error(self, err: BrainError) -> BrainEvent:
        return self.emit("error.raised", err.to_event_data())

    # ------------------------------------------------------------------ access

    @property
    def events(self) -> tuple[BrainEvent, ...]:
        return tuple(self._events)

    @property
    def seq(self) -> int:
        """The sequence number the next event will receive."""
        return self._seq

    @property
    def run_id(self) -> str:
        return self._run_id

    # ------------------------------------------------------------------ internals

    def _check(self, event: BrainEvent) -> None:
        if self._schema is None or self._validator is None:
            return
        errors = self._validator(self._schema, event.to_dict())
        if errors:
            raise ContractError(
                f"event {event.type!r} does not satisfy the event schema: " + "; ".join(errors),
                details={"type": event.type, "errors": errors},
            )

    def _dispatch(self, event: BrainEvent) -> None:
        try:
            self._sink.emit(event)
        except Exception:
            # Contract: a sink must never kill a run. Count it and say so on the next event
            # that itself reports an error, so the failure is visible without being fatal.
            self.dropped += 1
