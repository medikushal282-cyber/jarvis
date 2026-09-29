from typing import Dict, Any, List, Optional
import logging
from app.tools.base import Tool, ToolResult, ToolContext

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise TypeError(f"Expected Tool instance, got {type(tool)}")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def unregister(self, tool_name: str) -> bool:
        if tool_name in self._tools:
            del self._tools[tool_name]
            return True
        return False

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def get_tool_definitions(
        self,
        tool_names: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        names: Optional[List[str]] = None,
        as_openai: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Returns JSON-serializable tool definitions for LLM function calling.
        Supports optional filtering by specific tool names or category prefixes.
        """
        effective_names = tool_names or names
        tools = list(self._tools.values())
        if effective_names is not None:
            name_set = set(effective_names)
            tools = [t for t in tools if t.name in name_set]
        if categories is not None:
            cat_set = set(categories)
            tools = [t for t in tools if getattr(t, "category", None) in cat_set or getattr(t, "required_permission", "").split(".")[0] in cat_set]
        
        if as_openai:
            return [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
        return [tool.get_definition() for tool in tools]

    def validate_schema(self, tool: Tool, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Validates arguments against the tool's parameter specification.
        Returns an error dict if validation fails, None if valid.
        """
        params = tool.parameters
        if not params:
            return None

        # Check required fields if defined in JSON schema format
        required = params.get("required", [])
        properties = params.get("properties", {})

        for req_field in required:
            if req_field not in arguments:
                return {
                    "code": "MISSING_REQUIRED_ARGUMENT",
                    "message": f"Tool '{tool.name}' requires argument '{req_field}'"
                }

        # Check legacy parameter dict format (e.g. {"path": "string (required)"})
        for param_name, param_spec in params.items():
            if param_name in ["type", "properties", "required"]:
                continue
            if isinstance(param_spec, str) and "required" in param_spec.lower():
                if param_name not in arguments or arguments[param_name] is None:
                    return {
                        "code": "MISSING_REQUIRED_ARGUMENT",
                        "message": f"Tool '{tool.name}' requires argument '{param_name}'"
                    }

        return None

    def execute(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        context: Optional[ToolContext] = None
    ) -> ToolResult:
        """
        Executes a registered tool with schema and permission validation.
        """
        if arguments is None:
            arguments = {}

        if not isinstance(arguments, dict):
            return ToolResult(
                success=False,
                tool=tool_name,
                error={
                    "code": "INVALID_ARGUMENTS",
                    "message": "Arguments must be a JSON object"
                }
            )

        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                tool=tool_name,
                error={
                    "code": "UNKNOWN_TOOL",
                    "message": f"Tool '{tool_name}' is not registered in ToolRegistry"
                }
            )

        # 1. Permission Enforcement
        ctx = context or ToolContext()
        for required_perm in tool.required_permissions:
            if not ctx.has_permission(required_perm):
                return ToolResult(
                    success=False,
                    tool=tool_name,
                    status="permission_denied",
                    error={
                        "code": "PERMISSION_DENIED",
                        "message": f"Execution of '{tool_name}' requires permission '{required_perm}'",
                        "required_permission": required_perm
                    }
                )

        # 2. Schema Validation
        schema_err = self.validate_schema(tool, arguments)
        if schema_err:
            return ToolResult(
                success=False,
                tool=tool_name,
                status="schema_validation_error",
                error=schema_err
            )

        # 3. Tool Execution
        try:
            return tool.execute(arguments, ctx)
        except Exception as e:
            logger.exception(f"Unexpected error executing tool '{tool_name}': {e}")
            return ToolResult(
                success=False,
                tool=tool_name,
                error={
                    "code": "TOOL_EXECUTION_ERROR",
                    "message": str(e)
                }
            )


_global_tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _global_tool_registry
