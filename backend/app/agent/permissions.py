"""Permission engine integration for the JARVIS agent.

The agent CONSUMES permission checking; it never reimplements the policy engine.
This module defines the protocol (interface contract) and provides a mock
adapter for offline development and testing.

When Lohit's real engine is merged, change JARVIS_PERMISSION_ENGINE=real and
RealPermissionAdapter will load it. The agent loop code does not change.

TURBO POLICY (enforced here, not in the agent loop):
- Turbo skips interactive approval for PRE-AUTHORIZED capabilities only
- Hard security restrictions (DENY tier) are ALWAYS enforced in turbo mode
- Turbo is NOT allow_everything=True

Ported policy decision logic from brain/loop/engine.py PolicyEngine.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PermissionContext:
    """Context passed to the permission engine for a specific tool call."""

    run_id: str
    user_id: str
    workspace_id: str
    turbo_mode: bool = False
    pre_authorized_scope: List[str] = field(default_factory=list)
    session_id: str = ""


@dataclass
class PermissionDecision:
    """Result of evaluating one tool call."""

    decision: Literal["allow", "confirm", "deny"]
    reason: str
    tier: str = "auto"  # auto | confirm | deny

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    @property
    def needs_confirmation(self) -> bool:
        return self.decision == "confirm"

    @property
    def denied(self) -> bool:
        return self.decision == "deny"


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PermissionEngineProtocol(Protocol):
    """Interface contract for the permission engine (Lohit's ownership)."""

    def check(
        self, tool_name: str, args: Dict[str, Any], ctx: PermissionContext
    ) -> PermissionDecision:
        """Evaluate whether ``tool_name`` may run with ``args`` given ``ctx``."""
        ...

    def is_hard_blocked(self, tool_name: str) -> bool:
        """Return True if this tool is categorically blocked (DENY tier)."""
        ...

    def is_turbo_pre_authorized(self, tool_name: str, scope: List[str]) -> bool:
        """Return True if this tool is pre-authorized for turbo within the given scope."""
        ...


# ---------------------------------------------------------------------------
# Mock adapter (offline / unmerged)
# ---------------------------------------------------------------------------

# Tools that require confirmation before execution (CONFIRM tier)
_CONFIRM_TIER: frozenset[str] = frozenset(
    {
        "delete_file",
        "run_command",
        "terminal_exec",
        "git_push",
        "git_reset",
        "git_force_push",
        "rollback_deploy",
        "drop_database",
    }
)

# Tools that are categorically blocked (DENY tier) — never run at any autonomy level
_DENY_TIER: frozenset[str] = frozenset(
    {
        "rm_rf",
        "format_drive",
        "shutdown_system",
        "kill_process_all",
        "sudo_exec",
        "exfiltrate_data",
    }
)

# Default pre-authorized scope for turbo mode
_TURBO_DEFAULT_SCOPE: frozenset[str] = frozenset(
    {
        "read_file",
        "write_file",
        "create_file",
        "list_directory",
        "update_file",
        "search_files",
        "http_get",
        "browser_navigate",
        "browser_screenshot",
        "open_browser",
        "git_status",
        "git_diff",
        "git_add",
        "git_commit",
    }
)


class MockPermissionEngine:
    """Mock permission engine for offline development and testing.

    Behaviour matches the intended real engine:
    - DENY tier: always denied, even in turbo
    - CONFIRM tier: needs confirmation unless turbo pre-authorized
    - AUTO tier: allowed (read-only / safe operations)
    """

    def check(
        self, tool_name: str, args: Dict[str, Any], ctx: PermissionContext
    ) -> PermissionDecision:
        # 1. Hard blocks: always denied
        if self.is_hard_blocked(tool_name):
            return PermissionDecision(
                decision="deny",
                tier="deny",
                reason=f"Tool '{tool_name}' is categorically blocked and cannot run at any autonomy level.",
            )

        # 2. Turbo pre-authorization check
        if ctx.turbo_mode:
            if self.is_turbo_pre_authorized(tool_name, ctx.pre_authorized_scope or list(_TURBO_DEFAULT_SCOPE)):
                return PermissionDecision(
                    decision="allow",
                    tier="confirm",
                    reason=f"Turbo mode: '{tool_name}' is pre-authorized within the session scope.",
                )

        # 3. Confirm tier
        if tool_name in _CONFIRM_TIER:
            return PermissionDecision(
                decision="confirm",
                tier="confirm",
                reason=f"Tool '{tool_name}' has side-effects and requires user approval.",
            )

        # 4. Everything else: auto-allow (read-only / safe)
        return PermissionDecision(
            decision="allow",
            tier="auto",
            reason="Read-only or safe operation; proceeds without interruption.",
        )

    def is_hard_blocked(self, tool_name: str) -> bool:
        return tool_name in _DENY_TIER

    def is_turbo_pre_authorized(self, tool_name: str, scope: List[str]) -> bool:
        return tool_name in scope or tool_name in _TURBO_DEFAULT_SCOPE


# ---------------------------------------------------------------------------
# Real adapter stub (loads when JARVIS_PERMISSION_ENGINE=real)
# ---------------------------------------------------------------------------


class RealPermissionAdapter:
    """Thin wrapper around Lohit's real permission engine.

    Replace the body of each method with the real import when merged.
    Config: set JARVIS_PERMISSION_ENGINE=real in environment.
    """

    def check(
        self, tool_name: str, args: Dict[str, Any], ctx: PermissionContext
    ) -> PermissionDecision:
        # TODO (Lohit handoff): import and delegate to real engine
        raise NotImplementedError("Real permission engine not yet merged. Set JARVIS_PERMISSION_ENGINE=mock.")

    def is_hard_blocked(self, tool_name: str) -> bool:
        raise NotImplementedError

    def is_turbo_pre_authorized(self, tool_name: str, scope: List[str]) -> bool:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_permission_engine() -> PermissionEngineProtocol:
    """Return the configured permission engine instance."""
    mode = os.environ.get("JARVIS_PERMISSION_ENGINE", "mock").lower()
    if mode == "real":
        return RealPermissionAdapter()
    return MockPermissionEngine()


__all__ = [
    "PermissionContext",
    "PermissionDecision",
    "PermissionEngineProtocol",
    "MockPermissionEngine",
    "RealPermissionAdapter",
    "get_permission_engine",
]
