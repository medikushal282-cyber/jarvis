from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import time
from dotenv import load_dotenv
from app.workspace.manager import active_workspace_id

load_dotenv()

from app.api.runs import router as runs_router
from app.api.sessions import router as sessions_router, runs_router as run_reads_router
from app.api.voice import router as voice_router
from app.api.workspace import router as workspace_router
from app.api.preview import router as preview_router
from app.api.sandbox import router as sandbox_router
from app.api.artifacts import router as artifacts_router
from app.api.workers import router as workers_router
from app.api.tools import router as tools_router
from app.api.providers import router as providers_router, models_router
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

# Runtime layer (sessions, events, results, voice). The write route for
# runs is registered before the read routes so POST /api/runs/ resolves first.
app.include_router(runs_router, prefix="/api")
app.include_router(run_reads_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")
app.include_router(preview_router, prefix="/api")
app.include_router(sandbox_router, prefix="/api")
app.include_router(artifacts_router, prefix="/api")
app.include_router(workers_router, prefix="/api")
app.include_router(tools_router, prefix="/api")
app.include_router(providers_router, prefix="/api")
app.include_router(models_router, prefix="/api")

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
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8006, reload=True)
