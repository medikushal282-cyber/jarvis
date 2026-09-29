"""Turn an event stream into a RunResult.

A pure reducer: ``List[Event] -> RunResult``. No I/O, no agent, no globals.
That is what lets the brain be rewritten without touching the result panel,
and it means a run that crashed halfway still produces a usable report from
the events that did land.

See docs/runtime/RESULTS.md.
"""

from __future__ import annotations

import posixpath
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from app.runtime.events import catalog
from app.runtime.ids import stable_artifact_id

#: Action kind -> (singular, plural) label templates.
ACTION_LABELS: Dict[str, tuple] = {
    "read": ("Read {n} file", "Read {n} files"),
    "create": ("Created {n} file", "Created {n} files"),
    "modify": ("Modified {n} file", "Modified {n} files"),
    "delete": ("Deleted {n} file", "Deleted {n} files"),
    "command": ("Ran {n} command", "Ran {n} commands"),
    "browser": ("Opened {n} page", "Opened {n} pages"),
    "memory": ("Recalled {n} past experience", "Recalled {n} past experiences"),
    "verify": ("Ran {n} verification", "Ran {n} verifications"),
    "tool": ("Called {n} tool", "Called {n} tools"),
    "research": ("Gathered {n} research finding", "Gathered {n} research findings"),
}

ACTION_ORDER = [
    "read", "research", "memory", "create", "modify", "delete",
    "command", "browser", "verify", "tool",
]

MIME_BY_SUFFIX = {
    ".py": "text/x-python", ".js": "text/javascript", ".ts": "text/typescript",
    ".tsx": "text/typescript", ".json": "application/json", ".md": "text/markdown",
    ".html": "text/html", ".css": "text/css", ".csv": "text/csv",
    ".txt": "text/plain", ".yml": "text/yaml", ".yaml": "text/yaml",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".zip": "application/zip", ".wav": "audio/wav", ".mp3": "audio/mpeg",
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

INTERACTION_RE = re.compile(r"click|type|scroll|screenshot|press|hover|fill", re.IGNORECASE)
_OWN_PREVIEW_RE = re.compile(r"(^|//[^/]+)/api/(runs/[^/]+/artifacts|preview)/")


def _is_own_preview(url: str) -> bool:
    """A URL served by this backend's artifact or preview endpoints."""
    if _OWN_PREVIEW_RE.search(url):
        return True
    # A bare workspace path ("shop/index.html") from the current brain.
    return "://" not in url and not url.startswith("/")


def _url_label(url: str) -> str:
    """Show an outside page by its host, never as a raw URL."""
    try:
        host = urlparse(url).hostname
    except ValueError:
        host = None
    return host or url


def _norm(path: str) -> str:
    """Normalise a path for dedupe: forward slashes, no leading ./."""
    if not path:
        return ""
    cleaned = str(path).replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return posixpath.normpath(cleaned) if cleaned else ""


def _mime_for(path: str) -> Optional[str]:
    idx = path.rfind(".")
    return MIME_BY_SUFFIX.get(path[idx:].lower()) if idx >= 0 else None


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _label(kind: str, n: int) -> str:
    singular, plural = ACTION_LABELS.get(kind, ("{n} action", "{n} actions"))
    return (singular if n == 1 else plural).format(n=n)


class ResultBuilder:
    """Folds events into a RunResult. Feed it live or replay a whole log."""

    def __init__(self, run_id: str = "", session_id: str = "", objective: str = ""):
        self.run_id = run_id
        self.session_id = session_id
        self.objective = objective

        self.status = "running"
        self.summary = ""
        self.reply = ""
        self.model = ""
        self.provider = ""
        self.started_at: Optional[str] = None
        self.ended_at: Optional[str] = None
        self.event_count = 0
        self.last_seq = 0

        self._artifacts: Dict[str, Dict[str, Any]] = {}
        self._artifact_order: List[str] = []
        self._counts: Dict[str, int] = {}
        self._commands: List[Dict[str, Any]] = []
        self._urls: List[str] = []
        self._errors: List[Dict[str, Any]] = []
        self._verification: Optional[Dict[str, Any]] = None
        self._memory = {"recalled": 0, "applied": [], "recorded": None}
        self._plan: List[Dict[str, Any]] = []

    # --- folding ------------------------------------------------------------

    def add_all(self, events: Iterable[Dict[str, Any]]) -> "ResultBuilder":
        for event in events:
            self.add(event)
        return self

    def add(self, envelope: Dict[str, Any]) -> "ResultBuilder":
        name = catalog.canonical(envelope.get("event", ""))
        if name in (catalog.STREAM_READY, catalog.HEARTBEAT):
            return self

        data = envelope.get("data") or {}
        ts = envelope.get("ts")
        self.event_count += 1
        self.last_seq = max(self.last_seq, envelope.get("seq", 0))

        if not self.run_id:
            self.run_id = envelope.get("run_id", "")
        if not self.session_id:
            self.session_id = envelope.get("session_id", "")

        handler = self._HANDLERS.get(name)
        if handler is not None:
            handler(self, data, ts)
        return self

    # --- individual handlers ------------------------------------------------

    def _on_run_started(self, data: dict, ts: Optional[str]) -> None:
        self.objective = data.get("objective") or self.objective
        self.model = data.get("model", self.model)
        self.provider = data.get("provider", self.provider)
        self.started_at = self.started_at or ts

    def _on_run_completed(self, data: dict, ts: Optional[str]) -> None:
        self.status = data.get("status") or "completed"
        if self.status not in ("completed", "failed", "cancelled", "rejected"):
            self.status = "completed"
        self.summary = data.get("summary") or self.summary
        self.reply = data.get("reply") or data.get("summary") or self.reply
        self.ended_at = ts

    def _on_run_failed(self, data: dict, ts: Optional[str]) -> None:
        self.status = "failed"
        self.ended_at = ts
        self._errors.append(
            {
                "type": data.get("error_type", "Error"),
                "message": data.get("message", "Run failed"),
                "node": data.get("node") or envelope_node(data),
            }
        )
        if not self.summary:
            self.summary = data.get("message", "Run failed")

    def _on_run_cancelled(self, data: dict, ts: Optional[str]) -> None:
        self.status = "cancelled"
        self.ended_at = ts
        self.summary = self.summary or data.get("reason", "Run cancelled")

    def _on_plan(self, data: dict, ts: Optional[str]) -> None:
        steps = data.get("steps")
        if isinstance(steps, list):
            self._plan = steps

    def _on_file_created(self, data: dict, ts: Optional[str]) -> None:
        self._upsert_artifact(data, "created", ts)
        self._bump("create")

    def _on_file_updated(self, data: dict, ts: Optional[str]) -> None:
        self._upsert_artifact(data, "modified", ts)
        self._bump("modify")

    def _on_file_deleted(self, data: dict, ts: Optional[str]) -> None:
        path = _norm(data.get("path", ""))
        if not path:
            return
        # A file created then deleted in the same run stays visible.
        existing = self._artifacts.get(path)
        if existing:
            existing["action"] = "deleted"
        else:
            self._add_artifact(path, "deleted", 0, ts)
        self._bump("delete")

    def _on_file_read(self, data: dict, ts: Optional[str]) -> None:
        self._bump("read")

    def _on_command_completed(self, data: dict, ts: Optional[str]) -> None:
        entry = {
            "command": data.get("command", ""),
            "exit_code": data.get("exit_code"),
            "duration_ms": data.get("duration_ms", 0),
        }
        self._commands.append(entry)
        self._bump("command")
        if entry["exit_code"] not in (0, None):
            self._errors.append(
                {
                    "type": "CommandFailed",
                    "message": (data.get("stderr") or f"exit {entry['exit_code']}")[:500],
                    "command": entry["command"],
                }
            )

    def _on_browser_action(self, data: dict, ts: Optional[str]) -> None:
        # Interactions inside a page are not "opened a page". The current brain
        # puts its tool name in `action` (e.g. "open_browser"), so anything
        # that is not an interaction counts as opening.
        action = str(data.get("action") or "")
        if INTERACTION_RE.search(action):
            return
        url = str(data.get("url") or "").strip()
        if not url:
            return
        if url not in self._urls:
            self._urls.append(url)
            # A preview of one of JARVIS's own files is that file, which is
            # already an artifact; only outside pages get a card of their own.
            if not _is_own_preview(url):
                self._add_artifact(
                    url, "created", 0, ts, kind="url", name=_url_label(url), url=url
                )
        self._bump("browser")

    def _on_tool_completed(self, data: dict, ts: Optional[str]) -> None:
        self._bump("tool")

    def _on_tool_failed(self, data: dict, ts: Optional[str]) -> None:
        self._errors.append(
            {
                "type": "ToolFailed",
                "message": str(data.get("error", "tool failed"))[:500],
                "tool": data.get("tool"),
            }
        )

    def _on_memory_recalled(self, data: dict, ts: Optional[str]) -> None:
        hits = data.get("hits")
        n = len(hits) if isinstance(hits, list) else int(data.get("count", 0) or 0)
        self._memory["recalled"] += n
        if n:
            self._bump("memory", n)

    def _on_memory_applied(self, data: dict, ts: Optional[str]) -> None:
        how = data.get("how") or data.get("summary")
        if how:
            self._memory["applied"].append(str(how))

    def _on_memory_recorded(self, data: dict, ts: Optional[str]) -> None:
        self._memory["recorded"] = data.get("experience_id")

    def _on_verification_completed(self, data: dict, ts: Optional[str]) -> None:
        self._verification = {
            "valid": bool(data.get("valid")),
            "reason": data.get("reason", ""),
            "checks": data.get("checks", []),
        }
        self._bump("verify")
        if not data.get("valid") and data.get("reason"):
            self._errors.append(
                {"type": "VerificationFailed", "message": str(data.get("reason"))[:500]}
            )

    def _on_research_finding(self, data: dict, ts: Optional[str]) -> None:
        self._bump("research")

    def _on_chat_response(self, data: dict, ts: Optional[str]) -> None:
        self.reply = data.get("text") or self.reply

    # --- helpers ------------------------------------------------------------

    def _bump(self, kind: str, n: int = 1) -> None:
        self._counts[kind] = self._counts.get(kind, 0) + n

    def _upsert_artifact(self, data: dict, action: str, ts: Optional[str]) -> None:
        path = _norm(data.get("path", ""))
        if not path:
            return
        size = int(data.get("bytes") or data.get("size") or 0)
        existing = self._artifacts.get(path)
        if existing is not None:
            # Created-then-updated stays one row, keeps the original action.
            if size:
                existing["bytes"] = size
            if existing["action"] == "deleted":
                existing["action"] = action
            return
        self._add_artifact(path, action, size, ts)

    def _add_artifact(
        self,
        key: str,
        action: str,
        size: int,
        ts: Optional[str],
        *,
        kind: str = "file",
        name: Optional[str] = None,
        url: Optional[str] = None,
    ) -> None:
        if key in self._artifacts:
            return
        display = name or posixpath.basename(key) or key
        mime = _mime_for(key) if kind == "file" else None
        if kind == "file" and mime and any(key.lower().endswith(s) for s in IMAGE_SUFFIXES):
            kind = "image"
        entry = {
            "id": stable_artifact_id(self.run_id, key),
            "type": kind,
            "name": display,
            "action": action,
            "bytes": size,
            "created_at": ts,
        }
        if kind == "url":
            entry["url"] = url or key
        else:
            entry["path"] = key
            entry["mime"] = mime
            entry["preview_url"] = f"/api/runs/{self.run_id}/artifacts/{entry['id']}"
        self._artifacts[key] = entry
        self._artifact_order.append(key)

    # --- output -------------------------------------------------------------

    def actions(self) -> List[Dict[str, Any]]:
        out = []
        for kind in ACTION_ORDER:
            n = self._counts.get(kind, 0)
            if n:
                out.append({"kind": kind, "label": _label(kind, n), "count": n})
        return out

    def artifacts(self) -> List[Dict[str, Any]]:
        return [self._artifacts[k] for k in self._artifact_order]

    def duration_ms(self) -> int:
        start, end = _parse_ts(self.started_at), _parse_ts(self.ended_at)
        if start and end:
            return max(0, int((end - start).total_seconds() * 1000))
        return 0

    def build(self) -> Dict[str, Any]:
        artifacts = self.artifacts()
        files = {"created": [], "modified": [], "deleted": []}
        for art in artifacts:
            if art["type"] == "url":
                continue
            bucket = {"created": "created", "modified": "modified", "deleted": "deleted"}
            key = bucket.get(art["action"])
            if key:
                files[key].append(art.get("path", art["name"]))

        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status,
            "objective": self.objective,
            "summary": self.summary or self._fallback_summary(),
            "reply": self.reply,
            "model": self.model,
            "provider": self.provider,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms(),
            "actions": self.actions(),
            "artifacts": artifacts,
            "files_created": files["created"],
            "files_modified": files["modified"],
            "files_deleted": files["deleted"],
            "urls_opened": list(self._urls),
            "commands": list(self._commands),
            "plan": self._plan,
            "memory": dict(self._memory),
            "verification": self._verification,
            "errors": list(self._errors),
            "event_count": self.event_count,
            "last_seq": self.last_seq,
        }

    def _fallback_summary(self) -> str:
        acts = self.actions()
        if not acts:
            return self.objective or ""
        return ", ".join(a["label"] for a in acts[:3]) + "."

    _HANDLERS = {
        catalog.RUN_STARTED: _on_run_started,
        catalog.RUN_COMPLETED: _on_run_completed,
        catalog.RUN_FAILED: _on_run_failed,
        catalog.RUN_CANCELLED: _on_run_cancelled,
        catalog.PLAN_CREATED: _on_plan,
        catalog.PLAN_UPDATED: _on_plan,
        catalog.FILE_CREATED: _on_file_created,
        catalog.FILE_UPDATED: _on_file_updated,
        catalog.FILE_DELETED: _on_file_deleted,
        catalog.FILE_READ: _on_file_read,
        catalog.COMMAND_COMPLETED: _on_command_completed,
        catalog.BROWSER_ACTION: _on_browser_action,
        catalog.LEGACY_BROWSER_OPENED: _on_browser_action,
        catalog.TOOL_COMPLETED: _on_tool_completed,
        catalog.TOOL_FAILED: _on_tool_failed,
        catalog.MEMORY_RECALLED: _on_memory_recalled,
        catalog.MEMORY_APPLIED: _on_memory_applied,
        catalog.MEMORY_RECORDED: _on_memory_recorded,
        catalog.VERIFICATION_COMPLETED: _on_verification_completed,
        catalog.LEGACY_VALIDATION_RESULT: _on_verification_completed,
        catalog.LEGACY_RESEARCH_FINDING: _on_research_finding,
        catalog.LEGACY_CHAT_RESPONSE: _on_chat_response,
    }


def envelope_node(data: dict) -> str:
    return data.get("node", "") if isinstance(data, dict) else ""


def build_result(events: Iterable[Dict[str, Any]], **seed: str) -> Dict[str, Any]:
    """One-shot: fold a whole event log into a result."""
    return ResultBuilder(**seed).add_all(events).build()


__all__ = ["ResultBuilder", "build_result", "ACTION_LABELS"]
