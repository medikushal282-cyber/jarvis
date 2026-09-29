"""
app/tools/base.py — Core tool contracts for the JARVIS Capability Layer.

Defines:
  - ToolResult  : canonical result object returned by every tool
  - ToolContext : security and authorization context for a tool invocation
  - Tool        : abstract base class for all capability tools

SECURITY FIX (CRITICAL):
  ToolContext.approved previously defaulted to True, which caused
  has_permission() to bypass all permission checks. This is now corrected:

  - approved=False (default)
  - approved=True means ONLY that a specific pending action has been
    explicitly approved by the user for this invocation — it does NOT
    grant any additional permissions beyond what the policy/context allows.
  - Permission evaluation uses the permissions set, not the approved flag.

Owner: Lohith (Capability / Tool Layer)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    """
    Canonical result returned by every tool execution.

    Fields:
        success   : True if the operation completed without error
        tool      : Name of the tool that produced this result
        result    : Structured output data (primary result payload)
        data      : Alias for result (kept for backward compatibility)
        error     : Structured error dict when success=False
        status    : Human-readable status string
        artifacts : List of artifact metadata dicts registered during execution
        metadata  : Additional structured metadata (permission info, timing, etc.)
    """
    success: bool
    tool: str
    result: Optional[Any] = None
    data: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        # Keep result ↔ data in sync for backward compatibility
        if self.data is None and self.result is not None:
            self.data = self.result
        elif self.result is None and self.data is not None:
            self.result = self.data

        # Auto-populate status
        if self.status is None:
            self.status = "completed" if self.success else "failed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "tool": self.tool,
            "result": self.result,
            "data": self.data,
            "error": self.error,
            "status": self.status,
            "artifacts": self.artifacts,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# ToolContext
# ---------------------------------------------------------------------------


class ToolContext(BaseModel):
    """
    Security and authorization context for a single tool invocation.

    IMPORTANT — approved flag semantics:
        approved=False (default): normal state
        approved=True: ONLY means that this specific pending destructive
            action has been explicitly approved by the user via the approval
            flow. It does NOT bypass permission checks. The permission set
            still controls what the tool is allowed to do.

    Permission evaluation:
        - Uses the permissions set + wildcard/alias matching
        - admin or * grants everything (for tests/trusted internal calls only)
        - approved flag does NOT short-circuit permission checks
    """
    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}

    run_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = "default_user"
    workspace_id: Optional[str] = "default"
    workspace_root: Optional[str] = "."
    emit: Optional[Any] = None

    # SECURITY FIX: Default changed from True → False.
    # approved=True means THIS SPECIFIC ACTION was explicitly user-approved.
    # It does NOT bypass the permission set.
    approved: bool = False

    timeout_s: int = 45

    # Default permission set: all standard permissions granted.
    # Pass a restricted set to enforce least-privilege.
    permissions: Set[str] = Field(
        default_factory=lambda: {
            "filesystem.read",
            "filesystem.write",
            "filesystem.delete",
            "terminal.execute",
            "git.read",
            "git.write",
            "git.push",
            "github.read",
            "github.write",
            "http.read",
            "http.write",
            "browser.execute",
            "browser.preview",
            "sandbox.execute",
            "vision.analyze",
            "attachment.read",
        }
    )
    allow_private_http: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def has_permission(self, permission: str) -> bool:
        """
        Evaluate whether the given permission is granted by this context.

        Evaluation order:
        1. admin / wildcard * → grants everything (explicit trusted contexts)
        2. Exact match in permissions set
        3. Wildcard prefix (filesystem.* matches filesystem.read)
        4. Alias match (browser.preview ↔ browser.execute)

        NOTE: The approved flag is intentionally NOT checked here.
              approved=True means the user approved a specific action,
              not that all permissions are granted.
        """
        if "*" in self.permissions or "admin" in self.permissions:
            return True
        if permission in self.permissions:
            return True
        # Wildcard prefix check
        parts = permission.split(".")
        if len(parts) >= 2 and f"{parts[0]}.*" in self.permissions:
            return True
        # Alias: browser.preview ↔ browser.execute
        _ALIASES = {
            "browser.preview": "browser.execute",
            "browser.execute": "browser.preview",
        }
        alias = _ALIASES.get(permission)
        if alias and alias in self.permissions:
            return True
        return False


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class Tool(ABC):
    """
    Abstract base class for all JARVIS capability tools.

    Subclasses must define:
        name                : str — unique tool identifier
        description         : str — human/LLM-facing description
        parameters          : dict — JSON Schema for arguments
        required_permissions: list — permission strings required to execute
        risk                : str — "low" | "medium" | "high"
    """
    name: str
    description: str
    parameters: Dict[str, Any]
    required_permissions: List[str] = []
    risk: str = "medium"  # Default risk level; subclasses should override

    @abstractmethod
    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        """Execute the tool with given arguments and security context."""
        pass

    def get_definition(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required_permissions": self.required_permissions,
            "risk": getattr(self, "risk", "medium"),
        }
