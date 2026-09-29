"""Wraps the existing graph in ``app/graph/`` as an ``AgentRunner``.

The graph is frozen (see docs/INTERFACES.md rule 3). This adapter is the only
thing that knows its call signature, so the runtime can drive it through the
same interface Nikunj's brain will implement, and ``JARVIS_AGENT=legacy``
keeps a working demo while the real brain is built.

The graph emits its own terminal events, so this adapter only supplies the
``run_started`` the graph never learned to send.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.runtime.protocols import AgentRunner, EventEmitter, RunOutcome, RunRequest

logger = logging.getLogger(__name__)


class LegacyGraphRunner(AgentRunner):
    """Adapter over ``app.graph.workflow.execute_run_task``."""

    name = "legacy"

    async def run(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        from app.graph.workflow import execute_run_task

        emit(
            "run_started",
            {
                "objective": request.objective,
                "model": request.model,
                "provider": request.provider,
                "input_mode": request.input_mode,
            },
            node="runtime",
        )

        # The graph still expects a mutable dict keyed by run_id.
        runs_db: Dict[str, Dict[str, Any]] = {
            request.run_id: {
                "run_id": request.run_id,
                "objective": request.objective,
                "model": request.model,
                "provider": request.provider,
                "workspace_id": request.workspace_id,
                "conversation_id": request.session_id,
                "status": "pending",
                "state": {},
            }
        }

        await execute_run_task(
            request.run_id,
            request.objective,
            runs_db,
            recent_context=request.conversation,
            session_context_summary=request.context_summary,
            workspace_id=request.workspace_id,
            conversation_id=request.session_id,
            on_complete=None,
            model=request.model,
            provider=request.provider,
            attachments=request.attachments,
        )

        record = runs_db.get(request.run_id, {})
        state = record.get("state") or {}
        status = record.get("status", "completed")

        if status == "paused":
            return RunOutcome(
                status="paused",
                reply="Waiting for your approval before continuing.",
            )

        reply = (
            state.get("final_response")
            or self._summarise(state, request.objective, status)
        )

        error = state.get("error") if status == "failed" else None
        return RunOutcome(
            status="completed" if status == "completed" else "failed",
            reply=reply,
            error=error if isinstance(error, dict) else None,
        )

    @staticmethod
    def _summarise(state: Dict[str, Any], objective: str, status: str) -> str:
        if status != "completed":
            err = state.get("error")
            if isinstance(err, dict):
                return f"I could not finish that: {err.get('message', 'unknown error')}"
            return f"I could not finish: {objective}"

        artifacts = [
            a.get("path") for a in (state.get("artifacts") or []) if a.get("path")
        ]
        if artifacts:
            return f"Done. Created {', '.join(artifacts[:3])}."
        return f"Done: {objective}"


class NullAgentRunner(AgentRunner):
    """Does nothing but complete. For wiring tests and for Nikunj's scaffolding."""

    name = "null"

    async def run(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        emit("run_started", {"objective": request.objective})
        emit("agent_thinking", {"summary": "null runner: no work performed"})
        emit("run_completed", {"status": "completed", "summary": "no-op"})
        return RunOutcome(status="completed", reply="(null runner)")


def get_agent_runner() -> AgentRunner:
    """Resolve the configured brain. Falls back to legacy, loudly."""
    from app.runtime import config

    impl = config.agent_impl()

    if impl == "null":
        return NullAgentRunner()

    if impl == "scripted":
        from app.runtime.adapters.scripted import ScriptedRunner

        return ScriptedRunner()

    if impl == "core":
        try:
            from app.agent import JarvisBrain  # type: ignore[attr-defined]

            return JarvisBrain()
        except Exception as exc:  # noqa: BLE001 - the brain may not exist yet
            logger.warning(
                "JARVIS_AGENT=core but app.agent.JarvisBrain is unavailable (%s); "
                "falling back to the legacy graph",
                exc,
            )

    return LegacyGraphRunner()


__all__ = ["LegacyGraphRunner", "NullAgentRunner", "get_agent_runner"]
