"""Make the repository root and backend/ importable under pytest.

Needed because:
1. `tests/` has no `__init__.py`, so pytest inserts `tests/` on sys.path, not the repo root.
2. The backend `app` package lives in `backend/app/`, so `backend/` must also be on sys.path.
3. A root-level `app.py` (if present) would shadow `backend/app/`; inserting `backend/` BEFORE
   the root prevents this shadowing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

# Evict any shadowed app.py from sys.modules if already imported
if "app" in sys.modules:
    app_mod = sys.modules["app"]
    if getattr(app_mod, "__file__", "") and not getattr(app_mod, "__file__", "").endswith("__init__.py"):
        del sys.modules["app"]

# Ensure ROOT and BACKEND are positioned correctly: BACKEND at the very front
backend_str = str(BACKEND)
root_str = str(ROOT)

while backend_str in sys.path:
    sys.path.remove(backend_str)
while root_str in sys.path:
    sys.path.remove(root_str)

# Remove empty string or current dir if it resolves to root
if "" in sys.path:
    sys.path.remove("")

sys.path.insert(0, root_str)
sys.path.insert(0, backend_str)

try:
    from dotenv import load_dotenv
    _env_path = ROOT / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

