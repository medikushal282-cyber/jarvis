from typing import Dict, Any, List, Optional, Set
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod


class ToolResult(BaseModel):
    success: bool
    tool: str
    result: Optional[Any] = None
    data: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.data is None and self.result is not None:
            self.data = self.result
        elif self.result is None and self.data is not None:
            self.result = self.data
        if self.status is None:
            self.status = "completed" if self.success else "failed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "tool": self.tool,
            "result": self.result,
            "data": self.data,
            "error": self.error,
            "status": self.status,
            "metadata": self.metadata,
        }


class ToolContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}

    run_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = "default_user"
    workspace_id: Optional[str] = "default"
    workspace_root: Optional[str] = "."
    emit: Optional[Any] = None
    approved: bool = True
    timeout_s: int = 45
    permissions: Set[str] = Field(
        default_factory=lambda: {
            "filesystem.read",
            "filesystem.write",
            "filesystem.delete",
            "terminal.execute",
            "git.read",
            "git.write",
            "git.push",
            "github.read",
            "github.write",
            "http.read",
            "http.write",
            "browser.execute",
            "sandbox.execute",
        }
    )
    allow_private_http: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def has_permission(self, permission: str) -> bool:
        if self.approved or "*" in self.permissions or "admin" in self.permissions:
            return True
        if permission in self.permissions:
            return True
        # Check wildcard (e.g. filesystem.* matches filesystem.read)
        parts = permission.split(".")
        if len(parts) == 2 and f"{parts[0]}.*" in self.permissions:
            return True
        return False


class Tool(ABC):
    name: str
    description: str
    parameters: Dict[str, Any]
    required_permissions: List[str] = []

    @abstractmethod
    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        """Execute the tool with given arguments and security context."""
        pass

    def get_definition(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required_permissions": self.required_permissions,
        }
