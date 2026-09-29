"""Unit tests for tool selection and dynamic filtering (P4)."""

import pytest
from app.agent.tool_selector import (
    CORE_TOOLS,
    _compact_description,
    select_tools_for_objective,
)
from app.tools.registry import get_tool_registry


def test_core_tools_always_selected():
    """CORE_TOOLS must be present for any objective."""
    defs = select_tools_for_objective("What is 2+2?")
    tool_names = {d["function"]["name"] for d in defs}
    for core in CORE_TOOLS:
        assert core in tool_names, f"Core tool {core} must be in selected tools"


def test_never_all_tools_for_simple_objective():
    """A simple objective must return a small subset, never all ~42 tools."""
    all_defs = get_tool_registry().get_tool_definitions(as_openai=True)
    selected = select_tools_for_objective("Create hello.txt containing Hello World.")
    assert len(selected) < len(all_defs), (
        f"Selected {len(selected)} tools; should be strictly fewer than all {len(all_defs)} tools"
    )
    assert len(selected) <= 15, f"Expected <= 15 tools for simple file task, got {len(selected)}"


def test_browser_tools_selected_for_website():
    """Browser tools must be selected when objective mentions a website or preview."""
    defs = select_tools_for_objective("Create a website and display it in browser.")
    names = {d["function"]["name"] for d in defs}
    assert "open_browser" in names or "browser_screenshot" in names


def test_git_tools_selected_for_git_objective():
    """Git tools must be selected for git-related objective."""
    defs = select_tools_for_objective("Check git status and commit changes.")
    names = {d["function"]["name"] for d in defs}
    assert "git_status" in names


def test_active_tools_history_retained():
    """Previously used tools in active run must remain selected."""
    defs = select_tools_for_objective(
        "Continue the task",
        active_tools_history={"http_get", "git_diff"},
    )
    names = {d["function"]["name"] for d in defs}
    assert "http_get" in names
    assert "git_diff" in names


def test_escape_hatch_widens_tools():
    """If model signals missing capability, all tools are exposed."""
    all_defs = get_tool_registry().get_tool_definitions(as_openai=True)
    defs = select_tools_for_objective(
        "Do something",
        last_model_output="I don't have access to the required tool for this.",
    )
    assert len(defs) == len(all_defs), "Escape hatch should return full registry"


def test_compact_description():
    """Tool descriptions should be compacted to first sentence."""
    long_desc = "Execute a shell command in the workspace. Returns stdout, stderr, and exit code. Use with care."
    compact = _compact_description(long_desc)
    assert compact == "Execute a shell command in the workspace."
