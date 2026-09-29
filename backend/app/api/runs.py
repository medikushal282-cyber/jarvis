"""Legacy run entry point, now backed by the runtime.

``POST /api/runs/`` with no session is kept as a convenience so curl and the
current frontend keep working: it resolves or creates a default session and
dispatches through the same service as ``POST /api/sessions/{id}/runs``.

The read endpoints (``/runs/{id}``, ``/events``, ``/result``, artifacts) live
in app/api/sessions.py on the shared ``runs_router``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.sessions import current_user_id
from app.runtime.events.emitter import get_emitter
from app.runtime.models import RUN_PAUSED
from app.runtime.sessions.service import run_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["Runs"])


class AttachmentItem(BaseModel):
    name: str
    content: str
    size: Optional[int] = 0


class RunRequestBody(BaseModel):
    objective: str
    model: Optional[str] = None
    provider: Optional[str] = None
    workspace_id: Optional[str] = None
    conversation_id: Optional[str] = None  # legacy name for session_id
    session_id: Optional[str] = None
    input_mode: str = "text"
    execution_mode: str = "normal"
    attachments: Optional[List[AttachmentItem]] = None


class RunResponse(BaseModel):
    run_id: str
    status: str
    session_id: Optional[str] = None


class ApprovalRequest(BaseModel):
    decision: str
    request_id: Optional[str] = None


@router.post("/", response_model=RunResponse)
async def create_run(body: RunRequestBody, request: Request):
    session_id = body.session_id or body.conversation_id
    try:
        run = await run_service.start_run(
            body.objective,
            session_id=session_id,
            workspace_id=body.workspace_id,
            user_id=current_user_id(request),
            model=body.model,
            provider=body.provider,
            input_mode=body.input_mode,
            execution_mode=body.execution_mode,
            attachments=[a.model_dump() for a in (body.attachments or [])],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"run_id": run.id, "status": run.status, "session_id": run.session_id}


@router.post("/{run_id}/approval", response_model=RunResponse)
@router.post("/{run_id}/approve", response_model=RunResponse)
async def approve_run(run_id: str, body: ApprovalRequest):
    decision = body.decision.strip().lower()
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Decision must be 'approve' or 'reject'")

    try:
        run = run_service.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RUN_PAUSED:
        raise HTTPException(status_code=409, detail="Run is not waiting for approval")

    emit = get_emitter(run_id, "runtime")
    emit(
        "permission_granted" if decision == "approve" else "permission_denied",
        {"request_id": body.request_id or (run.approval_request or {}).get("request_id", "")},
    )

    # The approval resume path still lives in the legacy graph.
    from app.graph.workflow import resume_approved_run

    runs_db: Dict[str, Dict[str, Any]] = {
        run_id: {
            "run_id": run_id,
            "status": run.status,
            "state": (run.metadata or {}).get("graph_state", {}),
        }
    }
    try:
        await resume_approved_run(run_id, decision, runs_db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    run.status = runs_db[run_id].get("status", run.status)
    run_service.runs.save(run)
    return {"run_id": run_id, "status": run.status, "session_id": run.session_id}


__all__ = ["router"]
