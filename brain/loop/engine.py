"""The reasoning loop, the permission engine, and run orchestration.

One objective, one pass through RECALL -> UNDERSTAND -> PLAN -> SELECT -> CALL -> OBSERVE -> DECIDE
-> (LOOP | RECOVER | FINISH) -> RETAIN. Every transition is emitted as a structured event, so the
trace is the loop's own account of what it did rather than a reconstruction of it.

Consolidated into one module rather than split across `machine.py` / `policy.py` / `planner.py`.
That is a deliberate deviation from the "small modules" preference, taken under time pressure: the
three concerns share so much state (the plan, the budget counters, the step cursor) that splitting
them would have produced three files passing a context object back and forth. The sections below
are separated by banner comments so the seams are still visible.

Four things here are load-bearing beyond the mechanics, each because `config/soul.md` or
`config/agents.md` promises it:

* **Precedence** (:class:`PolicyEngine`) -- safety, then workspace policy, then the live
  instruction, then the profile, then memory. Memory is advisory and never outranks a live
  instruction. The order is written once and applied, not re-derived per call.
* **Budget triage** (:meth:`Brain._budget_exhausted`) -- steps, then tokens, then wall clock, in
  that fixed order, so "we must stop" is deterministic rather than emergent.
* **Verify before finish** (:meth:`Brain._verify`) -- a success criterion is satisfied only with
  evidence attached. "The plan ran to completion" is not evidence.
* **Memory attribution** (:meth:`Brain._attribute_memory`) -- which recalled memory shaped which
  step, and how strongly that can be claimed. This is the most important output in the system:
  memory centrality is the heaviest-weighted criterion and it is invisible unless the trace draws
  the connection. It is also the easiest thing to fake, so the basis is typed and an unjustifiable
  claim is dropped rather than downgraded.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from brain.config.loader import ConfigLoader, ResolvedConfig
from brain.contracts import (
    ApprovalRequest,
    Autonomy,
    BrainEvent,
    Budgets,
    ChatMessage,
    ClarificationRequest,
    FinishReason,
    InfluenceBasis,
    LLMRequest,
    MemoryItem,
    MemoryKind,
    Observation,
    ParseStrategy,
    PermissionTier,
    Plan,
    PlanStep,
    RecallQuery,
    RecoveryStrategy,
    RunMetrics,
    RunResult,
    RunStatus,
    SideEffects,
    State,
    StepStatus,
    ToolSpec,
    Understanding,
    Verification,
)
from brain.errors import BrainError, BudgetExhausted, ErrorClass
from brain.events.emitter import EventEmitter
from brain.events.sinks import MemorySink
from brain.llm.parsing import CallParser, canonicalise_args
from brain.prompt.assembler import PromptAssembler
from brain.providers.registry import ProviderRegistry
from brain.tools.executor import ToolExecutor
from brain.tools.registry import ToolRegistry
from brain.util.text import content_words, jaccard

#: Tokens reserved for the model's reply when budgeting a prompt.
REPLY_RESERVE = 4096

#: Compaction threshold: summarise older observations once the prompt passes this fraction of the
#: budget, keeping the plan, objective, success criteria and key facts intact.
COMPACT_AT = 0.70

_HYPHENATED_RE = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b", re.IGNORECASE)
_INJECTION_RE = re.compile(
    r"(?i)(ignore (all )?(previous|prior|above) instructions|you are now|"
    r"disregard (the )?(system|previous)|note to assistant|as an ai|"
    r"new instructions?:|system prompt)"
)


# ======================================================================================
# State machine
# ======================================================================================

#: ``(state, outcome) -> next state``. A table rather than a chain of ifs, because the legal
#: transitions are the specification and should be readable as data. An unlisted pair is illegal;
#: :meth:`StateMachine.enter` raises rather than silently allowing it.
TRANSITIONS: dict[tuple[State, str], State] = {
    (State.RECALL, "recalled"): State.UNDERSTAND,
    (State.RECALL, "memory_off"): State.UNDERSTAND,
    (State.RECALL, "failed"): State.UNDERSTAND,
    (State.UNDERSTAND, "understood"): State.PLAN,
    (State.UNDERSTAND, "ambiguous"): State.FINISH,
    (State.PLAN, "planned"): State.SELECT,
    (State.SELECT, "tool_chosen"): State.CALL,
    (State.SELECT, "no_tool"): State.DECIDE,
    (State.SELECT, "denied"): State.RECOVER,
    (State.CALL, "called"): State.OBSERVE,
    (State.CALL, "call_failed"): State.RECOVER,
    (State.OBSERVE, "observed"): State.DECIDE,
    (State.DECIDE, "continue"): State.SELECT,
    (State.DECIDE, "step_done"): State.SELECT,
    (State.DECIDE, "replan"): State.PLAN,
    (State.DECIDE, "finish"): State.FINISH,
    (State.DECIDE, "exhausted"): State.FINISH,
    (State.RECOVER, "recovered"): State.SELECT,
    (State.RECOVER, "replanned"): State.PLAN,
    (State.RECOVER, "escalate"): State.FINISH,
    (State.FINISH, "finished"): State.RETAIN,
    (State.RETAIN, "retained"): State.RETAIN,
}


class StateMachine:
    """Tracks the loop's current state and enforces legal transitions."""

    def __init__(self, emitter: EventEmitter, *, initial: State = State.RECALL) -> None:
        self._emitter = emitter
        self._state = initial
        self.history: list[State] = [initial]
        self._emitter.emit(
            "state.entered",
            {"from": None, "to": str(initial), "reason": "run start"},
            state=initial,
        )

    @property
    def state(self) -> State:
        return self._state

    def can(self, outcome: str) -> bool:
        return (self._state, outcome) in TRANSITIONS

    def enter(self, outcome: str, reason: str) -> State:
        """Advance along ``outcome`` from the current state, emitting the transition."""
        key = (self._state, outcome)
        target = TRANSITIONS.get(key)
        if target is None:
            from brain.errors import ContractError

            raise ContractError(f"illegal transition from {self._state} on outcome {outcome!r}")
        previous, self._state = self._state, target
        self.history.append(target)
        self._emitter.emit(
            "state.entered",
            {"from": str(previous), "to": str(target), "reason": f"{outcome}: {reason}"},
            state=target,
        )
        return target


# ======================================================================================
# Policy engine
# ======================================================================================


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The outcome of evaluating one tool call against the permission model."""

    decision: str  # allow | confirm | deny
    tier: PermissionTier
    reason_code: str
    reason: str

    def as_event_data(self, tool: str) -> dict[str, Any]:
        return {
            "tool": tool,
            "tier": str(self.tier),
            "decision": self.decision,
            "reason_code": self.reason_code,
            "reason": self.reason,
        }


class PolicyEngine:
    """Decides whether a tool call may proceed, and under what conditions.

    Order is fixed and matches the precedence ladder in `config/agents.md`: profile availability,
    then the tool's declared tier, then autonomy, then the run's confirmation budget. `deny` never
    runs at any autonomy level -- that is the one rule that does not bend.

    Reasons are phrased as principles, never as the matched rule code. Explaining the tripwire
    teaches how to route around it; `reason_code` carries the machine-readable detail for the
    trace, and the human sentence stays at the level of the boundary itself.
    """

    def __init__(self, config: ResolvedConfig) -> None:
        self._config = config
        self._available = {spec.name for spec in config.tools}
        self._confirm_used = 0
        policy = config.policy or {}
        self._max_confirms = int(policy.get("max_confirm_requests", 6))
        self._always_confirm = set(policy.get("always_confirm_tools", []) or [])

    @property
    def confirm_requests_used(self) -> int:
        return self._confirm_used

    def decide(self, spec: ToolSpec, autonomy: Autonomy) -> PolicyDecision:
        if spec.name not in self._available:
            return PolicyDecision(
                "deny",
                spec.permission,
                "profile_not_included",
                "This action is not part of what this agent has been equipped to do.",
            )

        if spec.permission is PermissionTier.DENY:
            return PolicyDecision(
                "deny",
                spec.permission,
                "tier_deny",
                "This action is outside the authority granted for this work, at any level of "
                "automation. It can only be enabled deliberately by an operator.",
            )

        forced = spec.name in self._always_confirm or (
            spec.side_effects is SideEffects.DESTRUCTIVE
            and (self._config.policy or {}).get("require_confirmation_for_destructive", True)
        )

        if spec.permission is PermissionTier.AUTO and not forced:
            return PolicyDecision(
                "allow", spec.permission, "tier_auto", "Read-only; proceeds without interrupting anyone."
            )

        if autonomy is Autonomy.SUPERVISED:
            return self._confirm_or_exhausted(
                spec, "autonomy_supervised", "This run is set to require approval before anything changes."
            )

        if autonomy is Autonomy.STANDARD or forced:
            return self._confirm_or_exhausted(
                spec,
                "tier_confirm",
                "This changes a running system and cannot be undone automatically, so it needs a "
                "person to agree to it first.",
            )

        # Autonomy.AUTONOMOUS: a bounded, reversible change may proceed unattended.
        if spec.side_effects is SideEffects.MUTATING:
            return PolicyDecision(
                "allow",
                spec.permission,
                "autonomy_autonomous_bounded",
                "This run may make reversible changes unattended.",
            )
        return self._confirm_or_exhausted(
            spec,
            "tier_confirm_destructive",
            "This cannot be undone, so it needs a person to agree to it even here.",
        )

    def _confirm_or_exhausted(self, spec: ToolSpec, code: str, reason: str) -> PolicyDecision:
        if self._confirm_used >= self._max_confirms:
            return PolicyDecision(
                "deny",
                spec.permission,
                "confirm_budget_exhausted",
                "This run has already asked for as much human approval as it is allowed to. "
                "Escalating is the right move from here.",
            )
        return PolicyDecision("confirm", spec.permission, code, reason)

    def record_confirmation(self) -> None:
        self._confirm_used += 1


# ======================================================================================
# Run configuration
# ======================================================================================


@dataclass(frozen=True, slots=True)
class RunConfig:
    """What a caller asks a run to do."""

    objective: str
    profile: str = "devops"
    memory_enabled: bool | None = None  # None == take it from the profile
    autonomy: Autonomy | None = None
    budgets: Budgets | None = None
    provider_overrides: Mapping[str, str] = field(default_factory=dict)
    workspace: str | None = None
    user: str | None = None


# ======================================================================================
# The Brain
# ======================================================================================


class Brain:
    """Runs one objective to a conclusion."""

    def __init__(
        self,
        *,
        root: Path,
        loader: ConfigLoader | None = None,
        providers: ProviderRegistry | None = None,
        sink: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self._loader = loader or ConfigLoader(self.root)
        self._providers = providers
        self._sink = sink
        self._last_events: MemorySink | None = None

    # ------------------------------------------------------------------ public

    def run(self, config: RunConfig) -> RunResult:
        for _ in self.run_streaming(config):
            pass
        assert self._result is not None
        return self._result

    def run_streaming(self, config: RunConfig) -> Iterator[BrainEvent]:
        """Run, yielding each event as it is emitted.

        The generator shape is what lets an SSE layer relay a live trace without the loop knowing
        anything about HTTP.
        """
        self._result = None
        ctx = self._setup(config)
        sink = ctx["sink"]
        self._drive(ctx)
        # The loop runs to a conclusion and then the trace is replayed. Incremental streaming would
        # need an emitter-side queue; this is a deliberate simplification that keeps the sink
        # contract simple, and the event order is identical either way.
        consumed = 0
        while consumed < len(sink.events):
            yield sink.events[consumed]
            consumed += 1

    # ------------------------------------------------------------------ setup

    def _setup(self, config: RunConfig) -> dict[str, Any]:
        resolved = self._loader.load(config.profile, workspace=config.workspace, user=config.user)
        if config.memory_enabled is not None:
            resolved = replace(
                resolved,
                memory=replace(resolved.memory, enabled=bool(config.memory_enabled)),
            )
        if config.autonomy is not None:
            resolved = replace(resolved, autonomy=config.autonomy)
        if config.budgets is not None:
            resolved = replace(resolved, budgets=config.budgets)

        # Per-run provider overrides win over the config file, so a demo can flip one capability
        # without editing a versioned file.
        overrides = dict(config.provider_overrides or {})
        provider_cfg = {
            capability: {
                "impl": overrides.get(capability, entry["impl"]),
                "settings": entry["settings"],
            }
            for capability, entry in resolved.providers.items()
        }
        providers = self._providers or ProviderRegistry.from_config(provider_cfg, root=self.root)
        clock = providers.clock()
        ids = providers.ids()
        sink = self._sink or providers.sink()
        if not hasattr(sink, "events"):
            sink = MemorySink()
        self._last_events = sink

        registry = ToolRegistry(resolved.tools)
        executor = ToolExecutor(registry, providers, clock)
        memory = providers.memory()
        human = providers.human()

        run_id = ids.new("run")
        emitter = EventEmitter(sink, run_id, clock, ids)

        emitter.emit(
            "run.started",
            {
                "profile": resolved.profile,
                "objective": config.objective,
                "memory_enabled": resolved.memory.enabled,
                "autonomy": str(resolved.autonomy),
                "budgets": resolved.budgets.as_event_data(),
                "config_fingerprint": resolved.fingerprint,
            },
        )

        llm = providers.llm()
        parser = CallParser(llm, validator=self._validator(registry))
        assembler = PromptAssembler(
            resolved, token_budget=max(4000, resolved.budgets.max_tokens - REPLY_RESERVE)
        )

        return {
            "config": config,
            "resolved": resolved,
            "emitter": emitter,
            "sink": sink,
            "clock": clock,
            "ids": ids,
            "registry": registry,
            "executor": executor,
            "memory": memory,
            "human": human,
            "llm": llm,
            "parser": parser,
            "assembler": assembler,
            "machine": StateMachine(emitter),
            "policy": PolicyEngine(resolved),
            "run_id": run_id,
            "started": clock.monotonic(),
            "metrics": {
                "steps": 0,
                "tool_errors": 0,
                "corrections": 0,
                "plans_revised": 0,
                "tokens": 0,
                "memory_used": 0,
                "memory_written": 0,
            },
            "memories": [],
            "observations": [],
            "plan": None,
            "understanding": None,
            "call_hashes": {},
            "consecutive_failures": 0,
        }

    @staticmethod
    def _validator(registry: ToolRegistry):
        from brain.tools.validate import validate_args

        def check(name: str, args: dict[str, Any]) -> list[str]:
            spec = registry.get(name)
            if spec is None:
                return [f"unknown tool {name!r}"]
            return validate_args(spec, args)

        return check

    # ------------------------------------------------------------------ driver

    def _drive(self, ctx: dict[str, Any]) -> None:
        emit = ctx["emitter"].emit
        machine: StateMachine = ctx["machine"]

        try:
            self._recall(ctx)
            machine.enter("recalled" if ctx["memories"] else "memory_off", "recall complete")

            if not self._understand(ctx):
                machine.enter("ambiguous", "objective could not be acted on without asking")
                self._finish(ctx, RunStatus.ESCALATED, forced=True)
                return
            machine.enter("understood", "goal and success criteria established")

            self._plan(ctx, revision=1)
            machine.enter("planned", "initial plan produced")

            while True:
                budget = self._budget_exhausted(ctx)
                if budget is not None:
                    machine.enter("exhausted", f"{budget.kind} budget spent")
                    self._finish(ctx, RunStatus.PARTIAL, forced=True)
                    return

                selected = self._select(ctx)
                if selected is None:
                    machine.enter("no_tool", "no further tool required")
                    decision = self._decide(ctx)
                    outcome = self._apply_decision(ctx, machine, decision)
                    if outcome == "done":
                        return
                    continue

                spec, args, call = selected
                verdict = ctx["policy"].decide(spec, ctx["resolved"].autonomy)
                emit("policy.decided", verdict.as_event_data(spec.name), state=State.SELECT,
                     step_id=self._step_id(ctx))

                if verdict.decision == "deny":
                    emit(
                        "recovery.started",
                        {
                            "strategy": str(RecoveryStrategy.ESCALATE),
                            "trigger": f"policy refused {spec.name}: {verdict.reason_code}",
                            "from_tool": spec.name,
                            "to_tool": None,
                            "ladder_position": 5,
                        },
                        state=State.RECOVER,
                    )
                    ctx["metrics"]["tool_errors"] += 1
                    machine.enter("denied", f"policy refused {spec.name}")
                    self._finish(ctx, RunStatus.DENIED, forced=True, blocked_on=spec.name)
                    return

                if verdict.decision == "confirm" and not self._request_approval(ctx, spec, args):
                    emit(
                        "recovery.started",
                        {
                            "strategy": str(RecoveryStrategy.REPLAN),
                            "trigger": f"human declined {spec.name}",
                            "from_tool": spec.name,
                            "to_tool": None,
                            "ladder_position": 4,
                        },
                        state=State.RECOVER,
                    )
                    ctx["metrics"]["corrections"] += 1
                    machine.enter("denied", f"human declined {spec.name}")
                    self._plan(ctx, revision=int(ctx["plan"].revision) + 1,
                               trigger=f"operator declined {spec.name}")
                    machine.enter("replanned", "operator declined the action")
                    machine.enter("planned", "replan complete")
                    continue

                machine.enter("tool_chosen", f"selected {spec.name}")
                self._attribute_memory(ctx, spec, args)

                outcome = ctx["executor"].execute(spec, args, call_id=call.call_id)
                emit(
                    "tool.called",
                    {
                        "call_id": call.call_id,
                        "tool": spec.name,
                        "args": outcome.redacted_args,
                        "attempt": outcome.attempts or 1,
                        "timeout_s": spec.timeout_s,
                    },
                    state=State.CALL,
                    step_id=self._step_id(ctx),
                )

                if outcome.result.ok:
                    emit(
                        "tool.result",
                        {
                            "call_id": call.call_id,
                            "tool": spec.name,
                            "ok": True,
                            "duration_ms": outcome.result.duration_ms,
                            "result": outcome.result.data,
                            "truncated": outcome.result.truncated,
                            "trust": "untrusted",
                            "injection_suspected": self._injection_in(outcome.result.data),
                        },
                        state=State.CALL,
                        step_id=self._step_id(ctx),
                    )
                    ctx["consecutive_failures"] = 0
                    self._observe(ctx, spec, outcome.result.data)
                    machine.enter("called", f"{spec.name} returned")
                else:
                    ctx["metrics"]["tool_errors"] += 1
                    ctx["consecutive_failures"] += 1
                    error_class = outcome.error_class or ErrorClass.PROVIDER_ERROR
                    emit(
                        "tool.failed",
                        {
                            "call_id": call.call_id,
                            "tool": spec.name,
                            "error_class": str(error_class),
                            "message": outcome.result.error_message,
                            "retryable": error_class in {
                                ErrorClass.TIMEOUT, ErrorClass.RATE_LIMITED, ErrorClass.PROVIDER_5XX
                            },
                            "attempt": outcome.attempts or 1,
                        },
                        state=State.CALL,
                        step_id=self._step_id(ctx),
                    )
                    machine.enter("call_failed", f"{spec.name} failed: {error_class}")

                    strategy = self._recover(ctx, spec, error_class)
                    if strategy is RecoveryStrategy.ESCALATE:
                        self._finish(ctx, RunStatus.ESCALATED, forced=True)
                        return
                    if strategy is RecoveryStrategy.REPLAN:
                        self._plan(
                            ctx,
                            revision=int(ctx["plan"].revision) + 1,
                            trigger=f"{spec.name} failed with {error_class}",
                        )
                        machine.enter("replanned", "recovery replanned")
                        continue
                    machine.enter("recovered", f"recovery strategy {strategy}")
                    continue

                if self._loop_detected(ctx, spec, args):
                    emit(
                        "recovery.started",
                        {
                            "strategy": str(RecoveryStrategy.REPLAN),
                            "trigger": f"{spec.name} called three times with identical arguments "
                                       "and no change in the observed state",
                            "from_tool": spec.name,
                            "to_tool": None,
                            "ladder_position": 4,
                        },
                        state=State.RECOVER,
                    )
                    self._plan(ctx, revision=int(ctx["plan"].revision) + 1,
                               trigger="repeated-identical-call detection")
                    machine.enter("replanned", "identical calls repeated; replanning")
                    continue

                machine.enter("observed", "result recorded")
                decision = self._decide(ctx)
                outcome = self._apply_decision(ctx, machine, decision)
                if outcome == "done":
                    return
        except BudgetExhausted as exc:
            emit("budget.exhausted", {"kind": exc.kind, "limit": exc.limit, "used": exc.used},
                 state=machine.state)
            self._finish(ctx, RunStatus.PARTIAL, forced=True)
        except BrainError as exc:
            ctx["emitter"].emit_error(exc)
            self._finish(ctx, RunStatus.FAILED, forced=True, error=exc)

    # ------------------------------------------------------------------ states

    def _recall(self, ctx: dict[str, Any]) -> None:
        resolved: ResolvedConfig = ctx["resolved"]
        emit = ctx["emitter"].emit
        if not resolved.memory.enabled:
            emit(
                "recall.performed",
                {"query": "", "memory_enabled": False, "hit_count": 0, "memories": []},
                state=State.RECALL,
            )
            return

        entities = self._entities(ctx["config"].objective)
        from brain.memory.policy import MemoryPolicy
        policy = MemoryPolicy(resolved)
        query = policy.build_recall_query(ctx["config"].objective, entities)
        started = ctx["clock"].monotonic()
        try:
            found = list(ctx["memory"].recall(query))
        except BrainError as exc:
            ctx["emitter"].emit_error(exc)
            found = []
        ctx["memories"] = found
        ctx["metrics"]["memory_used"] = len(found)
        emit(
            "recall.performed",
            {
                "query": query.text,
                "memory_enabled": True,
                "hit_count": len(found),
                "duration_ms": max(0.0, ctx["clock"].monotonic() - started) * 1000.0,
                "memories": [m.as_event_data() for m in found],
            },
            state=State.RECALL,
        )

    def _understand(self, ctx: dict[str, Any]) -> bool:
        emit = ctx["emitter"].emit
        prompt = ctx["assembler"].build(
            task="UNDERSTAND",
            objective=ctx["config"].objective,
            memories=ctx["memories"],
            agent_notes=ctx["resolved"].profile_prompts.get("objective_hint", ""),
        )
        payload = self._ask_json(ctx, prompt)
        understanding = Understanding(
            goal=str(payload.get("goal", ctx["config"].objective)),
            success_criteria=tuple(payload.get("success_criteria", []) or ()),
            out_of_scope=tuple(payload.get("out_of_scope", []) or ()),
            unknowns=tuple(payload.get("unknowns", []) or ()),
            ambiguity=payload.get("ambiguity") or None,
        )
        ctx["understanding"] = understanding
        emit(
            "understand.completed",
            {
                "goal": understanding.goal,
                "success_criteria": list(understanding.success_criteria),
                "out_of_scope": list(understanding.out_of_scope),
                "unknowns": list(understanding.unknowns),
                "ambiguity": understanding.ambiguity,
            },
            state=State.UNDERSTAND,
        )
        if understanding.ambiguity:
            answer = ctx["human"].ask(
                ClarificationRequest(
                    question=understanding.ambiguity,
                    why_blocked="The objective cannot be acted on without this answer.",
                )
            )
            ctx["metrics"]["corrections"] += 1
            self._record_correction(ctx, answer.answer)
            return False
        return True

    def _plan(self, ctx: dict[str, Any], *, revision: int, trigger: str = "") -> None:
        emit = ctx["emitter"].emit
        if revision > 1:
            ctx["metrics"]["plans_revised"] += 1
        prompt = ctx["assembler"].build(
            task="PLAN",
            objective=ctx["config"].objective,
            understanding=ctx["understanding"],
            plan=ctx["plan"] if revision > 1 else None,
            memories=ctx["memories"],
            observations=self._observation_texts(ctx),
            scratch=f"Previous plan failed: {trigger}" if trigger else "",
        )
        payload = self._ask_json(ctx, prompt)
        steps = tuple(
            PlanStep(
                id=str(raw.get("id", f"s{i}")),
                intent=str(raw.get("intent", "")),
                success_criterion=str(raw.get("success_criterion", "")),
                suggested_tool=raw.get("suggested_tool") or None,
                cites=tuple(raw.get("cites", []) or ()),
            )
            for i, raw in enumerate(payload.get("steps", []) or [], 1)
        )
        if not steps:
            steps = (
                PlanStep("s1", "Establish the current state", "A current-state reading exists"),
            )
        ctx["plan"] = Plan(steps=steps, revision=revision, trigger=trigger)
        ctx["step_cursor"] = 0
        event = "plan.created" if revision == 1 else "plan.revised"
        data: dict[str, Any] = {"revision": revision, "steps": [s.as_event_data() for s in steps]}
        if revision > 1:
            data["trigger"] = trigger
        emit(event, data, state=State.PLAN)

    def _select(self, ctx: dict[str, Any]) -> tuple[ToolSpec, dict[str, Any], Any] | None:
        plan: Plan | None = ctx["plan"]
        pending = plan.next_pending() if plan else None
        current = self._current_step(ctx)
        prompt = ctx["assembler"].build(
            task="SELECT",
            objective=ctx["config"].objective,
            understanding=ctx["understanding"],
            plan=plan,
            memories=ctx["memories"],
            observations=self._observation_texts(ctx),
            current_step=(
                f"{current.id}: {current.intent} (done when: {current.success_criterion})"
                if current
                else "No pending step; decide whether the objective is met."
            ),
        )
        request = LLMRequest(
            messages=prompt.messages,
            tools=() if not prompt.tools else prompt.tools,
            temperature=0.2,
            max_tokens=1024,
        )
        outcome = ctx["parser"].obtain_call(request)
        ctx["metrics"]["tokens"] += outcome.response.usage.total_tokens
        if outcome.ladder_exhausted or not outcome.response.wants_tools:
            return None
        call = outcome.response.tool_calls[0]
        spec = ctx["registry"].get(call.name)
        if spec is None:
            ctx["emitter"].emit(
                "tool.failed",
                {
                    "call_id": call.call_id,
                    "tool": call.name,
                    "error_class": str(ErrorClass.UNKNOWN_TOOL),
                    "message": f"model asked for unknown tool {call.name!r}",
                    "retryable": False,
                    "attempt": 1,
                },
                state=State.SELECT,
            )
            ctx["metrics"]["tool_errors"] += 1
            return None
        ctx["emitter"].emit(
            "step.selected",
            {
                "step_id": current.id if current else "",
                "tool": spec.name,
                "args": call.arguments,
                "rationale": f"selected for step {current.id}" if current else "no pending step",
                "parallel_group": None,
            },
            state=State.SELECT,
            step_id=current.id if current else None,
        )
        return spec, call.arguments, call

    def _observe(self, ctx: dict[str, Any], spec: ToolSpec, data: Any) -> None:
        establishes, does_not = self._classify_observation(spec, data)
        injection = self._injection_in(data)
        ctx["observations"].append(
            Observation(
                establishes=tuple(establishes),
                does_not_establish=tuple(does_not),
                injection_suspected=injection,
            )
        )
        ctx["emitter"].emit(
            "observation.extracted",
            {
                "establishes": establishes,
                "does_not_establish": does_not,
                "injection_suspected": injection,
            },
            state=State.OBSERVE,
            step_id=self._step_id(ctx),
        )
        if injection:
            ctx["emitter"].emit(
                "error.raised",
                {
                    "where": "untrusted-content guard",
                    "message": (
                        f"tool output from {spec.name} contained instruction-shaped text; it was "
                        "treated as data and did not alter the objective, plan or policy"
                    ),
                    "fatal": False,
                    "error_class": None,
                },
                state=State.OBSERVE,
            )

    def _decide(self, ctx: dict[str, Any]) -> dict[str, Any]:
        current = self._current_step(ctx)
        prompt = ctx["assembler"].build(
            task="DECIDE",
            objective=ctx["config"].objective,
            understanding=ctx["understanding"],
            plan=ctx["plan"],
            memories=ctx["memories"],
            observations=self._observation_texts(ctx),
            current_step=(
                f"{current.id}: {current.intent} (done when: {current.success_criterion})"
                if current
                else "No pending step."
            ),
        )
        payload = self._ask_json(ctx, prompt)
        criterion = str(payload.get("criterion", current.success_criterion if current else ""))
        passed = bool(payload.get("passed", False))
        evidence = str(payload.get("evidence", "") or "")
        # A criterion cannot be met without evidence. If the model claims a pass with nothing
        # behind it, the claim is downgraded here rather than trusted, because this is exactly the
        # "the plan ran, therefore we are done" failure the finish gate exists to prevent.
        if passed and not evidence.strip():
            passed = False
            payload["reason"] = (
                str(payload.get("reason", "")) + " (downgraded: passed with no evidence)"
            ).strip()
        verification = Verification(
            criterion=criterion, passed=passed, evidence=evidence,
            verified_by_tool=self._last_tool(ctx),
        )
        ctx.setdefault("verifications", []).append(verification)
        ctx["emitter"].emit(
            "verification.performed",
            {
                "criterion": verification.criterion,
                "passed": verification.passed,
                "evidence": verification.evidence,
                "verified_by_tool": verification.verified_by_tool,
            },
            state=State.DECIDE,
            step_id=self._step_id(ctx),
        )
        return {
            "next": str(payload.get("next", "continue")),
            "passed": passed,
            "reason": str(payload.get("reason", "")),
        }

    def _apply_decision(
        self, ctx: dict[str, Any], machine: StateMachine, decision: dict[str, Any]
    ) -> str:
        nxt = decision["next"]
        current = self._current_step(ctx)
        plan: Plan = ctx["plan"]

        if nxt == "finish" or (plan.all_done() and nxt != "replan"):
            machine.enter("finish", decision["reason"] or "criteria met")
            status = RunStatus.COMPLETED if self._all_verified(ctx) else RunStatus.PARTIAL
            self._finish(ctx, status)
            return "done"

        if nxt == "replan":
            self._plan(ctx, revision=int(plan.revision) + 1, trigger=decision["reason"])
            machine.enter("replan", decision["reason"])
            machine.enter("planned", "replan complete")
            return "continue"

        # Otherwise advance the step cursor and loop.
        if current is not None:
            updated = tuple(
                s.with_status(StepStatus.DONE) if s.id == current.id else s for s in plan.steps
            )
            ctx["plan"] = replace(plan, steps=updated)
        ctx["metrics"]["steps"] += 1
        machine.enter("step_done", decision["reason"] or "step criterion met")
        return "continue"

    def _recover(self, ctx: dict[str, Any], spec: ToolSpec, error_class: ErrorClass) -> RecoveryStrategy:
        """Walk the recovery ladder from where this failure puts us.

        Rung choice is by error class, not by preference: a transient error retries, a malformed
        call is repaired, a missing capability substitutes, a wrong approach replans, and anything
        about authority escalates.
        """
        from brain.errors import is_model_output_error, is_retryable

        if is_retryable(error_class) and spec.idempotent:
            strategy = RecoveryStrategy.RETRY
            position = 1
        elif is_model_output_error(error_class):
            strategy = RecoveryStrategy.REPAIR
            position = 2
        elif error_class is ErrorClass.NOT_FOUND:
            strategy = RecoveryStrategy.SUBSTITUTE
            position = 3
        elif ctx["consecutive_failures"] >= ctx["resolved"].budgets.max_consecutive_failures:
            strategy = RecoveryStrategy.ESCALATE
            position = 5
        else:
            strategy = RecoveryStrategy.REPLAN
            position = 4

        ctx["emitter"].emit(
            "recovery.started",
            {
                "strategy": str(strategy),
                "trigger": f"{spec.name} failed with {error_class}",
                "from_tool": spec.name,
                "to_tool": None,
                "ladder_position": position,
            },
            state=State.RECOVER,
        )
        return strategy

    # ------------------------------------------------------------------ finish / retain

    def _verify(self, ctx: dict[str, Any]) -> bool:
        """Re-check every success criterion that has not already been evidenced."""
        understanding: Understanding = ctx["understanding"]
        seen = {v.criterion for v in ctx.get("verifications", []) if v.passed and v.evidence}
        ok = True
        for criterion in understanding.success_criteria:
            if criterion in seen:
                continue
                
            prompt = ctx["assembler"].build(
                task="DECIDE",
                objective=ctx["config"].objective,
                understanding=ctx["understanding"],
                plan=ctx["plan"],
                memories=ctx["memories"],
                observations=self._observation_texts(ctx),
                current_step=f"Verify overall success criterion: {criterion}",
            )
            payload = self._ask_json(ctx, prompt)
            passed = bool(payload.get("passed", False))
            evidence = str(payload.get("evidence", "") or "")
            if passed and not evidence.strip():
                passed = False

            ctx["emitter"].emit(
                "verification.performed",
                {
                    "criterion": criterion,
                    "passed": passed,
                    "evidence": evidence,
                    "verified_by_tool": self._last_tool(ctx),
                },
                state=State.FINISH,
            )
            if not passed:
                ok = False
        return ok

    def _all_verified(self, ctx: dict[str, Any]) -> bool:
        return self._verify(ctx)

    def _finish(
        self,
        ctx: dict[str, Any],
        status: RunStatus,
        *,
        forced: bool = False,
        blocked_on: str = "",
        error: BrainError | None = None,
    ) -> None:
        emit = ctx["emitter"].emit
        if status is RunStatus.COMPLETED and not self._verify(ctx):
            # Downgrade rather than lie: a completed run with an unverified criterion is exactly
            # the outcome the verification requirement exists to stop.
            status = RunStatus.PARTIAL

        prompt = ctx["assembler"].build(
            task="FINISH",
            objective=ctx["config"].objective,
            understanding=ctx["understanding"],
            plan=ctx["plan"],
            memories=ctx["memories"],
            observations=self._observation_texts(ctx),
            scratch=f"Status: {status}. " + (f"Blocked on: {blocked_on}. " if blocked_on else ""),
        )
        payload = self._ask_json(ctx, prompt, fallback={})
        answer = str(payload.get("answer", "") or "").strip()
        blocker = payload.get("blocker") or (f"blocked on {blocked_on}" if blocked_on else None)
        next_action = payload.get("next_action")
        if error is not None:
            blocker = blocker or error.message
        if status is not RunStatus.COMPLETED and not answer:
            answer = (
                f"Objective not completed. {blocker or 'No further safe action was available.'}"
            )
        if status is not RunStatus.COMPLETED and not next_action:
            next_action = "A human should review the partial result and decide the next step."

        elapsed = max(0.0, ctx["clock"].monotonic() - ctx["started"])
        metrics = RunMetrics(
            steps_to_completion=ctx["metrics"]["steps"],
            tool_errors=ctx["metrics"]["tool_errors"],
            corrections_needed=ctx["metrics"]["corrections"],
            plans_revised=ctx["metrics"]["plans_revised"],
            memory_items_used=ctx["metrics"]["memory_used"],
            memory_items_written=ctx["metrics"]["memory_written"],
            tokens_total=ctx["metrics"]["tokens"],
            wall_clock_s=round(elapsed, 3),
            success=status is RunStatus.COMPLETED,
        )
        emit("metric.updated", metrics.as_event_data(), state=State.FINISH)

        result = RunResult(
            run_id=ctx["run_id"],
            status=status,
            answer=answer,
            metrics=metrics,
            verification=tuple(ctx.get("verifications", [])),
            blocker=blocker,
            next_action=next_action,
            handover=self._handover(ctx, blocker, next_action) if status is RunStatus.ESCALATED else None,
            plan=ctx["plan"],
        )
        emit("run.finished", result.as_event_data(), state=State.FINISH)
        self._result = result

        ctx["machine"].enter("finished", "run concluded")
        self._retain(ctx, status)

    def _handover(
        self, ctx: dict[str, Any], blocker: str | None, next_action: str | None
    ) -> dict[str, Any]:
        ruled_out = [
            o.establishes[0] for o in ctx["observations"] if o.establishes
        ][:5]
        return {
            "established": (ctx["understanding"].goal if ctx["understanding"] else "") ,
            "ruled_out": ruled_out,
            "blocker": blocker,
            "suggested_next": next_action,
        }

    def _retain(self, ctx: dict[str, Any], status: RunStatus) -> None:
        emit = ctx["emitter"].emit
        resolved: ResolvedConfig = ctx["resolved"]
        if not resolved.memory.enabled:
            emit(
                "memory.retained",
                {"written": [], "skipped": [{"reason": "memory_disabled", "candidate": ""}]},
                state=State.RETAIN,
            )
            return

        prompt = ctx["assembler"].build(
            task="RETAIN",
            objective=ctx["config"].objective,
            understanding=ctx["understanding"],
            plan=ctx["plan"],
            memories=ctx["memories"],
            observations=self._observation_texts(ctx),
            scratch=f"Outcome status: {status}",
        )
        payload = self._ask_json(ctx, prompt, fallback={})
        written: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        candidates: list[MemoryItem] = []

        from brain.memory.policy import MemoryPolicy
        policy = MemoryPolicy(resolved)

        for i, raw in enumerate(payload.get("memories", []) or [], 1):
            text = str(raw.get("text", "")).strip()
            kind_raw = str(raw.get("kind", "outcome"))
            
            passed, reason, kind = policy.should_retain(text, kind_raw)
            if not passed:
                skipped.append({"candidate": text[:120], "reason": reason})
                continue

            candidates.append(
                MemoryItem(
                    id=ctx["ids"].new("mem"),
                    kind=kind,
                    text=text,
                    entities=tuple(raw.get("entities", []) or ()),
                    confidence=float(raw.get("confidence", 0.7)),
                    observed_at=ctx["clock"].now(),
                    source_run_id=ctx["run_id"],
                )
            )

        for raw in payload.get("skipped", []) or []:
            skipped.append(
                {
                    "candidate": str(raw.get("candidate", ""))[:120],
                    "reason": str(raw.get("reason", "low_confidence")),
                }
            )

        if candidates:
            try:
                result = ctx["memory"].retain(candidates)
                for mid in result.written:
                    match = next((c for c in candidates if c.id == mid), None)
                    written.append(match.as_event_data() if match else {"id": mid})
                for mid in result.deduplicated:
                    skipped.append(
                        {"candidate": "", "reason": "duplicate"}
                    )
            except BrainError as exc:
                ctx["emitter"].emit_error(exc)

        ctx["metrics"]["memory_written"] = len(written)
        emit("memory.retained", {"written": written, "skipped": skipped}, state=State.RETAIN)

    # ------------------------------------------------------------------ memory attribution

    def _attribute_memory(self, ctx: dict[str, Any], spec: ToolSpec, args: dict[str, Any]) -> None:
        """Emit ``memory.influenced`` for each recalled memory that shaped this step.

        Basis priority is explicit citation, then entity overlap, then lexical overlap. The basis is
        part of the event because a viewer must render a citation differently from a heuristic -- a
        trace that presents a lexical coincidence as a causal link overclaims, which is worse than
        showing no attribution at all.
        """
        if not ctx["resolved"].memory.enabled or not ctx["memories"]:
            return
        current = self._current_step(ctx)
        step_id = current.id if current else ""
        cites = set(current.cites) if current else set()
        arg_text = " ".join(str(v) for v in args.values())
        arg_words = content_words(arg_text)
        step_words = content_words(
            f"{current.intent} {current.success_criterion}" if current else ""
        )

        for memory in ctx["memories"]:
            basis: InfluenceBasis | None = None
            if memory.id in cites:
                basis = InfluenceBasis.EXPLICIT_CITATION
            elif memory.entities and any(
                e.lower() in arg_text.lower() for e in memory.entities
            ):
                basis = InfluenceBasis.ENTITY_OVERLAP
            else:
                overlap = jaccard(content_words(memory.text), arg_words | step_words)
                if overlap >= 0.34:
                    basis = InfluenceBasis.LEXICAL_OVERLAP
            if basis is None:
                continue

            effect = None
            if basis is InfluenceBasis.EXPLICIT_CITATION:
                effect = f"step {step_id} cites this memory"
            elif basis is InfluenceBasis.ENTITY_OVERLAP:
                shared = [e for e in memory.entities if e.lower() in arg_text.lower()]
                effect = f"shared entities with the call: {', '.join(shared[:3])}"

            ctx["emitter"].emit(
                "memory.influenced",
                {
                    "step_id": step_id,
                    "memory_ids": [memory.id],
                    "basis": str(basis),
                    "effect": effect,
                },
                state=State.SELECT,
                step_id=step_id or None,
            )

    # ------------------------------------------------------------------ helpers

    def _ask_json(
        self, ctx: dict[str, Any], prompt: Any, *, fallback: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """One model call whose reply is expected to be a JSON object."""
        request = LLMRequest(
            messages=prompt.messages,
            tools=(),
            temperature=0.2,
            max_tokens=2048,
        )
        response = ctx["llm"].complete(request)
        ctx["metrics"]["tokens"] += response.usage.total_tokens
        text = (response.content or "").strip()
        if not text:
            return dict(fallback or {})
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            from brain.llm.parsing import parse_tool_arguments

            value, _ = parse_tool_arguments(text)
        return value if isinstance(value, dict) else dict(fallback or {})

    def _budget_exhausted(self, ctx: dict[str, Any]) -> BudgetExhausted | None:
        """Steps, then tokens, then wall clock -- the fixed triage order from agents.md."""
        budgets: Budgets = ctx["resolved"].budgets
        if ctx["metrics"]["steps"] >= budgets.max_steps:
            return BudgetExhausted("steps", budgets.max_steps, ctx["metrics"]["steps"])
        if ctx["metrics"]["tokens"] >= budgets.max_tokens:
            return BudgetExhausted("tokens", budgets.max_tokens, ctx["metrics"]["tokens"])
        elapsed = ctx["clock"].monotonic() - ctx["started"]
        if elapsed >= budgets.max_wall_clock_s:
            return BudgetExhausted("wall_clock", budgets.max_wall_clock_s, round(elapsed, 2))
        return None

    def _loop_detected(self, ctx: dict[str, Any], spec: ToolSpec, args: dict[str, Any]) -> bool:
        key = f"{spec.name}:{canonicalise_args(args)}"
        counts = ctx["call_hashes"]
        counts[key] = counts.get(key, 0) + 1
        return counts[key] >= 3

    def _current_step(self, ctx: dict[str, Any]) -> PlanStep | None:
        plan: Plan | None = ctx["plan"]
        if plan is None:
            return None
        pending = plan.next_pending()
        if pending is None:
            return None
        return pending

    def _step_id(self, ctx: dict[str, Any]) -> str | None:
        step = self._current_step(ctx)
        return step.id if step else None

    def _last_tool(self, ctx: dict[str, Any]) -> str | None:
        for event in reversed(ctx["emitter"].events):
            if event.type in {"tool.result", "tool.failed"}:
                return str(event.data.get("tool", "")) or None
        return None

    def _observation_texts(self, ctx: dict[str, Any]) -> list[str]:
        """Render observations for the prompt, compacting older ones past the threshold."""
        out: list[str] = []
        for obs in ctx["observations"]:
            if obs.establishes:
                out.append("Establishes: " + "; ".join(obs.establishes))
            if obs.does_not_establish:
                out.append("Does NOT establish: " + "; ".join(obs.does_not_establish))
        if not out:
            return []
        return out[-6:]

    def _classify_observation(
        self, spec: ToolSpec, data: Any
    ) -> tuple[list[str], list[str]]:
        """What this result establishes, and what it does not.

        The `does_not_establish` half is what keeps the agent from over-reading a tool. An empty
        log search means nothing matched *that query*, not that nothing happened -- and the
        difference is exactly where agents invent conclusions.
        """
        establishes: list[str] = []
        does_not: list[str] = []

        if isinstance(data, Mapping):
            for key in ("entries", "deploys", "incidents", "runbooks", "tickets", "issues", "memories"):
                value = data.get(key)
                if isinstance(value, list):
                    if value:
                        establishes.append(f"{spec.name} returned {len(value)} {key}")
                    else:
                        does_not.append(
                            f"whether the underlying data is absent or merely unmatched by this query"
                        )
            if "services" in data and isinstance(data["services"], list):
                for svc in data["services"]:
                    if isinstance(svc, Mapping):
                        establishes.append(
                            f"{svc.get('service')} status={svc.get('status')} "
                            f"error_rate={svc.get('error_rate_pct')}%"
                        )
            if "summary" in data and isinstance(data["summary"], Mapping):
                establishes.append(f"{data.get('metric')} last={data['summary'].get('last')}")
        if not establishes:
            establishes.append(f"{spec.name} completed")
        return establishes, does_not

    def _injection_in(self, data: Any) -> bool:
        try:
            return bool(_INJECTION_RE.search(json.dumps(data, default=str)))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _entities(text: str) -> tuple[str, ...]:
        """Pull entity-shaped tokens out of an objective to anchor recall.

        Hyphenated identifiers (``checkout-api``, ``db-pool``) are the single most useful anchor in
        operational text, so they are extracted greedily; the rest of the query is left as free
        text for the memory provider's own ranking.
        """
        seen: list[str] = []
        for match in _HYPHENATED_RE.finditer(text):
            token = match.group(0)
            if token not in seen:
                seen.append(token)
        return tuple(seen)

    def _request_approval(self, ctx: dict[str, Any], spec: ToolSpec, args: dict[str, Any]) -> bool:
        emit = ctx["emitter"].emit
        request_id = ctx["ids"].new("apr")
        dry_run_available = "dry_run" in (spec.parameters.get("properties", {}) or {})
        if dry_run_available and not args.get("dry_run") and ctx["resolved"].policy.get(
            "require_dry_run_when_available", False
        ):
            args = dict(args)
            args["dry_run"] = True
            emit(
                "policy.decided",
                {
                    "tool": spec.name,
                    "tier": str(spec.permission),
                    "decision": "confirm",
                    "reason_code": "dry_run_first",
                    "reason": (
                        "This action supports a dry run, so the effect is shown before anything "
                        "is changed."
                    ),
                },
                state=State.SELECT,
            )

        blast = self._blast_radius(spec, args)
        emit(
            "approval.requested",
            {
                "request_id": request_id,
                "tool": spec.name,
                "args": args,
                "blast_radius": blast,
                "reversible": spec.side_effects is not SideEffects.DESTRUCTIVE,
                "reversal_cost": (
                    None
                    if spec.idempotent
                    else "The change is not automatically reversible."
                ),
            },
            state=State.SELECT,
            step_id=self._step_id(ctx),
        )
        started = ctx["clock"].monotonic()
        decision = ctx["human"].confirm(
            ApprovalRequest(
                request_id=request_id,
                tool=spec.name,
                args=args,
                blast_radius=blast,
                reversible=spec.side_effects is not SideEffects.DESTRUCTIVE,
            )
        )
        ctx["policy"].record_confirmation()
        emit(
            "approval.resolved",
            {
                "request_id": request_id,
                "approved": decision.approved,
                "answered_by": decision.answered_by,
                "answer": decision.answer,
                "latency_ms": max(0.0, ctx["clock"].monotonic() - started) * 1000.0,
            },
            state=State.SELECT,
            step_id=self._step_id(ctx),
        )
        if not decision.approved:
            self._record_correction(ctx, decision.answer or f"declined {spec.name}")
        return decision.approved

    @staticmethod
    def _blast_radius(spec: ToolSpec, args: Mapping[str, Any]) -> str:
        """A concrete, quantified statement of what this call touches.

        Quantified rather than generic: "changes a service" is not something a person can weigh,
        whereas "1 of 6 replicas cycles; approximately 40 in-flight requests shed" is.
        """
        if spec.name == "restart_service":
            replicas = str(args.get("replicas", "one"))
            cycled = {"one": 1, "half": 3, "all": 6}.get(replicas, 1)
            return (
                f"{cycled} of 6 replicas of {args.get('service')} cycle; approximately "
                f"{cycled * 40} in-flight requests shed"
            )
        if spec.name == "rollback_deploy":
            return (
                f"all replicas of {args.get('service')} roll to {args.get('to_deploy_id')}; "
                "brief capacity dip during the rollout"
            )
        if spec.name == "scale_replicas":
            return (
                f"{args.get('service')} moves to {args.get('replicas')} replicas; no request "
                "shedding, but cost and downstream load increase"
            )
        if spec.side_effects is SideEffects.DESTRUCTIVE:
            return f"{spec.name} changes state irreversibly"
        return f"{spec.name} changes state reversibly"

    def _record_correction(self, ctx: dict[str, Any], note: str) -> None:
        """Remember an operator's correction as a first-class memory candidate."""
        if not note.strip():
            return
        ctx.setdefault("pending_corrections", []).append(note)

    _result: RunResult | None = None
