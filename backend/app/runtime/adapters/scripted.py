"""A scripted stand-in for the agent brain.

Emits the full event vocabulary in a realistic order -- memory recall, tool
calls, a worker switch, a real file, a preview, verification -- with no LLM
and no tools. It exists so the interface can be built and tested against the
event contract before the real brain, tool layer and worker gateway emit
everything, and so the demo has a run that cannot fail on stage.

Select it with ``JARVIS_AGENT=scripted``. The objective picks the scenario:

* a question ("what is 2 + 2?")        -> answers with no tools
* mentions "missing"                    -> a tool fails, the run explains it
* mentions "crash"                      -> the brain raises; the runtime
                                           turns that into ``run_failed``
* mentions "install"                    -> asks permission to run a command
                                           and waits for Allow / Deny; in
                                           Turbo it is auto-approved, standing
                                           in for the permission engine
* anything else                         -> builds a small website, switches
                                           worker mid-run, previews, verifies

Files are written only under the sandbox workspace directory, never into the
repository. ``JARVIS_SCRIPTED_DELAY_MS`` paces the events (default 350ms, 0 in
tests).
"""

from __future__ import annotations

import asyncio
import os
import re

from app.runtime.ids import new_call_id, new_request_id, stable_artifact_id
from app.runtime.protocols import AgentRunner, EventEmitter, RunOutcome, RunRequest

QUESTION_RE = re.compile(r"^\s*(what|who|why|how|when|where|is|are|can|does|do)\b|\?\s*$", re.I)

DEMO_DIR = "scripted_demo"

DEMO_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Northwind Goods</title>
<style>
  body { margin: 0; font-family: system-ui, sans-serif; background: #f4f1ea; color: #111; }
  header { padding: 24px 32px; background: #111; color: #ffe600; font-weight: 800; letter-spacing: .04em; }
  main { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; padding: 32px; }
  .card { background: #fff; border: 2px solid #111; box-shadow: 3px 3px 0 #111; padding: 16px; }
  .price { font-weight: 800; margin-top: 8px; }
  button { margin-top: 12px; border: 2px solid #111; background: #ffe600; font-weight: 700; padding: 6px 12px; }
</style>
</head>
<body>
<header>NORTHWIND GOODS</header>
<main>
  <div class="card"><div>Canvas Tote</div><div class="price">$24</div><button>Add to cart</button></div>
  <div class="card"><div>Ceramic Mug</div><div class="price">$16</div><button>Add to cart</button></div>
  <div class="card"><div>Linen Notebook</div><div class="price">$12</div><button>Add to cart</button></div>
</main>
</body>
</html>
"""


def _delay_s() -> float:
    try:
        return max(0, int(os.environ.get("JARVIS_SCRIPTED_DELAY_MS", "350"))) / 1000
    except ValueError:
        return 0.35


async def _pause() -> None:
    delay = _delay_s()
    if delay:
        await asyncio.sleep(delay)


class ScriptedRunner(AgentRunner):
    name = "scripted"

    async def run(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        emit("run_started", {
            "objective": request.objective,
            "model": "scripted",
            "provider": "scripted",
            "input_mode": request.input_mode,
            "execution_mode": request.execution_mode,
        }, node="agent")

        objective = request.objective.lower()
        if "crash" in objective:
            return await self._crash(request, emit)
        if "install" in objective:
            return await self._needs_permission(request, emit)
        if "missing" in objective:
            return await self._missing_file(request, emit)
        if QUESTION_RE.search(request.objective):
            return await self._answer(request, emit)
        return await self._website(request, emit)

    # --- scenarios ------------------------------------------------------------

    async def _answer(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        emit("planning", {"objective": request.objective}, node="agent")
        await _pause()
        reply = "That's 4." if "2 + 2" in request.objective else "Here's the answer, with no tools needed."
        emit("run_completed", {"status": "completed", "summary": reply, "reply": reply}, node="agent")
        return RunOutcome(status="completed", reply=reply)

    async def _missing_file(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        emit("planning", {"objective": request.objective}, node="agent")
        await _pause()
        call_id = new_call_id()
        emit("tool_started", {"tool": "read_file", "call_id": call_id,
                              "args": {"path": "missing.txt"}}, node="agent")
        await _pause()
        emit("tool_failed", {"tool": "read_file", "call_id": call_id, "duration_ms": 4,
                             "error": {"code": "FILE_NOT_FOUND",
                                       "message": "missing.txt does not exist"}}, node="agent")
        reply = "I couldn't read missing.txt because it doesn't exist in this workspace."
        emit("run_completed", {"status": "completed", "summary": reply, "reply": reply}, node="agent")
        return RunOutcome(status="completed", reply=reply)

    async def _needs_permission(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        """A risky action: the approval channel pauses the run for the user."""
        from app.runtime.approvals import approvals

        command = "npm install"
        summary = f"Execute {command}"
        emit("planning", {"objective": request.objective}, node="agent")
        await _pause()
        call_id = new_call_id()
        emit("tool_started", {"tool": "run_command", "call_id": call_id,
                              "args": {"command": command}}, node="agent")

        if request.execution_mode == "turbo":
            # What the permission engine does for a pre-authorised capability.
            approved = True
            emit("permission_granted", {"request_id": new_request_id(), "reason": "turbo",
                                        "auto": True, "summary": summary,
                                        "permission": "terminal.execute"}, node="agent")
        else:
            decision = await approvals.request(
                request.run_id, tool="run_command", permission="terminal.execute",
                summary=summary, risk="medium",
            )
            approved = decision.approved

        if not approved:
            emit("tool_failed", {"tool": "run_command", "call_id": call_id,
                                 "error": {"code": "PERMISSION_DENIED",
                                           "message": "Not run: permission was not given"}}, node="agent")
            reply = f"OK, I didn't run {command}."
            emit("run_completed", {"status": "completed", "summary": reply, "reply": reply}, node="agent")
            return RunOutcome(status="completed", reply=reply)

        emit("command_started", {"command": command}, node="agent")
        await _pause()
        emit("command_completed", {"command": command, "exit_code": 0, "duration_ms": 1200,
                                   "stdout": "added 42 packages"}, node="agent")
        emit("tool_completed", {"tool": "run_command", "call_id": call_id, "ok": True,
                                "duration_ms": 1200}, node="agent")
        reply = "Dependencies installed: 42 packages added."
        emit("run_completed", {"status": "completed", "summary": reply, "reply": reply}, node="agent")
        return RunOutcome(status="completed", reply=reply)

    async def _crash(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        emit("planning", {"objective": request.objective}, node="agent")
        await _pause()
        raise RuntimeError("scripted crash: the brain raised mid-run")

    async def _website(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        run_id = request.run_id

        emit("memory_recalled", {
            "query": request.objective,
            "latency_ms": 42,
            "hits": [
                {"id": "exp_demo1", "kind": "experience", "score": 0.82, "age_days": 3,
                 "content": "Last site build: a single inline-styled page previewed cleanly."},
            ],
        }, node="agent")
        await _pause()
        emit("memory_applied", {"experience_id": "exp_demo1",
                                "how": "Kept the styles inline: a separate stylesheet failed to load in last week's preview."},
             node="agent")
        emit("planning", {"objective": request.objective}, node="agent")
        await _pause()

        # 1. Create the page (a real file, inside the sandbox workspace only).
        rel_path = f"{DEMO_DIR}/index.html"
        call_id = new_call_id()
        emit("tool_started", {"tool": "create_file", "call_id": call_id,
                              "args": {"path": rel_path}}, node="agent")
        await _pause()
        size = self._write_demo_file(request, rel_path)
        emit("file_created", {"path": rel_path, "bytes": size,
                              "lines": DEMO_HTML.count("\n")}, node="agent")
        emit("tool_completed", {"tool": "create_file", "call_id": call_id, "ok": True,
                                "duration_ms": 12, "preview": f"Created {rel_path}"}, node="agent")
        await _pause()

        # 2. The first worker is rate-limited; the same run carries on.
        emit("worker_switching", {
            "from_worker": "groq-primary", "to_worker": "groq-secondary",
            "reason": "rate_limited", "retry_after_s": 20,
        }, node="gateway")
        await _pause()

        # 3. Preview and publish the artifact.
        artifact_id = stable_artifact_id(run_id, rel_path)
        secure_url = f"/api/runs/{run_id}/artifacts/{artifact_id}"
        call_id = new_call_id()
        emit("tool_started", {"tool": "preview_site", "call_id": call_id,
                              "args": {"entry": "index.html"}}, node="agent")
        await _pause()
        emit("browser_action", {"action": "open", "url": secure_url}, node="agent")
        emit("artifact_created", {
            "artifact_id": artifact_id,
            "filename": "index.html",
            "mime_type": "text/html",
            "size": size,
            "preview_supported": True,
            "secure_url": secure_url,
        }, node="agent")
        emit("tool_completed", {"tool": "preview_site", "call_id": call_id, "ok": True,
                                "duration_ms": 30, "preview": "Preview is live"}, node="agent")
        await _pause()

        # 4. Verify, because this objective asked for something visible.
        emit("verification_started", {"target": "index.html", "method": "preview_render"}, node="agent")
        await _pause()
        emit("verification_completed", {
            "valid": True, "reason": "Page renders with 3 products",
            "checks": [{"name": "file_exists", "passed": True},
                       {"name": "renders", "passed": True}],
        }, node="agent")

        emit("memory_recorded", {"experience_id": f"exp_{run_id[-6:]}",
                                 "summary": "Built and previewed a 3-product storefront",
                                 "kind": "experience"}, node="agent")

        reply = "Done. Your storefront is ready. Open the preview to see it."
        emit("run_completed", {"status": "completed",
                               "summary": "Built a 3-product storefront and verified the preview.",
                               "reply": reply}, node="agent")
        return RunOutcome(status="completed", reply=reply)

    # --- helpers ----------------------------------------------------------------

    @staticmethod
    def _write_demo_file(request: RunRequest, rel_path: str) -> int:
        """Write under sandbox/<workspace>/ only -- never the repository root."""
        from app.runtime.ids import resolve_within
        from app.runtime.sessions.store import workspace_store

        target = resolve_within(workspace_store.dir_for(request.workspace_id), rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEMO_HTML, encoding="utf-8")
        return target.stat().st_size


__all__ = ["ScriptedRunner"]
