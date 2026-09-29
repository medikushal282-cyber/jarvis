"""Mock infrastructure for offline agent tests.

All mocks implement the real interfaces defined in app.runtime.protocols.
Tests that use these mocks run fully offline (no Groq key required).
Live-Groq variants auto-skip when GROQ_API_KEY is absent.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------


class FakeLLM:
    """Scripted LLM response generator for deterministic tests.

    Usage:
        llm = FakeLLM()
        llm.add_response("What is 2+2?", "4")
        llm.add_tool_call("create file", "create_file", {"path": "hello.txt", "content": "Hello World"})
        llm.add_response("create file", None)  # second turn: final answer
    """

    def __init__(self) -> None:
        self._responses: List[Tuple[Optional[str], Optional[str]]] = []
        self._call_count = 0
        self.calls: List[Dict[str, Any]] = []

    def add_response(self, trigger: str, text: str) -> None:
        """Add a plain text response."""
        self._responses.append((text, None))

    def add_tool_call(self, trigger: str, tool_name: str, args: Dict[str, Any]) -> None:
        """Add a tool call response."""
        call_json = json.dumps({"name": tool_name, "arguments": args})
        text = f"<tool_call>\n{call_json}\n</tool_call>"
        self._responses.append((text, None))

    def add_thought_and_tool(self, thought: str, tool_name: str, args: Dict[str, Any]) -> None:
        """Add a response with thinking + tool call."""
        call_json = json.dumps({"name": tool_name, "arguments": args})
        text = f"<thought>{thought}</thought>\n<tool_call>\n{call_json}\n</tool_call>"
        self._responses.append((text, thought))

    def add_final(self, text: str) -> None:
        """Add a final text response (no tool calls)."""
        self._responses.append((text, None))

    def __call__(
        self,
        system: str,
        user: str,
        model: str = "fake",
        provider: str = "fake",
        tools: Optional[List] = None,
        emit: Optional[Callable] = None,
    ) -> Tuple[str, Optional[str]]:
        """Callable that matches the call_llm signature."""
        self.calls.append({"system": system, "user": user, "model": model, "tools": tools})
        if self._call_count < len(self._responses):
            response, thought = self._responses[self._call_count]
            self._call_count += 1
            return (response or ""), thought
        # Default: return a final answer if no more scripted responses
        return "Task completed.", None


# ---------------------------------------------------------------------------
# Mock memory
# ---------------------------------------------------------------------------


class MockMemory:
    """In-memory mock of Kushal's memory interface.

    Records all recall/record calls for assertion in tests.
    """

    def __init__(self, recall_result: Optional[Dict[str, Any]] = None) -> None:
        self._recall_result = recall_result or {
            "experiences": [],
            "observations": [],
            "user_knowledge": "",
            "project_knowledge": "",
        }
        self.recall_calls: List[Dict[str, Any]] = []
        self.record_calls: List[Dict[str, Any]] = []

    def set_recall_result(self, result: Dict[str, Any]) -> None:
        self._recall_result = result

    async def recall(
        self,
        user_id: str,
        objective: str,
        *,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        self.recall_calls.append({
            "user_id": user_id,
            "objective": objective,
            "session_id": session_id,
            "workspace_id": workspace_id,
        })
        return dict(self._recall_result)

    async def record(
        self,
        user_id: str,
        run_id: str,
        objective: str,
        outcome: Dict[str, Any],
    ) -> str:
        self.record_calls.append({
            "user_id": user_id,
            "run_id": run_id,
            "objective": objective,
            "outcome": outcome,
        })
        return f"exp_{run_id[:8]}"


# ---------------------------------------------------------------------------
# Mock tool registry
# ---------------------------------------------------------------------------


class MockToolResult:
    def __init__(self, success: bool, data: Dict = None, error: str = None):
        self.success = success
        self.data = data or {}
        self.error = error
        self.artifacts = []
        self.duration_ms = 1


class MockToolRegistry:
    """Scripted tool registry for deterministic tests."""

    def __init__(self) -> None:
        self._tools: Dict[str, MockToolResult] = {}
        self._schemas: Dict[str, Dict] = {}
        self.execute_calls: List[Dict] = []

    def register_tool(
        self,
        name: str,
        result: MockToolResult,
        schema: Optional[Dict] = None,
    ) -> None:
        self._tools[name] = result
        self._schemas[name] = schema or {}

    def get_tool(self, name: str):
        if name in self._tools:
            class FakeTool:
                parameters = {}
                required_permissions = []
                description = f"Mock tool: {name}"
            ft = FakeTool()
            ft.name = name
            ft.parameters = self._schemas.get(name, {})
            return ft
        return None

    def execute(self, tool_name: str, arguments: Dict, context=None) -> MockToolResult:
        self.execute_calls.append({"tool": tool_name, "arguments": arguments})
        if tool_name in self._tools:
            return self._tools[tool_name]
        return MockToolResult(success=False, error=f"Tool '{tool_name}' not found in mock registry")

    def get_tool_definitions(self, tool_names=None, categories=None, as_openai=False):
        tools = list(self._tools.keys())
        if tool_names:
            tools = [t for t in tools if t in tool_names]
        if as_openai:
            return [
                {"type": "function", "function": {"name": t, "description": f"Mock {t}", "parameters": self._schemas.get(t, {})}}
                for t in tools
            ]
        return [{"name": t, "description": f"Mock {t}"} for t in tools]


# ---------------------------------------------------------------------------
# Mock event emitter
# ---------------------------------------------------------------------------


class MockEmitter:
    """Records all events for assertion."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self._by_type: Dict[str, List[Dict]] = defaultdict(list)

    def __call__(self, event: str, data: Optional[Dict] = None, *, node: str = "") -> None:
        record = {"event": event, "data": data or {}, "node": node}
        self.events.append(record)
        self._by_type[event].append(record)

    def emit(self, event: str, data: Optional[Dict] = None, *, node: str = "") -> None:
        self(event, data, node=node)

    def scoped(self, node: str) -> "MockEmitter":
        return self

    def event_types(self) -> List[str]:
        return [e["event"] for e in self.events]

    def get(self, event_type: str) -> List[Dict]:
        return self._by_type.get(event_type, [])

    def has_event(self, event_type: str) -> bool:
        return event_type in self._by_type

    def tool_calls_made(self) -> List[str]:
        return [e["data"].get("tool") for e in self.get("tool_started")]


# ---------------------------------------------------------------------------
# Request builder
# ---------------------------------------------------------------------------


def make_request(
    objective: str,
    run_id: str = "test-run-001",
    user_id: str = "test-user",
    session_id: str = "test-session",
    workspace_id: str = "test-workspace",
    model: str = "fake",
    provider: str = "fake",
    turbo_mode: bool = False,
) -> Any:
    """Create a RunRequest for testing."""
    from app.runtime.protocols import RunRequest

    req = RunRequest(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        workspace_id=workspace_id,
        objective=objective,
        model=model,
        provider=provider,
        workspace_root=".",
    )
    req.turbo_mode = turbo_mode
    req.pre_authorized_scope = []
    return req


__all__ = [
    "FakeLLM",
    "MockMemory",
    "MockToolRegistry",
    "MockToolResult",
    "MockEmitter",
    "make_request",
]
