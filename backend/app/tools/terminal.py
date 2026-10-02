import subprocess
import threading
import uuid
import os
import sys
import time
import signal
from typing import Dict, List, Optional, Union, Any

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

from app.tools.base import Tool, ToolResult, ToolContext
from app.workspace.manager import get_workspace_manager
from app.workspace.policy import check_command_policy, POLICY_DENIED, POLICY_APPROVAL_REQUIRED


def kill_process_tree(pid: int, timeout: float = 1.0) -> None:
    """
    Safely terminates a process and all of its spawned child processes
    without killing the parent process or unrelated system processes.
    Cross-platform support for Unix process groups and Windows process trees.
    """
    if os.name != "nt":
        # Unix: Use process group if session leader, otherwise process group kill
        try:
            pgid = os.getpgid(pid)
            if pgid != os.getpgrp():  # Ensure we don't kill our own process group!
                os.killpg(pgid, signal.SIGTERM)
                time.sleep(0.05)
                os.killpg(pgid, signal.SIGKILL)
                return
        except Exception:
            pass

    # Windows/Cross-platform: psutil if installed
    if HAS_PSUTIL and psutil is not None:
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except Exception:
                    pass
            parent.terminate()

            gone, alive = psutil.wait_procs([parent] + children, timeout=timeout)
            for p in alive:
                try:
                    p.kill()
                except Exception:
                    pass
            return
        except Exception:
            pass

    # Standard library fallback for Windows
    if os.name == "nt":
        try:
            subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
        except Exception:
            pass


def _get_workspace(context: Optional[ToolContext] = None):
    if context:
        return get_workspace_manager(
            workspace_id=context.workspace_id,
            session_id=context.session_id,
            root_path=context.workspace_root if context.workspace_root not in (".", "") else None
        )
    return get_workspace_manager()

class RunCommandTool(Tool):
    name = "run_command"
    description = "Executes a safe shell command inside the workspace root."
    risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to execute"},
            "timeout": {"type": "integer", "description": "Execution timeout in seconds (default 30)"}
        },
        "required": ["command"]
    }
    required_permissions = ["terminal.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        command = arguments.get("command")
        timeout = int(arguments.get("timeout", 30))
        if not command:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "INVALID_ARGUMENTS", "message": "Command is required"}
            )

        policy, reason = check_command_policy(command)
        if policy == POLICY_DENIED:
            return ToolResult(
                success=False,
                tool=self.name,
                status="denied",
                error={
                    "code": "COMMAND_DENIED",
                    "message": f"Command execution denied by security policy: {reason}"
                }
            )
        elif policy == POLICY_APPROVAL_REQUIRED:
            return ToolResult(
                success=False,
                tool=self.name,
                status="approval_required",
                error={
                    "code": "APPROVAL_REQUIRED",
                    "message": f"Command requires approval: {reason}"
                }
            )

        ws = _get_workspace(context)
        cwd = ws.root_path
        cmd_str = " ".join(command) if isinstance(command, list) else str(command)
        start_time = time.time()

        # Configure process isolation flags
        kwargs: Dict[str, Any] = {
            "cwd": cwd,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "shell": isinstance(command, str)
        }

        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        proc: Optional[subprocess.Popen] = None
        try:
            proc = subprocess.Popen(command, **kwargs)
            stdout, stderr = proc.communicate(timeout=timeout)
            duration = round(time.time() - start_time, 3)
            exit_code = proc.returncode

            result_payload = {
                "command": cmd_str,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "duration": duration,
                "working_directory": cwd
            }

            if exit_code == 0:
                return ToolResult(
                    success=True,
                    tool=self.name,
                    result=result_payload
                )
            else:
                return ToolResult(
                    success=False,
                    tool=self.name,
                    result=result_payload,
                    error={
                        "code": "PROCESS_EXECUTION_ERROR",
                        "message": (stderr or "").strip() or f"Process exited with code {exit_code}",
                        "exit_code": exit_code
                    }
                )
        except subprocess.TimeoutExpired:
            duration = round(time.time() - start_time, 3)
            if proc:
                kill_process_tree(proc.pid)
                try:
                    proc.communicate(timeout=0.5)
                except Exception:
                    pass
            return ToolResult(
                success=False,
                tool=self.name,
                status="timeout",
                result={
                    "command": cmd_str,
                    "exit_code": 124,
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout} seconds",
                    "duration": duration,
                    "working_directory": cwd
                },
                error={
                    "code": "TIMEOUT",
                    "message": f"Command timed out after {timeout} seconds",
                    "exit_code": 124
                }
            )
        except Exception as e:
            if proc:
                kill_process_tree(proc.pid)
            duration = round(time.time() - start_time, 3)
            return ToolResult(
                success=False,
                tool=self.name,
                error={
                    "code": "TOOL_EXECUTION_ERROR",
                    "message": str(e)
                }
            )


class TerminalExecTool(RunCommandTool):
    name = "exec"
    description = "Executes a shell command in workspace (alias for run_command)."
    risk = "high"


class TerminalSession:
    """Manages long-running / interactive background terminal sessions."""
    def __init__(self, t_id: str, command: str, cwd: str):
        self.t_id = t_id
        self.command = command
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self.logs: List[str] = []
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None

    def start(self):
        kwargs: Dict[str, Any] = {
            "cwd": self.cwd,
            "shell": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
            "universal_newlines": True
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        self.process = subprocess.Popen(self.command, **kwargs)
        try:
            from app.db.database import db
            db.add_terminal(self.t_id, self.process.pid, self.command, self.cwd, "running")
        except Exception:
            pass

        self.thread = threading.Thread(target=self._read_output, daemon=True)
        self.thread.start()

    def _read_output(self):
        try:
            if self.process and self.process.stdout:
                for line in iter(self.process.stdout.readline, ''):
                    if line:
                        with self.lock:
                            self.logs.append(line)
        except Exception:
            pass
        finally:
            if self.process:
                self.process.wait()
            try:
                from app.db.database import db
                db.update_terminal_status(self.t_id, "stopped")
            except Exception:
                pass

    def kill(self) -> bool:
        if self.process and self.process.poll() is None:
            try:
                kill_process_tree(self.process.pid)
                try:
                    from app.db.database import db
                    db.update_terminal_status(self.t_id, "killed")
                except Exception:
                    pass
                return True
            except Exception:
                return False
        return False

    def get_logs(self) -> str:
        with self.lock:
            return "".join(self.logs)


class TerminalManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TerminalManager, cls).__new__(cls)
            cls._instance.sessions = {}
        return cls._instance

    def spawn(self, command: str, cwd: str) -> str:
        t_id = str(uuid.uuid4())
        session = TerminalSession(t_id, command, cwd)
        self.sessions[t_id] = session
        session.start()
        return t_id

    def kill_terminal(self, t_id: str) -> bool:
        session = self.sessions.get(t_id)
        if session:
            return session.kill()
        return False

    def get_logs(self, t_id: str) -> Optional[str]:
        session = self.sessions.get(t_id)
        if session:
            return session.get_logs()
        return None

    def list_terminals(self) -> List[Dict]:
        try:
            from app.db.database import db
            return db.get_terminals()
        except Exception:
            return []


def get_terminal_manager() -> TerminalManager:
    return TerminalManager()


def run_background_command(command: str, cwd: str) -> Dict[str, Any]:
    mgr = get_terminal_manager()
    t_id = mgr.spawn(command, cwd)
    return {"success": True, "terminal_id": t_id, "message": f"Started background process {t_id}"}


def manage_background_terminal(terminal_id: str, action: str) -> Dict[str, Any]:
    mgr = get_terminal_manager()
    if action == "kill":
        success = mgr.kill_terminal(terminal_id)
        return {"success": success, "message": "Terminal killed" if success else "Failed to kill"}
    elif action == "logs":
        logs = mgr.get_logs(terminal_id)
        return {"success": logs is not None, "logs": logs[-2000:] if logs else "Terminal not found"}
    return {"success": False, "error": "Invalid action"}
