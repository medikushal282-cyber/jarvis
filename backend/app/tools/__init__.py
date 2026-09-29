from app.tools.base import Tool, ToolResult, ToolContext
from app.tools.registry import ToolRegistry, get_tool_registry

from app.tools.filesystem import (
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
    CreateFileTool,
    UpdateFileTool,
    DeleteFileTool,
    MoveFileTool,
    RenameFileTool,
    CopyFileTool,
    CopyFileLegacyTool,
    CreateDirectoryTool,
    AppendFileTool,
    PatchFileTool,
    GetFileInfoTool,
    ListDirectoryTreeTool,
    DiffFilesTool,
    SearchFilesTool
)

# Terminal Tools
from app.tools.terminal import (
    RunCommandTool,
    TerminalExecTool,
    TerminalSession,
    TerminalManager,
    get_terminal_manager,
    run_background_command,
    manage_background_terminal
)

# HTTP Tools
from app.tools.http_tools import (
    HttpGetTool,
    HttpPostTool,
    HttpPutTool,
    HttpPatchTool,
    HttpDeleteTool,
    validate_url_for_ssrf,
    execute_http_request_streamed
)

# Git Tools
from app.tools.git_tools import (
    GitStatusTool,
    GitDiffTool,
    GitLogTool,
    GitAddTool,
    GitCommitTool,
    GitCheckoutTool,
    GitCreateBranchTool,
    GitPullTool,
    GitPushTool
)

# GitHub Tools
from app.tools.github_tools import (
    GitHubGetRepoTool,
    GitHubListIssuesTool,
    GitHubCreateIssueTool,
    GitHubCreatePRTool
)

# Browser Tools
from app.tools.browser_tools import (
    BrowserOpenTool,
    BrowserScreenshotTool,
    BrowserNavigateTool
)

# Sandbox Tools
from app.tools.sandbox_tools import (
    SandboxInspectTool,
    SandboxExecTool,
    SandboxResetTool
)

# Vision Tools
from app.tools.vision_tools import (
    AnalyzeImageTool,
    GetAttachmentInfoTool
)


# ---------------------------------------------------------------------------
# Compatibility Aliases
# ---------------------------------------------------------------------------
# These alias classes route through the same permission/security layer as
# their originals. They exist purely for API name compatibility.


class _ListFilesAlias(ListDirectoryTool):
    """list_files → list_directory compatibility alias."""
    name = "list_files"
    description = "Lists files and directories in a workspace path (alias for list_directory)."


class _EditFileAlias(PatchFileTool):
    """edit_file → patch_file compatibility alias for find-and-replace editing."""
    name = "edit_file"
    description = "Finds and replaces text within a file (alias for patch_file). " \
                  "Use for targeted edits to existing files."


def _init_default_registry(reg: ToolRegistry) -> None:
    tools_to_register = [
        # Filesystem
        ListDirectoryTool(),
        ReadFileTool(),
        WriteFileTool(),
        CreateFileTool(),
        UpdateFileTool(),
        DeleteFileTool(),
        MoveFileTool(),
        RenameFileTool(),
        CopyFileTool(),
        CopyFileLegacyTool(),   # copy_file compatibility alias
        CreateDirectoryTool(),
        AppendFileTool(),
        PatchFileTool(),
        GetFileInfoTool(),
        ListDirectoryTreeTool(),
        DiffFilesTool(),
        SearchFilesTool(),
        # Filesystem compatibility aliases (list_files, edit_file)
        _ListFilesAlias(),
        _EditFileAlias(),
        # Terminal
        RunCommandTool(),
        TerminalExecTool(),
        # HTTP
        HttpGetTool(),
        HttpPostTool(),
        HttpPutTool(),
        HttpPatchTool(),
        HttpDeleteTool(),
        # Git
        GitStatusTool(),
        GitDiffTool(),
        GitLogTool(),
        GitAddTool(),
        GitCommitTool(),
        GitCheckoutTool(),
        GitCreateBranchTool(),
        GitPullTool(),
        GitPushTool(),
        # GitHub
        GitHubGetRepoTool(),
        GitHubListIssuesTool(),
        GitHubCreateIssueTool(),
        GitHubCreatePRTool(),
        # Browser
        BrowserOpenTool(),
        BrowserScreenshotTool(),
        BrowserNavigateTool(),
        # Sandbox
        SandboxInspectTool(),
        SandboxExecTool(),
        SandboxResetTool(),
        # Vision & Attachments
        AnalyzeImageTool(),
        GetAttachmentInfoTool()
    ]
    for t in tools_to_register:
        reg.register(t)


# Register all tools into global registry
_init_default_registry(get_tool_registry())

__all__ = [
    "Tool",
    "ToolResult",
    "ToolContext",
    "ToolRegistry",
    "get_tool_registry",
    "TerminalSession",
    "TerminalManager",
    "get_terminal_manager",
    "run_background_command",
    "manage_background_terminal",
    "validate_url_for_ssrf",
    "execute_http_request_streamed"
]
