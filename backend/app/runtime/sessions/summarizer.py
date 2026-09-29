"""Session context compression.

Deliberately distinct from Kushal's Hindsight layer: this is "what are we
doing right now", Hindsight is "what did we learn across sessions". Both are
visible in the UI and they must stay distinguishable.

Runs on a background task after a turn is appended -- the previous
implementation blocked every reply on an extra LLM round-trip.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from app.runtime import config
from app.runtime.models import Turn

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a compact context memory compressor for an AI software engineering "
    "assistant. Given a conversation transcript, produce a dense, concise summary "
    "(under 100 words) capturing: 1) Core user goals, 2) Key files/features created, "
    "3) Current state and pending tasks. Be purely factual and token-efficient. "
    "Do NOT include conversational filler."
)

MAX_TRANSCRIPT_TURNS = 16
MAX_TURN_CHARS = 250
MAX_SUMMARY_CHARS = 400


def _transcript(turns: List[Turn]) -> str:
    lines = []
    for turn in turns[-MAX_TRANSCRIPT_TURNS:]:
        content = (turn.content or "")[:MAX_TURN_CHARS].replace("\n", " ")
        lines.append(f"{turn.role.upper()}: {content}")
    return "\n".join(lines)


def _heuristic(turns: List[Turn]) -> str:
    parts = []
    for turn in turns[-4:]:
        content = (turn.content or "")[:80].replace("\n", " ")
        parts.append(f"{turn.role}: {content}")
    return ("Recent turns: " + " | ".join(parts))[:MAX_SUMMARY_CHARS]


def summarize_sync(turns: List[Turn]) -> str:
    """Compress a turn list. Falls back to a heuristic if no model answers."""
    if not turns:
        return ""

    transcript = _transcript(turns)

    try:
        from app.llm.router import call_llm
    except Exception as exc:  # noqa: BLE001
        logger.debug("llm router unavailable for summarisation: %s", exc)
        return _heuristic(turns)

    for model in config.SUMMARY_MODELS:
        try:
            summary, _ = call_llm(
                system=SYSTEM_PROMPT,
                user=f"Compress this conversation into concise memory:\n\n{transcript}",
                model=model,
                provider="groq",
            )
            if summary and summary.strip():
                return summary.strip()[:MAX_SUMMARY_CHARS]
        except Exception as exc:  # noqa: BLE001
            logger.debug("summariser model %s failed: %s", model, exc)
            continue

    return _heuristic(turns)


async def summarize(turns: List[Turn]) -> str:
    return await asyncio.to_thread(summarize_sync, turns)


def schedule(session_id: str, store, workspace_id: Optional[str] = None) -> None:
    """Fire-and-forget summarisation. Never blocks the caller's reply."""
    if not config.SUMMARIZE_ASYNC:
        return

    async def _task() -> None:
        try:
            session = store.get(session_id, workspace_id)
            if session is None or len(session.turns) < 2:
                return
            summary = await summarize(session.turns)
            if not summary:
                return
            async with store.lock(session_id):
                fresh = store.get(session_id, workspace_id)
                if fresh is not None:
                    fresh.context_summary = summary
                    store.save(fresh)
        except Exception:  # noqa: BLE001 - a summary is never worth a crash
            logger.exception("session summarisation failed for %s", session_id)

    try:
        asyncio.get_running_loop().create_task(_task())
    except RuntimeError:
        logger.debug("no running loop; skipping summarisation for %s", session_id)


__all__ = ["summarize", "summarize_sync", "schedule"]
