"""Explicit, bounded AgentState for the JARVIS autonomous agent loop.

This is the canonical run-level state object. It is small enough to be
serialized and handed to a different worker mid-run (failover). Fields are
bounded: observations and messages are capped, not grown unbounded.

Ported: budget triage structure from brain/loop/engine.py (steps/tokens/time).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Hard limits for bounded fields
MAX_MESSAGES = 40          # messages kept in context window
MAX_OBSERVATIONS = 20      # raw observations kept before compaction
MAX_ERRORS = 10            # error records kept
MAX_RECOVERY_ATTEMPTS = 3  # loop recovery limit


@dataclass
class TurnDiagnostics:
    """Per-LLM-turn diagnostics. Logged to dev stream, never shown to users."""

    turn: int
    model: str
    tool_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn,
            "model": self.model,
            "tool_count": self.tool_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgentState:
    """Complete run-level state. Sufficient for a different worker to resume mid-run.

    Invariants:
    - ``messages`` length <= MAX_MESSAGES (oldest evicted, always keeping turn 0 + last N)
    - ``observations`` length <= MAX_OBSERVATIONS
    - ``errors`` length <= MAX_ERRORS
    - ``recovery_attempts`` <= MAX_RECOVERY_ATTEMPTS (enforced by loop)
    - ``status`` one of: running | permission_wait | completed | failed | partial | cancelled
    """

    # Identity
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    user_id: str = ""
    workspace_id: str = ""

    # Task
    objective: str = ""
    current_goal: str = ""   # the step-level goal within the objective
    current_action: str = "" # what the agent is about to do

    # Conversation history (bounded)
    messages: List[Dict[str, Any]] = field(default_factory=list)

    # Memory context loaded at run start (from Kushal's interface)
    memory_context: Dict[str, Any] = field(default_factory=dict)

    # Tool calls made this run (list of {"name", "arguments", "turn"})
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    # Observations from tool results (bounded; summarised when full)
    observations: List[Dict[str, Any]] = field(default_factory=list)

    # Produced artifacts (files, previews)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)

    # Verification record: {"checked": bool, "evidence": str, "pass": bool}
    verification: Optional[Dict[str, Any]] = None

    # Error records
    errors: List[Dict[str, Any]] = field(default_factory=list)

    # Recovery
    recovery_attempts: int = 0

    # Status
    status: str = "running"  # running | permission_wait | completed | failed | partial | cancelled

    # Turbo / permission
    turbo_mode: bool = False
    pre_authorized_scope: List[str] = field(default_factory=list)
    pending_approval: Optional[Dict[str, Any]] = None  # set when status=permission_wait

    # Budget tracking
    start_time: float = field(default_factory=time.time)
    max_steps: int = 15
    max_tokens: int = 150_000   # total across all turns
    max_wall_secs: int = 300    # 5 minutes
    steps_used: int = 0
    tokens_used: int = 0
    turn_diagnostics: List[TurnDiagnostics] = field(default_factory=list)

    # Loop detection: last N (call_name, frozen_args) tuples
    _call_fingerprints: List[str] = field(default_factory=list, repr=False)

    def add_message(self, role: str, content: str) -> None:
        """Add a message, evicting old ones when the cap is reached."""
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > MAX_MESSAGES:
            # Keep the very first (objective) + the most recent MAX_MESSAGES-1
            self.messages = [self.messages[0]] + self.messages[-(MAX_MESSAGES - 1):]

    def add_observation(self, tool: str, success: bool, summary: str, raw: Any = None) -> None:
        """Record a tool observation, evicting oldest when full."""
        obs = {"tool": tool, "success": success, "summary": summary}
        if raw is not None:
            obs["raw"] = raw
        self.observations.append(obs)
        if len(self.observations) > MAX_OBSERVATIONS:
            self.observations = self.observations[-MAX_OBSERVATIONS:]

    def add_error(self, kind: str, message: str, tool: Optional[str] = None) -> None:
        err = {"kind": kind, "message": message}
        if tool:
            err["tool"] = tool
        self.errors.append(err)
        if len(self.errors) > MAX_ERRORS:
            self.errors = self.errors[-MAX_ERRORS:]

    def record_turn_diagnostics(self, diag: TurnDiagnostics) -> None:
        self.turn_diagnostics.append(diag)
        self.tokens_used += diag.total_tokens

    def register_call(self, tool_name: str, args: Dict[str, Any]) -> None:
        """Register a tool call for loop detection."""
        import json
        try:
            fp = f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)}"
        except Exception:
            fp = f"{tool_name}:{str(args)}"
        self.tool_calls.append({"name": tool_name, "arguments": args, "turn": self.steps_used})
        self._call_fingerprints.append(fp)
        # Keep last 20 fingerprints
        if len(self._call_fingerprints) > 20:
            self._call_fingerprints = self._call_fingerprints[-20:]

    def is_loop_detected(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """Return True if the exact same call+args appeared in the last 3 turns."""
        import json
        try:
            fp = f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)}"
        except Exception:
            fp = f"{tool_name}:{str(args)}"
        recent = self._call_fingerprints[-3:]
        return recent.count(fp) >= 2  # appeared 2+ times in last 3

    def budget_exhausted(self) -> Optional[str]:
        """Return reason string if any budget is exhausted, else None. Fixed priority order."""
        if self.steps_used >= self.max_steps:
            return f"step budget exhausted ({self.steps_used}/{self.max_steps})"
        if self.tokens_used >= self.max_tokens:
            return f"token budget exhausted ({self.tokens_used}/{self.max_tokens})"
        elapsed = time.time() - self.start_time
        if elapsed >= self.max_wall_secs:
            return f"time budget exhausted ({int(elapsed)}s/{self.max_wall_secs}s)"
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for worker failover or persistence."""
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "objective": self.objective,
            "current_goal": self.current_goal,
            "current_action": self.current_action,
            "memory_context": self.memory_context,
            "tool_calls": self.tool_calls,
            "observations": self.observations,
            "artifacts": self.artifacts,
            "verification": self.verification,
            "errors": self.errors,
            "recovery_attempts": self.recovery_attempts,
            "status": self.status,
            "turbo_mode": self.turbo_mode,
            "pre_authorized_scope": self.pre_authorized_scope,
            "pending_approval": self.pending_approval,
            "start_time": self.start_time,
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_wall_secs": self.max_wall_secs,
            "steps_used": self.steps_used,
            "tokens_used": self.tokens_used,
            "turn_diagnostics": [d.as_dict() for d in self.turn_diagnostics],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentState":
        """Restore from serialized dict for worker failover."""
        state = cls(
            run_id=d.get("run_id", ""),
            session_id=d.get("session_id", ""),
            user_id=d.get("user_id", ""),
            workspace_id=d.get("workspace_id", ""),
            objective=d.get("objective", ""),
            current_goal=d.get("current_goal", ""),
            current_action=d.get("current_action", ""),
            memory_context=d.get("memory_context", {}),
            tool_calls=d.get("tool_calls", []),
            observations=d.get("observations", []),
            artifacts=d.get("artifacts", []),
            verification=d.get("verification"),
            errors=d.get("errors", []),
            recovery_attempts=d.get("recovery_attempts", 0),
            status=d.get("status", "running"),
            turbo_mode=d.get("turbo_mode", False),
            pre_authorized_scope=d.get("pre_authorized_scope", []),
            pending_approval=d.get("pending_approval"),
            start_time=d.get("start_time", time.time()),
            max_steps=d.get("max_steps", 15),
            max_tokens=d.get("max_tokens", 150_000),
            max_wall_secs=d.get("max_wall_secs", 300),
            steps_used=d.get("steps_used", 0),
            tokens_used=d.get("tokens_used", 0),
        )
        for td in d.get("turn_diagnostics", []):
            state.turn_diagnostics.append(TurnDiagnostics(**td))
        return state


__all__ = ["AgentState", "TurnDiagnostics", "MAX_MESSAGES", "MAX_OBSERVATIONS", "MAX_RECOVERY_ATTEMPTS"]
