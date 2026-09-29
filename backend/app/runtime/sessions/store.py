"""File-backed persistence for workspaces, sessions and runs.

All reads and writes to ``sandbox/`` go through here. Writes are atomic
(tmp + ``os.replace``) so a crash mid-write cannot corrupt a session, and
every path derived from request input goes through ``resolve_within``.

Layout::

    sandbox/<workspace_id>/
        workspace.json
        sessions/<session_id>.json
        runs/<run_id>/run.json
                     /events.ndjson
                     /result.json
                     /artifacts/
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.runtime import config
from app.runtime.ids import (
    LOCAL_USER_ID,
    require_safe_segment,
    resolve_within,
    safe_slug,
    utc_now,
)
from app.runtime.models import Run, Session, Turn

logger = logging.getLogger(__name__)


def _write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("unreadable json at %s: %s", path, exc)
        return None


class WorkspaceStore:
    """Workspaces are just directories; this keeps their ids safe."""

    def root(self) -> Path:
        return config.sandbox_root()

    def dir_for(self, workspace_id: str) -> Path:
        # Validate, never coerce: safe_slug("../victim") would silently
        # resolve onto a real workspace named "victim".
        return resolve_within(self.root(), require_safe_segment(workspace_id, kind="workspace_id"))

    def exists(self, workspace_id: str) -> bool:
        try:
            return self.dir_for(workspace_id).is_dir()
        except ValueError:
            return False

    def create(self, name: str, user_id: str = LOCAL_USER_ID, description: str = "") -> Dict[str, Any]:
        base = safe_slug(name)
        ws_dir = resolve_within(self.root(), base)
        if ws_dir.exists():
            import uuid

            base = f"{base}_{uuid.uuid4().hex[:6]}"
            ws_dir = resolve_within(self.root(), base)

        (ws_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (ws_dir / "runs").mkdir(parents=True, exist_ok=True)

        meta = {
            "id": base,
            "name": name,
            "description": description,
            "user_id": user_id,
            "created_at": utc_now(),
            "root_path": str(ws_dir),
        }
        _write_atomic(ws_dir / "workspace.json", meta)
        return meta

    def ensure(self, workspace_id: str, user_id: str = LOCAL_USER_ID) -> Dict[str, Any]:
        ws_id = require_safe_segment(workspace_id, kind="workspace_id")
        ws_dir = resolve_within(self.root(), ws_id)
        meta_path = ws_dir / "workspace.json"
        existing = _read_json(meta_path)
        if existing:
            return existing

        (ws_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (ws_dir / "runs").mkdir(parents=True, exist_ok=True)
        meta = {
            "id": ws_id,
            "name": workspace_id,
            "description": "",
            "user_id": user_id,
            "created_at": utc_now(),
            "root_path": str(ws_dir),
        }
        _write_atomic(meta_path, meta)
        return meta

    def get(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        try:
            meta = _read_json(self.dir_for(workspace_id) / "workspace.json")
        except ValueError:
            return None
        return meta

    def list(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        root = self.root()
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            meta = _read_json(entry / "workspace.json") or {}
            owner = meta.get("user_id", LOCAL_USER_ID)
            if user_id and owner not in (user_id, LOCAL_USER_ID):
                continue
            sessions_dir = entry / "sessions"
            legacy_dir = entry / "conversations"
            count = 0
            for d in (sessions_dir, legacy_dir):
                if d.is_dir():
                    count += len([f for f in d.iterdir() if f.suffix == ".json"])
            out.append(
                {
                    "id": meta.get("id", entry.name),
                    "name": meta.get("name", entry.name),
                    "description": meta.get("description", ""),
                    "user_id": owner,
                    "created_at": meta.get("created_at", ""),
                    "session_count": count,
                    "conversation_count": count,  # legacy alias
                }
            )
        return out

    def delete(self, workspace_id: str) -> bool:
        ws_dir = self.dir_for(workspace_id)  # raises on traversal
        if not ws_dir.is_dir():
            return False
        if ws_dir.resolve() == self.root().resolve():
            raise ValueError("refusing to delete the sandbox root")
        shutil.rmtree(ws_dir)
        return True


class SessionStore:
    """Sessions, with a write-through cache and a lock per session id."""

    def __init__(self, workspaces: Optional[WorkspaceStore] = None):
        self.workspaces = workspaces or WorkspaceStore()
        self._cache: Dict[str, Session] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._guard = threading.Lock()

    # --- locking ------------------------------------------------------------

    def lock(self, session_id: str) -> asyncio.Lock:
        with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            return lock

    # --- paths --------------------------------------------------------------

    def _dir(self, workspace_id: str) -> Path:
        ws_dir = self.workspaces.dir_for(workspace_id)
        sessions = ws_dir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        return sessions

    def _path(self, workspace_id: str, session_id: str) -> Path:
        session_id = require_safe_segment(session_id, kind="session_id")
        return resolve_within(self._dir(workspace_id), f"{session_id}.json")

    def _find_path(self, session_id: str) -> Optional[Path]:
        """Locate a session without knowing its workspace."""
        slug = require_safe_segment(session_id, kind="session_id")
        for ws in self.workspaces.root().iterdir():
            if not ws.is_dir():
                continue
            for sub in ("sessions", "conversations"):
                candidate = ws / sub / f"{slug}.json"
                if candidate.exists():
                    return candidate
        return None

    # --- crud ---------------------------------------------------------------

    def create(
        self,
        workspace_id: str,
        user_id: str = LOCAL_USER_ID,
        title: str = "New Session",
        session_id: Optional[str] = None,
    ) -> Session:
        from app.runtime.ids import new_session_id

        self.workspaces.ensure(workspace_id, user_id)
        session = Session(
            id=session_id or new_session_id(),
            user_id=user_id,
            workspace_id=require_safe_segment(workspace_id, kind="workspace_id"),
            title=title,
        )
        self.save(session)
        return session

    def get(self, session_id: str, workspace_id: Optional[str] = None) -> Optional[Session]:
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached

        path: Optional[Path]
        if workspace_id:
            try:
                path = self._path(workspace_id, session_id)
            except ValueError:
                return None
            if not path.exists():
                path = self._find_path(session_id)
        else:
            path = self._find_path(session_id)

        if path is None:
            return None

        raw = _read_json(path)
        if raw is None:
            return None

        raw.setdefault("id", session_id)
        # A legacy conversation file knows neither its workspace nor its owner.
        raw.setdefault("workspace_id", path.parent.parent.name)
        session = Session.from_dict(raw)
        self._cache[session.id] = session
        return session

    def save(self, session: Session) -> Session:
        session.updated_at = utc_now()
        path = self._path(session.workspace_id, session.id)
        _write_atomic(path, session.to_dict())
        self._cache[session.id] = session
        return session

    def list(
        self,
        workspace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        out: List[Session] = []
        root = self.workspaces.root()
        workspaces = (
            [self.workspaces.dir_for(workspace_id)] if workspace_id else
            [d for d in root.iterdir() if d.is_dir()]
        )
        for ws_dir in workspaces:
            for sub in ("sessions", "conversations"):
                d = ws_dir / sub
                if not d.is_dir():
                    continue
                for f in d.iterdir():
                    if f.suffix != ".json":
                        continue
                    raw = _read_json(f)
                    if raw is None:
                        continue
                    raw.setdefault("id", f.stem)
                    raw.setdefault("workspace_id", ws_dir.name)
                    session = Session.from_dict(raw)
                    if user_id and session.user_id not in (user_id, LOCAL_USER_ID):
                        continue
                    if status and session.status != status:
                        continue
                    out.append(session)

        out.sort(key=lambda s: s.updated_at or s.created_at, reverse=True)
        return [s.summary() for s in out]

    def append_turn(self, session_id: str, turn: Turn, workspace_id: Optional[str] = None) -> Optional[Session]:
        session = self.get(session_id, workspace_id)
        if session is None:
            return None
        session.turns.append(turn)
        if turn.run_id and turn.run_id not in session.run_ids:
            session.run_ids.append(turn.run_id)
        if session.title in ("New Session", "", None) and turn.role == "user":
            session.title = turn.content.strip()[:60] or session.title
        return self.save(session)

    def delete(self, session_id: str, workspace_id: Optional[str] = None, hard: bool = False) -> bool:
        session = self.get(session_id, workspace_id)
        if session is None:
            return False
        if hard:
            path = self._path(session.workspace_id, session.id)
            legacy = (
                self.workspaces.dir_for(session.workspace_id)
                / "conversations"
                / f"{require_safe_segment(session.id, kind='session_id')}.json"
            )
            for p in (path, legacy):
                if p.exists():
                    p.unlink()
            self._cache.pop(session_id, None)
            return True
        session.status = "archived"
        self.save(session)
        return True

    def invalidate(self, session_id: str) -> None:
        self._cache.pop(session_id, None)


class RunStore:
    """Runs, their event logs, results and captured artifacts."""

    def __init__(self, workspaces: Optional[WorkspaceStore] = None):
        self.workspaces = workspaces or WorkspaceStore()
        self._cache: Dict[str, Run] = {}

    def dir_for(self, workspace_id: str, run_id: str) -> Path:
        ws_dir = self.workspaces.dir_for(workspace_id)
        run_dir = resolve_within(ws_dir, "runs", require_safe_segment(run_id, kind="run_id"))
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _find_dir(self, run_id: str) -> Optional[Path]:
        slug = require_safe_segment(run_id, kind="run_id")
        for ws in self.workspaces.root().iterdir():
            candidate = ws / "runs" / slug
            if candidate.is_dir():
                return candidate
        return None

    def events_path(self, workspace_id: str, run_id: str) -> Path:
        return self.dir_for(workspace_id, run_id) / "events.ndjson"

    def artifacts_dir(self, workspace_id: str, run_id: str) -> Path:
        d = self.dir_for(workspace_id, run_id) / "artifacts"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, run: Run) -> Run:
        _write_atomic(self.dir_for(run.workspace_id, run.id) / "run.json", run.to_dict())
        self._cache[run.id] = run
        return run

    def get(self, run_id: str, workspace_id: Optional[str] = None) -> Optional[Run]:
        cached = self._cache.get(run_id)
        if cached is not None:
            return cached
        run_dir = (
            self.dir_for(workspace_id, run_id) if workspace_id else self._find_dir(run_id)
        )
        if run_dir is None:
            return None
        raw = _read_json(run_dir / "run.json")
        if raw is None:
            return None
        run = Run.from_dict(raw)
        self._cache[run.id] = run
        return run

    def save_result(self, run: Run, result: Dict[str, Any]) -> None:
        _write_atomic(self.dir_for(run.workspace_id, run.id) / "result.json", result)

    def get_result(self, run_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        run_dir = (
            self.dir_for(workspace_id, run_id) if workspace_id else self._find_dir(run_id)
        )
        if run_dir is None:
            return None
        return _read_json(run_dir / "result.json")

    def read_events(self, run_id: str, workspace_id: Optional[str] = None, from_seq: int = 0) -> List[Dict[str, Any]]:
        run_dir = (
            self.dir_for(workspace_id, run_id) if workspace_id else self._find_dir(run_id)
        )
        if run_dir is None:
            return []
        path = run_dir / "events.ndjson"
        if not path.exists():
            return []
        out: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        envelope = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if envelope.get("seq", 0) > from_seq:
                        out.append(envelope)
        except OSError as exc:
            logger.warning("could not read events for %s: %s", run_id, exc)
        return out

    def list_for_session(self, session_id: str, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        out: List[Run] = []
        root = self.workspaces.root()
        workspaces = (
            [self.workspaces.dir_for(workspace_id)] if workspace_id else
            [d for d in root.iterdir() if d.is_dir()]
        )
        for ws_dir in workspaces:
            runs_dir = ws_dir / "runs"
            if not runs_dir.is_dir():
                continue
            for run_dir in runs_dir.iterdir():
                raw = _read_json(run_dir / "run.json")
                if raw and raw.get("session_id") == session_id:
                    out.append(Run.from_dict(raw))
        out.sort(key=lambda r: r.created_at)
        return [r.summary() for r in out]

    def invalidate(self, run_id: str) -> None:
        self._cache.pop(run_id, None)


workspace_store = WorkspaceStore()
session_store = SessionStore(workspace_store)
run_store = RunStore(workspace_store)


__all__ = [
    "WorkspaceStore",
    "SessionStore",
    "RunStore",
    "workspace_store",
    "session_store",
    "run_store",
]
