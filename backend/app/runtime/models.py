"""Persisted entities: Session, Turn, Run, RunResult, Artifact.

Plain dataclasses with explicit ``to_dict`` / ``from_dict`` rather than
pydantic models, so the store can round-trip unknown fields written by an
older version without losing them.

See docs/runtime/SESSIONS.md and docs/runtime/RESULTS.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app.runtime.ids import new_turn_id, utc_now

# --- statuses ---------------------------------------------------------------

RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_PAUSED = "paused"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"
RUN_REJECTED = "rejected"

TERMINAL_RUN_STATUSES = frozenset(
    {RUN_COMPLETED, RUN_FAILED, RUN_CANCELLED, RUN_REJECTED}
)


def _strip_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


@dataclass
class Turn:
    """One utterance: a user message or a JARVIS reply."""

    role: str  # "user" | "assistant" | "system"
    content: str
    id: str = field(default_factory=new_turn_id)
    ts: str = field(default_factory=utc_now)
    input_mode: str = "text"  # "text" | "voice"
    run_id: Optional[str] = None
    audio_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _strip_none(asdict(self))

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Turn":
        known = {f for f in cls.__dataclass_fields__}
        extra = {k: v for k, v in raw.items() if k not in known}
        turn = cls(
            role=raw.get("role", "user"),
            content=raw.get("content", ""),
            id=raw.get("id") or new_turn_id(),
            ts=raw.get("ts") or raw.get("timestamp") or utc_now(),
            input_mode=raw.get("input_mode", "text"),
            run_id=raw.get("run_id"),
            audio_url=raw.get("audio_url"),
            metadata=raw.get("metadata") or {},
        )
        if extra:
            turn.metadata.setdefault("_extra", extra)
        return turn


@dataclass
class Session:
    """One continuous conversation. Holds many runs."""

    id: str
    user_id: str
    workspace_id: str
    title: str = "New Session"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    turns: List[Turn] = field(default_factory=list)
    run_ids: List[str] = field(default_factory=list)
    context_summary: str = ""
    status: str = "active"  # "active" | "archived"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turns": [t.to_dict() for t in self.turns],
            "run_ids": list(self.run_ids),
            "context_summary": self.context_summary,
            "status": self.status,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Session":
        # Accepts both the new shape and the legacy conversation shape
        # (``messages`` instead of ``turns``, no user_id).
        raw_turns = raw.get("turns")
        if raw_turns is None:
            raw_turns = raw.get("messages", [])
        return cls(
            id=raw.get("id", ""),
            user_id=raw.get("user_id", "usr_local"),
            workspace_id=raw.get("workspace_id", "default"),
            title=raw.get("title") or "New Session",
            created_at=raw.get("created_at") or utc_now(),
            updated_at=raw.get("updated_at") or raw.get("created_at") or utc_now(),
            turns=[Turn.from_dict(t) for t in raw_turns],
            run_ids=list(raw.get("run_ids", [])),
            context_summary=raw.get("context_summary", ""),
            status=raw.get("status", "active"),
            metadata=raw.get("metadata") or {},
        )

    def summary(self) -> Dict[str, Any]:
        """Lightweight view for list endpoints."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turn_count": len(self.turns),
            "run_count": len(self.run_ids),
            "context_summary": self.context_summary,
            "status": self.status,
        }

    def recent_turns(self, limit: int = 6) -> List[Dict[str, Any]]:
        return [
            {"role": t.role, "content": t.content, "ts": t.ts}
            for t in self.turns[-limit:]
        ]


@dataclass
class Run:
    """One objective, start to finish."""

    id: str
    session_id: str
    user_id: str
    workspace_id: str
    objective: str
    model: str = ""
    provider: str = ""
    input_mode: str = "text"
    execution_mode: str = "normal"
    status: str = RUN_PENDING
    created_at: str = field(default_factory=utc_now)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    event_count: int = 0
    error: Optional[Dict[str, Any]] = None
    approval_request: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.id,  # convenience alias for existing clients
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "objective": self.objective,
            "model": self.model,
            "provider": self.provider,
            "input_mode": self.input_mode,
            "execution_mode": self.execution_mode,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "event_count": self.event_count,
            "error": self.error,
            "approval_request": self.approval_request,
            "result": self.result,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Run":
        return cls(
            id=raw.get("id") or raw.get("run_id", ""),
            session_id=raw.get("session_id", ""),
            user_id=raw.get("user_id", "usr_local"),
            workspace_id=raw.get("workspace_id", "default"),
            objective=raw.get("objective", ""),
            model=raw.get("model", ""),
            provider=raw.get("provider", ""),
            input_mode=raw.get("input_mode", "text"),
            execution_mode=raw.get("execution_mode", "normal"),
            status=raw.get("status", RUN_PENDING),
            created_at=raw.get("created_at") or utc_now(),
            started_at=raw.get("started_at"),
            ended_at=raw.get("ended_at"),
            event_count=raw.get("event_count", 0),
            error=raw.get("error"),
            approval_request=raw.get("approval_request"),
            result=raw.get("result"),
            metadata=raw.get("metadata") or {},
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "objective": self.objective,
            "status": self.status,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
            "event_count": self.event_count,
        }


@dataclass
class Artifact:
    """Something the run produced that the user can open."""

    id: str
    type: str  # "file" | "url" | "image" | "data"
    name: str
    action: str = "created"  # "created" | "modified" | "deleted"
    path: Optional[str] = None
    url: Optional[str] = None
    bytes: int = 0
    mime: Optional[str] = None
    created_at: str = field(default_factory=utc_now)
    preview_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _strip_none(asdict(self))


__all__ = [
    "Turn",
    "Session",
    "Run",
    "Artifact",
    "RUN_PENDING",
    "RUN_RUNNING",
    "RUN_PAUSED",
    "RUN_COMPLETED",
    "RUN_FAILED",
    "RUN_CANCELLED",
    "RUN_REJECTED",
    "TERMINAL_RUN_STATUSES",
]
