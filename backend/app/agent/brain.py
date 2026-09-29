"""JarvisBrain: The primary autonomous agent brain.

This is the SINGLE entry point for the agent runtime. All other orchestration
paths (graph/workflow.py, graph/nodes/*) are retired from the call path.

The agent does NOT import from hindsight or memory storage directly.
It only calls memory.recall / memory.build_context / memory.record_experience
through the AgentMemoryBridge (Kushal's interface).

Implements the AgentRunner protocol from app.runtime.protocols.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.agent.loop import run_agent
from app.agent.memory_bridge import memory_bridge
from app.runtime.protocols import AgentRunner, EventEmitter, RunOutcome, RunRequest

logger = logging.getLogger(__name__)


class JarvisBrain(AgentRunner):
    """The central autonomous computer agent brain for JARVIS.

    Owns: agent runtime, loop, state, planner-lite, tool selection,
    context assembly + token budgeting, stopping, verification, recovery,
    memory integration (consume only), permission integration (consume only),
    LLM worker gateway + failover, agent events, prompts.

    Does NOT own: memory storage, tool implementations, session UI, voice/STT/TTS.
    """

    def __init__(self, memory=memory_bridge):
        self.memory = memory

    async def run(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        """Execute one user objective from start to finish.

        Exactly one path:
        1. recall memory (before execution)
        2. run_agent loop
        3. record_experience (ALWAYS, even on failure/partial runs)
        """
        # Step 1: Recall relevant experiential memory and preferences
        memory_ctx: Dict[str, Any] = await self.memory.recall(
            user_id=request.user_id,
            objective=request.objective,
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )

        # Step 2: Execute autonomous ReAct reasoning & tool loop
        outcome: RunOutcome = await run_agent(
            request=request,
            emit=emit,
            memory_context=memory_ctx,
        )

        # Step 3: Record outcome to memory — ALWAYS, including failures.
        # Failure signatures, what was tried, and what resolved it are
        # the most valuable things to remember for future runs.
        try:
            await self.memory.record(
                user_id=request.user_id,
                run_id=request.run_id,
                objective=request.objective,
                outcome={
                    "status": outcome.status,
                    "reply": outcome.reply,
                    "error": outcome.error,
                    "session_id": request.session_id,
                    "workspace_id": request.workspace_id,
                    "ok": outcome.ok,
                },
            )
        except Exception as exc:
            # Memory recording must never abort the run
            logger.debug("memory.record failed for run %s: %s", request.run_id, exc)

        return outcome


# Module-level function for clean import by API layer
async def run_agent_entrypoint(
    request: RunRequest,
    emit: EventEmitter,
    memory: Optional[Any] = None,
) -> RunOutcome:
    """The one canonical entry point for the agent.

    This function is the single point that API routes, tests, and the session
    layer call. There must be exactly one such function (enforced by regression test).
    """
    brain = JarvisBrain(memory=memory or memory_bridge)
    return await brain.run(request, emit)


# Singleton brain instance
brain = JarvisBrain()


def get_brain() -> JarvisBrain:
    return brain


__all__ = ["JarvisBrain", "brain", "get_brain", "run_agent_entrypoint"]
