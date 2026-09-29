"""Make the repository root importable so `import brain` works under pytest.

Needed because `tests/` has no `__init__.py`, so pytest inserts `tests/` itself on `sys.path` and
not the repo root where the `brain` package lives. Doing it here rather than shipping a
`pyproject.toml` at the repository root keeps our footprint out of a teammate's tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
