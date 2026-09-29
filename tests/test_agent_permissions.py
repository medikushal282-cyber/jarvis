"""Unit tests for agent permission checking and Turbo mode (P8)."""

import pytest
from app.agent.permissions import (
    MockPermissionEngine,
    PermissionContext,
    PermissionDecision,
    get_permission_engine,
)


def test_auto_tier_allowed():
    """Read-only and safe operations are auto-allowed."""
    engine = MockPermissionEngine()
    ctx = PermissionContext(run_id="r1", user_id="u1", workspace_id="ws1")
    decision = engine.check("read_file", {"path": "a.txt"}, ctx)
    assert decision.allowed
    assert decision.tier == "auto"


def test_confirm_tier_requires_confirmation():
    """Destructive or side-effecting operations require confirmation by default."""
    engine = MockPermissionEngine()
    ctx = PermissionContext(run_id="r1", user_id="u1", workspace_id="ws1")
    decision = engine.check("delete_file", {"path": "a.txt"}, ctx)
    assert decision.needs_confirmation
    assert decision.tier == "confirm"


def test_deny_tier_always_denied():
    """Hard-blocked tools are categorically denied."""
    engine = MockPermissionEngine()
    ctx = PermissionContext(run_id="r1", user_id="u1", workspace_id="ws1")
    decision = engine.check("rm_rf", {}, ctx)
    assert decision.denied
    assert decision.tier == "deny"


def test_turbo_mode_skips_pre_authorized():
    """Turbo mode automatically allows pre-authorized tools."""
    engine = MockPermissionEngine()
    ctx = PermissionContext(
        run_id="r1",
        user_id="u1",
        workspace_id="ws1",
        turbo_mode=True,
        pre_authorized_scope=["create_file"],
    )
    decision = engine.check("create_file", {"path": "a.txt", "content": "x"}, ctx)
    assert decision.allowed
    assert "Turbo" in decision.reason


def test_turbo_mode_still_blocks_hard_restricted():
    """Turbo mode NEVER allows hard-blocked tools."""
    engine = MockPermissionEngine()
    ctx = PermissionContext(
        run_id="r1",
        user_id="u1",
        workspace_id="ws1",
        turbo_mode=True,
    )
    decision = engine.check("rm_rf", {}, ctx)
    assert decision.denied
    assert decision.tier == "deny"
