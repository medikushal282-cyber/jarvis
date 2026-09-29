"""Cross-team interface contracts for the JARVIS runtime layer.

This module is the boundary between the runtime (sessions, events, results,
voice) and everything else. It holds types only -- no I/O, no side effects, no
imports from other ``app.*`` packages -- so any workstream can import it
without dragging the runtime in.

See ``docs/INTERFACES.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

# --- Runtime -> Brain -------------------------------------------------------

#: How much the user pre-authorised. "turbo" lets Lohit's permission engine
#: skip the interactive prompt for actions the user's configured permissions
#: already cover. It is a policy input to that engine, never a bypass: hard
#: restrictions stay enforced in both modes.
EXECUTION_NORMAL = "normal"
EXECUTION_TURBO = "turbo"
EXECUTION_MODES = frozenset({EXECUTION_NORMAL, EXECUTION_TURBO})


@dataclass
class RunRequest:
    """Everything the brain needs to execute one objective.

    Built by the runtime from the session, the user's utterance, and whatever
    context has accumulated. The brain treats it as read-only.
    """

    run_id: str
    session_id: str
    user_id: str
    workspace_id: str
    objective: str
    model: str = "openai/gpt-oss-120b"
    provider: str = "groq"
    input_mode: str = "text"  # "text" | "voice"
    execution_mode: str = EXECUTION_NORMAL  # "normal" | "turbo"
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    conversation: List[Dict[str, Any]] = field(default_factory=list)
    context_summary: str = ""
    workspace_root: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "objective": self.objective,
            "model": self.model,
            "provider": self.provider,
            "input_mode": self.input_mode,
            "execution_mode": self.execution_mode,
            "attachments": self.attachments,
            "conversation": self.conversation,
            "context_summary": self.context_summary,
            "workspace_root": self.workspace_root,
        }


@dataclass
class RunOutcome:
    """What the brain hands back when it is done.

    Deliberately thin. The timeline, artifacts and action summary are derived
    from the event stream, not from this object -- ``reply`` is only the
    sentence JARVIS says back to the user.
    """

    status: str = "completed"  # "completed" | "failed" | "rejected" | "cancelled"
    reply: str = ""
    error: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"


TERMINAL_STATUSES = frozenset({"completed", "failed", "rejected", "cancelled"})


@runtime_checkable
class EventEmitter(Protocol):
    """Fire-and-forget telemetry sink handed to the brain and to tools.

    Contract, enforced by the implementation in ``runtime.events.emitter``:

    * synchronous -- callable from a thread, a coroutine, or sync tool code
    * never raises -- a broken event pipe must never fail a run
    * never blocks -- a slow subscriber cannot stall the publisher
    """

    def __call__(self, event: str, data: Optional[dict] = None, *, node: str = "") -> None:
        ...

    def emit(self, event: str, data: Optional[dict] = None, *, node: str = "") -> None:
        ...

    def scoped(self, node: str) -> "EventEmitter":
        """Return an emitter that stamps ``node`` on everything it sends."""
        ...


@runtime_checkable
class AgentRunner(Protocol):
    """The agent brain, from the runtime's point of view.

    Implementations must emit ``run_started`` first and exactly one terminal
    event (``run_completed`` / ``run_failed``) last. The runtime arms a
    watchdog and synthesises the terminal event if one never arrives, so a
    crash still produces a usable run record.
    """

    async def run(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        ...


# --- Brain -> Tools ---------------------------------------------------------


@dataclass
class ToolContext:
    """Execution context passed down to a tool invocation."""

    run_id: str
    session_id: str
    user_id: str
    workspace_id: str
    workspace_root: str
    emit: Optional[EventEmitter] = None
    approved: bool = False
    timeout_s: int = 30
    permissions: List[str] = field(default_factory=list)
    #: Copied from RunRequest.execution_mode; read by the permission engine.
    execution_mode: str = EXECUTION_NORMAL

    def has_permission(self, permission: str) -> bool:
        if self.approved:
            return True
        if not self.permissions or "*" in self.permissions or "admin" in self.permissions:
            return True
        return permission in self.permissions


@dataclass
class ToolResult:
    """Standard tool return shape.

    ``artifacts`` lets the runtime's result builder pick up produced files
    without understanding what the tool does.
    """

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0


@runtime_checkable
class ToolExecutor(Protocol):
    def describe(self) -> List[Dict[str, Any]]:
        """Tool schemas in the shape the LLM tool-calling API expects."""
        ...

    async def execute(self, name: str, args: dict, ctx: ToolContext) -> ToolResult:
        ...


# --- Brain -> Memory --------------------------------------------------------


@runtime_checkable
class MemoryProvider(Protocol):
    async def recall(
        self,
        user_id: str,
        objective: str,
        *,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """``{"experiences": [...], "observations": [...],
        "user_knowledge": str, "project_knowledge": str}``"""
        ...

    async def record(
        self,
        user_id: str,
        run_id: str,
        objective: str,
        outcome: Dict[str, Any],
    ) -> str:
        """Persist what happened. Returns an experience id."""
        ...


__all__ = [
    "EXECUTION_NORMAL",
    "EXECUTION_TURBO",
    "EXECUTION_MODES",
    "RunRequest",
    "RunOutcome",
    "TERMINAL_STATUSES",
    "EventEmitter",
    "AgentRunner",
    "ToolContext",
    "ToolResult",
    "ToolExecutor",
    "MemoryProvider",
]
