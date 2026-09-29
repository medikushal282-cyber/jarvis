"""Start an isolated backend for scripts/e2e_ui.py.

Everything it writes goes to a temporary directory: the sandbox, and the
worker pool (normally backend/data/workers.json, which holds real API keys).
The brain is the scripted runner, so no LLM is called and nothing is written
into the repository.

    .venv\\Scripts\\python.exe scripts\\e2e_backend.py        (port 8016)
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

root = os.environ.setdefault("JARVIS_SANDBOX_ROOT", tempfile.mkdtemp(prefix="jarvis_e2e_"))
os.environ.setdefault("JARVIS_AGENT", "scripted")
os.environ.setdefault("JARVIS_SCRIPTED_DELAY_MS", "150")
os.environ.setdefault("JARVIS_SUMMARIZE_ASYNC", "0")

import app.llm.workers as worker_store  # noqa: E402

worker_store.WORKERS_FILE = os.path.join(root, "workers.json")

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("E2E_TEST_PORT", "8016"))
    print(f"isolated JARVIS backend on :{port}, data in {root}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
