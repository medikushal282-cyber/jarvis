import os
import time
import mimetypes
import webbrowser
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from pathlib import Path
from typing import Optional

from app.workspace.manager import get_workspace_manager

router = APIRouter(prefix="/preview", tags=["Preview"])

LAST_UPDATE_TIME = time.time()

def notify_file_change():
    global LAST_UPDATE_TIME
    LAST_UPDATE_TIME = time.time()

def get_live_reload_script(workspace_id: str) -> str:
    return f"""
<!-- frAIday Live Sync Agentic Preview Script -->
<script>
(() => {{
  let lastSeen = Date.now() / 1000;
  const poll = async () => {{
    try {{
      const res = await fetch('/api/preview/{workspace_id}/reload-check?since=' + lastSeen);
      if (res.ok) {{
        const data = await res.json();
        if (data.reload) {{
          console.log('[frAIday Live Preview] Detected file change, reloading...');
          window.location.reload();
          return;
        }}
      }}
    }} catch (e) {{}}
    setTimeout(poll, 800);
  }};
  setTimeout(poll, 800);
}})();
</script>
"""

class OpenBrowserRequest(BaseModel):
    file_path: str
    browser: Optional[str] = None  # 'default', 'chrome', 'chromium', etc.

@router.get("/{workspace_id}/reload-check")
async def reload_check(workspace_id: str, since: float = Query(...)):
    global LAST_UPDATE_TIME
    should_reload = LAST_UPDATE_TIME > since
    return {"reload": should_reload, "timestamp": LAST_UPDATE_TIME}

@router.post("/notify-update")
async def trigger_update():
    notify_file_change()
    return {"status": "ok", "timestamp": LAST_UPDATE_TIME}

@router.post("/{workspace_id}/open")
async def open_in_browser(workspace_id: str, req: OpenBrowserRequest):
    """Launches the preview URL in the system browser or Chromium."""
    wm = get_workspace_manager(workspace_id)
    abs_path = Path(wm.resolve_path(req.file_path))
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
    
    url = f"http://localhost:8006/api/preview/{workspace_id}/{req.file_path}"
    try:
        # Try opening via Python webbrowser module (opens default browser e.g. Chrome/Chromium/Edge)
        opened = webbrowser.open(url)
        return {"status": "opened", "url": url, "success": opened}
    except Exception as e:
        return {"status": "error", "message": str(e), "url": url}

@router.get("/{workspace_id}/{file_path:path}")
async def serve_preview_file(workspace_id: str, file_path: str):
    try:
        wm = get_workspace_manager(workspace_id)
        abs_path = Path(wm.resolve_path(file_path))
        
        import html as html_lib

        # If path is directory or empty, check for index.html
        if abs_path.is_dir():
            index_cand = abs_path / "index.html"
            if index_cand.exists():
                abs_path = index_cand
                
        if not abs_path.exists() or not abs_path.is_file():
            available = [f.name for f in Path(wm.root_path).glob("*") if f.is_file()][:10]
            avail_html = "".join([f'<li><a href="/api/preview/{workspace_id}/{name}" style="color:#FFE600;">{name}</a></li>' for name in available])
            not_found_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>File Not Found | Preview</title>
    <style>
        body {{ margin: 0; padding: 24px; background: #0A0A0A; color: #E5E5E5; font-family: monospace; font-size: 13px; }}
        h2 {{ color: #EF4444; margin-top: 0; }}
        ul {{ list-style-type: square; padding-left: 20px; }}
        li {{ margin: 6px 0; }}
    </style>
</head>
<body>
    <h2>File Not Found: {file_path}</h2>
    <p>Available files in workspace root:</p>
    <ul>{avail_html}</ul>
    {get_live_reload_script(workspace_id)}
</body>
</html>"""
            return HTMLResponse(content=not_found_html, status_code=200)
            
        mime_type, _ = mimetypes.guess_type(str(abs_path))
        mime_type = mime_type or "application/octet-stream"

        # For HTML files, inject the live reload script right before </body>
        if mime_type == "text/html" or abs_path.suffix.lower() in [".html", ".htm"]:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            script_tag = get_live_reload_script(workspace_id)
            if "</body>" in content:
                content = content.replace("</body>", f"{script_tag}\n</body>")
            else:
                content += f"\n{script_tag}"
            return HTMLResponse(content=content)

        # For code/text files, render with dark code theme
        text_exts = [".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".css", ".txt", ".md", ".sh", ".log", ".yaml", ".yml", ".sql"]
        if abs_path.suffix.lower() in text_exts or (mime_type and mime_type.startswith("text/")):
            code_content = abs_path.read_text(encoding="utf-8", errors="replace")
            escaped_code = html_lib.escape(code_content)
            lines = code_content.splitlines()
            code_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{abs_path.name} | Preview</title>
    <style>
        body {{ margin: 0; padding: 16px; background: #0F0F0F; color: #E0E0E0; font-family: 'JetBrains Mono', Consolas, monospace; font-size: 12px; line-height: 1.6; }}
        .header {{ padding-bottom: 10px; margin-bottom: 12px; border-bottom: 2px solid #262626; display: flex; justify-content: space-between; align-items: center; }}
        .badge {{ background: #FFE600; color: #000; padding: 2px 8px; font-weight: 800; font-size: 10px; text-transform: uppercase; border: 1px solid #000; }}
        pre {{ margin: 0; white-space: pre-wrap; word-break: break-all; background: #171717; padding: 12px; border: 1px solid #262626; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="header">
        <div><strong>{abs_path.name}</strong> <span style="color:#888; font-size: 11px;">({len(lines)} lines, {len(code_content)} bytes)</span></div>
        <div class="badge">{abs_path.suffix.upper()[1:] if abs_path.suffix else 'FILE'}</div>
    </div>
    <pre><code>{escaped_code}</code></pre>
    {get_live_reload_script(workspace_id)}
</body>
</html>"""
            return HTMLResponse(content=code_html)

        return FileResponse(path=str(abs_path), media_type=mime_type)
    except Exception as e:
        import traceback
        return HTMLResponse(content=f"<pre>Error: {str(e)}\n\n{traceback.format_exc()}</pre>", status_code=500)
