"""
app/tools/browser_tools.py — Browser capability tools

Security:
  - open_browser: local preview only (connects to preview server)
  - browser_screenshot / browser_navigate: SSRF-protected via shared validator
  - No arbitrary private URL access

Owner: Lohith (Capability / Tool Layer)
"""

import os
import time
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

from app.tools.base import Tool, ToolResult, ToolContext
from app.tools.http_tools import validate_url_for_ssrf


# ── Browser URL Security ──────────────────────────────────────────────────────

# The JARVIS local preview server endpoint
_PREVIEW_HOST = "http://localhost:8006"
_PREVIEW_HOST_ALT = "http://127.0.0.1:8006"

def _is_authorized_preview_url(url: str) -> bool:
    """Returns True if the URL is the controlled local preview server."""
    return url.startswith(_PREVIEW_HOST) or url.startswith(_PREVIEW_HOST_ALT)


def validate_browser_url(url: str, allow_local_preview: bool = False) -> tuple[bool, Optional[str]]:
    """
    Validate a URL for browser navigation.

    Local preview URLs (localhost:8006) are permitted only when
    allow_local_preview=True. All other private/internal URLs are blocked.

    Returns: (is_valid: bool, error_message: Optional[str])
    """
    if not url:
        return False, "URL is required"
    if not url.startswith(("http://", "https://")):
        return False, "Only http:// and https:// URLs are supported"

    # Allow authorized local preview
    if allow_local_preview and _is_authorized_preview_url(url):
        return True, None

    # For all other URLs, apply full SSRF protection
    return validate_url_for_ssrf(url, allow_private=False)


# ── Tools ─────────────────────────────────────────────────────────────────────


class BrowserOpenTool(Tool):
    name = "open_browser"
    description = "Opens a workspace file for live browser preview via the local preview server."
    risk = "low"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative workspace file path (e.g. 'index.html')"}
        }
    }
    required_permissions = ["browser.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", "index.html")
        # Sanitize path: remove leading / or ..
        clean_path = path.lstrip("/").lstrip("\\")
        if ".." in clean_path:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "PATH_SECURITY_ERROR", "message": "Path traversal not allowed in preview path"}
            )
        url = f"{_PREVIEW_HOST}/api/preview/{urllib.parse.quote(clean_path)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-Preview/1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode("utf-8", errors="replace")
                status_code = response.status
            if status_code != 200:
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={
                        "code": "PREVIEW_ERROR",
                        "message": f"Preview server returned HTTP {status_code}"
                    }
                )
            return ToolResult(
                success=True,
                tool=self.name,
                result={"path": clean_path, "url": url, "html_snippet": html[:2500]}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={
                    "code": "PREVIEW_UNAVAILABLE",
                    "message": f"Could not connect to local preview server: {e}. "
                               f"Ensure the preview server is running at {_PREVIEW_HOST}"
                }
            )


import asyncio
from app.artifacts import get_artifact_manager, get_default_artifacts_dir
from app.events import emit


class BrowserScreenshotTool(Tool):
    name = "browser_screenshot"
    description = (
        "Takes a screenshot of a web page using Playwright Chromium and registers it as an artifact. "
        "Only permits external URLs — private/internal network addresses are blocked."
    )
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target web page URL to screenshot (external URLs only)"},
            "output_path": {"type": "string", "description": "Optional custom filename (e.g. 'result.png')"}
        },
        "required": ["url"]
    }
    required_permissions = ["browser.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        url = arguments.get("url", "").strip()
        raw_output_path = arguments.get("output_path", "").strip()

        if not url:
            return ToolResult(
                success=False, tool=self.name,
                error={"code": "MISSING_URL", "message": "Argument 'url' is required."}
            )

        # SSRF protection: allow local preview server, block everything else private
        is_valid, err_msg = validate_browser_url(url, allow_local_preview=True)
        if not is_valid:
            return ToolResult(
                success=False, tool=self.name,
                status="security_blocked",
                error={"code": "SSRF_BLOCKED", "message": f"URL blocked by browser security policy: {err_msg}"}
            )

        # Ensure output goes to artifacts directory
        artifacts_dir = get_default_artifacts_dir()
        if not raw_output_path:
            filename = f"screenshot_{int(time.time())}.png"
        else:
            filename = os.path.basename(raw_output_path)
            if not filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                filename = f"{filename}.png"
        target_path = os.path.join(artifacts_dir, filename)

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.goto(url, timeout=20000, wait_until="load")
                page.screenshot(path=target_path, full_page=False)
                browser.close()

            if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
                return ToolResult(
                    success=False, tool=self.name,
                    error={"code": "ARTIFACT_CREATION_FAILED", "message": "Screenshot resulted in empty file."}
                )

            session_id = context.session_id if context else None
            manager = get_artifact_manager()
            artifact = manager.register_artifact(
                file_path=target_path,
                filename=filename,
                source_tool=self.name,
                session_id=session_id,
                metadata={"target_url": url}
            )

            if session_id:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(emit(session_id, "artifact_created", self.name, artifact.to_dict()))
                except Exception:
                    pass

            return ToolResult(
                success=True,
                tool=self.name,
                data=artifact.to_dict(),
                result=artifact.to_dict(),
                artifacts=[artifact.to_dict()],
                metadata={"artifact_verified": True}
            )

        except ImportError:
            return ToolResult(
                success=False, tool=self.name,
                error={"code": "DEPENDENCY_MISSING", "message": "Playwright not installed. Run: pip install playwright && playwright install chromium"}
            )
        except Exception as e:
            return ToolResult(
                success=False, tool=self.name,
                error={"code": "BROWSER_EXECUTION_ERROR", "message": f"Browser screenshot failed: {e}"}
            )


class BrowserNavigateTool(Tool):
    name = "browser_navigate"
    description = (
        "Navigates a browser session to a URL and returns page text. "
        "Private/internal network addresses are blocked for security."
    )
    risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL (external only)"}
        },
        "required": ["url"]
    }
    required_permissions = ["browser.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        url = arguments.get("url", "")

        # SSRF protection
        is_valid, err_msg = validate_browser_url(url, allow_local_preview=True)
        if not is_valid:
            return ToolResult(
                success=False, tool=self.name,
                status="security_blocked",
                error={"code": "SSRF_BLOCKED", "message": f"URL blocked by browser security policy: {err_msg}"}
            )

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=15000)
                content = page.content()
                title = page.title()
                browser.close()
            return ToolResult(
                success=True,
                tool=self.name,
                result={"url": url, "title": title, "content_snippet": content[:3000]}
            )
        except ImportError:
            return ToolResult(
                success=False, tool=self.name,
                error={"code": "DEPENDENCY_MISSING", "message": "Playwright not installed."}
            )
        except Exception as e:
            return ToolResult(
                success=False, tool=self.name,
                error={"code": "BROWSER_EXECUTION_ERROR", "message": f"Browser navigation failed: {e}"}
            )
