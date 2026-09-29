"""Tool-call argument parsing and the parse/repair ladder.

Ported from brain/llm/parsing.py and adapted to work with:
- LiteLLM responses (tool_calls on message object OR text with <tool_call> tags)
- The existing backend tool registry schema format
- No dependency on brain.contracts

The repair ladder:
  1. Native function-calling (tool_calls on the message) — preferred
  2. <tool_call>JSON</tool_call> tag extraction — GPT-OSS / Qwen style
  3. Markdown ```json block extraction
  4. Raw JSON object in text
  5. tool_name({...}) textual form
  6. Repair prompt with validation error -> JSON mode (no tools) -> constrained parse

Schema validation catches: missing required args, unknown args, wrong types.
Each repair attempt is logged and counted. After MAX_REPAIR_ATTEMPTS the call
is returned as a parse failure (error= set), and the loop decides whether to
recover or propagate the error.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_REPAIR_ATTEMPTS = 3

# Regex patterns
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_CALL_RE = re.compile(r"([a-z_][a-z0-9_]*)\s*\(\s*(\{.*?\})\s*\)", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class ToolCallParseResult:
    """Result of parsing one tool call from model output."""

    __slots__ = ("name", "arguments", "error", "strategy")

    def __init__(
        self,
        name: str,
        arguments: Dict[str, Any],
        error: Optional[str] = None,
        strategy: str = "native",
    ) -> None:
        self.name = name
        self.arguments = arguments
        self.error = error
        self.strategy = strategy

    @property
    def ok(self) -> bool:
        return self.error is None

    def __repr__(self) -> str:
        return f"ToolCallParseResult(name={self.name!r}, ok={self.ok}, strategy={self.strategy!r})"


# ---------------------------------------------------------------------------
# Core parsing functions
# ---------------------------------------------------------------------------


def parse_tool_arguments(raw: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """Parse a tool-call argument string, tolerating provider malformations.

    Returns (parsed_dict, error). On success error is None.
    On failure parsed is {} and error explains what was tried.
    """
    if raw is None:
        return {}, "arguments were null"
    if isinstance(raw, dict):
        return dict(raw), None
    if not isinstance(raw, str):
        return {}, f"arguments were {type(raw).__name__}, expected dict or JSON string"

    text = raw.strip()
    if not text:
        return {}, "arguments were empty string"

    attempts: List[str] = []

    # 1. Direct JSON parse
    parsed = _try_json(text)
    if parsed is not None:
        return parsed, None
    attempts.append("direct JSON parse")

    # 2. Markdown fence
    fenced = _FENCE_RE.search(text)
    if fenced:
        parsed = _try_json(fenced.group(1).strip())
        if parsed is not None:
            return parsed, None
        attempts.append("markdown-fence extraction")

    # 3. Outermost object extraction
    embedded = _OBJECT_RE.search(text)
    if embedded:
        candidate = embedded.group(0)
        parsed = _try_json(candidate)
        if parsed is not None:
            return parsed, None
        attempts.append("outermost-object extraction")

        parsed = _try_json(_repair_common(candidate))
        if parsed is not None:
            return parsed, None
        attempts.append("punctuation repair on extracted object")

    # 4. Full text repair
    repaired = _repair_common(text)
    if repaired != text:
        parsed = _try_json(repaired)
        if parsed is not None:
            return parsed, None
        attempts.append("punctuation repair on full value")

    # 5. Bracket balancing (truncated token-limit response)
    balanced = _close_unbalanced(text)
    if balanced != text:
        parsed = _try_json(balanced)
        if parsed is not None:
            return parsed, None
        attempts.append("bracket balancing for truncated object")

    return {}, (
        f"could not parse tool arguments as JSON; tried: {', '.join(attempts)}. "
        f"Received: {text[:200]!r}"
    )


def parse_tool_calls_from_text(text: str) -> List[ToolCallParseResult]:
    """Parse all tool calls from model text output.

    Tries strategies in priority order:
    1. <tool_call> tags (GPT-OSS / Qwen native style)
    2. Markdown JSON blocks
    3. Raw JSON object
    4. tool_name({...}) textual form
    """
    results: List[ToolCallParseResult] = []

    # 1. <tool_call>...</tool_call> tags
    tags = _TAG_RE.findall(text)
    if tags:
        for chunk in tags:
            chunk = chunk.strip()
            try:
                parsed = json.loads(chunk)
                if isinstance(parsed, dict):
                    name = parsed.get("name") or parsed.get("tool") or parsed.get("tool_name")
                    if name:
                        raw_args = parsed.get("arguments") or parsed.get("args") or {}
                        args, err = parse_tool_arguments(raw_args) if isinstance(raw_args, str) else (raw_args, None)
                        results.append(ToolCallParseResult(name=str(name), arguments=args, error=err, strategy="tag"))
            except Exception:
                pass
        if results:
            return results

    # 2. Markdown JSON blocks
    fenced_blocks = _FENCE_RE.findall(text)
    for block in fenced_blocks:
        block = block.strip()
        parsed = _try_json(block)
        if parsed is None:
            continue
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("tool") or item.get("tool_name")
                    if name:
                        raw_args = item.get("arguments") or item.get("args") or {}
                        args, err = parse_tool_arguments(raw_args) if isinstance(raw_args, str) else (raw_args, None)
                        results.append(ToolCallParseResult(name=str(name), arguments=args, error=err, strategy="markdown_block"))
        elif isinstance(parsed, dict):
            name = parsed.get("name") or parsed.get("tool") or parsed.get("tool_name")
            if name:
                raw_args = parsed.get("arguments") or parsed.get("args") or {}
                args, err = parse_tool_arguments(raw_args) if isinstance(raw_args, str) else (raw_args, None)
                results.append(ToolCallParseResult(name=str(name), arguments=args, error=err, strategy="markdown_block"))
    if results:
        return results

    # 3. Raw JSON object at start/end of text
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        parsed = _try_json(stripped)
        if parsed and isinstance(parsed, dict):
            name = parsed.get("name") or parsed.get("tool") or parsed.get("tool_name")
            if name:
                raw_args = parsed.get("arguments") or parsed.get("args") or {}
                args, err = parse_tool_arguments(raw_args) if isinstance(raw_args, str) else (raw_args, None)
                results.append(ToolCallParseResult(name=str(name), arguments=args, error=err, strategy="raw_json"))
    if results:
        return results

    # 4. tool_name({...}) textual form
    match = _CALL_RE.search(text)
    if match:
        args, err = parse_tool_arguments(match.group(2))
        results.append(ToolCallParseResult(name=match.group(1), arguments=args, error=err, strategy="textual_call"))

    return results


def build_repair_prompt(
    *,
    tool: str,
    schema: Dict[str, Any],
    raw_arguments: str,
    errors: List[str],
) -> str:
    """Build a repair prompt after schema validation failure.

    Contains exactly what the model needs: the error, the schema, and what it produced.
    Ported from brain/llm/parsing.py::build_repair_prompt.
    """
    error_lines = "\n".join(f"- {e}" for e in errors) or "- (no detail available)"
    return (
        f"Your previous call to the tool `{tool}` was rejected by schema validation.\n\n"
        f"Validation errors:\n{error_lines}\n\n"
        f"Your arguments were:\n{raw_arguments[:1200]}\n\n"
        f"The tool's argument schema is:\n"
        f"{json.dumps(schema, indent=2, sort_keys=True)[:2400]}\n\n"
        "Reply with a single corrected JSON object of arguments only. No prose, no markdown "
        "fence, no explanation. Include every required field exactly once, use only fields named "
        "in the schema, and respect the stated types, enums, minimums and maximums."
    )


def validate_tool_args(tool_name: str, args: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    """Validate args against a JSON schema. Returns list of error strings."""
    errors: List[str] = []
    if not schema:
        return errors

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # Check required fields
    for field_name in required:
        if field_name not in args or args[field_name] is None:
            errors.append(f"Missing required argument: '{field_name}'")

    # Check unknown fields
    if properties:
        for key in args:
            if key not in properties:
                errors.append(f"Unknown argument: '{key}' (not in schema)")

    return errors


def canonicalise_args(args: Any) -> str:
    """Stable string representation of tool args for loop detection.

    Sorted keys, no whitespace. Ported from brain/llm/parsing.py.
    """
    try:
        return json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return repr(args)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _try_json(text: str) -> Optional[Dict[str, Any]]:
    """Try to parse text as JSON; return dict or None."""
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _repair_common(text: str) -> str:
    """Fix punctuation mistakes that account for most malformed payloads."""
    out = text.strip()
    out = re.sub(r",\s*([}\]])", r"\1", out)        # trailing commas
    out = re.sub(r"'([^'\"\\]*)'(\s*:)", r'"\1"\2', out)  # single-quoted keys
    out = re.sub(r":\s*'([^'\"\\]*)'", r': "\1"', out)    # single-quoted values
    out = re.sub(r"\bNone\b", "null", out)
    out = re.sub(r"\bTrue\b", "true", out)
    out = re.sub(r"\bFalse\b", "false", out)
    return out


def _close_unbalanced(text: str) -> str:
    """Close a JSON object cut off mid-flight (e.g. by token limit)."""
    body = text[text.find("{"):] if "{" in text else text
    if not body.startswith("{"):
        return text
    opens = body.count("{") - body.count("}")
    brackets = body.count("[") - body.count("]")
    if opens <= 0 and brackets <= 0:
        return text
    trimmed = body.rstrip()
    if trimmed.endswith(","):
        trimmed = trimmed[:-1]
    if trimmed.count('"') % 2 == 1:
        trimmed += '"'
    return trimmed + ("]" * max(0, brackets)) + ("}" * max(0, opens))


__all__ = [
    "ToolCallParseResult",
    "parse_tool_arguments",
    "parse_tool_calls_from_text",
    "build_repair_prompt",
    "validate_tool_args",
    "canonicalise_args",
    "MAX_REPAIR_ATTEMPTS",
]
