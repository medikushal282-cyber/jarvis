import os
import time
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import contextvars

active_workspace_id = contextvars.ContextVar('active_workspace_id', default='default')

from app.workspace.runtime import detect_python, detect_all_runtimes
from app.workspace.policy import check_command_policy, POLICY_DENIED, POLICY_APPROVAL_REQUIRED, POLICY_SAFE

class PathSecurityError(ValueError):
    """Raised when an operation attempts to access paths outside the workspace."""
    pass

class CommandDeniedError(PermissionError):
    """Raised when an operation attempts to execute a denied command."""
    pass

class WorkspaceManager:
    def __init__(self, root_path: Optional[str] = None, workspace_id: str = "ws_default", name: str = "JARVIS"):
        if not root_path:
            root_path = os.environ.get("JARVIS_WORKSPACE_ROOT") or os.environ.get("FRAIDAY_WORKSPACE_ROOT")
        if not root_path:
            # Fallback to repository root (parent directory of backend)
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            backend_dir = os.path.dirname(app_dir)
            repo_root = os.path.dirname(backend_dir)
            root_path = repo_root

        # Canonicalize root path
        resolved_root = os.path.realpath(os.path.abspath(root_path))
        if not os.path.isdir(resolved_root):
            raise FileNotFoundError(f"Configured workspace root does not exist or is not a directory: {root_path}")

        self.workspace_id = workspace_id
        self.name = name
        self.root_path = resolved_root
        self.status = "ready"
        self._cached_runtime = None

    def resolve_path(self, target_path: str) -> str:
        r"""
        Safely resolves a path relative to workspace_root.
        Guarantees the target path cannot escape the workspace root via:
        - ../ traversal
        - absolute paths outside workspace
        - Windows drive escapes (e.g. D:\...)
        - Symlink or junction escapes
        """
        if not target_path or not str(target_path).strip():
            return self.root_path

        target_str = str(target_path).strip()

        # Check for obvious Windows drive prefix that differs from root drive
        root_drive = os.path.splitdrive(self.root_path)[0].lower()
        target_drive = os.path.splitdrive(target_str)[0].lower()
        if target_drive and target_drive != root_drive:
            raise PathSecurityError(f"Access denied: Windows drive escape '{target_str}' is outside workspace drive '{root_drive}'.")

        # Normalize and construct absolute path
        if os.path.isabs(target_str):
            candidate = os.path.abspath(target_str)
        else:
            candidate = os.path.abspath(os.path.join(self.root_path, target_str))

        # Canonicalize symlinks if path exists, or resolve parent
        if os.path.exists(candidate):
            real_candidate = os.path.realpath(candidate)
        else:
            # Check realpath of closest existing parent to prevent junction escapes
            parent = candidate
            while parent and not os.path.exists(parent):
                new_parent = os.path.dirname(parent)
                if new_parent == parent:
                    break
                parent = new_parent
            real_parent = os.path.realpath(parent)
            rel_to_parent = os.path.relpath(candidate, parent)
            real_candidate = os.path.abspath(os.path.join(real_parent, rel_to_parent))

        # Check containment
        try:
            common = os.path.commonpath([real_candidate, self.root_path])
        except ValueError:
            # Paths on different drives on Windows
            raise PathSecurityError(f"Access denied: path '{target_str}' is on a different drive than workspace.")

        if common != self.root_path:
            raise PathSecurityError(f"Access denied: path '{target_str}' resolves outside workspace root '{self.root_path}'.")

        return real_candidate

    def get_relative_path(self, full_path: str) -> str:
        """Converts an absolute path within workspace to a clean relative path."""
        rel = os.path.relpath(full_path, self.root_path)
        return "" if rel == "." else rel.replace("\\", "/")

    def list_directory(self, rel_path: str = "") -> Dict[str, Any]:
        full_path = self.resolve_path(rel_path)
        if not os.path.exists(full_path):
            return {
                "success": False,
                "path": self.get_relative_path(full_path),
                "operation": "list_directory",
                "error": "Directory does not exist"
            }
        if not os.path.isdir(full_path):
            return {
                "success": False,
                "path": self.get_relative_path(full_path),
                "operation": "list_directory",
                "error": "Target is not a directory"
            }

        entries = []
        try:
            for entry in os.scandir(full_path):
                # Omit hidden git and large cache folders from top listings
                if entry.name in [".git", "node_modules", "__pycache__", ".next"]:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    entries.append({
                        "name": entry.name,
                        "path": self.get_relative_path(entry.path),
                        "is_directory": is_dir,
                        "size": 0 if is_dir else entry.stat().st_size
                    })
                    continue

                is_dir = entry.is_dir(follow_symlinks=False)
                size = 0
                try:
                    if not is_dir:
                        size = entry.stat().st_size
                except Exception:
                    pass

                entries.append({
                    "name": entry.name,
                    "path": self.get_relative_path(entry.path),
                    "is_directory": is_dir,
                    "size": size
                })

            return {
                "success": True,
                "path": self.get_relative_path(full_path),
                "operation": "list_directory",
                "entries": entries
            }
        except Exception as e:
            return {
                "success": False,
                "path": self.get_relative_path(full_path),
                "operation": "list_directory",
                "error": str(e)
            }

    def read_file(self, rel_path: str, max_bytes: int = 1024 * 1024) -> Dict[str, Any]:
        full_path = self.resolve_path(rel_path)
        if not os.path.exists(full_path):
            return {
                "success": False,
                "path": self.get_relative_path(full_path),
                "operation": "read_file",
                "error": "File does not exist"
            }
        if os.path.isdir(full_path):
            return {
                "success": False,
                "path": self.get_relative_path(full_path),
                "operation": "read_file",
                "error": "Path points to a directory"
            }

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_bytes)
            return {
                "success": True,
                "path": self.get_relative_path(full_path),
                "operation": "read_file",
                "content": content
            }
        except Exception as e:
            return {
                "success": False,
                "path": self.get_relative_path(full_path),
                "operation": "read_file",
                "error": str(e)
            }

    def write_file(self, rel_path: str, content: str) -> Dict[str, Any]:
        full_path = self.resolve_path(rel_path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return {
                "success": True,
                "path": self.get_relative_path(full_path),
                "operation": "write_file",
                "bytes_written": len(content.encode("utf-8"))
            }
        except Exception as e:
            return {
                "success": False,
                "path": self.get_relative_path(full_path),
                "operation": "write_file",
                "error": str(e)
            }

    def create_directory(self, rel_path: str) -> Dict[str, Any]:
        full_path = self.resolve_path(rel_path)
        try:
            os.makedirs(full_path, exist_ok=True)
            return {
                "success": True,
                "path": self.get_relative_path(full_path),
                "operation": "create_directory"
            }
        except Exception as e:
            return {
                "success": False,
                "path": self.get_relative_path(full_path),
                "operation": "create_directory",
                "error": str(e)
            }

    def delete_file(self, rel_path: str) -> Dict[str, Any]:
        full_path = self.resolve_path(rel_path)
        if not os.path.exists(full_path):
            return {
                "success": False,
                "path": self.get_relative_path(full_path),
                "operation": "delete_file",
                "error": "File does not exist"
            }
        try:
            if os.path.isdir(full_path):
                os.rmdir(full_path)
            else:
                os.remove(full_path)
            return {
                "success": True,
                "path": self.get_relative_path(full_path),
                "operation": "delete_file"
            }
        except Exception as e:
            return {
                "success": False,
                "path": self.get_relative_path(full_path),
                "operation": "delete_file",
                "error": str(e)
            }

    def get_python_executable(self) -> str:
        py_info = detect_python(self.root_path)
        if py_info["available"] and py_info["executable"]:
            return py_info["executable"]
        return "python"

    def execute_process(self, command: Union[str, List[str]], timeout: int = 30) -> Dict[str, Any]:
        """
        Synchronous worker for process execution with cwd = root_path.
        Checks command policy before running.
        """
        policy, reason = check_command_policy(command)
        if policy == POLICY_DENIED:
            raise CommandDeniedError(f"Command execution denied by policy: {reason}")

        cmd_repr = " ".join(command) if isinstance(command, list) else str(command)
        start_time = time.time()

        try:
            res = subprocess.run(
                command,
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=isinstance(command, str)
            )
            duration = round(time.time() - start_time, 3)
            return {
                "command": cmd_repr,
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "duration": duration,
                "timeout": timeout,
                "working_directory": self.root_path,
                "policy": policy
            }
        except subprocess.TimeoutExpired as e:
            duration = round(time.time() - start_time, 3)
            stdout = e.stdout.decode("utf-8", "ignore") if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = e.stderr.decode("utf-8", "ignore") if isinstance(e.stderr, bytes) else (e.stderr or f"Timeout after {timeout}s")
            return {
                "command": cmd_repr,
                "exit_code": 124,
                "stdout": stdout,
                "stderr": stderr,
                "duration": duration,
                "timeout": timeout,
                "working_directory": self.root_path,
                "policy": policy
            }
        except Exception as e:
            duration = round(time.time() - start_time, 3)
            return {
                "command": cmd_repr,
                "exit_code": 1,
                "stdout": "",
                "stderr": str(e),
                "duration": duration,
                "timeout": timeout,
                "working_directory": self.root_path,
                "policy": policy
            }

    async def execute_process_async(self, command: Union[str, List[str]], timeout: int = 30) -> Dict[str, Any]:
        """Non-blocking process execution wrapper using asyncio.to_thread."""
        return await asyncio.to_thread(self.execute_process, command, timeout)

    def get_runtime_info(self) -> Dict[str, Any]:
        return detect_all_runtimes(self.root_path)

    def get_workspace_info(self) -> Dict[str, Any]:
        runtimes = self.get_runtime_info()
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "root_path": self.root_path,
            "status": self.status,
            "runtime": runtimes,
            "permissions": {
                "read_only": False,
                "command_execution": True
            }
        }

# Multi-workspace manager cache
_workspace_managers: Dict[str, WorkspaceManager] = {}

def get_workspace_manager(workspace_id: str = None) -> WorkspaceManager:
    global _workspace_managers
    if workspace_id is None:
        workspace_id = active_workspace_id.get()
    if workspace_id not in _workspace_managers:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        backend_dir = os.path.dirname(app_dir)
        repo_root = os.path.dirname(backend_dir)
        sandbox_dir = os.path.join(repo_root, "sandbox", workspace_id)
        os.makedirs(sandbox_dir, exist_ok=True)
        _workspace_managers[workspace_id] = WorkspaceManager(root_path=sandbox_dir, workspace_id=workspace_id)
    return _workspace_managers[workspace_id]
