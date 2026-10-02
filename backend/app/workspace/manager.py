import os
import time
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import contextvars

active_workspace_id = contextvars.ContextVar('active_workspace_id', default='default')
active_session_id = contextvars.ContextVar('active_session_id', default='')

from app.workspace.runtime import detect_python, detect_all_runtimes
from app.workspace.policy import check_command_policy, POLICY_DENIED, POLICY_APPROVAL_REQUIRED, POLICY_SAFE
from app.runtime import config

class PathSecurityError(ValueError):
    """Raised when an operation attempts to access paths outside the workspace."""
    pass

class CommandDeniedError(PermissionError):
    """Raised when an operation attempts to execute a denied command."""
    pass

class WorkspaceManager:
    def __init__(
        self,
        workspace_id: str = "default",
        session_id: Optional[str] = None,
        root_path: Optional[str] = None,
        name: str = "JARVIS"
    ):
        self.workspace_id = workspace_id or "default"
        self.session_id = session_id or ""
        self.name = name

        # The root of all workspaces
        ws_base = config.sandbox_root()
        # This workspace's root directory: workspace/{workspace_id}/
        self.workspace_root = str((ws_base / self.workspace_id).resolve())
        os.makedirs(self.workspace_root, exist_ok=True)

        # Global workspace storage: workspace/{workspace_id}/storage/
        self.global_storage = str((Path(self.workspace_root) / "storage").resolve())
        os.makedirs(self.global_storage, exist_ok=True)

        # Chat-specific sub-storage: workspace/{workspace_id}/chats/{session_id}/storage/
        if self.session_id:
            chat_dir = Path(self.workspace_root) / "chats" / self.session_id
            self.chat_storage = str((chat_dir / "storage").resolve())
            os.makedirs(self.chat_storage, exist_ok=True)
            default_root = self.chat_storage
        else:
            self.chat_storage = self.global_storage
            default_root = self.global_storage

        if root_path:
            self.root_path = os.path.realpath(os.path.abspath(root_path))
        else:
            self.root_path = os.path.realpath(os.path.abspath(default_root))

        os.makedirs(self.root_path, exist_ok=True)
        self.status = "ready"
        self._cached_runtime = None

    def resolve_path(self, target_path: str) -> str:
        r"""
        Safely resolves a path relative to chat storage or global storage.
        
        Routing rules:
        - Paths starting with 'global/', 'global\', '/global/', 'storage/', '/storage/', or 'workspace/storage'
          resolve inside workspace global storage (workspace/{workspace_id}/storage/).
        - All other relative paths resolve inside active chat sub-storage (workspace/{workspace_id}/chats/{session_id}/storage/).
        - Strict security containment guarantees the target path cannot escape workspace_root.
        """
        if not target_path or not str(target_path).strip() or target_path in (".", "./", ".\\"):
            return self.root_path

        target_str = str(target_path).strip().replace("\\", "/")

        # Check for Windows drive prefix mismatch
        root_drive = os.path.splitdrive(self.workspace_root)[0].lower()
        target_drive = os.path.splitdrive(target_str)[0].lower()
        if target_drive and target_drive != root_drive:
            raise PathSecurityError(f"Access denied: Windows drive '{target_str}' is outside workspace drive '{root_drive}'.")

        # Global storage prefix handling
        is_global = False
        clean_target = target_str
        global_prefixes = ["global/", "/global/", "storage/", "/storage/", "workspace/storage/"]
        for prefix in global_prefixes:
            if clean_target.lower().startswith(prefix):
                clean_target = clean_target[len(prefix):]
                is_global = True
                break
        if clean_target.lower() in ("global", "/global", "storage", "/storage"):
            clean_target = ""
            is_global = True

        if is_global:
            base_dir = self.global_storage
        else:
            base_dir = self.root_path

        if os.path.isabs(clean_target):
            candidate = os.path.abspath(clean_target)
        else:
            candidate = os.path.abspath(os.path.join(base_dir, clean_target))

        # Resolve symlinks and parent directory
        if os.path.exists(candidate):
            real_candidate = os.path.realpath(candidate)
        else:
            parent = candidate
            while parent and not os.path.exists(parent):
                new_parent = os.path.dirname(parent)
                if new_parent == parent:
                    break
                parent = new_parent
            real_parent = os.path.realpath(parent)
            rel_to_parent = os.path.relpath(candidate, parent)
            real_candidate = os.path.abspath(os.path.join(real_parent, rel_to_parent))

        # Check containment within workspace_root
        try:
            common = os.path.commonpath([real_candidate, self.workspace_root])
        except ValueError:
            raise PathSecurityError(f"Access denied: path '{target_str}' is on a different drive than workspace.")

        if common != self.workspace_root and real_candidate != self.workspace_root:
            raise PathSecurityError(f"Access denied: path '{target_str}' resolves outside workspace root '{self.workspace_root}'.")

        return real_candidate

    def get_relative_path(self, full_path: str) -> str:
        """Converts an absolute path within workspace to a clean relative path."""
        norm_full = os.path.realpath(full_path)
        norm_global = os.path.realpath(self.global_storage)
        norm_chat = os.path.realpath(self.root_path)

        # Check if inside global storage
        try:
            if os.path.commonpath([norm_full, norm_global]) == norm_global:
                rel = os.path.relpath(norm_full, norm_global)
                return "global" if rel == "." else f"global/{rel.replace(os.sep, '/')}"
        except ValueError:
            pass

        # Check if inside chat sub-storage
        try:
            if os.path.commonpath([norm_full, norm_chat]) == norm_chat:
                rel = os.path.relpath(norm_full, norm_chat)
                return "" if rel == "." else rel.replace(os.sep, "/")
        except ValueError:
            pass

        # Fallback relative to workspace root
        try:
            rel = os.path.relpath(norm_full, self.workspace_root)
            return "" if rel == "." else rel.replace(os.sep, "/")
        except ValueError:
            return full_path

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
                if entry.name in [".git", "node_modules", "__pycache__", ".next", ".tmp"]:
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
                import shutil
                shutil.rmtree(full_path)
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
        return await asyncio.to_thread(self.execute_process, command, timeout)

    def get_runtime_info(self) -> Dict[str, Any]:
        return detect_all_runtimes(self.root_path)

    def get_workspace_info(self) -> Dict[str, Any]:
        runtimes = self.get_runtime_info()
        return {
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "name": self.name,
            "root_path": self.root_path,
            "workspace_root": self.workspace_root,
            "global_storage": self.global_storage,
            "status": self.status,
            "runtime": runtimes,
            "permissions": {
                "read_only": False,
                "command_execution": True
            }
        }


# Multi-workspace & chat manager cache
_workspace_managers: Dict[str, WorkspaceManager] = {}

def get_workspace_manager(
    workspace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    root_path: Optional[str] = None
) -> WorkspaceManager:
    global _workspace_managers
    if workspace_id is None:
        workspace_id = active_workspace_id.get()
    if session_id is None:
        session_id = active_session_id.get()

    cache_key = f"{workspace_id or 'default'}:{session_id or ''}:{root_path or ''}"
    if cache_key not in _workspace_managers:
        mgr = WorkspaceManager(
            workspace_id=workspace_id or "default",
            session_id=session_id,
            root_path=root_path,
        )
        _workspace_managers[cache_key] = mgr
    return _workspace_managers[cache_key]
