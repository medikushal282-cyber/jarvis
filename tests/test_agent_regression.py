"""Regression test: exactly one agent entry point.

This test enforces that there is exactly ONE function in the codebase
that serves as the canonical agent entry point. Any addition of a second
entry point (e.g., resurrecting the graph/workflow path) must fail this test.

The single entry point is: backend/app/agent/brain.py::run_agent_entrypoint
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


def test_single_entry_path():
    """Assert exactly one canonical agent entry point exists."""
    # The canonical entry point module
    from app.agent.brain import run_agent_entrypoint, JarvisBrain

    # It must be importable and callable
    assert callable(run_agent_entrypoint), "run_agent_entrypoint must be callable"
    assert hasattr(JarvisBrain, "run"), "JarvisBrain.run must exist"

    # The graph workflow must NOT be the active path
    # (it should have a retirement marker)
    workflow_path = Path(__file__).parent.parent / "backend" / "app" / "graph" / "workflow.py"
    if workflow_path.exists():
        content = workflow_path.read_text(encoding="utf-8", errors="replace")
        assert "RETIRED" in content, (
            "backend/app/graph/workflow.py must be marked RETIRED from the call path. "
            "It is a legacy reference only."
        )


def test_run_agent_entrypoint_is_coroutine():
    """The entry point must be an async function."""
    import asyncio
    import inspect
    from app.agent.brain import run_agent_entrypoint
    assert inspect.iscoroutinefunction(run_agent_entrypoint), \
        "run_agent_entrypoint must be async"


def test_loop_py_exports_run_agent():
    """loop.py must export run_agent as the canonical loop function."""
    from app.agent.loop import run_agent
    import inspect
    assert inspect.iscoroutinefunction(run_agent), "run_agent must be async"


def test_no_execute_run_task_in_active_api():
    """execute_run_task from graph/workflow should not be imported by active API routes."""
    # Check that api/runs.py does not import execute_run_task directly
    api_runs = Path(__file__).parent.parent / "backend" / "app" / "api" / "runs.py"
    if api_runs.exists():
        content = api_runs.read_text(encoding="utf-8", errors="replace")
        # The old workflow import (if present) indicates the path is still active
        # Note: checking for import of execute_run_task from graph
        from_graph = "from app.graph.workflow import execute_run_task" in content
        if from_graph:
            pytest.fail(
                "app/api/runs.py still imports execute_run_task from graph/workflow. "
                "This is the retired multi-agent DAG path. "
                "Update runs.py to use run_agent_entrypoint from app.agent.brain instead."
            )


def test_brain_py_uses_run_agent():
    """JarvisBrain.run must call run_agent from app.agent.loop, not execute_run_task."""
    brain_path = Path(__file__).parent.parent / "backend" / "app" / "agent" / "brain.py"
    content = brain_path.read_text(encoding="utf-8", errors="replace")
    assert "from app.agent.loop import run_agent" in content, \
        "brain.py must import run_agent from app.agent.loop"
    # Must NOT import from graph workflow
    assert "from app.graph" not in content, \
        "brain.py must not import from app.graph (retired path)"
