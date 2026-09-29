import os
import asyncio
from typing import Dict, Any, Optional, Union, Tuple, List

from app.workspace.manager import get_workspace_manager, PathSecurityError, CommandDeniedError
from app.workspace.policy import check_command_policy, POLICY_SAFE, POLICY_APPROVAL_REQUIRED, POLICY_DENIED
from app.events import emit
from app.workspace.artifact_cleaner import extract_and_validate_artifact

TOOL_SCHEMAS = {
    "list_directory": {
        "description": "Lists contents of a directory in the workspace.",
        "parameters": {"path": "string (optional, defaults to '.')"}
    },
    "read_file": {
        "description": "Reads contents of a file inside the workspace.",
        "parameters": {"path": "string (required)"}
    },
    "create_file": {
        "description": "Creates a new file in the workspace with given content.",
        "parameters": {"path": "string (required)", "content": "string (required)"}
    },
    "update_file": {
        "description": "Updates an existing file in the workspace with given content.",
        "parameters": {"path": "string (required)", "content": "string (required)"}
    },
    "delete_file": {
        "description": "Deletes a file inside the workspace. Requires approval if protected or destructive.",
        "parameters": {"path": "string (required)"}
    },
    "run_command": {
        "description": "Executes a safe process inside the workspace with cwd = workspace_root.",
        "parameters": {"command": "string or list of strings (required)", "timeout": "integer (optional, default 30)"}
    },
    "inspect_runtime": {
        "description": "Returns runtime environment information for Python, Node, Git, etc.",
        "parameters": {}
    },
    "search_files": {"description": "Search within files.", "parameters": {"pattern": "string", "path": "string", "regex": "bool"}},
    "search_web": {"description": "Web search for research.", "parameters": {"query": "string"}},
    "append_file": {"description": "Append to a file.", "parameters": {"path": "string", "content": "string"}},
    "rename_file": {"description": "Rename/move a file.", "parameters": {"old_path": "string", "new_path": "string"}},
    "copy_file": {"description": "Copy a file.", "parameters": {"src": "string", "dest": "string"}},
    "get_file_info": {"description": "Get file metadata.", "parameters": {"path": "string"}},
    "list_directory_tree": {"description": "Recursive tree listing.", "parameters": {"path": "string", "max_depth": "int"}},
    "diff_files": {"description": "Get unified diff.", "parameters": {"path_a": "string", "path_b": "string"}},
    "install_package": {"description": "Install dependencies.", "parameters": {"name": "string", "manager": "string"}},
    "patch_file": {"description": "Find-and-replace in a file.", "parameters": {"path": "string", "find": "string", "replace": "string"}},
    "preview_browser": {"description": "Preview a file rendering in the browser.", "parameters": {"path": "string"}}
}

def tool_list_directory(path: str = ".") -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        res = ws.list_directory(path)
        if not res.get("success"):
            err_msg = res.get("error", "Failed to list directory")
            code = "FILE_NOT_FOUND" if "does not exist" in err_msg else "TOOL_EXECUTION_ERROR"
            return {
                "success": False,
                "tool": "list_directory",
                "path": path,
                "result": None,
                "error": {"code": code, "message": err_msg}
            }
        result_payload = {
            "path": res.get("path", path),
            "entries": res.get("entries", [])
        }
        return {
            "success": True,
            "tool": "list_directory",
            "path": res.get("path", path),
            "entries": res.get("entries", []),
            "result": result_payload,
            "error": None
        }
    except PathSecurityError as e:
        return {
            "success": False,
            "tool": "list_directory",
            "path": path,
            "result": None,
            "error": {"code": "PATH_SECURITY_ERROR", "message": str(e)}
        }
    except Exception as e:
        return {
            "success": False,
            "tool": "list_directory",
            "path": path,
            "result": None,
            "error": {"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
        }

def tool_read_file(path: str) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        res = ws.read_file(path)
        if not res.get("success"):
            err_msg = res.get("error", "Failed to read file")
            code = "FILE_NOT_FOUND" if "does not exist" in err_msg else "TOOL_EXECUTION_ERROR"
            return {
                "success": False,
                "tool": "read_file",
                "path": path,
                "content": None,
                "result": None,
                "error": {"code": code, "message": err_msg}
            }
        content = res.get("content", "")
        result_payload = {
            "path": res.get("path", path),
            "content": content,
            "bytes_read": len(content.encode("utf-8"))
        }
        return {
            "success": True,
            "tool": "read_file",
            "path": res.get("path", path),
            "content": content,
            "result": result_payload,
            "error": None
        }
    except PathSecurityError as e:
        return {
            "success": False,
            "tool": "read_file",
            "path": path,
            "result": None,
            "error": {"code": "PATH_SECURITY_ERROR", "message": str(e)}
        }
    except Exception as e:
        return {
            "success": False,
            "tool": "read_file",
            "path": path,
            "result": None,
            "error": {"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
        }

def tool_create_file(path: str, content: str) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        valid, clean_content, err_msg = extract_and_validate_artifact(path, content)
        if not valid:
            return {
                "success": False,
                "tool": "create_file",
                "path": path,
                "result": None,
                "error": {"code": "ARTIFACT_EXTRACTION_ERROR", "message": err_msg or "Failed to extract valid artifact content"}
            }
        content = clean_content
        res = ws.write_file(path, content)
        if not res.get("success"):
            return {
                "success": False,
                "tool": "create_file",
                "path": path,
                "result": None,
                "error": {"code": "TOOL_EXECUTION_ERROR", "message": res.get("error", "Failed to create file")}
            }
        lines = len(content.splitlines())
        bytes_written = res.get("bytes_written", len(content.encode("utf-8")))
        result_payload = {
            "path": res.get("path", path),
            "lines": lines,
            "bytes_written": bytes_written
        }
        return {
            "success": True,
            "tool": "create_file",
            "path": res.get("path", path),
            "lines": lines,
            "bytes_written": bytes_written,
            "result": result_payload,
            "error": None
        }
    except PathSecurityError as e:
        return {
            "success": False,
            "tool": "create_file",
            "path": path,
            "result": None,
            "error": {"code": "PATH_SECURITY_ERROR", "message": str(e)}
        }
    except Exception as e:
        return {
            "success": False,
            "tool": "create_file",
            "path": path,
            "result": None,
            "error": {"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
        }

def tool_update_file(path: str, content: str) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        valid, clean_content, err_msg = extract_and_validate_artifact(path, content)
        if not valid:
            return {
                "success": False,
                "tool": "update_file",
                "path": path,
                "result": None,
                "error": {"code": "ARTIFACT_EXTRACTION_ERROR", "message": err_msg or "Failed to extract valid artifact content"}
            }
        content = clean_content
        full_path = ws.resolve_path(path)
        existed = os.path.exists(full_path)
        old_lines = 0
        if existed:
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    old_lines = len(f.readlines())
            except Exception:
                pass

        res = ws.write_file(path, content)
        if not res.get("success"):
            return {
                "success": False,
                "tool": "update_file",
                "path": path,
                "result": None,
                "error": {"code": "TOOL_EXECUTION_ERROR", "message": res.get("error", "Failed to update file")}
            }
        new_lines = len(content.splitlines())
        diff_info = f"+{max(0, new_lines - old_lines)} / -{max(0, old_lines - new_lines)} lines"
        bytes_written = res.get("bytes_written", len(content.encode("utf-8")))
        result_payload = {
            "path": res.get("path", path),
            "lines": new_lines,
            "diff": diff_info,
            "bytes_written": bytes_written
        }
        return {
            "success": True,
            "tool": "update_file",
            "path": res.get("path", path),
            "lines": new_lines,
            "diff": diff_info,
            "bytes_written": bytes_written,
            "result": result_payload,
            "error": None
        }
    except PathSecurityError as e:
        return {
            "success": False,
            "tool": "update_file",
            "path": path,
            "result": None,
            "error": {"code": "PATH_SECURITY_ERROR", "message": str(e)}
        }
    except Exception as e:
        return {
            "success": False,
            "tool": "update_file",
            "path": path,
            "result": None,
            "error": {"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
        }

def tool_delete_file(path: str, approved: bool = False) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        # Validate path containment first
        full_path = ws.resolve_path(path)
        if not approved:
            reason = "Destructive file deletion requires explicit user approval."
            return {
                "success": False,
                "tool": "delete_file",
                "path": path,
                "status": "approval_required",
                "reason": reason,
                "policy": POLICY_APPROVAL_REQUIRED,
                "result": {
                    "status": "approval_required",
                    "reason": reason,
                    "policy": POLICY_APPROVAL_REQUIRED
                },
                "error": {
                    "code": "APPROVAL_REQUIRED",
                    "message": reason
                }
            }

        result = ws.delete_file(path)
        if result.get("success"):
            return {
                "success": True,
                "tool": "delete_file",
                "path": path,
                "status": "deleted",
                "result": {"path": path, "status": "deleted"},
                "error": None
            }
        return {
            "success": False,
            "tool": "delete_file",
            "path": path,
            "status": "failed",
            "result": None,
            "error": {"code": "TOOL_EXECUTION_ERROR", "message": result.get("error", "File deletion failed.")}
        }
    except PathSecurityError as e:
        return {
            "success": False,
            "tool": "delete_file",
            "path": path,
            "status": "failed",
            "result": None,
            "error": {"code": "PATH_SECURITY_ERROR", "message": str(e)}
        }
    except Exception as e:
        return {
            "success": False,
            "tool": "delete_file",
            "path": path,
            "status": "failed",
            "result": None,
            "error": {"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
        }

def tool_run_command(command: Union[str, List[str]], timeout: int = 30) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        policy, reason = check_command_policy(command)
        if policy == POLICY_DENIED:
            return {
                "success": False,
                "tool": "run_command",
                "command": str(command),
                "status": "denied",
                "reason": reason,
                "exit_code": 126,
                "result": None,
                "error": {
                    "code": "COMMAND_DENIED",
                    "message": f"Command execution denied by security policy: {reason}"
                }
            }
        elif policy == POLICY_APPROVAL_REQUIRED:
            return {
                "success": False,
                "tool": "run_command",
                "command": str(command),
                "status": "approval_required",
                "reason": reason,
                "exit_code": 126,
                "result": {
                    "status": "approval_required",
                    "reason": reason
                },
                "error": {
                    "code": "APPROVAL_REQUIRED",
                    "message": f"Command requires approval: {reason}"
                }
            }

        res = ws.execute_process(command, timeout=timeout)
        success = (res.get("exit_code") == 0)
        result_payload = {
            "command": res.get("command", str(command)),
            "exit_code": res.get("exit_code", 1),
            "stdout": res.get("stdout", ""),
            "stderr": res.get("stderr", ""),
            "duration": res.get("duration", 0),
            "working_directory": res.get("working_directory")
        }
        
        error_info = None
        if not success:
            err_msg = res.get("stderr", "").strip() or f"Process exited with code {res.get('exit_code')}"
            error_info = {
                "code": "PROCESS_EXECUTION_ERROR",
                "message": err_msg
            }

        return {
            "success": success,
            "tool": "run_command",
            "command": res.get("command", str(command)),
            "exit_code": res.get("exit_code", 1),
            "stdout": res.get("stdout", ""),
            "stderr": res.get("stderr", ""),
            "duration": res.get("duration", 0),
            "working_directory": res.get("working_directory"),
            "result": result_payload,
            "error": error_info
        }
    except CommandDeniedError as e:
        return {
            "success": False,
            "tool": "run_command",
            "command": str(command),
            "status": "denied",
            "exit_code": 126,
            "result": None,
            "error": {"code": "COMMAND_DENIED", "message": str(e)}
        }
    except Exception as e:
        return {
            "success": False,
            "tool": "run_command",
            "command": str(command),
            "exit_code": 1,
            "result": None,
            "error": {"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
        }

def tool_inspect_runtime() -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        runtimes = ws.get_runtime_info()
        return {
            "success": True,
            "tool": "inspect_runtime",
            "runtime": runtimes,
            "result": {"runtime": runtimes},
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "tool": "inspect_runtime",
            "result": None,
            "error": {"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
        }


import fnmatch
import shutil
import difflib
import urllib.request
import urllib.parse
from datetime import datetime

def tool_search_files(pattern: str, path: str = ".", regex: bool = False) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        full_path = ws.resolve_path(path)
        if not os.path.isdir(full_path):
            return {"success": False, "tool": "search_files", "error": {"code": "NOT_A_DIRECTORY", "message": "Path is not a directory"}}
        
        matches = []
        if regex:
            compiled = re.compile(pattern)
        for root, _, files in os.walk(full_path):
            if '.git' in root or 'node_modules' in root:
                continue
            for name in files:
                filepath = os.path.join(root, name)
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f):
                            if regex:
                                if compiled.search(line):
                                    matches.append({"file": ws.get_relative_path(filepath), "line": i+1, "content": line.strip()})
                            else:
                                if pattern in line:
                                    matches.append({"file": ws.get_relative_path(filepath), "line": i+1, "content": line.strip()})
                except Exception:
                    pass
        return {"success": True, "tool": "search_files", "result": {"matches": matches[:100]}}
    except Exception as e:
        return {"success": False, "tool": "search_files", "error": {"code": "TOOL_ERROR", "message": str(e)}}

def tool_search_web(query: str) -> Dict[str, Any]:
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
        
        # Simple extraction of snippets
        results = []
        for m in re.finditer(r'<a class="result__snippet[^>]*>(.*?)</a>', html, re.DOTALL):
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if text:
                results.append(text)
        return {"success": True, "tool": "search_web", "result": {"query": query, "snippets": results[:5]}}
    except Exception as e:
        return {"success": False, "tool": "search_web", "error": {"code": "TOOL_ERROR", "message": str(e)}}

def tool_append_file(path: str, content: str) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        full_path = ws.resolve_path(path)
        with open(full_path, "a", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "tool": "append_file", "result": {"path": path, "appended": True}}
    except Exception as e:
        return {"success": False, "tool": "append_file", "error": {"code": "TOOL_ERROR", "message": str(e)}}

def tool_rename_file(old_path: str, new_path: str) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        old_full = ws.resolve_path(old_path)
        new_full = ws.resolve_path(new_path)
        os.rename(old_full, new_full)
        return {"success": True, "tool": "rename_file", "result": {"old": old_path, "new": new_path}}
    except Exception as e:
        return {"success": False, "tool": "rename_file", "error": {"code": "TOOL_ERROR", "message": str(e)}}

def tool_copy_file(src: str, dest: str) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        src_full = ws.resolve_path(src)
        dest_full = ws.resolve_path(dest)
        if os.path.isdir(src_full):
            shutil.copytree(src_full, dest_full)
        else:
            shutil.copy2(src_full, dest_full)
        return {"success": True, "tool": "copy_file", "result": {"src": src, "dest": dest}}
    except Exception as e:
        return {"success": False, "tool": "copy_file", "error": {"code": "TOOL_ERROR", "message": str(e)}}

def tool_get_file_info(path: str) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        full = ws.resolve_path(path)
        st = os.stat(full)
        info = {
            "size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
            "is_dir": os.path.isdir(full)
        }
        return {"success": True, "tool": "get_file_info", "result": {"path": path, "info": info}}
    except Exception as e:
        return {"success": False, "tool": "get_file_info", "error": {"code": "TOOL_ERROR", "message": str(e)}}

def tool_list_directory_tree(path: str = ".", max_depth: int = 3) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        start_full = ws.resolve_path(path)
        start_depth = start_full.count(os.sep)
        tree = []
        for root, dirs, files in os.walk(start_full):
            if '.git' in dirs: dirs.remove('.git')
            if 'node_modules' in dirs: dirs.remove('node_modules')
            depth = root.count(os.sep) - start_depth
            if depth >= max_depth:
                del dirs[:]
            rel_root = ws.get_relative_path(root)
            tree.append({"directory": rel_root, "files": files})
        return {"success": True, "tool": "list_directory_tree", "result": {"tree": tree[:100]}}
    except Exception as e:
        return {"success": False, "tool": "list_directory_tree", "error": {"code": "TOOL_ERROR", "message": str(e)}}

def tool_diff_files(path_a: str, path_b: str) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        fa = ws.resolve_path(path_a)
        fb = ws.resolve_path(path_b)
        with open(fa, 'r', encoding='utf-8', errors='ignore') as a, open(fb, 'r', encoding='utf-8', errors='ignore') as b:
            diff = list(difflib.unified_diff(a.readlines(), b.readlines(), fromfile=path_a, tofile=path_b))
        return {"success": True, "tool": "diff_files", "result": {"diff": "".join(diff)}}
    except Exception as e:
        return {"success": False, "tool": "diff_files", "error": {"code": "TOOL_ERROR", "message": str(e)}}

def tool_install_package(name: str, manager: str = "pip", approved: bool = False) -> Dict[str, Any]:
    if not approved:
        reason = "Package installation requires user approval."
        return {"success": False, "tool": "install_package", "status": "approval_required", "reason": reason, "error": {"code": "APPROVAL_REQUIRED", "message": reason}}
    cmd = f"{manager} install {name}"
    return tool_run_command(cmd)

def tool_patch_file(path: str, find: str, replace: str, count: int = 1) -> Dict[str, Any]:
    ws = get_workspace_manager()
    try:
        full = ws.resolve_path(path)
        with open(full, 'r', encoding='utf-8') as f:
            data = f.read()
        data = data.replace(find, replace, count)
        with open(full, 'w', encoding='utf-8') as f:
            f.write(data)
        return {"success": True, "tool": "patch_file", "result": {"path": path, "patched": True}}
    except Exception as e:
        return {"success": False, "tool": "patch_file", "error": {"code": "TOOL_ERROR", "message": str(e)}}

def tool_preview_browser(path: str = "") -> Dict[str, Any]:
    try:
        if not path:
            path = "index.html"
        url = "http://localhost:8005/api/preview/" + urllib.parse.quote(path)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='replace')
        return {"success": True, "tool": "preview_browser", "result": {"path": path, "html_snippet": html[:2500]}}
    except Exception as e:
        return {"success": False, "tool": "preview_browser", "error": {"code": "TOOL_ERROR", "message": str(e)}}

DISPATCH_TABLE = {
    "list_directory": tool_list_directory,
    "read_file": tool_read_file,
    "create_file": tool_create_file,
    "update_file": tool_update_file,
    "delete_file": tool_delete_file,
    "run_command": tool_run_command,
    "inspect_runtime": tool_inspect_runtime,
    "search_files": tool_search_files,
    "search_web": tool_search_web,
    "append_file": tool_append_file,
    "rename_file": tool_rename_file,
    "copy_file": tool_copy_file,
    "get_file_info": tool_get_file_info,
    "list_directory_tree": tool_list_directory_tree,
    "diff_files": tool_diff_files,
    "install_package": tool_install_package,
    "patch_file": tool_patch_file,
    "preview_browser": tool_preview_browser,
    "open_browser": tool_preview_browser,
}

def validate_action_schema(action: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    if not isinstance(action, dict):
        return False, {"code": "INVALID_ACTION_FORMAT", "message": "Action must be a JSON object"}
    
    tool_name = action.get("tool")
    if not tool_name or not isinstance(tool_name, str):
        return False, {"code": "INVALID_ACTION_FORMAT", "message": "Action missing required 'tool' field"}
        
    if tool_name not in TOOL_SCHEMAS:
        return False, {"code": "UNKNOWN_TOOL", "message": f"Tool '{tool_name}' is not recognized"}
        
    args = action.get("arguments")
    if args is None:
        args = {}
    elif not isinstance(args, dict):
        return False, {"code": "INVALID_ARGUMENTS", "message": "Action 'arguments' must be a JSON object"}
        
    if tool_name in ["read_file", "delete_file"]:
        if "path" not in args or not str(args["path"]).strip():
            return False, {"code": "INVALID_ARGUMENTS", "message": f"Tool '{tool_name}' requires non-empty 'path' argument"}
    elif tool_name in ["create_file", "update_file"]:
        if "path" not in args or not str(args["path"]).strip():
            return False, {"code": "INVALID_ARGUMENTS", "message": f"Tool '{tool_name}' requires non-empty 'path' argument"}
        if "content" not in args or args["content"] is None:
            return False, {"code": "INVALID_ARGUMENTS", "message": f"Tool '{tool_name}' requires 'content' argument"}
    elif tool_name == "run_command":
        if "command" not in args or not args["command"]:
            return False, {"code": "INVALID_ARGUMENTS", "message": "Tool 'run_command' requires 'command' argument"}

    return True, None

def execute_action(action: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates and executes a structured action:
    {
      "tool": "create_file",
      "arguments": {
        "path": "example.py",
        "content": "..."
      }
    }
    Returns a structured result.
    """
    valid, err = validate_action_schema(action)
    tool_name = action.get("tool", "unknown") if isinstance(action, dict) else "unknown"
    if not valid:
        return {
            "success": False,
            "tool": tool_name,
            "result": None,
            "error": err
        }
        
    args = action.get("arguments", {})
    fn = DISPATCH_TABLE[tool_name]
    try:
        return fn(**args)
    except TypeError as e:
        return {
            "success": False,
            "tool": tool_name,
            "result": None,
            "error": {"code": "INVALID_ARGUMENTS", "message": f"Invalid arguments for tool '{tool_name}': {e}"}
        }
    except Exception as e:
        return {
            "success": False,
            "tool": tool_name,
            "result": None,
            "error": {"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
        }

def execute_tool(tool: Union[str, Dict[str, Any]], **kwargs) -> Dict[str, Any]:
    """
    Flexible wrapper that handles both structured action dicts and traditional tool name + kwargs.
    """
    if isinstance(tool, dict):
        return execute_action(tool)
    else:
        return execute_action({"tool": tool, "arguments": kwargs})

def validate_python_source(rel_path: str) -> Dict[str, Any]:
    """
    Generic pre-execution artifact validator for Python source files.
    Verifies that target file exists inside workspace and is syntactically valid Python.
    Does NOT hardcode any specific filenames.
    """
    ws = get_workspace_manager()
    try:
        full_path = ws.resolve_path(rel_path)
    except PathSecurityError as e:
        return {
            "valid": False,
            "kind": "permission_error",
            "path": rel_path,
            "message": str(e)
        }

    if not os.path.exists(full_path):
        return {
            "valid": False,
            "kind": "missing_file",
            "path": rel_path,
            "message": f"File '{rel_path}' does not exist."
        }

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        from app.workspace.artifact_cleaner import extract_and_validate_artifact
        valid, clean_content, err_msg = extract_and_validate_artifact(rel_path, content)
        if not valid:
            return {
                "valid": False,
                "kind": "syntax_error",
                "path": rel_path,
                "message": err_msg or "Artifact structure validation failed.",
                "stderr": f"Artifact validation failed for {rel_path}: {err_msg}"
            }

        conversational_prefixes = (
            "i'll start by", "i'll", "i will", "let me", "first, i'll", "first,",
            "now i need to", "now i", "insight", "here is the corrected code",
            "here is the python code", "here is", "here's", "sure,", "sure",
            "let's", "to accomplish this", "to solve", "this script", "the following",
            "below is", "certainly", "i need", "i cannot"
        )
        for line in content.splitlines():
            stripped = line.strip().lower()
            if any(stripped.startswith(p) for p in conversational_prefixes):
                if not line.strip().startswith("#") and not line.strip().startswith("import ") and not line.strip().startswith("from "):
                    return {
                        "valid": False,
                        "kind": "syntax_error",
                        "path": rel_path,
                        "message": f"Python artifact contains model preamble text: '{line.strip()[:60]}'",
                        "stderr": f"SyntaxError: Invalid model preamble line in {rel_path}: '{line.strip()[:60]}'"
                    }

        compile(clean_content, rel_path, "exec")
        return {
            "valid": True,
            "kind": "syntax_ok",
            "path": rel_path,
            "message": "Python syntax validation passed."
        }
    except SyntaxError as e:
        return {
            "valid": False,
            "kind": "syntax_error",
            "path": rel_path,
            "line": getattr(e, "lineno", 1),
            "message": f"SyntaxError: {e.msg} (line {getattr(e, 'lineno', 1)})",
            "stderr": f"SyntaxError: {e.msg} (line {getattr(e, 'lineno', 1)})\n  {getattr(e, 'text', '') or ''}"
        }
    except Exception as e:
        return {
            "valid": False,
            "kind": "syntax_error",
            "path": rel_path,
            "message": f"Compilation error: {str(e)}",
            "stderr": str(e)
        }

def classify_failure(exit_code: int, stdout: str = "", stderr: str = "", obj_reason: str = "") -> str:
    """
    Classifies process or validation failures into distinct categories:
    - syntax_error
    - runtime_error
    - missing_file
    - missing_arguments
    - permission_error
    - validation_error
    - command_error
    - artifact_extraction_error
    """
    if exit_code == 0 and not obj_reason:
        return "syntax_ok"

    combined = (stderr + "\n" + stdout + "\n" + obj_reason).lower()

    if any(err in combined for err in ["syntaxerror", "indentationerror", "taberror", "invalid syntax", "compilation error", "artifact_extraction_error", "extracted content for"]):
        return "syntax_error"

    if any(err in combined for err in ["nameerror", "typeerror", "valueerror", "attributeerror", "keyerror", "indexerror", "unboundlocalerror", "runtimeerror", "importerror", "modulenotfounderror", "zerodivisionerror", "recursionerror", "assertionerror"]):
        return "runtime_error"

    if "filenotfounderror" in combined or "no such file or directory" in combined or "does not exist" in combined:
        return "missing_file"

    if "usage:" in combined or "required positional argument" in combined or "too few arguments" in combined or "argparse" in combined or "sys.argv" in combined or "missing required input arguments" in combined:
        return "missing_arguments"

    if "permissionerror" in combined or "access denied" in combined or "permission denied" in combined or "path_security_error" in combined:
        return "permission_error"

    if "failed objective requirement validation" in combined or "missing expected text" in combined:
        return "validation_error"

    return "command_error"


