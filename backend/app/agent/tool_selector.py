"""Dynamic tool filtering for token budget management.

Ensures only relevant tool schemas are presented to the model on any given turn.
Sending all ~42 tool schemas would consume ~3000+ tokens per turn.

Strategy:
1. Cheap, deterministic-first: keyword/tag matching on objective + current state
2. Core tools always included (5 tools)
3. History-aware: tools used in this run stay included
4. Escape hatch: if model explicitly reports needing a capability not in the set,
   widen to the full registry for one turn (triggered by _NEEDS_MORE_TOOLS_SIGNALS)

Compact tool descriptions: when generating definitions, descriptions are trimmed
to their first sentence to save ~40% of schema token cost.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from app.tools.registry import get_tool_registry

# Base essential tools that should almost always be available
CORE_TOOLS: Set[str] = {
    "list_directory",
    "read_file",
    "create_file",
    "update_file",
    "run_command",
}

# Signals that the model needs more tools than currently selected
_NEEDS_MORE_TOOLS_SIGNALS = (
    "i don't have access to",
    "i need a tool that",
    "no tool available",
    "tool not available",
    "i cannot perform this",
    "capability not in my tool list",
    "missing tool",
)


def _compact_description(desc: str) -> str:
    """Trim to first sentence for token efficiency."""
    if not desc:
        return desc
    # End at first period followed by space/newline, or first newline
    match = re.search(r"[.!?]\s|\n", desc)
    if match:
        return desc[:match.start() + 1].strip()
    return desc[:120].strip()


def select_tools_for_objective(
    objective: str,
    has_attachments: bool = False,
    active_tools_history: Optional[Set[str]] = None,
    last_model_output: Optional[str] = None,  # for escape hatch
    force_all: bool = False,  # escape hatch: widen to full set
) -> List[Dict[str, Any]]:
    """Select a focused subset of tools and return OpenAI-compatible definitions.

    Args:
        objective: The user's objective text.
        has_attachments: Whether the request includes file attachments.
        active_tools_history: Set of tool names already used this run.
        last_model_output: Last model response, checked for escape-hatch signals.
        force_all: If True, return all tools (escape hatch, use sparingly).
    """
    reg = get_tool_registry()
    obj_lower = objective.lower()
    selected_names: Set[str] = set(CORE_TOOLS)

    # Retain tools used in the active run
    if active_tools_history:
        selected_names.update(active_tools_history)

    # Escape hatch: model says it needs more tools
    if last_model_output:
        output_lower = last_model_output.lower()
        if any(signal in output_lower for signal in _NEEDS_MORE_TOOLS_SIGNALS):
            force_all = True

    if force_all:
        return reg.get_tool_definitions(as_openai=True)

    # 1. Web & HTTP keywords
    if any(k in obj_lower for k in ["http", "api", "fetch", "request", "download", "url", "web", "scrape", "rest"]):
        selected_names.update(["http_get", "http_post"])

    # 2. Browser & Visual preview keywords
    if any(k in obj_lower for k in ["browser", "screenshot", "html", "webpage", "website", "preview", "frontend", "ui", "display", "show me"]):
        selected_names.update(["open_browser", "browser_screenshot", "browser_navigate"])

    # 3. Git & GitHub keywords
    if any(k in obj_lower for k in ["git", "github", "commit", "branch", "pull", "repo", "pr", "issue", "version control"]):
        selected_names.update([
            "git_status", "git_diff", "git_commit", "git_add",
            "github_get_repo", "github_list_issues", "github_create_issue",
        ])

    # 4. Search & Directory tree keywords
    if any(k in obj_lower for k in ["search", "find", "grep", "tree", "structure", "find files", "locate"]):
        selected_names.update(["search_files", "list_directory_tree", "get_file_info"])

    # 5. Patching & Diff keywords
    if any(k in obj_lower for k in ["patch", "diff", "replace lines", "refactor", "edit lines"]):
        selected_names.update(["patch_file", "diff_files"])

    # 6. Deletion keywords
    if any(k in obj_lower for k in ["delete", "remove", "clean", "unlink"]):
        selected_names.update(["delete_file"])

    # 7. Image / Vision keywords or multimodal attachments
    if has_attachments or any(k in obj_lower for k in ["image", "picture", "photo", "visual", "diagram", "screenshot", "analyze image"]):
        selected_names.update(["analyze_image", "get_attachment_info"])

    # 8. Sandbox / isolated execution
    if any(k in obj_lower for k in ["sandbox", "isolated", "docker", "container"]):
        selected_names.update(["sandbox_exec"])

    # Retrieve filtered tool schemas
    tools_defs = reg.get_tool_definitions(tool_names=list(selected_names), as_openai=True)

    # Compact descriptions to save tokens
    for tool_def in tools_defs:
        fn = tool_def.get("function", {})
        if fn.get("description"):
            fn["description"] = _compact_description(fn["description"])

    return tools_defs


__all__ = ["select_tools_for_objective", "CORE_TOOLS"]
