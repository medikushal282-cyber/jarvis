"""Unit tests for agent events emission and safety (P9a)."""

import pytest
from app.agent.loop import _EVENTS


def test_required_events_in_catalog():
    """Verify all high-level events exist in the canonical catalog."""
    expected = [
        "understanding",
        "planning",
        "tool_started",
        "tool_completed",
        "permission_required",
        "verification",
        "recovery",
        "worker_switching",
        "memory_used",
        "completed",
        "failed",
    ]
    for ev in expected:
        assert ev in _EVENTS, f"Event '{ev}' missing from canonical catalog"


def test_no_thought_events_in_catalog():
    """Agent events must NEVER emit hidden reasoning, chain of thought, or thoughts."""
    for key, val in _EVENTS.items():
        assert "thought" not in key.lower(), f"Event key '{key}' should not expose thought"
        assert "cot" not in key.lower(), f"Event key '{key}' should not expose CoT"
        assert "reasoning" not in key.lower(), f"Event key '{key}' should not expose reasoning"
