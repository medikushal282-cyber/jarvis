import os
import sys
import unittest
import tempfile
import time
import subprocess
from typing import Set

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools.base import Tool, ToolResult, ToolContext
from app.tools.registry import ToolRegistry, get_tool_registry
from app.tools.filesystem import (
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
    CreateFileTool,
    UpdateFileTool,
    DeleteFileTool,
    MoveFileTool,
    CopyFileTool,
    CreateDirectoryTool,
    SearchFilesTool
)
from app.tools.terminal import RunCommandTool, kill_process_tree
from app.tools.http_tools import (
    HttpGetTool,
    HttpPostTool,
    validate_url_for_ssrf,
    is_private_or_internal_ip,
    execute_http_request_streamed
)
from app.tools.git_tools import GitStatusTool, GitDiffTool, GitLogTool
from app.tools.github_tools import GitHubGetRepoTool, GitHubListIssuesTool
from app.tools.browser_tools import BrowserOpenTool, BrowserScreenshotTool
from app.tools.sandbox_tools import SandboxInspectTool, SandboxExecTool
from app.workspace.manager import WorkspaceManager, get_workspace_manager


class TestCapabilityLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = get_tool_registry()
        cls.ws = get_workspace_manager()

    def setUp(self):
        self.test_filename = "test_cap_file.txt"
        self.abs_test_file = self.ws.resolve_path(self.test_filename)
        if os.path.exists(self.abs_test_file):
            try:
                os.remove(self.abs_test_file)
            except Exception:
                pass

    def tearDown(self):
        if os.path.exists(self.abs_test_file):
            try:
                os.remove(self.abs_test_file)
            except Exception:
                pass

    # --- 1. TOOL REGISTRY TESTS ---
    def test_tool_registry_registration_and_lookup(self):
        self.assertIsNotNone(self.registry.get_tool("read_file"))
        self.assertIsNotNone(self.registry.get_tool("write_file"))
        self.assertIsNotNone(self.registry.get_tool("run_command"))
        self.assertIsNotNone(self.registry.get_tool("http_get"))
        self.assertIsNotNone(self.registry.get_tool("git_status"))

        definitions = self.registry.get_tool_definitions()
        self.assertGreater(len(definitions), 15)
        names = [d["name"] for d in definitions]
        self.assertIn("read_file", names)
        self.assertIn("run_command", names)
        self.assertIn("http_get", names)

    def test_tool_registry_unknown_tool(self):
        res = self.registry.execute("non_existent_tool_xyz", {})
        self.assertFalse(res.success)
        self.assertEqual(res.error["code"], "UNKNOWN_TOOL")

    # --- 2. SCHEMA VALIDATION TESTS ---
    def test_schema_validation_missing_required_argument(self):
        # read_file requires 'path'
        res = self.registry.execute("read_file", {})
        self.assertFalse(res.success)
        self.assertEqual(res.status, "schema_validation_error")
        self.assertEqual(res.error["code"], "MISSING_REQUIRED_ARGUMENT")

    # --- 3. PERMISSION ENFORCEMENT TESTS ---
    def test_permission_denied_when_permission_missing(self):
        # Create context with ONLY read permissions
        read_only_ctx = ToolContext(permissions={"filesystem.read"})

        # read_file should succeed
        with open(self.abs_test_file, "w", encoding="utf-8") as f:
            f.write("hello read permission")

        res_read = self.registry.execute("read_file", {"path": self.test_filename}, context=read_only_ctx)
        self.assertTrue(res_read.success)

        # write_file should fail with PERMISSION_DENIED
        res_write = self.registry.execute(
            "write_file",
            {"path": self.test_filename, "content": "blocked write"},
            context=read_only_ctx
        )
        self.assertFalse(res_write.success)
        self.assertEqual(res_write.status, "permission_denied")
        self.assertEqual(res_write.error["code"], "PERMISSION_DENIED")
        self.assertIn("filesystem.write", res_write.error["required_permission"])

        # delete_file should fail with PERMISSION_DENIED
        res_del = self.registry.execute(
            "delete_file",
            {"path": self.test_filename},
            context=read_only_ctx
        )
        self.assertFalse(res_del.success)
        self.assertEqual(res_del.error["code"], "PERMISSION_DENIED")

    def test_destructive_operations_require_explicit_permissions(self):
        # Context lacking terminal.execute
        no_term_ctx = ToolContext(permissions={"filesystem.read", "filesystem.write"})
        res_term = self.registry.execute("run_command", {"command": "echo test"}, context=no_term_ctx)
        self.assertFalse(res_term.success)
        self.assertEqual(res_term.error["code"], "PERMISSION_DENIED")

        # Context lacking http.write
        no_http_ctx = ToolContext(permissions={"http.read"})
        res_post = self.registry.execute("http_post", {"url": "https://example.com", "data": {}}, context=no_http_ctx)
        self.assertFalse(res_post.success)
        self.assertEqual(res_post.error["code"], "PERMISSION_DENIED")

    # --- 4. FILESYSTEM CAPABILITY TESTS ---
    def test_filesystem_write_read_delete(self):
        ctx = ToolContext()  # Default full permissions

        # 1. Write
        res_write = self.registry.execute(
            "write_file",
            {"path": self.test_filename, "content": "JARVIS capability content"},
            context=ctx
        )
        self.assertTrue(res_write.success)
        self.assertTrue(os.path.exists(self.abs_test_file))

        # 2. Read
        res_read = self.registry.execute("read_file", {"path": self.test_filename}, context=ctx)
        self.assertTrue(res_read.success)
        self.assertIn("JARVIS capability content", res_read.result["content"])

        # 3. Delete
        res_del = self.registry.execute("delete_file", {"path": self.test_filename}, context=ctx)
        self.assertTrue(res_del.success)
        self.assertFalse(os.path.exists(self.abs_test_file))

    def test_filesystem_path_containment_security(self):
        ctx = ToolContext()
        # Path traversal outside workspace must be blocked
        res = self.registry.execute("read_file", {"path": "../../etc/passwd"}, context=ctx)
        self.assertFalse(res.success)
        self.assertEqual(res.error["code"], "PATH_SECURITY_ERROR")

    # --- 5. TERMINAL TIMEOUT & PROCESS ISOLATION TESTS ---
    def test_terminal_timeout_and_process_cleanup(self):
        ctx = ToolContext()
        # Command that sleeps for 10 seconds with a 1-second timeout
        py_sleep_cmd = f"{sys.executable} -c \"import time; time.sleep(10)\""
        
        start = time.time()
        res = self.registry.execute("run_command", {"command": py_sleep_cmd, "timeout": 1}, context=ctx)
        elapsed = time.time() - start

        self.assertFalse(res.success)
        self.assertEqual(res.status, "timeout")
        self.assertEqual(res.error["code"], "TIMEOUT")
        self.assertEqual(res.error["exit_code"], 124)
        # Should have finished in ~1-2 seconds, not waited 10s
        self.assertLess(elapsed, 4.0)

    def test_terminal_successful_execution(self):
        ctx = ToolContext()
        py_echo = f"{sys.executable} -c \"print('JARVIS_TEST_OK')\""
        res = self.registry.execute("run_command", {"command": py_echo}, context=ctx)
        self.assertTrue(res.success)
        self.assertIn("JARVIS_TEST_OK", res.result["stdout"])

    # --- 6. HTTP SSRF & PRIVATE NETWORK SECURITY TESTS ---
    def test_http_ssrf_blocked_destinations(self):
        # Localhost / Loopback / Private IP addresses must be blocked
        self.assertTrue(is_private_or_internal_ip("127.0.0.1"))
        self.assertTrue(is_private_or_internal_ip("10.0.0.1"))
        self.assertTrue(is_private_or_internal_ip("172.16.0.1"))
        self.assertTrue(is_private_or_internal_ip("192.168.1.1"))
        self.assertTrue(is_private_or_internal_ip("169.254.169.254"))

        # Default context blocks private network access
        ctx = ToolContext(allow_private_http=False)
        res = self.registry.execute("http_get", {"url": "http://127.0.0.1:8005/health"}, context=ctx)
        self.assertFalse(res.success)
        self.assertEqual(res.error["code"], "SSRF_BLOCKED")
        self.assertIn("blocked", res.error["message"].lower())

    def test_http_ssrf_allowed_via_trusted_context_policy(self):
        # When explicitly permitted by trusted context policy
        ctx = ToolContext(allow_private_http=True)
        valid, err = validate_url_for_ssrf("http://127.0.0.1:8005/health", allow_private=True)
        self.assertTrue(valid)
        self.assertIsNone(err)

    # --- 7. HTTP STREAMING MEMORY LIMIT TESTS ---
    def test_http_streaming_response_size_limit(self):
        # Calling an endpoint with a tiny max_response_size (e.g. 50 bytes)
        # using a mock or small local request
        from app.tools.http_tools import execute_http_request_streamed
        # Test with a mock or URL that exceeds max_bytes
        # Using a data URL or small http payload that exceeds 10 bytes limit
        res = execute_http_request_streamed(
            method="GET",
            url="http://127.0.0.1:8005/health",
            max_bytes=10,  # 10 bytes limit
            allow_private=True
        )
        # If server is running, it should abort and return RESPONSE_SIZE_EXCEEDED
        if res.get("status_code") == 200:
            self.assertFalse(res["success"])
            self.assertEqual(res["error"]["code"], "RESPONSE_SIZE_EXCEEDED")

    # --- 8. GIT & GITHUB TOOLS TESTS ---
    def test_git_status_tool(self):
        ctx = ToolContext()
        res = self.registry.execute("git_status", {}, context=ctx)
        self.assertTrue(res.success)
        self.assertIsNotNone(res.result)

    def test_github_tools_registration(self):
        self.assertIsNotNone(self.registry.get_tool("github_get_repo"))
        self.assertIsNotNone(self.registry.get_tool("github_list_issues"))
        self.assertIsNotNone(self.registry.get_tool("github_create_issue"))
        self.assertIsNotNone(self.registry.get_tool("github_create_pr"))

    # --- 9. BROWSER & SANDBOX TOOLS TESTS ---
    def test_sandbox_inspect_tool(self):
        ctx = ToolContext()
        res = self.registry.execute("sandbox_inspect", {}, context=ctx)
        self.assertTrue(res.success)
        self.assertIn("workspace_id", res.result)

    def test_browser_open_tool(self):
        ctx = ToolContext()
        res = self.registry.execute("open_browser", {"path": "index.html"}, context=ctx)
        self.assertTrue(res.success)
        self.assertIn("url", res.result)


if __name__ == "__main__":
    unittest.main()
