"""The approval channel: ask the user, wait, carry the answer back.

This is the runtime's part of docs/INTERFACES.md section 3.5. It does not
decide whether something needs permission -- Lohit's permission engine does
-- and it does not decide what to do with a refusal -- Nikunj's loop does.
It only makes the question reach the user and the answer reach the run,
**inside the same run**: the run pauses, it does not end.

    decision = await approvals.request(run_id, tool="run_command",
                                       permission="terminal.execute",
                                       summary="Execute npm install")
    # tools run in worker threads, so there is a blocking twin:
    decision = approvals.request_sync(ctx.run_id, tool=..., ...)
    if decision.approved: ...

Events: ``permission_required`` when asked; ``permission_granted`` or
``permission_denied`` when answered, timed out (deny) or cancelled (deny).
The run shows as ``paused`` while waiting.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.runtime.events.emitter import get_emitter
from app.runtime.ids import new_request_id, utc_now

logger = logging.getLogger(__name__)

RISKS = ("low", "medium", "high")


def _timeout_s() -> float:
    try:
        return max(1.0, float(os.environ.get("JARVIS_APPROVAL_TIMEOUT_S", "300")))
    except ValueError:
        return 300.0


@dataclass
class Decision:
    request_id: str
    approved: bool
    #: "user", "timeout" or "cancelled"
    reason: str = "user"


@dataclass
class _Pending:
    run_id: str
    request: Dict[str, Any]
    future: "asyncio.Future[Decision]"
    loop: asyncio.AbstractEventLoop
    created_at: str = field(default_factory=utc_now)
    #: Set under the lock the moment an answer is accepted, so a second
    #: answer is refused even before the first reaches the waiting run.
    decided: bool = False


class ApprovalChannel:
    def __init__(self) -> None:
        self._pending: Dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # --- setup ------------------------------------------------------------------

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the server's event loop so worker threads can ask too."""
        self._loop = loop

    # --- asking -----------------------------------------------------------------

    async def request(
        self,
        run_id: str,
        *,
        tool: str,
        permission: str,
        summary: str,
        risk: str = "medium",
        timeout_s: Optional[float] = None,
    ) -> Decision:
        loop = asyncio.get_running_loop()
        self._loop = self._loop or loop
        request_id = new_request_id()
        payload = {
            "request_id": request_id,
            "tool": str(tool),
            "permission": str(permission),
            "summary": str(summary)[:300],
            "risk": risk if risk in RISKS else "medium",
        }
        future: "asyncio.Future[Decision]" = loop.create_future()
        with self._lock:
            self._pending[request_id] = _Pending(run_id, payload, future, loop)

        emit = get_emitter(run_id, "runtime")
        emit("permission_required", payload)
        self._set_run_status(run_id, "paused", payload)

        try:
            decision = await asyncio.wait_for(
                asyncio.shield(future), timeout=timeout_s or _timeout_s()
            )
        except asyncio.TimeoutError:
            decision = Decision(request_id, approved=False, reason="timeout")
        except asyncio.CancelledError:
            decision = Decision(request_id, approved=False, reason="cancelled")
            self._finish(run_id, request_id, decision, emit)
            raise
        self._finish(run_id, request_id, decision, emit)
        return decision

    def request_sync(self, run_id: str, **kwargs: Any) -> Decision:
        """Blocking twin of ``request`` for code running in a worker thread."""
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("approval channel has no running event loop")
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None  # the normal case: a worker thread has no loop
        if current is loop:
            # Blocking here would deadlock the loop that must deliver the answer.
            raise RuntimeError("request_sync called on the event loop; use await request()")
        future = asyncio.run_coroutine_threadsafe(self.request(run_id, **kwargs), loop)
        return future.result()

    # --- answering ----------------------------------------------------------------

    def resolve(self, run_id: str, request_id: str, approve: bool) -> str:
        """Record the user's answer. Returns "ok", "unknown" or "decided"."""
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None or pending.run_id != run_id:
                return "unknown"
            if pending.decided or pending.future.done():
                return "decided"
            pending.decided = True
        decision = Decision(request_id, approved=approve, reason="user")
        pending.loop.call_soon_threadsafe(_settle, pending.future, decision)
        return "ok"

    def pending_for(self, run_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [p.request for p in self._pending.values() if p.run_id == run_id]

    def cancel_run(self, run_id: str) -> None:
        """Deny everything still waiting for a run that is ending."""
        with self._lock:
            waiting = [p for p in self._pending.values() if p.run_id == run_id]
        for p in waiting:
            p.decided = True
            decision = Decision(p.request["request_id"], approved=False, reason="cancelled")
            p.loop.call_soon_threadsafe(_settle, p.future, decision)

    # --- internals ------------------------------------------------------------------

    def _finish(self, run_id: str, request_id: str, decision: Decision, emit) -> None:
        with self._lock:
            self._pending.pop(request_id, None)
            still_waiting = any(p.run_id == run_id for p in self._pending.values())
        emit(
            "permission_granted" if decision.approved else "permission_denied",
            {"request_id": request_id, "reason": decision.reason},
        )
        if not still_waiting:
            self._set_run_status(run_id, "running", None)

    @staticmethod
    def _set_run_status(run_id: str, status: str, request: Optional[Dict[str, Any]]) -> None:
        try:
            from app.runtime.sessions.store import run_store

            run = run_store.get(run_id)
            if run is None or run.is_terminal:
                return
            run.status = status
            run.approval_request = request
            run_store.save(run)
        except Exception:  # noqa: BLE001 - status is informational; never break the wait
            logger.exception("could not update status for run %s", run_id)


def _settle(future: "asyncio.Future[Decision]", decision: Decision) -> None:
    if not future.done():
        future.set_result(decision)


approvals = ApprovalChannel()

__all__ = ["ApprovalChannel", "Decision", "approvals"]
