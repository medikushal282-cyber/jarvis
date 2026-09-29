"""Hindsight adapter for memory.

Provides the memory interface for the core loop and the tool interface for the planner.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from brain.contracts import (
    MemoryItem,
    MemoryKind,
    RecallQuery,
    RetainResult,
    SkippedRetention,
    ToolResult,
)
from brain.errors import ErrorClass

class HindsightAdapter:
    """A thin adapter over the hindsight tool definitions.
    
    Implements MemoryProvider for the loop (RETAIN phase, background recall) and
    ToolProvider for the agent (mid-plan recall_memory, save_memory).
    """

    def __init__(self, settings: Mapping[str, Any] | None = None) -> None:
        self.settings = settings or {}
        
        # Import the real backend hindsight client
        import sys
        import os
        backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend")
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
            
        from app.memory.hindsight.client import HindsightClient
        self.client = HindsightClient()

    # ------------------------------------------------------------------ MemoryProvider

    def recall(self, query: RecallQuery) -> list[MemoryItem]:
        results = self.client.search(
            user_id="default_user",
            query=query.text,
            limit=query.limit if query.limit > 0 else 5,
        )
        
        items = []
        for r in results:
            meta = r.get("metadata", {})
            try:
                kind = MemoryKind(meta.get("kind", "outcome"))
            except ValueError:
                kind = MemoryKind.OUTCOME
                
            items.append(
                MemoryItem(
                    id=r["id"],
                    kind=kind,
                    text=r["content"],
                    entities=tuple(meta.get("entities", [])),
                    confidence=meta.get("confidence", 0.7),
                    observed_at=datetime.fromtimestamp(r["timestamp"], UTC) if "timestamp" in r else None,
                )
            )
        return items

    def retain(self, items: Sequence[MemoryItem]) -> RetainResult:
        written = []
        for i in items:
            exp_id = self.client.store_experience(
                user_id="default_user",
                content=i.text,
                metadata={
                    "kind": str(i.kind),
                    "entities": list(i.entities),
                    "confidence": i.confidence,
                }
            )
            written.append(exp_id)
        return RetainResult(written=tuple(written), deduplicated=())

    # ------------------------------------------------------------------ ToolProvider

    def invoke(self, method: str, args: dict[str, Any]) -> ToolResult:
        handler = getattr(self, method, None)
        if handler is None or method.startswith("_"):
            return ToolResult.failure(
                ErrorClass.UNKNOWN_TOOL, f"hindsight provider has no method {method!r}"
            )
        return handler(args)

    def recall_memory(self, args: Mapping[str, Any]) -> ToolResult:
        """Tool entry point for mid-plan memory lookup."""
        query_text = str(args.get("query", ""))
        limit = int(args.get("limit", 5))
        
        results = self.client.search(
            user_id="default_user",
            query=query_text,
            limit=limit,
        )
        
        memories = []
        for r in results:
            meta = r.get("metadata", {})
            memories.append({
                "id": r["id"],
                "kind": meta.get("kind", "outcome"),
                "text": r["content"],
                "entities": meta.get("entities", []),
                "confidence": meta.get("confidence", 0.7),
            })
        
        return ToolResult.success({"memories": memories})

    def save_memory(self, args: Mapping[str, Any]) -> ToolResult:
        """Tool entry point for saving memory mid-plan."""
        text = str(args.get("text", ""))
        kind = str(args.get("kind", "outcome"))
        entities = args.get("entities", [])
        confidence = float(args.get("confidence", 0.7))
        
        exp_id = self.client.store_experience(
            user_id="default_user",
            content=text,
            metadata={
                "kind": kind,
                "entities": entities,
                "confidence": confidence,
            }
        )
        return ToolResult.success({"memory_id": exp_id, "stored": True})


def build(settings: dict[str, Any], *, root: Any = None) -> HindsightAdapter:
    """Factory for ProviderRegistry."""
    return HindsightAdapter(settings)
