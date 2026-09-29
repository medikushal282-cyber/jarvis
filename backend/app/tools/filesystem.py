import os
import re
import shutil
import difflib
from datetime import datetime
from typing import Dict, Any, Optional

from app.tools.base import Tool, ToolResult, ToolContext
from app.workspace.manager import get_workspace_manager, PathSecurityError


def _get_workspace(context: Optional[ToolContext] = None):
    if context and context.workspace_root and context.workspace_root not in (".", ""):
        return get_workspace_manager(workspace_id=context.workspace_id, root_path=context.workspace_root)
    if context and context.workspace_id:
        return get_workspace_manager(workspace_id=context.workspace_id)
    return get_workspace_manager()

class ListDirectoryTool(Tool):
    name = "list_directory"
    description = "Lists files and directories within a workspace path."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to list (defaults to '.')"}
        }
    }
    required_permissions = ["filesystem.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", ".")
        ws = _get_workspace(context)
        try:
            res = ws.list_directory(path)
            if not res.get("success"):
                err_msg = res.get("error", "Failed to list directory")
                code = "FILE_NOT_FOUND" if "does not exist" in err_msg else "TOOL_EXECUTION_ERROR"
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": code, "message": err_msg}
                )
            entries = res.get("entries", [])
            return ToolResult(
                success=True,
                tool=self.name,
                result={"path": res.get("path", path), "entries": entries}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
            )


class ReadFileTool(Tool):
    name = "read_file"
    description = "Reads contents of a file inside the workspace."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file"}
        },
        "required": ["path"]
    }
    required_permissions = ["filesystem.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", "")
        ws = _get_workspace(context)
        try:
            res = ws.read_file(path)
            if not res.get("success"):
                err_msg = res.get("error", "Failed to read file")
                code = "FILE_NOT_FOUND" if "does not exist" in err_msg else "TOOL_EXECUTION_ERROR"
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": code, "message": err_msg}
                )
            content = res.get("content", "")
            return ToolResult(
                success=True,
                tool=self.name,
                result={"path": res.get("path", path), "content": content, "bytes_read": len(content.encode("utf-8"))}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
            )


class WriteFileTool(Tool):
    name = "write_file"
    description = "Writes or overwrites content to a file in the workspace."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file"},
            "content": {"type": "string", "description": "Content to write"}
        },
        "required": ["path", "content"]
    }
    required_permissions = ["filesystem.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", "")
        content = arguments.get("content", "")
        ws = _get_workspace(context)
        try:
            res = ws.write_file(path, content)
            if not res.get("success"):
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": "TOOL_EXECUTION_ERROR", "message": res.get("error", "Failed to write file")}
                )
            lines = len(content.splitlines())
            bytes_written = res.get("bytes_written", len(content.encode("utf-8")))
            
            # Register user-visible files as artifacts
            actual_path = res.get("path", path)
            artifact_info = None
            try:
                from app.artifacts import get_artifact_manager
                import asyncio
                from app.events import emit
                manager = get_artifact_manager()
                full_path = ws._resolve_path(path)
                if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
                    art = manager.register_artifact(
                        file_path=full_path,
                        filename=os.path.basename(path),
                        source_tool=self.name,
                        session_id=context.session_id if context else None
                    )
                    artifact_info = art.to_dict()
                    if context and context.session_id:
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                asyncio.create_task(emit(context.session_id, "artifact_created", self.name, artifact_info))
                        except Exception:
                            pass
            except Exception:
                pass

            return ToolResult(
                success=True,
                tool=self.name,
                data={"path": actual_path, "lines": lines, "bytes_written": bytes_written, "artifact": artifact_info},
                result={"path": actual_path, "lines": lines, "bytes_written": bytes_written, "artifact": artifact_info}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
            )


class CreateFileTool(WriteFileTool):
    name = "create_file"
    description = "Creates a new file in the workspace with given content."
    risk = "medium"


class UpdateFileTool(WriteFileTool):
    name = "update_file"
    description = "Updates an existing file in the workspace with given content."
    risk = "medium"


class DeleteFileTool(Tool):
    name = "delete_file"
    description = "Deletes a file inside the workspace."
    risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file to delete"}
        },
        "required": ["path"]
    }
    required_permissions = ["filesystem.delete"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", "")
        ws = _get_workspace(context)
        try:
            res = ws.delete_file(path)
            if not res.get("success"):
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": "TOOL_EXECUTION_ERROR", "message": res.get("error", "File deletion failed.")}
                )
            return ToolResult(
                success=True,
                tool=self.name,
                result={"path": path, "status": "deleted"}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
            )


class CreateDirectoryTool(Tool):
    name = "create_directory"
    description = "Creates a directory in the workspace."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative directory path"}
        },
        "required": ["path"]
    }
    required_permissions = ["filesystem.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", "")
        ws = _get_workspace(context)
        try:
            res = ws.create_directory(path)
            if not res.get("success"):
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": "TOOL_EXECUTION_ERROR", "message": res.get("error", "Failed to create directory")}
                )
            return ToolResult(
                success=True,
                tool=self.name,
                result={"path": path, "status": "created"}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )


class MoveFileTool(Tool):
    name = "move"
    description = "Moves or renames a file or directory in the workspace."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "old_path": {"type": "string", "description": "Source path"},
            "new_path": {"type": "string", "description": "Destination path"}
        },
        "required": ["old_path", "new_path"]
    }
    required_permissions = ["filesystem.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        old_path = arguments.get("old_path", "")
        new_path = arguments.get("new_path", "")
        ws = _get_workspace(context)
        try:
            old_full = ws.resolve_path(old_path)
            new_full = ws.resolve_path(new_path)
            if not os.path.exists(old_full):
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": "FILE_NOT_FOUND", "message": f"Source path '{old_path}' does not exist"}
                )
            os.makedirs(os.path.dirname(new_full), exist_ok=True)
            shutil.move(old_full, new_full)
            return ToolResult(
                success=True,
                tool=self.name,
                result={"old_path": old_path, "new_path": new_path, "status": "moved"}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
            )


class RenameFileTool(MoveFileTool):
    name = "rename_file"
    description = "Renames a file in the workspace."
    risk = "medium"


class CopyFileTool(Tool):
    name = "copy"
    description = "Copies a file or directory within the workspace."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "src": {"type": "string", "description": "Source path"},
            "dest": {"type": "string", "description": "Destination path"}
        },
        "required": ["src", "dest"]
    }
    required_permissions = ["filesystem.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        src = arguments.get("src", "")
        dest = arguments.get("dest", "")
        ws = _get_workspace(context)
        try:
            src_full = ws.resolve_path(src)
            dest_full = ws.resolve_path(dest)
            if not os.path.exists(src_full):
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": "FILE_NOT_FOUND", "message": f"Source '{src}' does not exist"}
                )
            os.makedirs(os.path.dirname(dest_full), exist_ok=True)
            if os.path.isdir(src_full):
                shutil.copytree(src_full, dest_full)
            else:
                shutil.copy2(src_full, dest_full)
            return ToolResult(
                success=True,
                tool=self.name,
                result={"src": src, "dest": dest, "status": "copied"}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
            )


class CopyFileLegacyTool(CopyFileTool):
    name = "copy_file"


class AppendFileTool(Tool):
    name = "append_file"
    description = "Appends content to an existing file in the workspace."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file"},
            "content": {"type": "string", "description": "Content to append"}
        },
        "required": ["path", "content"]
    }
    required_permissions = ["filesystem.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", "")
        content = arguments.get("content", "")
        ws = _get_workspace(context)
        try:
            full_path = ws.resolve_path(path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "a", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(
                success=True,
                tool=self.name,
                result={"path": path, "appended_bytes": len(content.encode("utf-8"))}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
            )


class PatchFileTool(Tool):
    name = "patch_file"
    description = "Finds and replaces text within a file in the workspace."
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file"},
            "find": {"type": "string", "description": "String to find"},
            "replace": {"type": "string", "description": "Replacement string"},
            "count": {"type": "integer", "description": "Number of replacements (default 1)"}
        },
        "required": ["path", "find", "replace"]
    }
    required_permissions = ["filesystem.write"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", "")
        find_str = arguments.get("find", "")
        replace_str = arguments.get("replace", "")
        count = arguments.get("count", 1)
        ws = _get_workspace(context)
        try:
            full_path = ws.resolve_path(path)
            if not os.path.exists(full_path):
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": "FILE_NOT_FOUND", "message": f"File '{path}' does not exist"}
                )
            with open(full_path, "r", encoding="utf-8") as f:
                data = f.read()
            if find_str not in data:
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": "TARGET_NOT_FOUND", "message": f"Target string not found in '{path}'"}
                )
            new_data = data.replace(find_str, replace_str, count)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_data)
            return ToolResult(
                success=True,
                tool=self.name,
                result={"path": path, "patched": True}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
            )


class GetFileInfoTool(Tool):
    name = "get_file_info"
    description = "Retrieves file metadata including size, modification time, and type."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path"}
        },
        "required": ["path"]
    }
    required_permissions = ["filesystem.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", "")
        ws = _get_workspace(context)
        try:
            full = ws.resolve_path(path)
            if not os.path.exists(full):
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": "FILE_NOT_FOUND", "message": f"Path '{path}' does not exist"}
                )
            st = os.stat(full)
            info = {
                "path": path,
                "size": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                "is_dir": os.path.isdir(full)
            }
            return ToolResult(
                success=True,
                tool=self.name,
                result=info
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )


class ListDirectoryTreeTool(Tool):
    name = "list_directory_tree"
    description = "Recursively lists files and directories in workspace up to max_depth."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Start path (default '.')"},
            "max_depth": {"type": "integer", "description": "Maximum tree depth (default 3)"}
        }
    }
    required_permissions = ["filesystem.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", ".")
        max_depth = arguments.get("max_depth", 3)
        ws = _get_workspace(context)
        try:
            start_full = ws.resolve_path(path)
            if not os.path.exists(start_full):
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": "FILE_NOT_FOUND", "message": f"Path '{path}' does not exist"}
                )
            start_depth = start_full.count(os.sep)
            tree = []
            for root, dirs, files in os.walk(start_full):
                if ".git" in dirs:
                    dirs.remove(".git")
                if "node_modules" in dirs:
                    dirs.remove("node_modules")
                depth = root.count(os.sep) - start_depth
                if depth >= max_depth:
                    del dirs[:]
                rel_root = ws.get_relative_path(root)
                tree.append({"directory": rel_root, "files": files})
            return ToolResult(
                success=True,
                tool=self.name,
                result={"tree": tree[:100]}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )


class DiffFilesTool(Tool):
    name = "diff_files"
    description = "Generates a unified diff between two files."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "path_a": {"type": "string", "description": "First file path"},
            "path_b": {"type": "string", "description": "Second file path"}
        },
        "required": ["path_a", "path_b"]
    }
    required_permissions = ["filesystem.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path_a = arguments.get("path_a", "")
        path_b = arguments.get("path_b", "")
        ws = _get_workspace(context)
        try:
            fa = ws.resolve_path(path_a)
            fb = ws.resolve_path(path_b)
            with open(fa, "r", encoding="utf-8", errors="ignore") as a, open(fb, "r", encoding="utf-8", errors="ignore") as b:
                diff = list(difflib.unified_diff(a.readlines(), b.readlines(), fromfile=path_a, tofile=path_b))
            return ToolResult(
                success=True,
                tool=self.name,
                result={"diff": "".join(diff)}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )


class SearchFilesTool(Tool):
    name = "search_files"
    description = "Searches for text or regex patterns in workspace files."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Search pattern"},
            "path": {"type": "string", "description": "Search path (default '.')"},
            "regex": {"type": "boolean", "description": "Treat pattern as regular expression"}
        },
        "required": ["pattern"]
    }
    required_permissions = ["filesystem.read"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        pattern = arguments.get("pattern", "")
        path = arguments.get("path", ".")
        regex = arguments.get("regex", False)
        ws = _get_workspace(context)
        try:
            full_path = ws.resolve_path(path)
            if not os.path.isdir(full_path):
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={"code": "NOT_A_DIRECTORY", "message": "Path is not a directory"}
                )
            matches = []
            compiled = re.compile(pattern) if regex else None
            for root, _, files in os.walk(full_path):
                if ".git" in root or "node_modules" in root:
                    continue
                for name in files:
                    filepath = os.path.join(root, name)
                    try:
                        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                            for i, line in enumerate(f):
                                if regex:
                                    if compiled.search(line):
                                        matches.append({"file": ws.get_relative_path(filepath), "line": i + 1, "content": line.strip()})
                                else:
                                    if pattern in line:
                                        matches.append({"file": ws.get_relative_path(filepath), "line": i + 1, "content": line.strip()})
                    except Exception:
                        pass
            return ToolResult(
                success=True,
                tool=self.name,
                result={"matches": matches[:100]}
            )
        except PathSecurityError as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": str(e)}
            )
