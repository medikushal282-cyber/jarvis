"""
app/tools/registry.py — JARVIS Tool Registry

The SINGLE gateway for all capability execution.

Architecture:
    Agent/Brain → ToolRegistry.execute() → PermissionEngine → Tool → ToolResult

All tool invocations MUST go through this registry.
No code outside this module should call tool.execute() directly.

Owner: Lohith (Capability / Tool Layer)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

# Maximum chars for tool result data sent to agent (bounded LLM result)
_LLM_RESULT_MAX_CHARS = 8000
_LLM_STDOUT_MAX_CHARS = 4000


def _bound_string(s: str, max_chars: int, label: str = "content") -> Dict[str, Any]:
    """Return a bounded dict with truncation metadata."""
    if len(s) <= max_chars:
        return {label: s, "truncated": False}
    return {label: s[:max_chars], "truncated": True, "original_size": len(s)}


def _apply_llm_bounds(result: Any) -> Any:
    """
    Apply bounded LLM-facing result limits to tool output.
    Mutates and returns the result dict/value.
    """
    if not isinstance(result, dict):
        return result

    # Bound read_file content
    if "content" in result and isinstance(result["content"], str):
        original = result["content"]
        if len(original) > _LLM_RESULT_MAX_CHARS:
            result["content"] = original[:_LLM_RESULT_MAX_CHARS]
            result["truncated"] = True
            result["original_size"] = len(original)

    # Bound terminal stdout/stderr
    for key in ("stdout", "stderr"):
        if key in result and isinstance(result[key], str):
            val = result[key]
            if len(val) > _LLM_STDOUT_MAX_CHARS:
                result[key] = val[:_LLM_STDOUT_MAX_CHARS]
                result["truncated"] = True
                result[f"{key}_original_size"] = len(val)

    # Bound directory listings
    if "entries" in result and isinstance(result["entries"], list):
        entries = result["entries"]
        if len(entries) > 200:
            result["entries"] = entries[:200]
            result["truncated"] = True
            result["total_entries"] = len(entries)

    # Bound search results
    if "matches" in result and isinstance(result["matches"], list):
        matches = result["matches"]
        if len(matches) > 100:
            result["matches"] = matches[:100]
            result["truncated"] = True
            result["total_matches"] = len(matches)

    return result


class ToolRegistry:
    """
    Central registry and execution gateway for all JARVIS capability tools.

    Responsibilities:
    1. Tool registration and lookup
    2. Permission enforcement (via ToolContext + optional PermissionEngine)
    3. Schema validation
    4. Safe tool execution with bounded LLM-facing results
    5. Structured error returns for all failure modes
    """

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
        Includes name, description, parameters, required_permissions, and risk.
        """
        effective_names = tool_names or names
        tools = list(self._tools.values())
        if effective_names is not None:
            name_set = set(effective_names)
            tools = [t for t in tools if t.name in name_set]
        if categories is not None:
            cat_set = set(categories)
            tools = [
                t for t in tools
                if getattr(t, "category", None) in cat_set
                or (t.required_permissions and t.required_permissions[0].split(".")[0] in cat_set)
            ]

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

        required = params.get("required", [])

        for req_field in required:
            if req_field not in arguments:
                return {
                    "code": "MISSING_REQUIRED_ARGUMENT",
                    "message": f"Tool '{tool.name}' requires argument '{req_field}'"
                }

        # Legacy format support
        for param_name, param_spec in params.items():
            if param_name in ("type", "properties", "required"):
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
        context: Optional[ToolContext] = None,
    ) -> ToolResult:
        """
        Execute a registered tool through the full security gateway.

        Pipeline:
        1. Argument type validation
        2. Tool lookup
        3. Permission enforcement
        4. Schema validation
        5. Tool execution
        6. Bounded LLM result application
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

        # 1. Permission enforcement
        ctx = context or ToolContext()
        for required_perm in tool.required_permissions:
            if not ctx.has_permission(required_perm):
                # Build permission_required response with full metadata
                tool_risk = getattr(tool, "risk", "medium")
                import uuid as _uuid
                request_id = f"perm_{_uuid.uuid4().hex[:12]}"
                return ToolResult(
                    success=False,
                    tool=tool_name,
                    status="permission_required",
                    error={
                        "code": "PERMISSION_REQUIRED",
                        "message": f"Tool '{tool_name}' requires permission '{required_perm}'",
                    },
                    metadata={
                        "request_id": request_id,
                        "permission": required_perm,
                        "summary": f"Execute '{tool_name}' — requires {required_perm}",
                        "risk": tool_risk,
                        "run_id": ctx.run_id,
                        "session_id": ctx.session_id,
                    }
                )

        # 2. Schema validation
        schema_err = self.validate_schema(tool, arguments)
        if schema_err:
            return ToolResult(
                success=False,
                tool=tool_name,
                status="schema_validation_error",
                error=schema_err
            )

        # 3. Tool execution
        try:
            result = tool.execute(arguments, ctx)
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

        # 4. Apply bounded LLM-facing result limits
        if result.result is not None:
            result.result = _apply_llm_bounds(result.result)
        if result.data is not None and result.data is not result.result:
            result.data = result.result  # keep in sync after bounding

        return result


_global_tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _global_tool_registry
