"""Unit tests for the canonical agent loop (P6)."""

import asyncio
from unittest.mock import MagicMock, patch
import pytest

from app.agent.loop import _format_observation, _summarize_progress, run_agent
from app.agent.state import AgentState
from tests.mocks.agent import FakeLLM, MockEmitter, MockToolRegistry, MockToolResult, make_request


def test_loop_detection():
    """Repeated identical call + args triggers loop detection."""
    state = AgentState(objective="test")
    state.register_call("read_file", {"path": "foo.txt"})
    assert not state.is_loop_detected("read_file", {"path": "foo.txt"})

    state.register_call("read_file", {"path": "foo.txt"})
    assert state.is_loop_detected("read_file", {"path": "foo.txt"})


def test_objective_driven_stopping():
    """When LLM returns final text without tool call, loop stops gracefully."""
    fake_llm = FakeLLM()
    fake_llm._responses = [("I have completed the task successfully.", None)]
    emitter = MockEmitter()
    request = make_request("Finish task")

    with (
        patch("app.agent.loop.call_llm", side_effect=fake_llm),
        patch("app.agent.loop.get_tool_registry", return_value=MockToolRegistry()),
        patch("app.agent.loop.get_workspace_manager") as mock_ws,
        patch("app.agent.loop.build_system_prompt", return_value="SYS"),
        patch("app.agent.loop.select_tools_for_objective", return_value=[]),
    ):
        mock_ws.return_value.get_runtime_info.return_value = {"python": {"version": "3.11"}}
        outcome = asyncio.run(run_agent(request, emitter, memory_context={}))

    assert outcome.status == "completed"
    assert "completed the task successfully" in outcome.reply
    assert emitter.has_event("run_completed")


def test_recovery_on_tool_error():
    """Tool failure generates error observation and allows model to recover."""
    llm_responses = [
        "<tool_call>\n{\"name\": \"read_file\", \"arguments\": {\"path\": \"bad.txt\"}}\n</tool_call>",
        "The file was not found, so I will inform the user.",
    ]
    fake_llm = FakeLLM()
    fake_llm._responses = [(r, None) for r in llm_responses]
    reg = MockToolRegistry()
    reg.register_tool("read_file", MockToolResult(success=False, error="File not found"))
    emitter = MockEmitter()
    request = make_request("Read bad.txt")

    with (
        patch("app.agent.loop.call_llm", side_effect=fake_llm),
        patch("app.agent.loop.get_tool_registry", return_value=reg),
        patch("app.agent.loop.get_workspace_manager") as mock_ws,
        patch("app.agent.loop.build_system_prompt", return_value="SYS"),
        patch("app.agent.loop.select_tools_for_objective", return_value=[
            {"type": "function", "function": {"name": "read_file", "description": "read", "parameters": {}}}
        ]),
    ):
        mock_ws.return_value.get_runtime_info.return_value = {"python": {"version": "3.11"}}
        outcome = asyncio.run(run_agent(request, emitter, memory_context={}))

    assert outcome.status == "completed"
    assert emitter.has_event("tool_failed")

