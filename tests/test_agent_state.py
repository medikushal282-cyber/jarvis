"""Tests for AgentState: bounded fields, budget, loop detection, serialization."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.agent.state import AgentState, TurnDiagnostics, MAX_MESSAGES, MAX_OBSERVATIONS


class TestAgentStateBoundedFields:
    def test_messages_cap_enforced(self):
        state = AgentState(objective="test")
        # Add more than MAX_MESSAGES messages
        for i in range(MAX_MESSAGES + 10):
            state.add_message("user", f"message {i}")
        assert len(state.messages) <= MAX_MESSAGES, f"Messages should be capped at {MAX_MESSAGES}"

    def test_observations_cap_enforced(self):
        state = AgentState(objective="test")
        for i in range(MAX_OBSERVATIONS + 5):
            state.add_observation("read_file", True, f"observation {i}")
        assert len(state.observations) <= MAX_OBSERVATIONS

    def test_first_message_preserved_after_cap(self):
        """The initial objective message (index 0) must survive eviction."""
        state = AgentState(objective="test")
        state.add_message("user", "ORIGINAL OBJECTIVE")
        for i in range(MAX_MESSAGES + 5):
            state.add_message("assistant", f"turn {i}")
        # First message should still be ORIGINAL OBJECTIVE
        assert state.messages[0]["content"] == "ORIGINAL OBJECTIVE"

    def test_errors_cap_enforced(self):
        state = AgentState(objective="test")
        for i in range(15):
            state.add_error("TestError", f"error {i}")
        assert len(state.errors) <= 10


class TestBudget:
    def test_step_budget(self):
        state = AgentState(objective="test", max_steps=3)
        state.steps_used = 3
        reason = state.budget_exhausted()
        assert reason is not None, "Should report exhausted"
        assert "step" in reason.lower()

    def test_token_budget(self):
        state = AgentState(objective="test", max_tokens=1000)
        state.tokens_used = 1001
        reason = state.budget_exhausted()
        assert reason is not None
        assert "token" in reason.lower()

    def test_time_budget(self):
        state = AgentState(objective="test", max_wall_secs=1)
        state.start_time = time.time() - 10  # 10 seconds ago
        reason = state.budget_exhausted()
        assert reason is not None
        assert "time" in reason.lower()

    def test_priority_order_steps_first(self):
        """Steps exhausted -> step reason, not token reason."""
        state = AgentState(objective="test", max_steps=0, max_tokens=0)
        state.steps_used = 1
        state.tokens_used = 1
        reason = state.budget_exhausted()
        assert reason is not None
        assert "step" in reason.lower(), f"Should be step budget first, got: {reason}"


class TestLoopDetection:
    def test_loop_not_detected_first_occurrence(self):
        state = AgentState(objective="test")
        state.register_call("read_file", {"path": "a.txt"})
        assert not state.is_loop_detected("read_file", {"path": "a.txt"})

    def test_loop_detected_after_repeated_calls(self):
        state = AgentState(objective="test")
        state.register_call("read_file", {"path": "a.txt"})
        state.register_call("read_file", {"path": "a.txt"})
        assert state.is_loop_detected("read_file", {"path": "a.txt"})

    def test_loop_not_detected_different_args(self):
        state = AgentState(objective="test")
        state.register_call("read_file", {"path": "a.txt"})
        state.register_call("read_file", {"path": "b.txt"})
        assert not state.is_loop_detected("read_file", {"path": "a.txt"})

    def test_loop_not_detected_different_tool(self):
        state = AgentState(objective="test")
        state.register_call("read_file", {"path": "a.txt"})
        state.register_call("create_file", {"path": "a.txt", "content": "x"})
        assert not state.is_loop_detected("read_file", {"path": "a.txt"})


class TestSerialization:
    def test_roundtrip(self):
        state = AgentState(
            run_id="test-001",
            session_id="sess-1",
            objective="test roundtrip",
            steps_used=3,
            recovery_attempts=1,
        )
        state.add_message("user", "hello")
        state.add_observation("read_file", True, "content found")
        state.add_error("TestError", "something failed")
        state.artifacts.append({"path": "out.txt", "type": "file"})

        d = state.to_dict()
        restored = AgentState.from_dict(d)

        assert restored.run_id == "test-001"
        assert restored.session_id == "sess-1"
        assert restored.objective == "test roundtrip"
        assert restored.steps_used == 3
        assert restored.recovery_attempts == 1
        assert len(restored.observations) == 1
        assert len(restored.errors) == 1
        assert len(restored.artifacts) == 1

    def test_turn_diagnostics_serialized(self):
        state = AgentState(objective="test")
        diag = TurnDiagnostics(turn=1, model="gpt-x", tool_count=3,
                               prompt_tokens=100, completion_tokens=50, total_tokens=150)
        state.record_turn_diagnostics(diag)

        d = state.to_dict()
        assert len(d["turn_diagnostics"]) == 1
        assert state.tokens_used == 150

        restored = AgentState.from_dict(d)
        assert len(restored.turn_diagnostics) == 1
        assert restored.turn_diagnostics[0].total_tokens == 150
