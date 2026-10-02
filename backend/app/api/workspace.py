from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional, List

from app.workspace.manager import get_workspace_manager, PathSecurityError

router = APIRouter(prefix="/workspace", tags=["workspace"])

class FileWriteRequest(BaseModel):
    path: str
    content: str

class BatchDeleteRequest(BaseModel):
    paths: List[str]

def _resolve_ws(
    request: Request,
    workspace_id: Optional[str] = None,
    session_id: Optional[str] = None
):
    ws_id = workspace_id or (request.headers.get("X-Workspace-Id") if request else None) or "default"
    s_id = session_id or (request.headers.get("X-Session-Id") if request else None) or None
    return get_workspace_manager(workspace_id=ws_id, session_id=s_id)

@router.get("")
def get_workspace(
    request: Request,
    workspace_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None)
):
    ws = _resolve_ws(request, workspace_id, session_id)
    return ws.get_workspace_info()

@router.get("/runtime")
def get_runtime(
    request: Request,
    workspace_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None)
):
    ws = _resolve_ws(request, workspace_id, session_id)
    return ws.get_runtime_info()

@router.get("/files")
def get_files(
    request: Request,
    path: str = Query(default="", description="Relative path in workspace"),
    workspace_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None)
):
    ws = _resolve_ws(request, workspace_id, session_id)
    try:
        res = ws.list_directory(path)
        if not res.get("success"):
            raise HTTPException(status_code=400, detail=res.get("error", "Failed to list files"))
        return res
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/file")
def get_file(
    request: Request,
    path: str = Query(..., description="Relative path to file in workspace"),
    workspace_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None)
):
    ws = _resolve_ws(request, workspace_id, session_id)
    try:
        res = ws.read_file(path)
        if not res.get("success"):
            raise HTTPException(status_code=404, detail=res.get("error", "File not found"))
        return res
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/file")
def post_file(
    req: FileWriteRequest,
    request: Request,
    workspace_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None)
):
    ws = _resolve_ws(request, workspace_id, session_id)
    try:
        res = ws.write_file(req.path, req.content)
        if not res.get("success"):
            raise HTTPException(status_code=400, detail=res.get("error", "Failed to write file"))
        return res
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/file")
def delete_file(
    request: Request,
    path: str = Query(..., description="Relative path to file in workspace to delete"),
    workspace_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None)
):
    ws = _resolve_ws(request, workspace_id, session_id)
    try:
        res = ws.delete_file(path)
        if not res.get("success"):
            raise HTTPException(status_code=400, detail=res.get("error", "Failed to delete file"))
        return res
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files")
def delete_files(
    req: BatchDeleteRequest,
    request: Request,
    workspace_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None)
):
    ws = _resolve_ws(request, workspace_id, session_id)
    deleted = []
    failed = []
    for p in req.paths:
        try:
            res = ws.delete_file(p)
            if res.get("success"):
                deleted.append(p)
            else:
                failed.append({"path": p, "error": res.get("error", "Failed")})
        except Exception as e:
            failed.append({"path": p, "error": str(e)})
    return {"success": len(failed) == 0, "deleted": deleted, "failed": failed}
