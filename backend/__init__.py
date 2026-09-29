"""JARVIS backend package."""
import sys
from pathlib import Path

_backend_dir = str(Path(__file__).parent.resolve())
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if "app" in sys.modules and not getattr(sys.modules["app"], "__file__", "").endswith("__init__.py"):
    del sys.modules["app"]
