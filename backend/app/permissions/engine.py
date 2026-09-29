"""
JARVIS Permission Engine
========================
Central permission management for the Capability / Tool Layer.

Implements:
  - PermissionPolicy  (Normal | Turbo modes)
  - PermissionEngine  (evaluate, request, validate)
  - ApprovalRequest   (secure approval lifecycle)
  - Permission constants

Architecture:
  ToolRegistry → PermissionEngine → Capability

Owner: Lohith (Capability / Tool Layer)
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Permission mode
# ---------------------------------------------------------------------------


class PermissionMode(str, Enum):
    """
    NORMAL: Every tool invocation is evaluated against the configured
            permission set. Missing permissions produce a permission_required
            result that pauses the run for user approval.
    TURBO:  Pre-authorised permissions execute without per-action approval.
            Hard security restrictions (workspace containment, SSRF, command
            policy, sandbox isolation, etc.) are NEVER bypassed.
    """
    NORMAL = "normal"
    TURBO = "turbo"


# ---------------------------------------------------------------------------
# Permission constants
# ---------------------------------------------------------------------------

# All known permission strings in the system
PERMISSION_FILESYSTEM_READ   = "filesystem.read"
PERMISSION_FILESYSTEM_WRITE  = "filesystem.write"
PERMISSION_FILESYSTEM_DELETE = "filesystem.delete"
PERMISSION_TERMINAL_EXECUTE  = "terminal.execute"
PERMISSION_BROWSER_PREVIEW   = "browser.preview"
PERMISSION_BROWSER_EXECUTE   = "browser.execute"   # backward-compat alias
PERMISSION_GIT_READ          = "git.read"
PERMISSION_GIT_WRITE         = "git.write"
PERMISSION_GIT_PUSH          = "git.push"
PERMISSION_GITHUB_READ       = "github.read"
PERMISSION_GITHUB_WRITE      = "github.write"
PERMISSION_HTTP_READ         = "http.read"
PERMISSION_HTTP_WRITE        = "http.write"
PERMISSION_SANDBOX_EXECUTE   = "sandbox.execute"
PERMISSION_VISION_ANALYZE    = "vision.analyze"
PERMISSION_ATTACHMENT_READ   = "attachment.read"

# Canonical permission aliases mapping
PERMISSION_ALIASES: Dict[str, str] = {
    # browser.preview → browser.execute (legacy internal name)
    PERMISSION_BROWSER_PREVIEW: PERMISSION_BROWSER_EXECUTE,
}

# Default full permission set (used when no restrictions are configured)
DEFAULT_PERMISSIONS: Set[str] = {
    PERMISSION_FILESYSTEM_READ,
    PERMISSION_FILESYSTEM_WRITE,
    PERMISSION_FILESYSTEM_DELETE,
    PERMISSION_TERMINAL_EXECUTE,
    PERMISSION_BROWSER_EXECUTE,
    PERMISSION_BROWSER_PREVIEW,
    PERMISSION_GIT_READ,
    PERMISSION_GIT_WRITE,
    PERMISSION_GIT_PUSH,
    PERMISSION_GITHUB_READ,
    PERMISSION_GITHUB_WRITE,
    PERMISSION_HTTP_READ,
    PERMISSION_HTTP_WRITE,
    PERMISSION_SANDBOX_EXECUTE,
    PERMISSION_VISION_ANALYZE,
    PERMISSION_ATTACHMENT_READ,
}

# Risk classification constants
RISK_LOW    = "low"
RISK_MEDIUM = "medium"
RISK_HIGH   = "high"


# ---------------------------------------------------------------------------
# Permission Policy
# ---------------------------------------------------------------------------


@dataclass
class PermissionPolicy:
    """
    Defines the authorization policy for a run/session.

    Attributes:
        mode:        NORMAL or TURBO
        permissions: The set of permissions granted for this policy.
                     In NORMAL mode: each required permission is checked;
                       missing → permission_required.
                     In TURBO mode: pre-authorized permissions execute
                       automatically; unconfigured permissions still
                       produce permission_required.
    """
    mode: PermissionMode = PermissionMode.NORMAL
    permissions: Set[str] = field(default_factory=lambda: set(DEFAULT_PERMISSIONS))

    def normalize(self) -> "PermissionPolicy":
        """Expand aliases so internal checks are uniform."""
        expanded: Set[str] = set()
        for perm in self.permissions:
            expanded.add(perm)
            # If user granted browser.preview, also grant browser.execute
            alias = PERMISSION_ALIASES.get(perm)
            if alias:
                expanded.add(alias)
            # Reverse: if user granted browser.execute also grant browser.preview
            for canon, target in PERMISSION_ALIASES.items():
                if target == perm:
                    expanded.add(canon)
        self.permissions = expanded
        return self

    def has_permission(self, permission: str) -> bool:
        """
        Check whether a permission is granted by this policy.
        Supports:
          - exact match
          - wildcard (filesystem.* matches filesystem.read)
          - admin / * grants everything
          - alias mapping (browser.preview ↔ browser.execute)
        """
        if "*" in self.permissions or "admin" in self.permissions:
            return True
        if permission in self.permissions:
            return True
        # Wildcard check
        parts = permission.split(".")
        if len(parts) >= 2 and f"{parts[0]}.*" in self.permissions:
            return True
        # Alias check
        alias = PERMISSION_ALIASES.get(permission)
        if alias and alias in self.permissions:
            return True
        # Reverse alias check
        for canon, target in PERMISSION_ALIASES.items():
            if target == permission and canon in self.permissions:
                return True
        return False

    @classmethod
    def default_normal(cls) -> "PermissionPolicy":
        """Standard full-permission Normal mode policy (for testing/local dev)."""
        return cls(mode=PermissionMode.NORMAL, permissions=set(DEFAULT_PERMISSIONS)).normalize()

    @classmethod
    def default_turbo(cls) -> "PermissionPolicy":
        """Standard full-permission Turbo mode policy (for trusted automated runs)."""
        return cls(mode=PermissionMode.TURBO, permissions=set(DEFAULT_PERMISSIONS)).normalize()

    @classmethod
    def read_only(cls) -> "PermissionPolicy":
        """Read-only Normal mode policy."""
        return cls(
            mode=PermissionMode.NORMAL,
            permissions={
                PERMISSION_FILESYSTEM_READ,
                PERMISSION_GIT_READ,
                PERMISSION_GITHUB_READ,
                PERMISSION_HTTP_READ,
                PERMISSION_VISION_ANALYZE,
                PERMISSION_ATTACHMENT_READ,
            }
        ).normalize()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PermissionPolicy":
        mode = PermissionMode(data.get("mode", "normal"))
        permissions = set(data.get("permissions", DEFAULT_PERMISSIONS))
        return cls(mode=mode, permissions=permissions).normalize()


# ---------------------------------------------------------------------------
# Approval Request
# ---------------------------------------------------------------------------


class ApprovalStatus(str, Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    DENIED   = "denied"
    EXPIRED  = "expired"
    INVALID  = "invalid"


@dataclass
class ApprovalRequest:
    """
    Represents a pending approval for a capability action.

    Security properties:
    - Bound to a specific run_id
    - Bound to a specific tool + permission + arguments hash
    - Has an expiration timestamp
    - Status transitions are one-way (pending → approved/denied/expired)
    """
    request_id: str
    run_id: str
    tool: str
    permission: str
    summary: str
    risk: str
    arguments_hash: str          # SHA256 of canonical argument JSON
    original_arguments: Dict[str, Any]
    created_at: float
    expires_at: float
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    status: ApprovalStatus = ApprovalStatus.PENDING

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def is_valid_for_resume(self, run_id: str, tool: str, arguments: Dict[str, Any]) -> bool:
        """
        Validate that a resume request matches the original approval context.
        Prevents:
        - Cross-run approval
        - Tool substitution
        - Argument substitution
        """
        if self.run_id != run_id:
            return False
        if self.tool != tool:
            return False
        if self.is_expired():
            return False
        if self.status != ApprovalStatus.APPROVED:
            return False
        # Verify argument integrity
        actual_hash = _hash_arguments(arguments)
        return actual_hash == self.arguments_hash

    def to_dict(self) -> Dict[str, Any]:
        """Safe public serialization — does NOT include raw arguments."""
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "tool": self.tool,
            "permission": self.permission,
            "summary": self.summary,
            "risk": self.risk,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status.value,
            "session_id": self.session_id,
            "user_id": self.user_id,
        }


def _hash_arguments(arguments: Dict[str, Any]) -> str:
    """Deterministic SHA256 hash of arguments dict for integrity verification."""
    import json
    canonical = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Permission Engine
# ---------------------------------------------------------------------------


class PermissionEngine:
    """
    Central permission evaluation and approval lifecycle manager.

    Responsibilities:
    1. Evaluate whether a tool execution is authorized
    2. Generate structured ApprovalRequest when authorization is needed
    3. Validate and consume approvals on resume
    4. Track approval request state (pending, approved, expired, etc.)

    Thread safety: Uses a plain dict — appropriate for single-process async.
    For multi-process/distributed, replace with a proper store.
    """

    # Approval TTL in seconds (5 minutes)
    APPROVAL_TTL = 300

    def __init__(self):
        self._pending_approvals: Dict[str, ApprovalRequest] = {}

    def evaluate(
        self,
        tool_name: str,
        required_permission: str,
        policy: PermissionPolicy,
        arguments: Dict[str, Any],
        risk: str = RISK_MEDIUM,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        """
        Evaluate whether the policy grants the required permission.

        Returns:
            None if permission is granted (execution may proceed).
            ApprovalRequest if execution must be paused for approval.

        In TURBO mode: if the permission is configured, returns None (auto-approved).
        In NORMAL mode: always generates an ApprovalRequest for any tool that
            requires a permission that was not explicitly pre-approved for this
            specific action. However, if the permission IS in the policy's set
            and mode is NORMAL, it is considered authorized (the "configured"
            part of Normal mode means pre-authorized by the session policy).
        """
        if policy.has_permission(required_permission):
            # Permission is configured — execution authorized
            return None

        # Permission not configured — generate approval request
        req = self._create_request(
            tool_name=tool_name,
            permission=required_permission,
            arguments=arguments,
            risk=risk,
            run_id=run_id or "unknown",
            session_id=session_id,
            user_id=user_id,
            summary=summary or f"Execute tool '{tool_name}' requiring {required_permission}",
        )
        self._pending_approvals[req.request_id] = req
        return req

    def _create_request(
        self,
        tool_name: str,
        permission: str,
        arguments: Dict[str, Any],
        risk: str,
        run_id: str,
        session_id: Optional[str],
        user_id: Optional[str],
        summary: str,
    ) -> ApprovalRequest:
        now = time.time()
        return ApprovalRequest(
            request_id=f"perm_{uuid.uuid4().hex[:12]}",
            run_id=run_id,
            tool=tool_name,
            permission=permission,
            summary=summary,
            risk=risk,
            arguments_hash=_hash_arguments(arguments),
            original_arguments=dict(arguments),
            created_at=now,
            expires_at=now + self.APPROVAL_TTL,
            session_id=session_id,
            user_id=user_id,
            status=ApprovalStatus.PENDING,
        )

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        return self._pending_approvals.get(request_id)

    def approve(self, request_id: str, run_id: str) -> ApprovalRequest:
        """
        Mark a request as approved.

        Validates:
        - request exists
        - belongs to the specified run
        - is still pending and not expired
        """
        req = self._pending_approvals.get(request_id)
        if req is None:
            raise ValueError(f"Approval request '{request_id}' not found")
        if req.run_id != run_id:
            raise ValueError("Approval request does not belong to this run")
        if req.is_expired():
            req.status = ApprovalStatus.EXPIRED
            raise ValueError(f"Approval request '{request_id}' has expired")
        if req.status != ApprovalStatus.PENDING:
            raise ValueError(f"Approval request '{request_id}' is not pending (status={req.status.value})")
        req.status = ApprovalStatus.APPROVED
        return req

    def deny(self, request_id: str, run_id: str) -> ApprovalRequest:
        """Mark a request as denied."""
        req = self._pending_approvals.get(request_id)
        if req is None:
            raise ValueError(f"Approval request '{request_id}' not found")
        if req.run_id != run_id:
            raise ValueError("Approval request does not belong to this run")
        if req.status != ApprovalStatus.PENDING:
            raise ValueError(f"Approval request '{request_id}' is not pending")
        req.status = ApprovalStatus.DENIED
        return req

    def validate_resume(
        self,
        request_id: str,
        run_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> ApprovalRequest:
        """
        Validate that a resume is legitimate before re-executing the tool.

        Raises ValueError with descriptive code on any validation failure.
        """
        req = self._pending_approvals.get(request_id)
        if req is None:
            raise ValueError("PERMISSION_REQUEST_INVALID: Unknown request_id")
        if req.run_id != run_id:
            raise ValueError("PERMISSION_REQUEST_INVALID: Cross-run approval attempt")
        if req.tool != tool_name:
            raise ValueError("PERMISSION_REQUEST_INVALID: Tool mismatch — argument substitution detected")
        if req.is_expired():
            req.status = ApprovalStatus.EXPIRED
            raise ValueError("PERMISSION_REQUEST_EXPIRED: Approval request has expired")
        if req.status == ApprovalStatus.DENIED:
            raise ValueError("PERMISSION_DENIED: Request was denied by user")
        if req.status != ApprovalStatus.APPROVED:
            raise ValueError(f"PERMISSION_REQUEST_INVALID: Request status is '{req.status.value}'")

        # Verify argument integrity (replay/substitution protection)
        actual_hash = _hash_arguments(arguments)
        if actual_hash != req.arguments_hash:
            raise ValueError("PERMISSION_REQUEST_INVALID: Argument tampering detected")

        return req

    def expire_old_requests(self) -> int:
        """Mark and count expired pending requests. Returns count expired."""
        count = 0
        for req in self._pending_approvals.values():
            if req.status == ApprovalStatus.PENDING and req.is_expired():
                req.status = ApprovalStatus.EXPIRED
                count += 1
        return count

    def clear_run(self, run_id: str) -> None:
        """Remove all approval requests for a completed run."""
        to_remove = [rid for rid, req in self._pending_approvals.items() if req.run_id == run_id]
        for rid in to_remove:
            del self._pending_approvals[rid]


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_global_engine = PermissionEngine()


def get_permission_engine() -> PermissionEngine:
    return _global_engine
