from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.llm.workers import get_public_workers, add_worker, update_worker, delete_worker

router = APIRouter(prefix="/workers", tags=["Workers"])

class WorkerCreateRequest(BaseModel):
    provider: str
    model: str
    api_key: str
    display_name: Optional[str] = None
    priority: Optional[int] = 1

class WorkerUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    display_name: Optional[str] = None
    reset_cooldown: Optional[bool] = False

@router.get("/")
def list_workers():
    # Never returns raw API keys
    return get_public_workers()

@router.post("/")
def create_worker(data: WorkerCreateRequest):
    new_w = add_worker(data.model_dump())
    new_w.pop("api_key", None)
    return new_w

@router.patch("/{worker_id}")
def edit_worker(worker_id: str, data: WorkerUpdateRequest):
    updated = update_worker(worker_id, data.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Worker not found")
    updated.pop("api_key", None)
    return updated

@router.delete("/{worker_id}")
def remove_worker(worker_id: str):
    success = delete_worker(worker_id)
    if not success:
        raise HTTPException(status_code=404, detail="Worker not found")
    return {"success": True}
