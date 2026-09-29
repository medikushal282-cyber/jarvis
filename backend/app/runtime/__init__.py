"""JARVIS runtime layer: sessions, events, results, voice.

The edge between a human and the agent brain. See docs/runtime/README.md.
"""

from app.runtime.protocols import (
    AgentRunner,
    EventEmitter,
    MemoryProvider,
    RunOutcome,
    RunRequest,
    ToolContext,
    ToolExecutor,
    ToolResult,
)

__all__ = [
    "AgentRunner",
    "EventEmitter",
    "MemoryProvider",
    "RunRequest",
    "RunOutcome",
    "ToolContext",
    "ToolResult",
    "ToolExecutor",
]
