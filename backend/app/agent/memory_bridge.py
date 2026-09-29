"""Memory bridge integrating Hindsight and OKF into the JARVIS Agent.

Implements the MemoryProvider protocol from app.runtime.protocols.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from app.memory.api import build_context as memory_build_context
from app.memory.api import record_experience as memory_record_experience

logger = logging.getLogger(__name__)


class AgentMemoryBridge:
    """Async memory provider bridging Hindsight episodic recall and OKF knowledge."""

    async def recall(
        self,
        user_id: str,
        objective: str,
        *,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """Recall relevant past experiences and user knowledge before running."""
        try:
            ctx = await asyncio.to_thread(
                memory_build_context,
                user_id=user_id or "usr_local",
                objective=objective,
                project_id=workspace_id,
                session_id=session_id,
            )
            return ctx or {}
        except Exception as exc:  # noqa: BLE001 - memory failure must never abort execution
            logger.debug("memory recall failed for user %s: %s", user_id, exc)
            return {
                "experiences": [],
                "observations": [],
                "user_knowledge": "",
                "project_knowledge": "",
            }

    async def record(
        self,
        user_id: str,
        run_id: str,
        objective: str,
        outcome: Dict[str, Any],
    ) -> str:
        """Persist the execution outcome as a learned experience."""
        try:
            exp_id = await asyncio.to_thread(
                memory_record_experience,
                user_id=user_id or "usr_local",
                objective=objective,
                execution_state=outcome,
                session_id=outcome.get("session_id"),
                project_id=outcome.get("workspace_id"),
            )
            return exp_id or ""
        except Exception as exc:  # noqa: BLE001
            logger.debug("memory recording failed for run %s: %s", run_id, exc)
            return ""


memory_bridge = AgentMemoryBridge()
