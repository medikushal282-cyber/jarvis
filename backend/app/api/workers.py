from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.llm.workers import get_public_workers, add_worker, update_worker, delete_worker

router = APIRouter(prefix="/workers", tags=["Workers"])

class WorkerCreateRequest(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    credential_env: str = ""
    display_name: Optional[str] = None
    priority: Optional[int] = 1
    owner: Optional[str] = ""

class WorkerUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    credential_env: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    display_name: Optional[str] = None
    reset_cooldown: Optional[bool] = False

@router.get("")
@router.get("/")
def list_workers():
    # Never returns raw API keys
    return get_public_workers()

@router.post("")
@router.post("/")
def create_worker(data: WorkerCreateRequest):
    new_w = add_worker(data.model_dump())
    new_w.pop("api_key", None)
    new_w.pop("credential_env", None)
    return new_w

@router.patch("/{worker_id}")
def edit_worker(worker_id: str, data: WorkerUpdateRequest):
    updated = update_worker(worker_id, data.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Worker not found")
    updated.pop("api_key", None)
    updated.pop("credential_env", None)
    return updated

@router.delete("/{worker_id}")
def remove_worker(worker_id: str):
    success = delete_worker(worker_id)
    if not success:
        raise HTTPException(status_code=404, detail="Worker not found")
    return {"success": True}

class WorkerTestRequest(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    credential_env: str = ""

@router.post("/test")
def test_worker_connection(data: WorkerTestRequest):
    import os
    from app.llm.router import call_litellm
    prov = data.provider.lower()
    env_key = f"{prov.upper()}_API_KEY"
    old_key = os.environ.get(env_key)
    try:
        os.environ[env_key] = data.api_key.strip()
        call_litellm("Test prompt", "hello", model=data.model, provider=prov)
        return {"success": True, "message": "Connection successful"}
    except Exception:
        return {"success": False, "message": "Connection failed"}
    finally:
        if old_key is not None:
            os.environ[env_key] = old_key
        elif env_key in os.environ:
            del os.environ[env_key]

