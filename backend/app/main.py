from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import time
from dotenv import load_dotenv
from app.workspace.manager import active_workspace_id

load_dotenv()

from app.api.runs import router as runs_router
from app.api.workspace import router as workspace_router
from app.api.preview import router as preview_router
from app.api.sandbox import router as sandbox_router
from app.llm.router import get_models_catalog

app = FastAPI(title="JARVIS Orchestration API", version="1.0.0")

@app.middleware("http")
async def workspace_middleware(request: Request, call_next):
    ws_id = request.headers.get("X-Workspace-Id", "default")
    token = active_workspace_id.set(ws_id)
    try:
        response = await call_next(request)
        return response
    finally:
        active_workspace_id.reset(token)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")
app.include_router(preview_router, prefix="/api")
app.include_router(sandbox_router, prefix="/api")

@app.get("/api/models")
def list_models():
    return {"models": get_models_catalog()}

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "jarvis-orchestrator"}

@app.get("/health/groq")
def groq_health():
    start_time = time.time()
    try:
        from app.llm.router import call_litellm
        call_litellm("Reply only OK", "hi", "openai/gpt-oss-120b", "groq")
        latency_ms = int((time.time() - start_time) * 1000)
        return {
            "provider": "groq",
            "status": "connected",
            "latency_ms": latency_ms,
            "model": "openai/gpt-oss-120b",
            "error_type": None
        }
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        return {
            "provider": "groq",
            "status": "error",
            "latency_ms": latency_ms,
            "model": "qwen/qwen3.8-27b",
            "error_type": "missing_api_key" if "api_key" in str(e).lower() else "unknown_error"
        }
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        error_type = "unknown_error"
        error_str = str(e).lower()
        if "authentication" in error_str or "api key" in error_str or "401" in error_str:
            error_type = "authentication_error"
        elif "rate limit" in error_str or "429" in error_str:
            error_type = "rate_limit"
        elif "timeout" in error_str:
            error_type = "timeout"
        elif "connection" in error_str:
            error_type = "connection_error"
        elif "500" in error_str or "503" in error_str:
            error_type = "provider_error"
            
        return {
            "provider": "groq",
            "status": "error",
            "latency_ms": latency_ms,
            "model": "qwen/qwen3.8-27b",
            "error_type": error_type
        }

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
