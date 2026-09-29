"""Worker pool configuration API, used by the worker panel in the UI.

The pool itself -- selection, failover, cooldowns -- is Nikunj's gateway in
app/llm/. This module only lets a person see, add, change and test workers,
and it never hands a raw API key or raw provider error back to the browser.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.llm.workers import add_worker, delete_worker, get_public_workers, update_worker

router = APIRouter(prefix="/workers", tags=["Workers"])

#: Providers the panel offers, and the LiteLLM model prefix for each.
PROVIDER_PREFIX: Dict[str, str] = {
    "groq": "groq/",
    "openai": "openai/",
    "anthropic": "anthropic/",
    "gemini": "gemini/",
}

MIN_PRIORITY, MAX_PRIORITY = 1, 100
TEST_TIMEOUT_S = 20


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


class WorkerTestRequest(BaseModel):
    provider: str
    model: str
    api_key: str


def _provider(raw: str) -> str:
    provider = (raw or "").strip().lower()
    if provider not in PROVIDER_PREFIX:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider '{raw}'. Use one of: {', '.join(sorted(PROVIDER_PREFIX))}",
        )
    return provider


def _required(value: Optional[str], field: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    return cleaned


def _priority(value: Optional[int]) -> int:
    return max(MIN_PRIORITY, min(MAX_PRIORITY, int(value or MIN_PRIORITY)))


def _litellm_model(provider: str, model: str) -> str:
    prefix = PROVIDER_PREFIX[provider]
    return model if model.startswith(prefix) else f"{prefix}{model}"


def describe_error(error: Any) -> str:
    """A short, safe reason. Provider errors can echo request details."""
    text = str(error or "").lower()
    if any(k in text for k in ("401", "403", "invalid api key", "incorrect api key", "authentication", "unauthorized", "permission")):
        return "The API key was rejected."
    if any(k in text for k in ("404", "model_not_found", "does not exist", "not found", "unknown model")):
        return "That model isn't available for this key."
    if any(k in text for k in ("429", "rate_limit", "rate limit", "quota")):
        return "Rate limited right now. The key may be fine; try again shortly."
    if "timeout" in text or "timed out" in text:
        return "The provider didn't answer in time."
    if "connection" in text or "resolve" in text:
        return "Couldn't reach the provider."
    return "The provider returned an error."


def _public(worker: Dict[str, Any]) -> Dict[str, Any]:
    worker = dict(worker)
    worker.pop("api_key", None)
    error = worker.pop("last_error", None)
    worker["last_error_hint"] = describe_error(error) if error else None
    return worker


@router.get("")
@router.get("/")
def list_workers() -> List[Dict[str, Any]]:
    return [_public(w) for w in get_public_workers()]


@router.post("")
@router.post("/")
def create_worker(data: WorkerCreateRequest):
    provider = _provider(data.provider)
    model = _required(data.model, "model")
    key = _required(data.api_key, "api_key")
    created = add_worker({
        "provider": provider,
        "model": model,
        "api_key": key,
        "display_name": (data.display_name or "").strip() or f"{provider} - {model}",
        "priority": _priority(data.priority),
    })
    return _public(created)


@router.patch("/{worker_id}")
def edit_worker(worker_id: str, data: WorkerUpdateRequest):
    changes = data.model_dump(exclude_unset=True)
    if "priority" in changes:
        changes["priority"] = _priority(changes["priority"])
    if "api_key" in changes and not (changes["api_key"] or "").strip():
        changes.pop("api_key")
    updated = update_worker(worker_id, changes)
    if not updated:
        raise HTTPException(status_code=404, detail="Worker not found")
    return _public(updated)


@router.delete("/{worker_id}")
def remove_worker(worker_id: str):
    if not delete_worker(worker_id):
        raise HTTPException(status_code=404, detail="Worker not found")
    return {"success": True}


@router.post("/test")
def test_worker_connection(data: WorkerTestRequest):
    """Make one tiny call with the given key.

    The key is passed to that call only. The previous version wrote it into
    the process-wide environment for the duration, so a run in progress on
    another thread could pick up the untested key.
    """
    provider = _provider(data.provider)
    model = _required(data.model, "model")
    key = _required(data.api_key, "api_key")

    import litellm

    try:
        litellm.completion(
            model=_litellm_model(provider, model),
            messages=[{"role": "user", "content": "ping"}],
            api_key=key,
            max_tokens=1,
            timeout=TEST_TIMEOUT_S,
        )
        return {"success": True, "message": "Connection successful"}
    except Exception as exc:  # noqa: BLE001 - every failure becomes a safe reason
        return {"success": False, "message": describe_error(exc)}
