from typing import Dict, Any, Optional

from app.tools.base import Tool, ToolResult, ToolContext
from app.workspace.manager import get_workspace_manager


class SandboxInspectTool(Tool):
    name = "sandbox_inspect"
    description = "Inspects the isolated sandbox workspace environment."
    parameters = {
        "type": "object",
        "properties": {}
    }
    required_permissions = ["sandbox.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        ws = get_workspace_manager()
        runtimes = ws.get_runtime_info()
        return ToolResult(
            success=True,
            tool=self.name,
            result={
                "workspace_id": ws.workspace_id,
                "name": ws.name,
                "root_path": ws.root_path,
                "status": ws.status,
                "runtimes": runtimes
            }
        )


class SandboxExecTool(Tool):
    name = "sandbox_exec"
    description = "Executes a command inside the isolated sandbox."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"}
        },
        "required": ["command"]
    }
    required_permissions = ["sandbox.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        from app.tools.terminal import RunCommandTool
        terminal_tool = RunCommandTool()
        return terminal_tool.execute(arguments, context)


class SandboxResetTool(Tool):
    name = "sandbox_reset"
    description = "Resets the sandbox temporary workspace files."
    parameters = {
        "type": "object",
        "properties": {}
    }
    required_permissions = ["sandbox.execute", "filesystem.delete"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        return ToolResult(
            success=True,
            tool=self.name,
            result={"status": "reset_ready"}
        )
