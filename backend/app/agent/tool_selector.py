"""Dynamic tool filtering for token budget management.

Ensures that only relevant tool schemas are presented to the model on any
given turn, preventing the schema definition from consuming excessive tokens
(critical for Groq's 8,000 token input window).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from app.tools.registry import get_tool_registry

# Base essential tools that should almost always be available
CORE_TOOLS: Set[str] = {
    "list_directory",
    "read_file",
    "create_file",
    "update_file",
    "run_command",
}


def select_tools_for_objective(
    objective: str,
    has_attachments: bool = False,
    active_tools_history: Set[str] | None = None,
) -> List[Dict[str, Any]]:
    """Select a focused subset of tools and return their OpenAI-compatible definitions."""
    reg = get_tool_registry()
    obj_lower = objective.lower()
    selected_names: Set[str] = set(CORE_TOOLS)

    # Retain any tools previously used in the active run
    if active_tools_history:
        selected_names.update(active_tools_history)

    # 1. Web & HTTP keywords
    if any(k in obj_lower for k in ["http", "api", "fetch", "request", "download", "url", "web", "scrape"]):
        selected_names.update(["http_get", "http_post"])

    # 2. Browser & Visual preview keywords
    if any(k in obj_lower for k in ["browser", "screenshot", "html", "webpage", "website", "preview", "frontend", "ui"]):
        selected_names.update(["open_browser", "browser_screenshot", "browser_navigate"])

    # 3. Git & GitHub keywords
    if any(k in obj_lower for k in ["git", "github", "commit", "branch", "pull", "repo", "pr", "issue"]):
        selected_names.update([
            "git_status", "git_diff", "git_commit", "git_add",
            "github_get_repo", "github_list_issues", "github_create_issue"
        ])

    # 4. Search & Directory tree keywords
    if any(k in obj_lower for k in ["search", "find", "grep", "tree", "structure", "find files"]):
        selected_names.update(["search_files", "list_directory_tree", "get_file_info"])

    # 5. Patching & Diff keywords
    if any(k in obj_lower for k in ["patch", "diff", "replace lines", "refactor"]):
        selected_names.update(["patch_file", "diff_files"])

    # 6. Deletion keywords
    if any(k in obj_lower for k in ["delete", "remove", "clean", "unlink"]):
        selected_names.update(["delete_file"])

    # 7. Image / Vision keywords or multimodal attachments present
    if has_attachments or any(k in obj_lower for k in ["image", "picture", "photo", "visual", "diagram", "screenshot"]):
        selected_names.update(["analyze_image", "get_attachment_info"])

    # Retrieve filtered tool schemas from registry
    tools_defs = reg.get_tool_definitions(tool_names=list(selected_names))
    return tools_defs
