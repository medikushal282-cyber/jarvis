"""Memory retention and recall policy."""

from __future__ import annotations

import re
from typing import Any

from brain.config.loader import ResolvedConfig
from brain.contracts import MemoryItem, MemoryKind, RecallQuery

_INJECTION_RE = re.compile(
    r"(?i)(ignore (all )?(previous|prior|above) instructions|you are now|"
    r"disregard (the )?(system|previous)|note to assistant|as an ai|"
    r"new instructions?:|system prompt)"
)

class MemoryPolicy:
    """Evaluates candidates for retention and formulates recall queries."""
    
    def __init__(self, config: ResolvedConfig) -> None:
        self._config = config
        
    def should_retain(self, text: str, kind_raw: str) -> tuple[bool, str, MemoryKind]:
        """Check if a memory candidate passes the origin and horizon tests.
        
        Returns:
            (passed, reason, MemoryKind)
        """
        if _INJECTION_RE.search(text):
            return False, "origin_test", MemoryKind.OUTCOME
            
        if re.search(r"(?i)\b(the above|this incident|just now|as we saw)\b", text):
            return False, "horizon_test", MemoryKind.OUTCOME
            
        try:
            kind = MemoryKind(kind_raw)
        except ValueError:
            kind = MemoryKind.OUTCOME
            
        if kind not in self._config.memory.retain_kinds:
            return False, "horizon_test", kind
            
        return True, "", kind

    def build_recall_query(self, objective: str, entities: tuple[str, ...]) -> RecallQuery:
        """Formulate the initial recall query for a run."""
        return RecallQuery(
            text=(
                f"What do we know about {objective}? "
                "Which approaches have already failed on this, and how does this operator want it done?"
            ),
            entities=entities,
            limit=self._config.memory.recall_limit,
        )
