import os
import mimetypes
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from typing import Optional, List, Dict, Any
from app.artifacts import get_artifact_manager

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])


@router.get("/")
async def list_artifacts(conversation_id: Optional[str] = Query(None)):
    """Lists registered user-facing artifacts."""
    manager = get_artifact_manager()
    arts = manager.list_artifacts(conversation_id=conversation_id)
    return {"artifacts": [a.to_dict() for a in arts]}


@router.get("/{artifact_id}")
async def get_artifact_metadata(artifact_id: str):
    """Returns metadata for a specific registered artifact."""
    manager = get_artifact_manager()
    art = manager.get_artifact(artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found.")
    return art.to_dict()


@router.get("/{artifact_id}/content")
async def get_artifact_content(artifact_id: str):
    """
    Securely serves the raw artifact content with inline disposition for in-browser preview.
    Prevents path traversal by resolving only registered artifact paths.
    """
    manager = get_artifact_manager()
    art = manager.get_artifact(artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found.")

    if not os.path.exists(art.file_path):
        raise HTTPException(status_code=404, detail="Underlying artifact file is missing on disk.")

    media_type = art.mime_type or "application/octet-stream"
    return FileResponse(
        path=art.file_path,
        media_type=media_type,
        filename=art.filename,
        content_disposition_type="inline"
    )


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: str):
    """
    Securely serves the artifact as an attachment download.
    """
    manager = get_artifact_manager()
    art = manager.get_artifact(artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found.")

    if not os.path.exists(art.file_path):
        raise HTTPException(status_code=404, detail="Underlying artifact file is missing on disk.")

    media_type = art.mime_type or "application/octet-stream"
    return FileResponse(
        path=art.file_path,
        media_type=media_type,
        filename=art.filename,
        content_disposition_type="attachment"
    )
