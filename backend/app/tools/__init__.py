from app.tools.base import Tool, ToolResult, ToolContext
from app.tools.registry import ToolRegistry, get_tool_registry

# Filesystem Tools
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
        CreateDirectoryTool(),
        AppendFileTool(),
        PatchFileTool(),
        GetFileInfoTool(),
        ListDirectoryTreeTool(),
        DiffFilesTool(),
        SearchFilesTool(),
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
