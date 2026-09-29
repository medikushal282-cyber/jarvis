"""Identifier generation and path containment.

Every id that can become a filesystem path goes through ``safe_slug``, and
every path built from request input goes through ``resolve_within``. See
``docs/runtime/SESSIONS.md`` section 6 for why.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

USER_PREFIX = "usr"
SESSION_PREFIX = "ses"
RUN_PREFIX = "run"
TURN_PREFIX = "trn"
ARTIFACT_PREFIX = "art"
CALL_PREFIX = "call"
REQUEST_PREFIX = "req"

LOCAL_USER_ID = "usr_local"

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_RESERVED = {"", ".", "..", "con", "prn", "aux", "nul"}


def _hex(n: int) -> str:
    return uuid.uuid4().hex[:n]


def new_user_id() -> str:
    return f"{USER_PREFIX}_{_hex(12)}"


def new_session_id() -> str:
    return f"{SESSION_PREFIX}_{_hex(12)}"


def new_run_id() -> str:
    return f"{RUN_PREFIX}_{_hex(8)}"


def new_turn_id() -> str:
    return f"{TURN_PREFIX}_{_hex(8)}"


def new_artifact_id() -> str:
    return f"{ARTIFACT_PREFIX}_{_hex(8)}"


def new_call_id() -> str:
    return f"{CALL_PREFIX}_{_hex(8)}"


def new_request_id() -> str:
    return f"{REQUEST_PREFIX}_{_hex(8)}"


def utc_now() -> str:
    """ISO 8601, UTC, millisecond precision, trailing Z."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def safe_slug(raw: str, *, max_len: int = 48) -> str:
    """Collapse arbitrary text into a filesystem-safe single path segment.

    Raises ``ValueError`` rather than returning a fallback: a caller that
    supplied ``../../etc`` should get an error, not a silently renamed
    workspace.
    """
    if not isinstance(raw, str):
        raise ValueError("identifier must be a string")

    slug = _SLUG_RE.sub("_", raw.strip().lower()).strip("_-")[:max_len]

    if slug.lower() in _RESERVED:
        raise ValueError(f"invalid identifier: {raw!r}")

    return slug


def is_safe_segment(raw: str) -> bool:
    """True when ``raw`` is already a safe single path segment."""
    try:
        return bool(raw) and safe_slug(raw, max_len=len(raw) or 1) == raw.lower()
    except ValueError:
        return False


def require_safe_segment(raw: str, *, kind: str = "identifier") -> str:
    """Validate an existing identifier instead of coercing it.

    ``safe_slug`` is right when turning a human-supplied *name* into an id.
    It is wrong for a lookup: ``safe_slug("../victim")`` yields ``"victim"``,
    which would let a traversal attempt resolve onto a real, unrelated
    workspace. Anything used to address existing data must already be safe.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"invalid {kind}")
    candidate = raw.strip()
    if candidate.lower() in _RESERVED or not is_safe_segment(candidate):
        raise ValueError(f"invalid {kind}: {raw!r}")
    return candidate.lower()


def resolve_within(root: Union[str, Path], *parts: Union[str, Path]) -> Path:
    """Join ``parts`` onto ``root`` and refuse anything that escapes it.

    Guards against ``..``, absolute-path injection, and (on Windows) drive
    switching. Symlinks are resolved before the comparison, so a symlink
    pointing outside the root is rejected too.
    """
    root_path = Path(root).resolve()

    cleaned: list[str] = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip().replace("\\", "/")
        if not text:
            continue
        for segment in text.split("/"):
            if segment in ("", "."):
                continue
            # A segment carrying a drive letter ("C:", "C:foo") would replace
            # the root entirely on Windows rather than extend it.
            if ":" in segment:
                raise ValueError("path escapes root")
            cleaned.append(segment)

    target = root_path.joinpath(*cleaned) if cleaned else root_path

    try:
        resolved = target.resolve()
    except (OSError, RuntimeError) as exc:  # pragma: no cover - platform dependent
        raise ValueError(f"could not resolve path: {exc}") from exc

    if resolved != root_path and not resolved.is_relative_to(root_path):
        raise ValueError("path escapes root")

    return resolved


__all__ = [
    "LOCAL_USER_ID",
    "new_user_id",
    "new_session_id",
    "new_run_id",
    "new_turn_id",
    "new_artifact_id",
    "new_call_id",
    "new_request_id",
    "utc_now",
    "safe_slug",
    "is_safe_segment",
    "resolve_within",
]
