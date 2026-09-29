"""Secret redaction and prompt injection detection for the JARVIS agent.

Ported from brain/redact.py with additions:
- gsk_ pattern (Groq API keys)
- Expanded injection detection regex (from brain/loop/engine.py)
- Tool output sanitisation

SECURITY RULE: This module must be called on ALL data that flows to:
- Events emitted to the frontend
- Log output
- Saved traces
- LLM turns (tool outputs)

Never print, log, or pass raw API keys anywhere.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Secret patterns
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # Groq API keys: gsk_<base62, ~50 chars>
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"),
    # OpenAI keys
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    # Anthropic keys
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"),
    # Generic Bearer tokens in headers
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-]{20,}"),
    # URL-embedded passwords/tokens: http://user:token@host
    re.compile(r"(?i)://[^:@/\s]+:[^:@/\s]{8,}@"),
]

# ---------------------------------------------------------------------------
# Injection patterns (ported from brain/loop/engine.py _INJECTION_RE)
# ---------------------------------------------------------------------------

_INJECTION_RE = re.compile(
    r"(?i)("
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions|"
    r"you\s+are\s+now|"
    r"disregard\s+(the\s+)?(system|previous)|"
    r"note\s+to\s+assistant|"
    r"as\s+an\s+ai|"
    r"new\s+instructions?\s*:|"
    r"system\s+prompt|"
    r"override\s+(your\s+)?instructions|"
    r"forget\s+everything|"
    r"jailbreak"
    r")"
)

REDACTION_PLACEHOLDER = "[REDACTED]"


def redact(text: str) -> str:
    """Redact secrets from a string. Never raises."""
    if not text:
        return text
    try:
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(REDACTION_PLACEHOLDER, text)
        return text
    except Exception:
        return "[REDACTION_ERROR]"


def redact_dict(data: Any, max_depth: int = 8) -> Any:
    """Recursively redact secrets from dict/list/str structures."""
    if max_depth <= 0:
        return data
    if isinstance(data, str):
        return redact(data)
    if isinstance(data, dict):
        return {k: redact_dict(v, max_depth - 1) for k, v in data.items()}
    if isinstance(data, list):
        return [redact_dict(item, max_depth - 1) for item in data]
    return data


def contains_injection(text: str) -> bool:
    """Return True if text contains a prompt injection attempt."""
    if not text:
        return False
    return bool(_INJECTION_RE.search(text))


def sanitise_tool_output(tool_name: str, output: str) -> str:
    """Redact secrets and flag (but not remove) injection attempts in tool output.

    Tool output is untrusted data. We redact secrets unconditionally.
    Injection attempts are logged at WARNING level; the output is still
    passed to the LLM but the loop.py checks contains_injection() and
    decides not to act on it.
    """
    redacted = redact(output)
    if contains_injection(redacted):
        logger.warning(
            "Prompt injection attempt detected in output of tool '%s'. "
            "The output will be passed to the LLM as data; the loop is responsible "
            "for ignoring embedded instructions.",
            tool_name,
        )
    return redacted


def safe_error_message(exc: BaseException) -> str:
    """Convert an exception to a redacted, safe error string."""
    return redact(str(exc))


__all__ = [
    "redact",
    "redact_dict",
    "contains_injection",
    "sanitise_tool_output",
    "safe_error_message",
    "REDACTION_PLACEHOLDER",
]
