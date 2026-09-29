import subprocess
import os
from typing import Dict, Any, Optional, List

from app.tools.base import Tool, ToolResult, ToolContext
from app.workspace.manager import get_workspace_manager


def run_git_cmd(args: List[str], cwd: Optional[str] = None, context: Optional[ToolContext] = None) -> Dict[str, Any]:
    if context and context.workspace_root and context.workspace_root not in (".", ""):
        ws = get_workspace_manager(workspace_id=context.workspace_id, root_path=context.workspace_root)
    elif context and context.workspace_id:
        ws = get_workspace_manager(workspace_id=context.workspace_id)
    else:
        ws = get_workspace_manager()
    work_dir = cwd or ws.root_path
    cmd = ["git"] + args
    try:
        res = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        return {
            "success": res.returncode == 0,
            "exit_code": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "exit_code": 124,
            "error": "Git operation timed out after 30s"
        }
    except Exception as e:
        return {
            "success": False,
            "exit_code": 1,
            "error": str(e)
        }


class GitStatusTool(Tool):
    name = "git_status"
    description = "Shows the working tree status."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {}
    }
    required_permissions = ["git.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        res = run_git_cmd(["status", "--porcelain"], context=context)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GIT_ERROR", "message": res.get("stderr") or res.get("error")})
        return ToolResult(success=True, tool=self.name, result={"status": res.get("stdout")})


class GitDiffTool(Tool):
    name = "git_diff"
    description = "Shows changes between commits, commit and working tree, etc."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Optional path to diff"},
            "staged": {"type": "boolean", "description": "Whether to diff staged changes"}
        }
    }
    required_permissions = ["git.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        args = ["diff"]
        if arguments.get("staged"):
            args.append("--staged")
        if arguments.get("path"):
            args.append(arguments["path"])
        res = run_git_cmd(args, context=context)
        if not res.get("success"):

            return ToolResult(success=False, tool=self.name, error={"code": "GIT_ERROR", "message": res.get("stderr") or res.get("error")})
        return ToolResult(success=True, tool=self.name, result={"diff": res.get("stdout")})


class GitLogTool(Tool):
    name = "git_log"
    description = "Shows commit logs."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "max_count": {"type": "integer", "description": "Max number of commits to show (default 10)"}
        }
    }
    required_permissions = ["git.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        max_count = int(arguments.get("max_count", 10))
        res = run_git_cmd(["log", f"-n{max_count}", "--oneline"], context=context)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GIT_ERROR", "message": res.get("stderr") or res.get("error")})
        return ToolResult(success=True, tool=self.name, result={"log": res.get("stdout")})


class GitAddTool(Tool):
    name = "git_add"
    description = "Adds file contents to the staging index."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "files": {"type": "array", "description": "List of files or '.' for all"}
        },
        "required": ["files"]
    }
    required_permissions = ["git.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        files = arguments.get("files", ["."])
        if isinstance(files, str):
            files = [files]
        res = run_git_cmd(["add"] + files, context=context)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GIT_ERROR", "message": res.get("stderr") or res.get("error")})
        return ToolResult(success=True, tool=self.name, result={"files": files, "staged": True})



class GitCommitTool(Tool):
    name = "git_commit"
    description = "Records changes to the repository."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Commit message"}
        },
        "required": ["message"]
    }
    required_permissions = ["git.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        msg = arguments.get("message", "")
        res = run_git_cmd(["commit", "-m", msg], context=context)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GIT_ERROR", "message": res.get("stderr") or res.get("error")})
        return ToolResult(success=True, tool=self.name, result={"message": msg, "output": res.get("stdout")})


class GitCheckoutTool(Tool):
    name = "git_checkout"
    description = "Switches branches or restores working tree files."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "Branch name to checkout"}
        },
        "required": ["branch"]
    }
    required_permissions = ["git.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        branch = arguments.get("branch", "")
        res = run_git_cmd(["checkout", branch], context=context)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GIT_ERROR", "message": res.get("stderr") or res.get("error")})
        return ToolResult(success=True, tool=self.name, result={"branch": branch, "output": res.get("stdout") or res.get("stderr")})


class GitCreateBranchTool(Tool):
    name = "git_create_branch"
    description = "Creates a new Git branch."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "New branch name"},
            "checkout": {"type": "boolean", "description": "Whether to switch to the new branch"}
        },
        "required": ["branch"]
    }
    required_permissions = ["git.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        branch = arguments.get("branch", "")
        checkout = arguments.get("checkout", True)
        args = ["checkout", "-b", branch] if checkout else ["branch", branch]
        res = run_git_cmd(args, context=context)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GIT_ERROR", "message": res.get("stderr") or res.get("error")})
        return ToolResult(success=True, tool=self.name, result={"branch": branch, "created": True})


class GitPullTool(Tool):
    name = "git_pull"
    description = "Fetches and integrates with another repository or local branch."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "remote": {"type": "string", "description": "Remote name (default 'origin')"},
            "branch": {"type": "string", "description": "Branch name"}
        }
    }
    required_permissions = ["git.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        remote = arguments.get("remote", "origin")
        branch = arguments.get("branch", "")
        args = ["pull", remote]
        if branch:
            args.append(branch)
        res = run_git_cmd(args, context=context)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GIT_ERROR", "message": res.get("stderr") or res.get("error")})
        return ToolResult(success=True, tool=self.name, result={"output": res.get("stdout") or res.get("stderr")})


class GitPushTool(Tool):
    name = "git_push"
    description = "Updates remote refs along with associated objects."
    risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "remote": {"type": "string", "description": "Remote name (default 'origin')"},
            "branch": {"type": "string", "description": "Branch name"}
        }
    }
    required_permissions = ["git.push"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        remote = arguments.get("remote", "origin")
        branch = arguments.get("branch", "")
        args = ["push", remote]
        if branch:
            args.append(branch)
        res = run_git_cmd(args, context=context)
        if not res.get("success"):

            return ToolResult(success=False, tool=self.name, error={"code": "GIT_ERROR", "message": res.get("stderr") or res.get("error")})
        return ToolResult(success=True, tool=self.name, result={"output": res.get("stdout") or res.get("stderr")})
