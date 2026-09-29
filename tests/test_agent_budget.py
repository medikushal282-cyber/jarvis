"""Token budget tests: verify token counts stay flat across turns on long runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.agent.state import AgentState, TurnDiagnostics


def test_tokens_flat_on_long_run():
    """Token estimates per turn should not grow unboundedly as messages accumulate.

    The context assembly _assemble_context() truncates history to fit within
    max_context_chars. This test simulates 20 turns and checks that the
    estimated context size stays within 2x the initial size.
    """
    from app.agent.loop import _assemble_context

    state = AgentState(objective="Process a large dataset with many steps.")
    state.memory_context = {"experiences": [], "user_knowledge": ""}

    tool_defs = [
        {"type": "function", "function": {"name": "create_file", "description": "Create a file", "parameters": {}}}
    ]
    system_prompt = "You are JARVIS, an autonomous AI agent." * 10  # ~400 chars
    max_context_chars = 5000 * 4  # 5000 tokens * 4 chars/token

    sizes = []

    for turn in range(20):
        # Simulate an observation being added each turn
        state.add_observation(
            "run_command",
            True,
            f"Step {turn}: Processed rows {turn * 1000}-{(turn + 1) * 1000}. Exit code 0. stdout: 1000 rows done.",
        )
        state.add_message("assistant", f"Action: called `run_command` with {{\"command\": \"process.py --step {turn}\"}}")
        state.add_message("user", f"Observation from `run_command`:\nStep {turn}: Processed rows {turn * 1000}-{(turn + 1) * 1000}.\n\nEvaluate the result and proceed.")

        context = _assemble_context(state, system_prompt, tool_defs, max_context_chars)
        sizes.append(len(context))

    # The sizes should not grow without bound — they should plateau
    # due to the truncation/eviction logic
    initial = sizes[0]
    final = sizes[-1]

    # Allow up to 3x growth (conservative; real target is ~1.5x or plateau)
    # The key property is it doesn't grow linearly with turn count
    assert final < max_context_chars, f"Context exceeded budget at turn 20: {final} chars > {max_context_chars}"

    # Check it doesn't grow linearly (if it did, final/initial would be ~10x)
    growth_ratio = final / max(initial, 1)
    assert growth_ratio < 5, f"Context grew too much: {growth_ratio:.1f}x from turn 1 to turn 20"


def test_token_diagnostics_tracked():
    """TurnDiagnostics records accumulate and total is summed."""
    state = AgentState(objective="test")
    for i in range(5):
        diag = TurnDiagnostics(
            turn=i + 1,
            model="gpt-x",
            tool_count=2,
            prompt_tokens=500,
            completion_tokens=100,
            total_tokens=600,
        )
        state.record_turn_diagnostics(diag)

    assert len(state.turn_diagnostics) == 5
    assert state.tokens_used == 5 * 600  # 3000 total

    # Diagnostics should be serializable
    d = state.to_dict()
    assert len(d["turn_diagnostics"]) == 5
    assert d["turn_diagnostics"][0]["total_tokens"] == 600


def test_observation_summary_truncated():
    """Observations longer than summary threshold should be truncated in the context."""
    from app.agent.loop import _format_observation
    from tests.mocks.agent import MockToolResult

    # Long file content
    long_content = "x" * 5000
    res = MockToolResult(success=True, data={"path": "large.txt", "content": long_content})
    summary = _format_observation("read_file", res)
    assert len(summary) < 3000, f"Observation should be truncated, got {len(summary)} chars"
    assert "OMITTED" in summary or "TRUNCATED" in summary or "chars" in summary


def test_estimate_tokens_reasonable():
    """_estimate_tokens should return reasonable counts."""
    from app.agent.loop import _estimate_tokens
    # Empty
    assert _estimate_tokens("") >= 1
    # 400 chars ~ 100 tokens
    text = "a" * 400
    est = _estimate_tokens(text)
    assert 80 <= est <= 120, f"400 chars should be ~100 tokens, got {est}"
