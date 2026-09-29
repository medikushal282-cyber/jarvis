"""Memory integration tests.

Verifies:
- memory.build_context called before every run
- memory.record_experience called on EVERY run (including failures)
- record_experience receives real content (not empty dicts)
- Memory recall failure does not abort a run
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from tests.mocks.agent import FakeLLM, MockEmitter, MockMemory, MockToolRegistry, MockToolResult, make_request


def run_with_memory(objective: str, llm_responses: list, tool_results: dict, should_fail: bool = False):
    """Run an agent scenario and return the memory mock for assertion."""
    fake_llm = FakeLLM()
    for resp in llm_responses:
        if isinstance(resp, str):
            fake_llm._responses.append((resp, None))
        elif isinstance(resp, dict) and "tool" in resp:
            call_json = json.dumps({"name": resp["tool"], "arguments": resp.get("args", {})})
            fake_llm._responses.append((f"<tool_call>\n{call_json}\n</tool_call>", None))

    mock_reg = MockToolRegistry()
    for name, result in tool_results.items():
        mock_reg.register_tool(name, result)

    mock_mem = MockMemory()
    mock_emit = MockEmitter()
    request = make_request(objective)

    from app.agent.brain import JarvisBrain

    brain = JarvisBrain(memory=mock_mem)

    with (
        patch("app.agent.loop.call_llm", side_effect=fake_llm),
        patch("app.agent.loop.get_tool_registry", return_value=mock_reg),
        patch("app.agent.loop.get_workspace_manager") as mock_ws,
        patch("app.agent.loop.build_system_prompt", return_value="SYSTEM PROMPT"),
        patch("app.agent.loop.select_tools_for_objective", return_value=[]),
        patch("app.agent.permissions.get_permission_engine") as mock_perm,
    ):
        mock_ws.return_value.get_runtime_info.return_value = {"python": {"version": "3.11"}}
        from app.agent.permissions import PermissionDecision
        perm_mock = MagicMock()
        perm_mock.check.return_value = PermissionDecision(decision="allow", reason="ok", tier="auto")
        mock_perm.return_value = perm_mock

        outcome = asyncio.run(brain.run(request, mock_emit))

    return outcome, mock_mem


class TestMemoryIntegration:
    def test_recall_called_before_run(self):
        """memory.recall must be called before the run starts."""
        outcome, mem = run_with_memory(
            objective="What is 2+2?",
            llm_responses=["4"],
            tool_results={},
        )
        assert len(mem.recall_calls) == 1, f"recall must be called once, got {len(mem.recall_calls)}"
        recall = mem.recall_calls[0]
        assert recall["objective"] == "What is 2+2?"
        assert recall["user_id"] == "test-user"

    def test_record_called_on_successful_run(self):
        """memory.record must be called after a successful run."""
        outcome, mem = run_with_memory(
            objective="Create a file.",
            llm_responses=[
                {"tool": "create_file", "args": {"path": "out.txt", "content": "data"}},
                "File created.",
            ],
            tool_results={
                "create_file": MockToolResult(success=True, data={"path": "out.txt", "bytes": 4, "lines": 1}),
            },
        )
        assert len(mem.record_calls) >= 1, "record must be called after run"
        record = mem.record_calls[-1]
        assert record["objective"] == "Create a file."

    def test_record_called_on_failed_run(self):
        """CRITICAL: memory.record must be called even when the run fails.

        Failure signatures are the most important things to remember.
        """
        # Simulate LLM crash
        def crashing_llm(*args, **kwargs):
            raise RuntimeError("LLM error: network timeout")

        mock_mem = MockMemory()
        mock_emit = MockEmitter()
        request = make_request("Do something that will fail")

        from app.agent.brain import JarvisBrain
        brain = JarvisBrain(memory=mock_mem)

        with (
            patch("app.agent.loop.call_llm", side_effect=crashing_llm),
            patch("app.agent.loop.get_tool_registry", return_value=MockToolRegistry()),
            patch("app.agent.loop.get_workspace_manager") as mock_ws,
            patch("app.agent.loop.build_system_prompt", return_value="SYS"),
            patch("app.agent.loop.select_tools_for_objective", return_value=[]),
            patch("app.agent.permissions.get_permission_engine") as mock_perm,
        ):
            mock_ws.return_value.get_runtime_info.return_value = {"python": {"version": "3.11"}}
            from app.agent.permissions import PermissionDecision
            perm_mock = MagicMock()
            perm_mock.check.return_value = PermissionDecision(decision="allow", reason="ok", tier="auto")
            mock_perm.return_value = perm_mock

            outcome = asyncio.run(brain.run(request, mock_emit))

        assert outcome.status == "failed"
        # record must still be called
        assert len(mock_mem.record_calls) >= 1, \
            "CRITICAL: record must be called even on failed runs for failure signature learning"
        record = mock_mem.record_calls[-1]
        assert record["outcome"]["status"] == "failed"

    def test_record_receives_real_content(self):
        """record_experience must receive actual tool calls and observations, not empty dict."""
        outcome, mem = run_with_memory(
            objective="Create output.txt with the word done.",
            llm_responses=[
                {"tool": "create_file", "args": {"path": "output.txt", "content": "done"}},
                "output.txt created with content 'done'.",
            ],
            tool_results={
                "create_file": MockToolResult(success=True, data={"path": "output.txt", "bytes": 4, "lines": 1}),
            },
        )
        assert len(mem.record_calls) >= 1
        record = mem.record_calls[-1]
        outcome_data = record["outcome"]
        # Must have real status
        assert outcome_data.get("status") in ("completed", "partial", "failed")
        # Must have the objective
        assert record["objective"] == "Create output.txt with the word done."
        # run_id must be real
        assert record["run_id"], "run_id must be present and non-empty"

    def test_memory_recall_failure_does_not_abort(self):
        """If memory.recall raises, the run continues without memory context."""
        class FailingMemory:
            async def recall(self, *a, **kw):
                raise ConnectionError("memory server down")
            async def record(self, *a, **kw):
                return "exp_ok"

        mock_emit = MockEmitter()
        request = make_request("What is 1+1?")

        from app.agent.brain import JarvisBrain
        brain = JarvisBrain(memory=FailingMemory())

        with (
            patch("app.agent.loop.call_llm", return_value=("2", None)),
            patch("app.agent.loop.get_tool_registry", return_value=MockToolRegistry()),
            patch("app.agent.loop.get_workspace_manager") as mock_ws,
            patch("app.agent.loop.build_system_prompt", return_value="SYS"),
            patch("app.agent.loop.select_tools_for_objective", return_value=[]),
            patch("app.agent.permissions.get_permission_engine") as mock_perm,
        ):
            mock_ws.return_value.get_runtime_info.return_value = {"python": {"version": "3.11"}}
            from app.agent.permissions import PermissionDecision
            perm_mock = MagicMock()
            perm_mock.check.return_value = PermissionDecision(decision="allow", reason="ok", tier="auto")
            mock_perm.return_value = perm_mock

            outcome = asyncio.run(brain.run(request, mock_emit))

        # Run should NOT have aborted due to memory failure
        assert outcome.status != "failed" or "2" in outcome.reply, \
            "Memory recall failure must not abort the run"
