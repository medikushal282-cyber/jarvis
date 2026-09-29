"""Frozen interfaces and shared data types for the agent brain.

This module is the boundary. Everything else in ``brain/`` is implementation; this file is
the contract that teammates code against, and it is versioned in
``docs/brain/CONTRACTS.md``. Two rules keep it honest:

1. **No logic lives here.** Only types, enums and Protocols. If you want to put a decision in
   this file, it belongs in the module that owns that decision.
2. **The external capabilities are Protocols, not base classes.** An implementer never
   imports or subclasses brain code; structural typing means a teammate's real adapter and
   our mock are the same kind of thing, so the mock is a first-class implementation rather
   than a test double.

Dependencies are stdlib only. This module must stay importable with nothing installed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from brain.errors import ErrorClass

CONTRACT_VERSION = "1.0.0"
EVENT_SCHEMA_VERSION = "1.0.0"


# ======================================================================================
# Enumerations
# ======================================================================================


class State(StrEnum):
    """The loop's states. The machine's legal transitions are declared in the state machine,
    not here; this enum only names the nodes."""

    RECALL = "RECALL"
    UNDERSTAND = "UNDERSTAND"
    PLAN = "PLAN"
    SELECT = "SELECT"
    CALL = "CALL"
    OBSERVE = "OBSERVE"
    DECIDE = "DECIDE"
    RECOVER = "RECOVER"
    FINISH = "FINISH"
    RETAIN = "RETAIN"


class PermissionTier(StrEnum):
    """A tool's declared authority, enforced before the call leaves the loop."""

    AUTO = "auto"
    CONFIRM = "confirm"
    DENY = "deny"


class SideEffects(StrEnum):
    """A tool's blast radius. ``DESTRUCTIVE`` may never be combined with ``AUTO``; the
    registry rejects that pairing rather than trusting reviewers to notice it."""

    NONE = "none"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


class MemoryKind(StrEnum):
    """The only five things worth remembering. Anything that is not one of these is run
    state, not memory -- see ``config/agents.md``."""

    OUTCOME = "outcome"
    FAILURE = "failure"
    CORRECTION = "correction"
    PREFERENCE = "preference"
    ENTITY_FACT = "entity_fact"


class Autonomy(StrEnum):
    """How much the run may do without asking. Set by the profile; the model cannot raise
    its own level."""

    SUPERVISED = "supervised"
    STANDARD = "standard"
    AUTONOMOUS = "autonomous"


class RunStatus(StrEnum):
    """Terminal status of a run."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    ESCALATED = "escalated"
    DENIED = "denied"
    FAILED = "failed"


class RecoveryStrategy(StrEnum):
    """Rungs of the recovery ladder, in order. The string values are the ladder positions
    the trace reports."""

    RETRY = "retry"
    REPAIR = "repair"
    SUBSTITUTE = "substitute"
    REPLAN = "replan"
    ESCALATE = "escalate"


#: Order matters: the ladder is walked down, not jumped around. ``ladder_position`` in a
#: ``recovery.started`` event is this index + 1.
RECOVERY_LADDER: tuple[RecoveryStrategy, ...] = (
    RecoveryStrategy.RETRY,
    RecoveryStrategy.REPAIR,
    RecoveryStrategy.SUBSTITUTE,
    RecoveryStrategy.REPLAN,
    RecoveryStrategy.ESCALATE,
)


class InfluenceBasis(StrEnum):
    """How a memory's influence on a step was established.

    This distinction is load-bearing for the demo. ``EXPLICIT_CITATION`` is the model naming
    the memory; the two overlap bases are deterministic fallbacks. A viewer must render them
    differently, because collapsing them would let the trace claim a stronger causal link
    than the evidence supports -- and an overstated memory claim is worse than none.
    """

    EXPLICIT_CITATION = "explicit_citation"
    ENTITY_OVERLAP = "entity_overlap"
    LEXICAL_OVERLAP = "lexical_overlap"


class FinishReason(StrEnum):
    """Why generation stopped. ``LENGTH`` must be treated as a failure, not as content: a
    truncated tool call parses as malformed and would otherwise be blamed on the model's
    formatting."""

    TOOL_CALLS = "tool_calls"
    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"


class StepStatus(StrEnum):
    """Lifecycle of a plan step."""

    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    SUPERSEDED = "superseded"


class ParseStrategy(StrEnum):
    """Rungs of the tool-call parsing ladder.

    ``NATIVE_TOOLS`` uses the provider's function calling. ``JSON_MODE`` drops the ``tools``
    parameter entirely and asks for a JSON object describing the call -- necessary because
    Groq does not permit structured outputs and tool use in the same request, so the fallback
    cannot be "the same call with response_format added". ``CONSTRAINED_TEXT`` is the last
    resort: a strict text grammar parsed locally.
    """

    NATIVE_TOOLS = "native_tools"
    JSON_MODE = "json_mode"
    CONSTRAINED_TEXT = "constrained_text"


# ======================================================================================
# Budgets and policy
# ======================================================================================


@dataclass(frozen=True, slots=True)
class Budgets:
    """Per-run limits. Evaluated in a fixed order -- steps, then tokens, then wall clock --
    so the "we must stop" decision is deterministic rather than emergent."""

    max_steps: int = 24
    max_tokens: int = 120_000
    max_wall_clock_s: int = 900
    max_tool_calls_per_step: int = 3
    max_consecutive_failures: int = 4

    def as_event_data(self) -> dict[str, int]:
        return {
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_wall_clock_s": self.max_wall_clock_s,
        }


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """A tool's declared retry behaviour.

    ``retry_on`` may only contain transient classes; the schema forbids ``validation``,
    because retrying a malformed call unchanged is the defect the recovery ladder exists to
    avoid.
    """

    max_attempts: int = 1
    backoff: str = "exponential"
    base_delay_s: float = 0.5
    jitter: bool = True
    retry_on: tuple[ErrorClass, ...] = ()

    def permits(self, error_class: ErrorClass) -> bool:
        return error_class in self.retry_on


# ======================================================================================
# Tools
# ======================================================================================


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool as declared in ``config/tools/*.yaml``.

    ``parameters`` is raw JSON Schema and is forwarded verbatim to the provider, so argument
    constraints are enforced by the same artifact the model reads. That is deliberate: prose
    guidance ("use a short window") is advisory, an ``enum`` is not.
    """

    name: str
    description: str
    provider: str
    method: str
    parameters: dict[str, Any]
    permission: PermissionTier
    timeout_s: float
    idempotent: bool
    side_effects: SideEffects
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    returns: str = ""
    redact: tuple[str, ...] = ()
    #: Which file it came from, for error messages and for the docs generator.
    source: str = ""

    def api_schema(self) -> dict[str, Any]:
        """The tool as the provider's function-calling API expects it."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @property
    def requires_confirmation(self) -> bool:
        return self.permission is PermissionTier.CONFIRM

    @property
    def is_denied(self) -> bool:
        return self.permission is PermissionTier.DENY


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Outcome of one tool invocation.

    Providers return ``ok=False`` with an ``error_class`` for expected failure rather than
    raising, so the recovery ladder can classify the failure without exception archaeology.
    Raising is reserved for programmer error.
    """

    ok: bool
    data: Any = None
    error_class: ErrorClass | None = None
    error_message: str = ""
    duration_ms: float = 0.0
    truncated: bool = False
    raw_bytes: int = 0

    @classmethod
    def success(cls, data: Any, *, duration_ms: float = 0.0, truncated: bool = False) -> ToolResult:
        return cls(ok=True, data=data, duration_ms=duration_ms, truncated=truncated)

    @classmethod
    def failure(
        cls,
        error_class: ErrorClass,
        message: str,
        *,
        duration_ms: float = 0.0,
    ) -> ToolResult:
        return cls(ok=False, error_class=error_class, error_message=message, duration_ms=duration_ms)


# ======================================================================================
# LLM
# ======================================================================================


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool call requested by the model.

    ``arguments_raw`` is part of the contract on purpose. Providers return arguments as a
    JSON *string*, and that string is frequently malformed -- fenced in markdown, truncated
    by a token limit, or wrapped in prose. A client that parses and discards the raw text
    makes repair impossible, so the raw text is preserved and ``parse_error`` records what
    went wrong while parsing it.
    """

    call_id: str
    name: str
    arguments_raw: str
    arguments: dict[str, Any] = field(default_factory=dict)
    parse_error: str | None = None

    @property
    def is_parsed(self) -> bool:
        return self.parse_error is None


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One provider-agnostic message.

    ``tool_calls`` is set on an assistant message that requested tools; ``tool_call_id`` on a
    tool message that answers one. Keeping both here rather than in provider-specific dicts
    is what lets the fake and the real client be interchangeable.
    """

    role: str
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None

    def to_api(self) -> dict[str, Any]:
        """Render for the OpenAI-compatible wire format."""
        msg: dict[str, Any] = {"role": self.role}
        if self.role == "tool":
            msg["content"] = self.content
            msg["tool_call_id"] = self.tool_call_id
            if self.name:
                msg["name"] = self.name
            return msg
        # An assistant turn that only requested tools carries null content on the wire.
        msg["content"] = self.content or None
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments_raw},
                }
                for tc in self.tool_calls
            ]
        return msg


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token accounting. ``total_tokens`` is used for the run budget; a client that cannot
    report real usage must set ``estimated=True`` so the trace does not present a guess as a
    measurement."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """One model call. Deliberately a plain description of the request rather than anything
    provider-shaped, so the fake client can honour it exactly."""

    messages: Sequence[ChatMessage]
    model: str = ""
    tools: Sequence[dict[str, Any]] = ()
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    temperature: float = 0.2
    max_tokens: int = 4096
    #: Providers disagree about whether they support this. The client decides what to send;
    #: the loop only needs to know that N tool calls may come back and must all be answered.
    parallel_tool_calls: bool = False
    #: Opt out of native tool calling entirely -- used by the JSON-mode rung of the parse
    #: ladder, which cannot send ``tools`` alongside a structured-output request.
    disable_native_tools: bool = False


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """One model reply."""

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: FinishReason = FinishReason.STOP
    model: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        """Whether the model asked for tools.

        Gated on ``finish_reason`` as well as on the presence of calls, because a response
        truncated at the token limit can contain a partially-formed call that must be treated
        as malformed rather than executed.
        """
        return bool(self.tool_calls) and self.finish_reason is FinishReason.TOOL_CALLS

    @property
    def was_truncated(self) -> bool:
        return self.finish_reason is FinishReason.LENGTH


# ======================================================================================
# Memory
# ======================================================================================


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """One remembered thing.

    ``id`` must be stable across recalls: ``memory.influenced`` points at it, so a provider
    that mints a fresh id per query silently breaks attribution and the trace will show an
    empty memory lane while memory is on.
    """

    id: str
    kind: MemoryKind
    text: str
    entities: tuple[str, ...] = ()
    confidence: float = 0.7
    observed_at: datetime | None = None
    source_run_id: str | None = None
    score: float | None = None

    def as_event_data(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": str(self.kind),
            "text": self.text,
            "confidence": self.confidence,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "source_run_id": self.source_run_id,
            "score": self.score,
        }

    def content_fingerprint(self) -> str:
        """Stable hash of what this memory says, used for deduplication.

        Computed over the normalised text and kind only -- not over ``id``, ``score`` or
        timestamps -- so that retaining the same lesson twice is detected as a duplicate
        rather than as two memories.
        """
        normalised = " ".join(self.text.lower().split())
        return hashlib.sha256(f"{self.kind}:{normalised}".encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class RecallQuery:
    """A recall question. A query, not a dump: the text is a real question, because a generic
    query returns generic memories."""

    text: str
    entities: tuple[str, ...] = ()
    kinds: tuple[MemoryKind, ...] = ()
    limit: int = 8


@dataclass(frozen=True, slots=True)
class SkippedRetention:
    """A memory the run considered and deliberately did not write, with the test that
    rejected it. Emitting this is what makes the retain policy auditable instead of a black
    box -- and it is half of what a judge means by "memory is central"."""

    candidate: str
    reason: str  # horizon_test | origin_test | duplicate | memory_disabled | low_confidence


@dataclass(frozen=True, slots=True)
class RetainResult:
    """What ``retain`` actually did. ``retain`` must be idempotent per item, or replaying a
    completed run inflates the benchmark."""

    written: tuple[str, ...] = ()
    skipped: tuple[SkippedRetention, ...] = ()
    deduplicated: tuple[str, ...] = ()


# ======================================================================================
# Human in the loop
# ======================================================================================


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """A confirm-tier call awaiting a human.

    Carries the same fields the ``approval.requested`` event carries, so a UI can be built
    from the event stream alone without a second round trip.
    """

    request_id: str
    tool: str
    args: dict[str, Any]
    blast_radius: str
    reversible: bool
    reversal_cost: str | None = None
    step_id: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    approved: bool
    answered_by: str = "unknown"
    answer: str | None = None
    latency_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class ClarificationRequest:
    """A question the agent cannot answer itself.

    ``options`` exists so the operator can pick rather than compose prose, and ``why_blocked``
    so they can judge whether the question was worth asking.
    """

    question: str
    why_blocked: str
    options: tuple[str, ...] = ()
    step_id: str | None = None


@dataclass(frozen=True, slots=True)
class ClarificationAnswer:
    answer: str
    answered_by: str = "unknown"


# ======================================================================================
# Planning
# ======================================================================================


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One step of a plan.

    ``success_criterion`` is what DECIDE evaluates; ``intent`` is prose for the reader. A step
    whose criterion cannot be checked against evidence is not a step, it is a wish.

    ``cites`` holds memory ids this step was built on and is the strongest form of memory
    attribution available: the model itself naming its source.
    """

    id: str
    intent: str
    success_criterion: str
    suggested_tool: str | None = None
    status: StepStatus = StepStatus.PENDING
    cites: tuple[str, ...] = ()

    def as_event_data(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "intent": self.intent,
            "success_criterion": self.success_criterion,
            "suggested_tool": self.suggested_tool,
            "status": str(self.status),
            "cites": list(self.cites),
        }

    def with_status(self, status: StepStatus) -> PlanStep:
        return replace(self, status=status)


@dataclass(frozen=True, slots=True)
class Plan:
    """A short, revisable plan. ``revision`` > 1 means the plan was rebuilt after evidence
    invalidated the previous one, which the trace renders as a replan rather than a failure."""

    steps: tuple[PlanStep, ...]
    revision: int = 1
    trigger: str = ""

    def active_step(self) -> PlanStep | None:
        for step in self.steps:
            if step.status is StepStatus.ACTIVE:
                return step
        return None

    def next_pending(self) -> PlanStep | None:
        for step in self.steps:
            if step.status is StepStatus.PENDING:
                return step
        return None

    def all_done(self) -> bool:
        return all(
            s.status in (StepStatus.DONE, StepStatus.SKIPPED, StepStatus.SUPERSEDED)
            for s in self.steps
        )


@dataclass(frozen=True, slots=True)
class Understanding:
    """The objective restated as something testable. Produced by UNDERSTAND, consumed by
    PLAN and by the finish check."""

    goal: str
    success_criteria: tuple[str, ...] = ()
    out_of_scope: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    ambiguity: str | None = None


@dataclass(frozen=True, slots=True)
class Verification:
    """One success criterion checked against evidence.

    ``evidence`` is required when ``passed`` is true. A criterion marked passed without
    evidence is a defect: it is exactly the "the plan ran, therefore we are done" failure the
    finish gate exists to prevent.
    """

    criterion: str
    passed: bool
    evidence: str = ""
    verified_by_tool: str | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    """What a tool result establishes -- and what it does not.

    ``does_not_establish`` is the field that keeps the agent from over-reading a tool: an
    empty log search means "nothing matched this query", not "nothing happened".
    """

    establishes: tuple[str, ...] = ()
    does_not_establish: tuple[str, ...] = ()
    injection_suspected: bool = False


# ======================================================================================
# Metrics and results
# ======================================================================================


@dataclass(frozen=True, slots=True)
class RunMetrics:
    """The learning-curve metrics. ``steps_to_completion`` is the headline number the
    benchmark compares across memory-off and memory-on runs."""

    steps_to_completion: int = 0
    tool_errors: int = 0
    corrections_needed: int = 0
    plans_revised: int = 0
    memory_items_used: int = 0
    memory_items_written: int = 0
    tokens_total: int = 0
    wall_clock_s: float = 0.0
    success: bool = False

    def as_event_data(self) -> dict[str, Any]:
        return {
            "steps_to_completion": self.steps_to_completion,
            "tool_errors": self.tool_errors,
            "corrections_needed": self.corrections_needed,
            "plans_revised": self.plans_revised,
            "memory_items_used": self.memory_items_used,
            "memory_items_written": self.memory_items_written,
            "tokens_total": self.tokens_total,
            "wall_clock_s": self.wall_clock_s,
            "success": self.success,
        }


@dataclass(frozen=True, slots=True)
class RunResult:
    """What a finished run returns to its caller."""

    run_id: str
    status: RunStatus
    answer: str
    metrics: RunMetrics = field(default_factory=RunMetrics)
    verification: tuple[Verification, ...] = ()
    blocker: str | None = None
    next_action: str | None = None
    handover: dict[str, Any] | None = None
    plan: Plan | None = None

    def as_event_data(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "answer": self.answer,
            "verification": [
                {"criterion": v.criterion, "passed": v.passed, "evidence": v.evidence}
                for v in self.verification
            ],
            "blocker": self.blocker,
            "next_action": self.next_action,
            "handover": self.handover,
        }


# ======================================================================================
# Events
# ======================================================================================


@dataclass(frozen=True, slots=True)
class BrainEvent:
    """One entry in the run's trace.

    Constructed by the emitter, validated against ``docs/brain/schemas/event.schema.json``,
    then handed to a sink. Emission happens before the loop advances, so the trace is
    causally ordered rather than merely timestamped.
    """

    schema_version: str
    event_id: str
    run_id: str
    seq: int
    ts: datetime
    type: str
    data: dict[str, Any]
    state: State | None = None
    step_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise for the wire. ``ts`` is RFC 3339 UTC; ``state`` is omitted when null so
        that a consumer can treat its absence as "outside the loop"."""
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "seq": self.seq,
            "ts": self.ts.isoformat().replace("+00:00", "Z"),
            "type": self.type,
            "data": self.data,
        }
        if self.state is not None:
            payload["state"] = str(self.state)
        if self.step_id is not None:
            payload["step_id"] = self.step_id
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), default=str)


# ======================================================================================
# Interfaces -- the seams a teammate implements
# ======================================================================================


@runtime_checkable
class LLMClient(Protocol):
    """A model provider. Implemented by ``FakeLLM`` (scripted, offline, deterministic) and
    ``GroqClient``.

    Implementations must raise :class:`brain.errors.LLMError` with a classified
    ``error_class`` rather than leaking a transport exception, so the retry policy can decide
    without inspecting provider internals.
    """

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Run one completion. Must return tool arguments raw *and* parsed."""
        ...


@runtime_checkable
class MemoryProvider(Protocol):
    """The memory layer. Implemented by ``MockMemory`` and, for real use, a Hindsight
    adapter.

    Two invariants the conformance suite checks, because violating either silently breaks the
    trace rather than raising:

    * ``recall`` returns items with **stable ids** across calls.
    * ``retain`` is **idempotent** per content: retaining the same lesson twice is one memory.
    """

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        ...

    def retain(self, items: Sequence[MemoryItem]) -> RetainResult:
        ...


@runtime_checkable
class ToolProvider(Protocol):
    """A capability behind one or more tools, e.g. ``observability`` or ``remediation``.

    A provider exposes one method per ``method:`` value its tools declare. It must not retry
    internally and must not apply its own timeout -- both belong to the brain, so that retry
    and budget behaviour is uniform and visible in the trace.
    """

    def invoke(self, method: str, args: dict[str, Any]) -> ToolResult:
        ...


@runtime_checkable
class HumanProvider(Protocol):
    """The human in the loop. ``ScriptedHuman`` answers from a fixture so unattended runs and
    tests can exercise the approval path without a person present."""

    def confirm(self, request: ApprovalRequest) -> ApprovalDecision:
        ...

    def ask(self, question: ClarificationRequest) -> ClarificationAnswer:
        ...


@runtime_checkable
class EventSink(Protocol):
    """Where events go. Implemented by ``MemorySink`` (tests, trace rendering),
    ``JsonlSink`` (SSE relay) and ``StdoutSink`` (human debugging).

    A sink must not raise on a healthy path, and must not block the loop beyond the run
    budget. A failing sink degrades to dropping events and reports itself via
    ``error.raised`` rather than aborting a run in progress.
    """

    def emit(self, event: BrainEvent) -> None:
        ...


@runtime_checkable
class Clock(Protocol):
    """Time. Faked so that traces, budgets and benchmarks are reproducible."""

    def now(self) -> datetime:
        """Current time, always timezone-aware UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin, for measuring durations without wall-clock
        jumps."""
        ...


@runtime_checkable
class IdFactory(Protocol):
    """Identifier minting. Sequential in tests so that traces are byte-comparable."""

    def new(self, prefix: str) -> str:
        ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Where large outputs go when they should not sit in the prompt."""

    def write(self, name: str, data: bytes) -> str:
        """Store ``data`` and return an opaque reference."""
        ...

    def read(self, ref: str) -> bytes:
        ...
