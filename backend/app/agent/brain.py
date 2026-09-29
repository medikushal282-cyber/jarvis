"""JarvisBrain: The primary autonomous agent brain.

Implements the AgentRunner protocol from app.runtime.protocols.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.agent.loop import run_agent_loop
from app.agent.memory_bridge import memory_bridge
from app.runtime.protocols import AgentRunner, EventEmitter, RunOutcome, RunRequest

logger = logging.getLogger(__name__)


class JarvisBrain(AgentRunner):
    """The central autonomous computer agent brain for JARVIS."""

    def __init__(self, memory=memory_bridge):
        self.memory = memory

    async def run(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        """Executes one user objective from start to finish."""
        # Step 1: Recall relevant experiential memory and preferences
        memory_ctx = await self.memory.recall(
            user_id=request.user_id,
            objective=request.objective,
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )

        # Step 2: Execute autonomous ReAct reasoning & tool loop
        outcome: RunOutcome = await run_agent_loop(
            request=request,
            emit=emit,
            memory_context=memory_ctx,
        )

        # Step 3: Record outcome to Hindsight memory for lifelong learning
        if outcome.ok:
            await self.memory.record(
                user_id=request.user_id,
                run_id=request.run_id,
                objective=request.objective,
                outcome={
                    "status": outcome.status,
                    "reply": outcome.reply,
                    "session_id": request.session_id,
                    "workspace_id": request.workspace_id,
                },
            )

        return outcome


# Singleton brain instance
brain = JarvisBrain()


def get_brain() -> JarvisBrain:
    return brain


__all__ = ["JarvisBrain", "brain", "get_brain"]
