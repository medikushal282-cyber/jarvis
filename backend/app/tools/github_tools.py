import os
import urllib.request
import urllib.parse
import json
from typing import Dict, Any, Optional

from app.tools.base import Tool, ToolResult, ToolContext


def make_github_request(endpoint: str, method: str = "GET", data: Optional[Dict] = None) -> Dict[str, Any]:
    token = os.environ.get("GITHUB_TOKEN")
    url = f"https://api.github.com/{endpoint.lstrip('/')}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "JARVIS-GitHub-Capability"
    }
    if token:
        headers["Authorization"] = f"token {token}"

    body = json.dumps(data).encode("utf-8") if data else None
    if body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
            return {"success": True, "status": resp.status, "data": json.loads(content) if content else {}}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"success": False, "status": e.code, "error": f"GitHub API error {e.code}: {e.reason}", "details": err_body}
    except Exception as e:
        return {"success": False, "error": str(e)}


class GitHubGetRepoTool(Tool):
    name = "github_get_repo"
    description = "Retrieves information about a GitHub repository."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"}
        },
        "required": ["owner", "repo"]
    }
    required_permissions = ["github.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        owner = arguments.get("owner", "")
        repo = arguments.get("repo", "")
        res = make_github_request(f"repos/{owner}/{repo}")
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GITHUB_ERROR", "message": res.get("error"), "details": res.get("details")})
        return ToolResult(success=True, tool=self.name, result=res.get("data"))


class GitHubListIssuesTool(Tool):
    name = "github_list_issues"
    description = "Lists issues for a GitHub repository."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "state": {"type": "string", "description": "Issue state ('open', 'closed', 'all', default 'open')"}
        },
        "required": ["owner", "repo"]
    }
    required_permissions = ["github.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        owner = arguments.get("owner", "")
        repo = arguments.get("repo", "")
        state = arguments.get("state", "open")
        res = make_github_request(f"repos/{owner}/{repo}/issues?state={state}")
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GITHUB_ERROR", "message": res.get("error"), "details": res.get("details")})
        return ToolResult(success=True, tool=self.name, result={"issues": res.get("data")})


class GitHubCreateIssueTool(Tool):
    name = "github_create_issue"
    description = "Creates an issue in a GitHub repository."
    risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "title": {"type": "string", "description": "Issue title"},
            "body": {"type": "string", "description": "Issue body markdown"}
        },
        "required": ["owner", "repo", "title"]
    }
    required_permissions = ["github.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        owner = arguments.get("owner", "")
        repo = arguments.get("repo", "")
        title = arguments.get("title", "")
        body = arguments.get("body", "")
        payload = {"title": title, "body": body}
        res = make_github_request(f"repos/{owner}/{repo}/issues", method="POST", data=payload)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GITHUB_ERROR", "message": res.get("error"), "details": res.get("details")})
        return ToolResult(success=True, tool=self.name, result=res.get("data"))


class GitHubCreatePRTool(Tool):
    name = "github_create_pr"
    description = "Creates a Pull Request in a GitHub repository."
    risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "title": {"type": "string", "description": "PR title"},
            "head": {"type": "string", "description": "Head branch"},
            "base": {"type": "string", "description": "Base branch (e.g. main)"},
            "body": {"type": "string", "description": "PR description"}
        },
        "required": ["owner", "repo", "title", "head", "base"]
    }
    required_permissions = ["github.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        owner = arguments.get("owner", "")
        repo = arguments.get("repo", "")
        payload = {
            "title": arguments.get("title", ""),
            "head": arguments.get("head", ""),
            "base": arguments.get("base", "main"),
            "body": arguments.get("body", "")
        }
        res = make_github_request(f"repos/{owner}/{repo}/pulls", method="POST", data=payload)
        if not res.get("success"):
            return ToolResult(success=False, tool=self.name, error={"code": "GITHUB_ERROR", "message": res.get("error"), "details": res.get("details")})
        return ToolResult(success=True, tool=self.name, result=res.get("data"))
