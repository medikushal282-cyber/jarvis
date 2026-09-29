import json
import os
import time
import uuid
from typing import List, Dict, Any, Optional

WORKERS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "workers.json")

def load_workers() -> List[Dict[str, Any]]:
    if not os.path.exists(WORKERS_FILE):
        return []
    try:
        with open(WORKERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_workers(workers: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(WORKERS_FILE), exist_ok=True)
    with open(WORKERS_FILE, "w") as f:
        json.dump(workers, f, indent=2)

def get_public_workers() -> List[Dict[str, Any]]:
    workers = load_workers()
    now = time.time()
    for w in workers:
        # Mask API key
        key = w.get("api_key", "")
        if key:
            w["api_key_hint"] = f"...{key[-4:]}" if len(key) >= 4 else "***"
        else:
            w["api_key_hint"] = ""
        # Remove raw key before returning to UI
        w.pop("api_key", None)
        w.pop("credential_env", None)
        
        # Update dynamic status based on cooldown
        cooldown = w.get("cooldown_until", 0)
        if cooldown > now:
            w["status"] = "COOLDOWN"
            w["cooldown_remaining"] = int(cooldown - now)
        elif not w.get("enabled", True):
            w["status"] = "DISABLED"
        elif w.get("last_error"):
            # If it's not in cooldown but had an error recently, maybe still flag it, but let's call it READY if cooldown expired
            w["status"] = "READY"
        else:
            w["status"] = "HEALTHY"
            
    # Sort by priority
    workers.sort(key=lambda x: x.get("priority", 0), reverse=True)
    return workers

def add_worker(data: Dict[str, Any]) -> Dict[str, Any]:
    workers = load_workers()
    worker_id = f"worker_{str(uuid.uuid4())[:8]}"
    
    new_worker = {
        "worker_id": worker_id,
        "owner": data.get("owner", ""),
        "provider": data.get("provider", "groq"),
        "model": data.get("model", "llama-3.1-8b-instant"),
        "display_name": data.get("display_name", f"{data.get('provider')} - {data.get('model')}"),
        "api_key": data.get("api_key", ""),
        "credential_env": data.get("credential_env", ""),
        "enabled": data.get("enabled", True),
        "priority": data.get("priority", 1),
        "status": "HEALTHY",
        "cooldown_until": 0,
        "last_error": None,
        "last_used_at": 0
    }
    workers.append(new_worker)
    save_workers(workers)
    return new_worker

def update_worker(worker_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    workers = load_workers()
    for w in workers:
        if w["worker_id"] == worker_id:
            if "owner" in data:
                w["owner"] = data["owner"].strip()
            if "credential_env" in data:
                w["credential_env"] = data["credential_env"].strip()
            if "api_key" in data and data["api_key"].strip():
                w["api_key"] = data["api_key"].strip()
            if "enabled" in data:
                w["enabled"] = data["enabled"]
            if "priority" in data:
                w["priority"] = data["priority"]
            if "display_name" in data:
                w["display_name"] = data["display_name"]
            
            # Allow manual reset of cooldown
            if data.get("reset_cooldown"):
                w["cooldown_until"] = 0
                w["last_error"] = None
                
            save_workers(workers)
            return w
    return None

def delete_worker(worker_id: str) -> bool:
    workers = load_workers()
    initial_len = len(workers)
    workers = [w for w in workers if w["worker_id"] != worker_id]
    if len(workers) < initial_len:
        save_workers(workers)
        return True
    return False

def mark_worker_error(worker_id: str, error_msg: str, cooldown_s: int = 30) -> None:
    workers = load_workers()
    for w in workers:
        if w["worker_id"] == worker_id:
            w["last_error"] = error_msg
            w["cooldown_until"] = time.time() + cooldown_s
            save_workers(workers)
            break

def mark_worker_used(worker_id: str) -> None:
    workers = load_workers()
    for w in workers:
        if w["worker_id"] == worker_id:
            w["last_used_at"] = time.time()
            w["last_error"] = None
            w["cooldown_until"] = 0
            save_workers(workers)
            break
