"""Session, run, result and artifact endpoints.

Replaces /api/sandbox/*. The old routes stay as deprecated aliases in
app/api/sandbox.py for one milestone so the frontend can migrate separately.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.runtime import config
from app.runtime.events.bus import bus
from app.runtime.events.sse import resolve_from_seq, sse_response, stream_run
from app.runtime.ids import LOCAL_USER_ID, resolve_within
from app.runtime.models import Turn
from app.runtime.results.artifacts import (
    captured_file,
    locate,
    public_artifact,
    public_result,
)
from app.runtime.sessions.service import run_service
from app.runtime.sessions.store import run_store, session_store, workspace_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sessions"])


# --- request models ---------------------------------------------------------


class CreateSessionRequest(BaseModel):
    workspace_id: Optional[str] = None
    title: Optional[str] = "New Session"


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None


class AppendTurnRequest(BaseModel):
    role: str = "user"
    content: str
    input_mode: str = "text"
    metadata: Optional[Dict[str, Any]] = None


class AttachmentItem(BaseModel):
    name: str
    content: str
    size: Optional[int] = 0


class StartRunRequest(BaseModel):
    objective: str
    model: Optional[str] = None
    provider: Optional[str] = None
    input_mode: str = "text"
    execution_mode: str = "normal"
    workspace_id: Optional[str] = None
    attachments: Optional[List[AttachmentItem]] = None
    audio_url: Optional[str] = None
    #: Transcript details when input_mode is "voice" (confidence, duration_s, ...).
    voice: Optional[Dict[str, Any]] = None


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: Optional[str] = ""


# --- identity ---------------------------------------------------------------


def current_user_id(request: Request) -> str:
    """Resolve the caller.

    The Node auth service owns real identity; until a run carries a verified
    session cookie we fall back to the local single-user id so the whole app
    still works with auth switched off.
    """
    header = request.headers.get("X-User-Id")
    if header and header.strip():
        return header.strip()
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("id"):
        return str(user["id"])
    if config.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="Authentication required")
    return LOCAL_USER_ID


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# --- workspaces -------------------------------------------------------------


@router.get("/workspaces")
def list_workspaces(request: Request):
    return {"workspaces": workspace_store.list(current_user_id(request))}


@router.post("/workspaces")
def create_workspace(req: CreateWorkspaceRequest, request: Request):
    try:
        meta = workspace_store.create(
            req.name, current_user_id(request), req.description or ""
        )
    except ValueError as exc:
        raise _bad_request(exc)
    return {"success": True, "workspace": meta}


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str):
    try:
        deleted = workspace_store.delete(workspace_id)
    except ValueError as exc:
        raise _bad_request(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    return {"success": True, "deleted": workspace_id}


# --- sessions ---------------------------------------------------------------


@router.get("/sessions")
def list_sessions(
    request: Request,
    workspace_id: Optional[str] = None,
    status: Optional[str] = None,
):
    try:
        return {
            "sessions": session_store.list(
                workspace_id=workspace_id,
                user_id=current_user_id(request),
                status=status,
            )
        }
    except ValueError as exc:
        raise _bad_request(exc)


@router.post("/sessions")
def create_session(req: CreateSessionRequest, request: Request):
    try:
        session = session_store.create(
            workspace_id=req.workspace_id or config.DEFAULT_WORKSPACE_ID,
            user_id=current_user_id(request),
            title=req.title or "New Session",
        )
    except ValueError as exc:
        raise _bad_request(exc)
    return {"success": True, "session": session.summary()}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, workspace_id: Optional[str] = None):
    try:
        session = session_store.get(session_id, workspace_id)
    except ValueError as exc:
        raise _bad_request(exc)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    payload = session.to_dict()
    payload["runs"] = run_store.list_for_session(session.id, session.workspace_id)
    for turn in payload["turns"]:
        meta = turn.get("metadata") or {}
        if meta.get("artifacts"):
            meta["artifacts"] = [public_artifact(a) for a in meta["artifacts"]]
    # Legacy alias: the current UI reads `messages`.
    payload["messages"] = payload["turns"]
    return payload


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, req: UpdateSessionRequest, workspace_id: Optional[str] = None):
    try:
        session = session_store.get(session_id, workspace_id)
    except ValueError as exc:
        raise _bad_request(exc)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if req.title is not None:
        session.title = req.title
    if req.status is not None:
        if req.status not in ("active", "archived"):
            raise HTTPException(status_code=400, detail="status must be active or archived")
        session.status = req.status
    session_store.save(session)
    return {"success": True, "session": session.summary()}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, workspace_id: Optional[str] = None, hard: bool = False):
    try:
        deleted = session_store.delete(session_id, workspace_id, hard=hard)
    except ValueError as exc:
        raise _bad_request(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return {"success": True, "deleted": session_id, "hard": hard}


@router.get("/sessions/{session_id}/turns")
def list_turns(session_id: str, limit: int = Query(50, ge=1, le=500), workspace_id: Optional[str] = None):
    try:
        session = session_store.get(session_id, workspace_id)
    except ValueError as exc:
        raise _bad_request(exc)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    turns = [t.to_dict() for t in session.turns[-limit:]]
    return {"turns": turns, "messages": turns, "total": len(session.turns)}


@router.post("/sessions/{session_id}/turns")
def append_turn(session_id: str, req: AppendTurnRequest, workspace_id: Optional[str] = None):
    try:
        session = session_store.append_turn(
            session_id,
            Turn(
                role=req.role,
                content=req.content,
                input_mode=req.input_mode,
                metadata=req.metadata or {},
            ),
            workspace_id,
        )
    except ValueError as exc:
        raise _bad_request(exc)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return {"success": True, "turn_count": len(session.turns)}


@router.get("/sessions/{session_id}/context")
def get_context(session_id: str, workspace_id: Optional[str] = None):
    try:
        session = session_store.get(session_id, workspace_id)
    except ValueError as exc:
        raise _bad_request(exc)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return {
        "context_summary": session.context_summary,
        "turn_count": len(session.turns),
        "message_count": len(session.turns),
        "recent_turns": session.recent_turns(6),
    }


@router.get("/sessions/{session_id}/runs")
def list_session_runs(session_id: str, workspace_id: Optional[str] = None):
    try:
        return {"runs": run_store.list_for_session(session_id, workspace_id)}
    except ValueError as exc:
        raise _bad_request(exc)


@router.post("/sessions/{session_id}/runs")
async def start_session_run(session_id: str, req: StartRunRequest, request: Request):
    """The main entry point: one objective, inside a session."""
    try:
        run = await run_service.start_run(
            req.objective,
            session_id=session_id,
            workspace_id=req.workspace_id,
            user_id=current_user_id(request),
            model=req.model,
            provider=req.provider,
            input_mode=req.input_mode,
            execution_mode=req.execution_mode,
            attachments=[a.model_dump() for a in (req.attachments or [])],
            audio_url=req.audio_url,
            voice=req.voice,
        )
    except ValueError as exc:
        raise _bad_request(exc)
    return {"run_id": run.id, "session_id": run.session_id, "status": run.status}


@router.get("/sessions/{session_id}/artifacts")
def session_artifacts(session_id: str, workspace_id: Optional[str] = None):
    out: List[Dict[str, Any]] = []
    try:
        runs = run_store.list_for_session(session_id, workspace_id)
    except ValueError as exc:
        raise _bad_request(exc)
    for summary in runs:
        result = run_service.get_result(summary["id"], workspace_id)
        for artifact in (result or {}).get("artifacts", []):
            out.append({**public_artifact(artifact), "run_id": summary["id"]})
    return {"artifacts": out}


@router.get("/sessions/{session_id}/events")
async def stream_session_events(
    session_id: str,
    request: Request,
    workspace_id: Optional[str] = None,
    from_seq: Optional[int] = None,
):
    """Merged stream across the session's runs.

    Stays open across runs, so a follow-up objective appears without the
    client re-subscribing -- which is what the voice loop needs.
    """
    import asyncio
    import json as _json

    from app.runtime.events import catalog
    from app.runtime.events.sse import frame

    async def generator():
        seen_runs: set[str] = set()
        start_seq = resolve_from_seq(request, from_seq)

        while True:
            if await request.is_disconnected():
                return

            try:
                runs = run_store.list_for_session(session_id, workspace_id)
            except ValueError:
                return

            pending = [r for r in runs if r["id"] not in seen_runs]
            if not pending:
                yield frame(
                    {
                        "seq": 0,
                        "event": catalog.HEARTBEAT,
                        "run_id": "",
                        "session_id": session_id,
                        "node": "runtime",
                        "data": {"waiting": True},
                    }
                )
                await asyncio.sleep(config.SSE_HEARTBEAT_S)
                continue

            for summary in pending:
                seen_runs.add(summary["id"])
                async for chunk in stream_run(
                    request, summary["id"], start_seq, close_on_terminal=True
                ):
                    yield chunk
                start_seq = 0

    return sse_response(generator())


# --- runs -------------------------------------------------------------------

runs_router = APIRouter(prefix="/runs", tags=["Runs"])


@runs_router.get("/{run_id}")
def get_run(run_id: str, workspace_id: Optional[str] = None):
    try:
        run = run_service.get_run(run_id, workspace_id)
    except ValueError as exc:
        raise _bad_request(exc)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    payload = run.to_dict()
    result = public_result(run.result) or {}
    payload["result"] = result or None
    # Legacy alias: older clients read `state.artifacts` off this response.
    payload["state"] = {
        "artifacts": result.get("artifacts", []),
        "status": run.status,
        "final_response": result.get("reply", ""),
    }
    return payload


@runs_router.get("/{run_id}/result")
def get_run_result(run_id: str, workspace_id: Optional[str] = None):
    try:
        result = run_service.get_result(run_id, workspace_id)
    except ValueError as exc:
        raise _bad_request(exc)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No result for run '{run_id}'")
    return public_result(result)


@runs_router.get("/{run_id}/artifacts")
def get_run_artifacts(run_id: str, workspace_id: Optional[str] = None):
    try:
        result = run_service.get_result(run_id, workspace_id)
    except ValueError as exc:
        raise _bad_request(exc)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {"artifacts": [public_artifact(a) for a in result.get("artifacts", [])]}


@runs_router.get("/{run_id}/artifacts/{artifact_id}")
def serve_artifact(
    run_id: str,
    artifact_id: str,
    workspace_id: Optional[str] = None,
    download: bool = False,
):
    """Serve one produced file.

    Looked up by id in the run's own result, never by a path from the
    request. The file is taken from the copy captured when the run ended,
    else from wherever the tools wrote it -- each candidate root re-checked
    for containment.
    """
    from fastapi.responses import RedirectResponse

    try:
        run = run_service.get_run(run_id, workspace_id)
        result = run_service.get_result(run_id, workspace_id)
    except ValueError as exc:
        raise _bad_request(exc)
    if run is None or result is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    artifact = next(
        (a for a in result.get("artifacts", []) if a.get("id") == artifact_id), None
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.get("type") == "url":
        return JSONResponse({"url": artifact.get("url")})

    target = captured_file(run_store.artifacts_dir(run.workspace_id, run.id), artifact_id)
    if target is None and artifact.get("path"):
        target = locate(run.workspace_id, artifact["path"])
    if target is None:
        # Registered by the tool layer and served by it (/api/artifacts/...).
        own = artifact.get("preview_url") or ""
        if own.startswith("/api/artifacts/"):
            return RedirectResponse(own, status_code=307)
        raise HTTPException(status_code=404, detail="Artifact file is gone")

    name = artifact.get("name") or target.name
    mime = artifact.get("mime") or mimetypes.guess_type(name)[0] or "application/octet-stream"
    inline = not download and (
        mime.startswith(("text/", "image/")) or mime in ("application/json", "application/pdf")
    )
    # Header injection guard: no quotes or line breaks in the filename.
    safe_name = "".join(ch for ch in name if ch not in '"\r\n')
    headers = {
        "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{safe_name}"',
        "X-Content-Type-Options": "nosniff",
    }
    if mime in ("text/html", "image/svg+xml"):
        # Agent-generated HTML served from our own origin: lock it down.
        headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"
        )

    return FileResponse(target, media_type=mime, headers=headers)


@runs_router.post("/{run_id}/cancel")
async def cancel_run(run_id: str):
    cancelled = await run_service.cancel(run_id)
    if not cancelled:
        raise HTTPException(status_code=409, detail="Run is not active")
    return {"run_id": run_id, "status": "cancelling"}


@runs_router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    from_seq: Optional[int] = None,
):
    """SSE. Resumable via ?from_seq= or the Last-Event-ID header."""
    return sse_response(stream_run(request, run_id, resolve_from_seq(request, from_seq)))


@runs_router.get("/{run_id}/events/log")
def get_event_log(
    run_id: str,
    workspace_id: Optional[str] = None,
    since: int = 0,
    types: Optional[str] = None,
):
    """The whole timeline as JSON -- for a finished run, or for debugging."""
    try:
        events = run_service.read_events(run_id, workspace_id, since)
    except ValueError as exc:
        raise _bad_request(exc)
    if types:
        wanted = {t.strip() for t in types.split(",") if t.strip()}
        events = [e for e in events if e.get("event") in wanted]
    return {"run_id": run_id, "events": events, "count": len(events)}


__all__ = ["router", "runs_router", "current_user_id"]
