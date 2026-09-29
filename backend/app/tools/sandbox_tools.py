"""
app/tools/sandbox_tools.py — Sandbox capability tools

Security:
  - sandbox_exec routes through DockerSandbox when Docker is available
  - Returns SANDBOX_UNAVAILABLE when Docker daemon is offline
  - NEVER falls back to host subprocess execution
  - sandbox_reset reports truthful state (stub only when Docker is offline)

Owner: Lohith (Capability / Tool Layer)
"""

from typing import Dict, Any, Optional

from app.tools.base import Tool, ToolResult, ToolContext
from app.workspace.manager import get_workspace_manager


def _check_docker_available() -> tuple[bool, str]:
    """
    Check if Docker daemon is accessible.
    Returns (available: bool, reason: str).
    """
    try:
        import docker
        client = docker.from_env()
        client.ping()
        return True, "Docker daemon is running"
    except ImportError:
        return False, "Docker Python SDK not installed"
    except Exception as e:
        return False, f"Docker daemon unavailable: {e}"


class SandboxInspectTool(Tool):
    name = "sandbox_inspect"
    description = "Inspects the sandbox workspace environment and Docker availability."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {}
    }
    required_permissions = ["sandbox.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        ws = get_workspace_manager()
        docker_available, docker_reason = _check_docker_available()
        try:
            runtimes = ws.get_runtime_info()
        except Exception:
            runtimes = {}
        return ToolResult(
            success=True,
            tool=self.name,
            result={
                "workspace_id": ws.workspace_id,
                "name": ws.name,
                "root_path": ws.root_path,
                "status": ws.status,
                "runtimes": runtimes,
                "docker_available": docker_available,
                "docker_status": docker_reason,
            }
        )


class SandboxExecTool(Tool):
    name = "sandbox_exec"
    description = (
        "Executes a command inside an isolated Docker sandbox container. "
        "Returns SANDBOX_UNAVAILABLE if Docker daemon is not running. "
        "NEVER falls back to host subprocess execution."
    )
    risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command or Python code to execute in the sandbox"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
            "memory_limit": {"type": "string", "description": "Memory limit (default '512m')"},
            "network": {"type": "boolean", "description": "Allow network access (default false)"}
        },
        "required": ["command"]
    }
    required_permissions = ["sandbox.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        command = arguments.get("command", "")
        timeout = int(arguments.get("timeout", 30))
        memory_limit = arguments.get("memory_limit", "512m")
        network = bool(arguments.get("network", False))

        if not command:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "INVALID_ARGUMENTS", "message": "Command is required"}
            )

        # Check Docker availability FIRST — never fall back to host
        docker_available, docker_reason = _check_docker_available()
        if not docker_available:
            return ToolResult(
                success=False,
                tool=self.name,
                status="blocked",
                error={
                    "code": "SANDBOX_UNAVAILABLE",
                    "message": f"Docker sandbox is not available: {docker_reason}. "
                               "sandbox_exec requires Docker daemon to be running. "
                               "Host subprocess execution is not permitted as a sandbox fallback."
                }
            )

        # Execute inside Docker container
        try:
            from app.sandbox.docker_env import DockerSandbox
            sandbox = DockerSandbox()
            result = sandbox.execute_python(
                code=command,
                timeout=timeout,
                memory_limit=memory_limit,
                network=network
            )

            exit_code = result.get("exit_code", -1)
            stdout = result.get("stdout", "")
            error_msg = result.get("error")

            # Apply output limits
            _MAX_OUTPUT = 8000
            truncated = False
            original_size = len(stdout)
            if len(stdout) > _MAX_OUTPUT:
                stdout = stdout[:_MAX_OUTPUT]
                truncated = True

            if exit_code == 0 and not error_msg:
                return ToolResult(
                    success=True,
                    tool=self.name,
                    result={
                        "command": command[:500],
                        "exit_code": exit_code,
                        "stdout": stdout,
                        "truncated": truncated,
                        "original_size": original_size if truncated else len(stdout),
                        "execution_environment": "docker_sandbox",
                    }
                )
            else:
                return ToolResult(
                    success=False,
                    tool=self.name,
                    result={
                        "command": command[:500],
                        "exit_code": exit_code,
                        "stdout": stdout,
                        "execution_environment": "docker_sandbox",
                    },
                    error={
                        "code": "SANDBOX_EXECUTION_FAILED",
                        "message": error_msg or f"Process exited with code {exit_code}"
                    }
                )

        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={
                    "code": "SANDBOX_EXECUTION_ERROR",
                    "message": f"Docker sandbox execution failed: {e}"
                }
            )


class SandboxResetTool(Tool):
    name = "sandbox_reset"
    description = "Resets the Docker sandbox environment by stopping and removing any lingering containers."
    risk = "high"
    parameters = {
        "type": "object",
        "properties": {}
    }
    required_permissions = ["sandbox.execute", "filesystem.delete"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        docker_available, docker_reason = _check_docker_available()
        if not docker_available:
            return ToolResult(
                success=False,
                tool=self.name,
                status="blocked",
                error={
                    "code": "SANDBOX_UNAVAILABLE",
                    "message": f"Cannot reset sandbox: {docker_reason}"
                }
            )

        # Remove any lingering JARVIS sandbox containers
        removed = []
        errors = []
        try:
            import docker
            client = docker.from_env()
            containers = client.containers.list(all=True, filters={"name": "fraiday_sandbox_"})
            for c in containers:
                try:
                    c.remove(force=True)
                    removed.append(c.name)
                except Exception as e:
                    errors.append(f"{c.name}: {e}")
        except Exception as e:
            errors.append(str(e))

        return ToolResult(
            success=len(errors) == 0,
            tool=self.name,
            result={
                "status": "reset_complete" if not errors else "partial_reset",
                "removed_containers": removed,
                "errors": errors,
            }
        )
