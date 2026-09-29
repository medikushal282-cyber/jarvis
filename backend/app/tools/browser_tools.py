import os
import time
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

from app.tools.base import Tool, ToolResult, ToolContext


class BrowserOpenTool(Tool):
    name = "open_browser"
    description = "Opens a workspace file or URL for live browser preview."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path or preview URL (e.g. 'index.html')"}
        }
    }
    required_permissions = ["browser.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        path = arguments.get("path", "index.html")
        try:
            url = f"http://localhost:8006/api/preview/{urllib.parse.quote(path)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8', errors='replace')
            return ToolResult(
                success=True,
                tool=self.name,
                result={"path": path, "url": url, "html_snippet": html[:2500]}
            )
        except Exception as e:
            return ToolResult(
                success=True,
                tool=self.name,
                result={"path": path, "url": f"http://localhost:8006/api/preview/{urllib.parse.quote(path)}", "note": str(e)}
            )


import os
from app.artifacts import get_artifact_manager, get_default_artifacts_dir
from app.events import emit
import asyncio

class BrowserScreenshotTool(Tool):
    name = "browser_screenshot"
    description = (
        "Takes a screenshot of a web page using Playwright Chromium and registers it as a user-facing visual artifact. "
        "Returns secure artifact metadata and URL for the clickable preview."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target web page URL to screenshot"},
            "output_path": {"type": "string", "description": "Optional custom filename or relative path (e.g. 'mr_beast_google_search.png')"}
        },
        "required": ["url"]
    }
    required_permissions = ["browser.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        url = arguments.get("url", "").strip()
        raw_output_path = arguments.get("output_path", "").strip()

        if not url:
            return ToolResult(
                success=False,
                tool=self.name,
                error={"code": "MISSING_URL", "message": "Argument 'url' is required."}
            )

        # Ensure target directory is inside artifacts folder
        artifacts_dir = get_default_artifacts_dir()
        if not raw_output_path:
            filename = f"screenshot_{int(time.time())}.png"
            target_path = os.path.join(artifacts_dir, filename)
        else:
            filename = os.path.basename(raw_output_path)
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
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

            # 1. VERIFY ARTIFACT EXISTS AND IS NON-ZERO
            if not os.path.exists(target_path) or os.path.getsize(target_path) == 0:
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={
                        "code": "ARTIFACT_CREATION_FAILED",
                        "message": f"Browser screenshot could not be captured or resulted in an empty file."
                    }
                )

            # 2. REGISTER WITH ARTIFACT MANAGER
            session_id = context.session_id if context else None
            manager = get_artifact_manager()
            artifact = manager.register_artifact(
                file_path=target_path,
                filename=filename,
                source_tool=self.name,
                session_id=session_id,
                metadata={"target_url": url}
            )

            # 3. EMIT ARTIFACT CREATED EVENT TO FRONTEND STREAM
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
                metadata={"artifact_verified": True}
            )

        except ImportError:
            return ToolResult(
                success=False,
                tool=self.name,
                error={
                    "code": "DEPENDENCY_MISSING",
                    "message": "Playwright is not installed. Install with 'pip install playwright && playwright install chromium'."
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={
                    "code": "BROWSER_EXECUTION_ERROR",
                    "message": f"Browser screenshot failed: {str(e)}."
                }
            )


class BrowserNavigateTool(Tool):
    name = "browser_navigate"
    description = "Navigates a browser session to a URL and returns text content."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL"}
        },
        "required": ["url"]
    }
    required_permissions = ["browser.execute"]

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        url = arguments.get("url", "")
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
                success=False,
                tool=self.name,
                error={
                    "code": "DEPENDENCY_MISSING",
                    "message": "Playwright is not installed. Run 'pip install playwright && playwright install chromium'."
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                error={
                    "code": "BROWSER_EXECUTION_ERROR",
                    "message": f"Browser navigation failed: {e}"
                }
            )
