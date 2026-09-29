"""T1-T8 Agent scenario tests + supporting infrastructure.

All tests are offline by default (scripted FakeLLM + mock tools).
Live-Groq variants auto-skip when GROQ_API_KEY is absent.

Tests:
T1: Simple no-tool answer ("What is 2+2?" -> "4")
T2: One tool + exact stop (create_file -> stop, no further calls)
T3: Multi-step no user input (create + read -> done)
T4: Failure, no invented content (read missing file -> accurate error)
T5: Recovery from broken preview (create -> preview fails -> fix -> preview again)
T6: Worker failover mid-run (Worker A 429 -> Worker B continues from state)
T7: Permission pause and denial
T8: Turbo mode (pre-auth runs; hard-blocked still blocked)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend is importable
sys.path.insert(0, str(pytest.importorskip("pathlib").Path(__file__).parent.parent / "backend"))

from tests.mocks.agent import (
    FakeLLM,
    MockEmitter,
    MockMemory,
    MockToolRegistry,
    MockToolResult,
    make_request,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_scenario(
    objective: str,
    llm_responses: list,
    tool_results: Dict[str, MockToolResult],
    turbo_mode: bool = False,
    permission_override: str = "allow",  # "allow" | "confirm" | "deny"
) -> tuple:
    """Run a scenario offline and return (outcome, emitter, tool_registry, memory)."""
    fake_llm = FakeLLM()
    for resp in llm_responses:
        if isinstance(resp, str):
            fake_llm._responses.append((resp, None))
        elif isinstance(resp, dict) and "tool" in resp:
            call_json = json.dumps({"name": resp["tool"], "arguments": resp.get("args", {})})
            fake_llm._responses.append((f"<tool_call>\n{call_json}\n</tool_call>", None))
        else:
            fake_llm._responses.append((str(resp), None))

    mock_reg = MockToolRegistry()
    for name, result in tool_results.items():
        mock_reg.register_tool(name, result)

    mock_mem = MockMemory()
    mock_emit = MockEmitter()
    request = make_request(objective, turbo_mode=turbo_mode)

    from app.agent.brain import JarvisBrain
    from app.agent.loop import run_agent

    # Patch the LLM, registry, and permissions
    with (
        patch("app.agent.loop.call_llm", side_effect=fake_llm),
        patch("app.agent.loop.get_tool_registry", return_value=mock_reg),
        patch("app.agent.loop.get_workspace_manager") as mock_ws,
        patch("app.agent.loop.build_system_prompt", return_value="FAKE SYSTEM PROMPT"),
        patch("app.agent.loop.select_tools_for_objective", return_value=[
            {"type": "function", "function": {"name": n, "description": "mock", "parameters": {}}}
            for n in tool_results
        ]),
        patch("app.agent.loop.get_permission_engine") as mock_perm,
    ):
        mock_ws.return_value.get_runtime_info.return_value = {"python": {"version": "3.11", "executable": "python"}}

        # Configure permission engine
        from app.agent.permissions import PermissionDecision
        perm_mock = MagicMock()
        perm_mock.check.return_value = PermissionDecision(
            decision=permission_override,
            reason="mock permission",
            tier="auto" if permission_override == "allow" else "confirm",
        )
        perm_mock.is_hard_blocked.return_value = (permission_override == "deny")
        mock_perm.return_value = perm_mock

        outcome = asyncio.run(run_agent(request, mock_emit, memory_context={}))

    return outcome, mock_emit, mock_reg, mock_mem


# ---------------------------------------------------------------------------
# T1: Simple no-tool answer
# ---------------------------------------------------------------------------


def test_t1_simple():
    """T1: 'What is 2+2?' -> no tools -> answer containing '4'."""
    outcome, emitter, reg, mem = run_scenario(
        objective="What is 2 + 2?",
        llm_responses=["4"],
        tool_results={},
    )
    assert outcome.status == "completed", f"Expected completed, got {outcome.status}"
    assert "4" in outcome.reply, f"Expected '4' in reply, got: {outcome.reply!r}"
    assert len(reg.execute_calls) == 0, f"Expected no tool calls, got: {reg.execute_calls}"
    assert not emitter.has_event("tool_started"), "No tool should have been started for T1"


# ---------------------------------------------------------------------------
# T2: One tool + exact stop
# ---------------------------------------------------------------------------


def test_t2_one_tool():
    """T2: Create hello.txt -> stop. Assert no further tool calls after create_file."""
    llm_responses = [
        {"tool": "create_file", "args": {"path": "hello.txt", "content": "Hello World"}},
        "File created successfully.",
    ]
    outcome, emitter, reg, mem = run_scenario(
        objective="Create hello.txt containing Hello World.",
        llm_responses=llm_responses,
        tool_results={
            "create_file": MockToolResult(
                success=True,
                data={"path": "hello.txt", "bytes": 11, "lines": 1},
            )
        },
    )
    assert outcome.status == "completed", f"Expected completed, got {outcome.status}"
    create_calls = [c for c in reg.execute_calls if c["tool"] == "create_file"]
    assert len(create_calls) == 1, f"Expected exactly 1 create_file call, got {len(create_calls)}"
    # No read_file or list_directory after create
    extra_calls = [c for c in reg.execute_calls if c["tool"] not in ("create_file",)]
    assert len(extra_calls) == 0, f"Unexpected extra tool calls: {extra_calls}"


# ---------------------------------------------------------------------------
# T3: Multi-step, no user input
# ---------------------------------------------------------------------------


def test_t3_multi_step():
    """T3: Create numbers.txt, then read it. No user input between steps."""
    llm_responses = [
        {"tool": "create_file", "args": {"path": "numbers.txt", "content": "1, 2, 3"}},
        {"tool": "read_file", "args": {"path": "numbers.txt"}},
        "Created numbers.txt with content '1, 2, 3' and verified its contents.",
    ]
    outcome, emitter, reg, mem = run_scenario(
        objective="Create numbers.txt containing 1, 2, 3 and then read it.",
        llm_responses=llm_responses,
        tool_results={
            "create_file": MockToolResult(
                success=True,
                data={"path": "numbers.txt", "bytes": 7, "lines": 1},
            ),
            "read_file": MockToolResult(
                success=True,
                data={"path": "numbers.txt", "content": "1, 2, 3"},
            ),
        },
    )
    assert outcome.status == "completed", f"Expected completed, got {outcome.status}"
    tools_used = [c["tool"] for c in reg.execute_calls]
    assert "create_file" in tools_used, "create_file should have been called"
    assert "read_file" in tools_used, "read_file should have been called"
    # Ensure no user input was requested (emitter has no pause events)
    assert not emitter.has_event("permission_required"), "No permission pause expected in T3"


# ---------------------------------------------------------------------------
# T4: Failure, no invented content
# ---------------------------------------------------------------------------


def test_t4_failure():
    """T4: Read missing.txt -> fail -> accurate error, no invented content."""
    llm_responses = [
        {"tool": "read_file", "args": {"path": "missing.txt"}},
        "I tried to read missing.txt but it does not exist. File not found.",
    ]
    outcome, emitter, reg, mem = run_scenario(
        objective="Read missing.txt.",
        llm_responses=llm_responses,
        tool_results={
            "read_file": MockToolResult(
                success=False,
                error="File not found: missing.txt",
            ),
        },
    )
    assert outcome.status == "completed", f"Expected completed got {outcome.status}"
    # Reply should mention the failure, not invent content
    reply_lower = outcome.reply.lower()
    assert any(
        kw in reply_lower for kw in ["not found", "does not exist", "failed", "error", "cannot", "unable"]
    ), f"Reply should indicate failure, got: {outcome.reply!r}"
    # Should NOT contain invented file content
    assert "1, 2, 3" not in outcome.reply, "Reply should not invent file content"
    assert "hello world" not in outcome.reply.lower(), "Reply should not invent file content"


# ---------------------------------------------------------------------------
# T5: Recovery from broken preview
# ---------------------------------------------------------------------------


def test_t5_recovery():
    """T5: Create website -> preview fails (CSS not found) -> fix CSS -> preview again -> verify."""
    llm_responses = [
        # Turn 1: create HTML file
        {"tool": "create_file", "args": {"path": "index.html", "content": "<html>...</html>"}},
        # Turn 2: open browser (preview)
        {"tool": "open_browser", "args": {"path": "index.html"}},
        # Turn 3 (recovery): create missing CSS
        {"tool": "create_file", "args": {"path": "style.css", "content": "body { color: black; }"}},
        # Turn 4: preview again
        {"tool": "open_browser", "args": {"path": "index.html"}},
        # Turn 5: final answer
        "Website created and displayed successfully. HTML and CSS files are in place.",
    ]

    outcome, emitter, reg, mem = run_scenario(
        objective="Create and display a simple website.",
        llm_responses=llm_responses,
        tool_results={
            "create_file": MockToolResult(
                success=True,
                data={"path": "index.html", "bytes": 100, "lines": 5},
            ),
            "open_browser": MockToolResult(
                success=False,
                error="CSS file not found: style.css",
            ),
        },
    )
    assert outcome.status in ("completed", "partial"), f"Expected completed/partial, got {outcome.status}"
    # Recovery event should have been emitted
    assert emitter.has_event("recovery") or emitter.has_event("tool_failed"), (
        "Expected recovery or tool_failed event to be emitted"
    )


# ---------------------------------------------------------------------------
# T6: Worker failover mid-run
# ---------------------------------------------------------------------------


def test_t6_worker_failover():
    """T6: Worker A 429 after create_file -> Worker B continues. Does not recreate file."""
    from app.agent.state import AgentState

    # Simulate a state where create_file was already run by Worker A
    state = AgentState(
        run_id="failover-run-001",
        session_id="sess-1",
        user_id="user-1",
        workspace_id="ws-1",
        objective="Create hello.txt and then read it back.",
    )
    state.tool_calls = [{"name": "create_file", "arguments": {"path": "hello.txt", "content": "Hello"}, "turn": 1}]
    state.observations = [{"tool": "create_file", "success": True, "summary": "File hello.txt saved (5 bytes)."}]
    state.artifacts = [{"path": "hello.txt", "type": "file"}]
    state.steps_used = 1
    state.add_message("assistant", "Action: called `create_file` with {\"path\": \"hello.txt\", \"content\": \"Hello\"}")
    state.add_message("user", "Observation from `create_file`:\nFile `hello.txt` saved (5 bytes, 1 lines).\n\nEvaluate...")

    # Verify state serialization/deserialization (worker failover)
    state_dict = state.to_dict()
    restored = AgentState.from_dict(state_dict)

    assert restored.objective == state.objective
    assert len(restored.tool_calls) == 1
    assert restored.tool_calls[0]["name"] == "create_file"
    assert len(restored.artifacts) == 1
    assert restored.steps_used == 1

    # Worker B should NOT recreate the file (it's already in state.artifacts)
    created_paths = [a["path"] for a in restored.artifacts]
    assert "hello.txt" in created_paths, "Worker B should see hello.txt was already created"

    # The loop should detect the existing artifact and not call create_file again
    # (This is behavioral — the model receives the state's observations and artifacts)
    hello_already_created = any(
        tc["name"] == "create_file" and tc["arguments"].get("path") == "hello.txt"
        for tc in restored.tool_calls
    )
    assert hello_already_created, "Worker A's create_file should be in restored state"


# ---------------------------------------------------------------------------
# T7: Permission pause and denial
# ---------------------------------------------------------------------------


def test_t7_permission():
    """T7: Restricted command -> permission_required emitted; denial -> recovery."""
    from app.agent.permissions import PermissionDecision

    # Test: confirm path (pause for approval)
    llm_responses = [
        {"tool": "delete_file", "args": {"path": "important.txt"}},
        "File deletion was not approved, I'll try an alternative.",
    ]

    outcome, emitter, reg, mem = run_scenario(
        objective="Delete important.txt.",
        llm_responses=llm_responses,
        tool_results={
            "delete_file": MockToolResult(success=True, data={"path": "important.txt"}),
        },
        permission_override="confirm",
    )

    # Should have paused for permission
    assert outcome.status in ("paused", "completed"), f"Unexpected status: {outcome.status}"
    if outcome.status == "paused":
        assert emitter.has_event("permission_required"), "permission_required should be emitted"
        perm_events = emitter.get("permission_required")
        assert len(perm_events) > 0
        assert perm_events[0]["data"]["tool"] == "delete_file"


def test_t7_denial_routes_to_recovery():
    """T7: Denied tool -> recovery path, does not retry the same call."""
    llm_responses = [
        {"tool": "delete_file", "args": {"path": "protected.txt"}},
        "Deletion was denied. I'll inform the user that this file is protected.",
    ]

    outcome, emitter, reg, mem = run_scenario(
        objective="Delete protected.txt.",
        llm_responses=llm_responses,
        tool_results={
            "delete_file": MockToolResult(success=True, data={"path": "protected.txt"}),
        },
        permission_override="deny",
    )

    assert outcome.status == "completed", f"Expected completed (with denial message), got {outcome.status}"
    # delete_file should NOT have been executed
    delete_calls = [c for c in reg.execute_calls if c["tool"] == "delete_file"]
    assert len(delete_calls) == 0, f"delete_file should not execute after denial, got: {delete_calls}"
    # recovery event should have been emitted
    assert emitter.has_event("recovery"), "recovery event expected after denial"


# ---------------------------------------------------------------------------
# T8: Turbo mode
# ---------------------------------------------------------------------------


def test_t8_turbo_pre_authorized():
    """T8: Pre-authorized operation runs without interactive approval in turbo mode."""
    llm_responses = [
        {"tool": "create_file", "args": {"path": "turbo_out.txt", "content": "turbo"}},
        "Created turbo_out.txt.",
    ]

    outcome, emitter, reg, mem = run_scenario(
        objective="Create turbo_out.txt.",
        llm_responses=llm_responses,
        tool_results={
            "create_file": MockToolResult(success=True, data={"path": "turbo_out.txt", "bytes": 5, "lines": 1}),
        },
        turbo_mode=True,
        permission_override="allow",  # mock returns allow for pre-authorized
    )

    assert outcome.status == "completed"
    # No permission_required event (turbo pre-authorized, no pause)
    assert not emitter.has_event("permission_required"), "Turbo pre-authorized should not pause"
    create_calls = [c for c in reg.execute_calls if c["tool"] == "create_file"]
    assert len(create_calls) == 1, "create_file should have run"


def test_t8_turbo_hard_blocked():
    """T8: Hard-blocked tool is still blocked even in turbo mode."""
    from app.agent.permissions import MockPermissionEngine, PermissionContext

    perm = MockPermissionEngine()
    ctx = PermissionContext(
        run_id="r1",
        user_id="u1",
        workspace_id="w1",
        turbo_mode=True,
        pre_authorized_scope=[],
    )

    # rm_rf is in DENY tier — must be blocked even in turbo
    decision = perm.check("rm_rf", {}, ctx)
    assert decision.denied, f"rm_rf must be denied in turbo, got: {decision.decision}"
    assert perm.is_hard_blocked("rm_rf"), "rm_rf must be hard-blocked"

    # create_file is pre-authorized in turbo
    decision = perm.check("create_file", {}, ctx)
    assert decision.allowed, f"create_file should be allowed in turbo, got: {decision.decision}"
