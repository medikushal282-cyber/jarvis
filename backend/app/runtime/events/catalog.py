"""Canonical event names and their payload shapes.

Adding an event means adding it here. The SSE layer validates against this
catalog in dev and logs a warning (never rejects) otherwise -- an unknown
event still reaches the browser, because losing telemetry is worse than
carrying an undocumented name.

See ``docs/runtime/EVENTS.md``.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Set

# --- Run lifecycle ----------------------------------------------------------

RUN_STARTED = "run_started"
RUN_COMPLETED = "run_completed"
RUN_FAILED = "run_failed"
RUN_CANCELLED = "run_cancelled"

# --- Reasoning --------------------------------------------------------------

PLANNING = "planning"
PLAN_CREATED = "plan_created"
PLAN_UPDATED = "plan_updated"
AGENT_THINKING = "agent_thinking"
THOUGHT_GENERATED = "thought_generated"
STEP_STARTED = "step_started"
STEP_COMPLETED = "step_completed"
STEP_FAILED = "step_failed"
DECISION = "decision"

# --- Tools ------------------------------------------------------------------

TOOL_STARTED = "tool_started"
TOOL_PROGRESS = "tool_progress"
TOOL_COMPLETED = "tool_completed"
TOOL_FAILED = "tool_failed"
COMMAND_STARTED = "command_started"
COMMAND_OUTPUT = "command_output"
COMMAND_COMPLETED = "command_completed"
BROWSER_ACTION = "browser_action"

# --- Filesystem -------------------------------------------------------------

FILE_CREATED = "file_created"
FILE_UPDATED = "file_updated"
FILE_DELETED = "file_deleted"
FILE_READ = "file_read"

# --- Memory -----------------------------------------------------------------

MEMORY_RECALLED = "memory_recalled"
MEMORY_APPLIED = "memory_applied"
MEMORY_RECORDED = "memory_recorded"

# --- Verification and approval ---------------------------------------------

VERIFICATION_STARTED = "verification_started"
VERIFICATION_COMPLETED = "verification_completed"
APPROVAL_REQUESTED = "approval_requested"
APPROVAL_GRANTED = "approval_granted"
APPROVAL_REJECTED = "approval_rejected"

# --- Transport-only (runtime emits these, nobody else) ----------------------

STREAM_READY = "stream_ready"
HEARTBEAT = "heartbeat"
VOICE_TRANSCRIBED = "voice_transcribed"
VOICE_SPOKEN = "voice_spoken"

# --- Legacy -----------------------------------------------------------------
# Emitted by app/graph/. Kept working by the shim in app/events.py so the
# existing UI does not go dark. Removed once the frontend is migrated.

LEGACY_NODE_STARTED = "node_started"
LEGACY_NODE_COMPLETED = "node_completed"
LEGACY_CONTEXT_LOADED = "context_loaded"
LEGACY_OBSERVATION_CREATED = "observation_created"
LEGACY_RESEARCH_FINDING = "research_finding"
LEGACY_VALIDATION_RESULT = "validation_result"
LEGACY_CHAT_RESPONSE = "chat_response"
LEGACY_TOOL_CALL_STARTED = "tool_call_started"
LEGACY_TOOL_CALL_COMPLETED = "tool_call_completed"
LEGACY_BROWSER_OPENED = "browser_opened"
LEGACY_APPROVAL_REQUIRED = "approval_required"


TERMINAL_EVENTS: FrozenSet[str] = frozenset(
    {RUN_COMPLETED, RUN_FAILED, RUN_CANCELLED}
)

TRANSPORT_EVENTS: FrozenSet[str] = frozenset(
    {STREAM_READY, HEARTBEAT}
)

LEGACY_EVENTS: FrozenSet[str] = frozenset(
    {
        LEGACY_NODE_STARTED,
        LEGACY_NODE_COMPLETED,
        LEGACY_CONTEXT_LOADED,
        LEGACY_OBSERVATION_CREATED,
        LEGACY_RESEARCH_FINDING,
        LEGACY_VALIDATION_RESULT,
        LEGACY_CHAT_RESPONSE,
        LEGACY_TOOL_CALL_STARTED,
        LEGACY_TOOL_CALL_COMPLETED,
        LEGACY_BROWSER_OPENED,
        LEGACY_APPROVAL_REQUIRED,
    }
)

#: Required keys per event. Advisory -- used for dev-time warnings only.
PAYLOAD_KEYS: Dict[str, Set[str]] = {
    RUN_STARTED: {"objective"},
    RUN_COMPLETED: {"status"},
    RUN_FAILED: {"message"},
    RUN_CANCELLED: {"reason"},
    PLAN_CREATED: {"steps"},
    PLAN_UPDATED: {"steps"},
    AGENT_THINKING: {"summary"},
    STEP_STARTED: {"step_id"},
    STEP_COMPLETED: {"step_id"},
    STEP_FAILED: {"step_id"},
    TOOL_STARTED: {"tool"},
    TOOL_COMPLETED: {"tool"},
    TOOL_FAILED: {"tool"},
    COMMAND_STARTED: {"command"},
    COMMAND_COMPLETED: {"command", "exit_code"},
    BROWSER_ACTION: {"action"},
    FILE_CREATED: {"path"},
    FILE_UPDATED: {"path"},
    FILE_DELETED: {"path"},
    FILE_READ: {"path"},
    MEMORY_RECALLED: {"hits"},
    MEMORY_APPLIED: {"how"},
    MEMORY_RECORDED: {"experience_id"},
    VERIFICATION_COMPLETED: {"valid"},
    APPROVAL_REQUESTED: {"tool"},
    APPROVAL_GRANTED: {"request_id"},
    APPROVAL_REJECTED: {"request_id"},
    VOICE_TRANSCRIBED: {"text"},
}

KNOWN_EVENTS: FrozenSet[str] = frozenset(
    {
        RUN_STARTED, RUN_COMPLETED, RUN_FAILED, RUN_CANCELLED,
        PLANNING, PLAN_CREATED, PLAN_UPDATED, AGENT_THINKING,
        THOUGHT_GENERATED, STEP_STARTED, STEP_COMPLETED, STEP_FAILED, DECISION,
        TOOL_STARTED, TOOL_PROGRESS, TOOL_COMPLETED, TOOL_FAILED,
        COMMAND_STARTED, COMMAND_OUTPUT, COMMAND_COMPLETED, BROWSER_ACTION,
        FILE_CREATED, FILE_UPDATED, FILE_DELETED, FILE_READ,
        MEMORY_RECALLED, MEMORY_APPLIED, MEMORY_RECORDED,
        VERIFICATION_STARTED, VERIFICATION_COMPLETED,
        APPROVAL_REQUESTED, APPROVAL_GRANTED, APPROVAL_REJECTED,
        STREAM_READY, HEARTBEAT, VOICE_TRANSCRIBED, VOICE_SPOKEN,
    }
    | LEGACY_EVENTS
)

#: Legacy name -> canonical name, applied by the shim.
LEGACY_ALIASES: Dict[str, str] = {
    LEGACY_APPROVAL_REQUIRED: APPROVAL_REQUESTED,
}


def canonical(event: str) -> str:
    """Map a legacy event name onto its replacement, if there is one."""
    return LEGACY_ALIASES.get(event, event)


def is_terminal(event: str) -> bool:
    return canonical(event) in TERMINAL_EVENTS


def is_known(event: str) -> bool:
    return canonical(event) in KNOWN_EVENTS


def missing_keys(event: str, data: dict) -> Set[str]:
    """Required payload keys absent from ``data``. Advisory only."""
    required = PAYLOAD_KEYS.get(canonical(event))
    if not required:
        return set()
    return required - set(data or {})
