"""One-way projection from our event envelope onto the team's existing SSE consumer.

The team's frontend already consumes a `{"event","run_id","node","ts","data"}` envelope and its
graph panel keys on node names. Rather than weaken our schema to match, this module projects:
:func:`to_legacy_envelope` maps a :class:`~brain.contracts.BrainEvent` onto that shape, so the
existing UI can render our trace unchanged.

This is a **presentation adapter, not a second source of truth.** Our schema in
`docs/brain/schemas/event.schema.json` stays canonical; a field that exists only here is a bug, and
the reverse mapping deliberately does not exist because it would lose `seq`, `event_id` and the
causal ordering that `since_seq` reconnect depends on.
"""

from __future__ import annotations

from typing import Any

from brain.contracts import BrainEvent, State

#: Loop state -> the node name the existing graph panel lights up. Several of our states map to one
#: coarse node, because their panel predates our finer states and inventing names it does not know
#: would simply leave the panel dark.
_STATE_TO_NODE: dict[str, str] = {
    "RECALL": "researcher",
    "UNDERSTAND": "orchestrator",
    "PLAN": "orchestrator",
    "SELECT": "orchestrator",
    "CALL": "executor",
    "OBSERVE": "executor",
    "DECIDE": "validator",
    "RECOVER": "recovery",
    "FINISH": "orchestrator",
    "RETAIN": "orchestrator",
}

#: Our event type -> the event name their consumer already handles. Anything unmapped passes through
#: under a namespaced name, so an unknown type is visibly ours rather than mislabelled as theirs.
_TYPE_ALIASES: dict[str, str] = {
    "run.started": "run_started",
    "run.finished": "run_completed",
    "plan.created": "plan_created",
    "plan.revised": "plan_revised",
    "tool.called": "tool_call",
    "tool.result": "tool_result",
    "tool.failed": "tool_error",
    "error.raised": "run_error",
    "approval.requested": "approval_required",
}


def legacy_node_for(state: State | None, event_type: str) -> str:
    """The node name the existing UI expects for this event."""
    if state is not None:
        node = _STATE_TO_NODE.get(str(state))
        if node:
            return node
    if event_type.startswith("tool."):
        return "executor"
    return "orchestrator"


def to_legacy_envelope(event: BrainEvent) -> dict[str, Any]:
    """Project one event into the existing consumer's envelope shape."""
    return {
        "event": _TYPE_ALIASES.get(event.type, f"brain.{event.type}"),
        "run_id": event.run_id,
        "node": legacy_node_for(event.state, event.type),
        "ts": event.ts.isoformat().replace("+00:00", "Z"),
        # `seq` and the original type ride inside `data` rather than being dropped, so our trace
        # stays reconstructable from their stream and a consumer can upgrade without a flag day.
        "data": {
            **event.data,
            "_brain": {
                "type": event.type,
                "seq": event.seq,
                "event_id": event.event_id,
                "schema_version": event.schema_version,
                "state": str(event.state) if event.state else None,
                "step_id": event.step_id,
            },
        },
    }
