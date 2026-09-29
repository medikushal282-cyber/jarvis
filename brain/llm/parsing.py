"""Tool-argument parsing and the parse/repair ladder.

This module exists because the hackathon brief says, in as many words, to "make sure you have
your agent ready to handle function calling errors". Providers return tool arguments as a JSON
*string*, and that string arrives malformed often enough to be a normal case rather than an
edge case: wrapped in markdown fences, prefixed with a sentence of commentary, truncated by a
token limit, or carrying a trailing comma.

The design consequence is that raw argument text is preserved all the way from the client
(:attr:`brain.contracts.ToolCall.arguments_raw`) into this module. A pipeline that parses early
and keeps only the result cannot repair anything, because by then the evidence of what went
wrong has been thrown away.

Two layers:

* :func:`parse_tool_arguments` is the tolerant local parser, trying increasingly permissive
  strategies and reporting what failed when none works.
* :class:`CallParser` is the ladder: it decides when to stop asking the same way and switch
  strategy, and it is the only place that knows the order.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from brain.contracts import (
    ChatMessage,
    FinishReason,
    LLMClient,
    LLMRequest,
    LLMResponse,
    ParseStrategy,
    ToolCall,
)

#: A fenced block, optionally tagged as json.
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
#: The outermost brace-delimited run, used to strip prose surrounding a JSON object.
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
#: A ``tool_name({...})`` shape, the last-resort textual form.
_CALL_RE = re.compile(r"([a-z_][a-z0-9_]*)\s*\(\s*(\{.*?\})\s*\)", re.DOTALL | re.IGNORECASE)


def parse_tool_arguments(raw: Any) -> tuple[dict[str, Any], str | None]:
    """Parse a tool-call argument string, tolerating the malformations providers emit.

    Returns ``(parsed, error)``. On success ``error`` is ``None``; on failure ``parsed`` is
    empty and ``error`` explains what was tried, because that text becomes part of the repair
    prompt and a vague message costs a real recovery attempt.
    """
    if raw is None:
        return {}, "arguments were null"
    if isinstance(raw, dict):
        # Some providers hand back an already-decoded object. Accept it rather than failing a
        # call that is in fact fine.
        return dict(raw), None
    if not isinstance(raw, str):
        return {}, f"arguments were {type(raw).__name__}"

    text = raw.strip()
    if not text:
        return {}, "arguments were empty"

    attempts: list[str] = []

    parsed = _try_json(text)
    if parsed is not None:
        return parsed, None
    attempts.append("direct JSON parse")

    fenced = _FENCE_RE.search(text)
    if fenced:
        parsed = _try_json(fenced.group(1).strip())
        if parsed is not None:
            return parsed, None
        attempts.append("markdown-fence extraction")

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
        attempts.append("punctuation repair")

    repaired = _repair_common(text)
    if repaired != text:
        parsed = _try_json(repaired)
        if parsed is not None:
            return parsed, None
        attempts.append("punctuation repair on the whole value")

    balanced = _close_unbalanced(text)
    if balanced != text:
        parsed = _try_json(balanced)
        if parsed is not None:
            return parsed, None
        attempts.append("bracket balancing for a truncated object")

    return {}, (
        f"could not parse tool arguments as JSON; tried: {', '.join(attempts)}. "
        f"Received: {text[:200]!r}"
    )


def _try_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    # A bare array or scalar is not a valid argument object; reporting that here is clearer than
    # letting a schema validator produce a confusing type error later.
    return value if isinstance(value, dict) else None


def _repair_common(text: str) -> str:
    """Fix the punctuation mistakes that account for most malformed payloads."""
    out = text.strip()
    out = re.sub(r",\s*([}\]])", r"\1", out)  # trailing commas
    out = re.sub(r"'([^'\"\\]*)'(\s*:)", r'"\1"\2', out)  # single-quoted keys
    out = re.sub(r":\s*'([^'\"\\]*)'", r': "\1"', out)  # single-quoted values
    out = re.sub(r"\bNone\b", "null", out)
    out = re.sub(r"\bTrue\b", "true", out)
    out = re.sub(r"\bFalse\b", "false", out)
    return out


def _close_unbalanced(text: str) -> str:
    """Close an object cut off mid-flight, so a token-limit truncation can be salvaged.

    Only closes what is genuinely unbalanced, and only when the text starts with a brace. A
    half-written value is still dropped by the parser, which is the correct outcome: a truncated
    argument is reported as missing rather than silently invented.
    """
    body = text[text.find("{") :] if "{" in text else text
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


def canonicalise_args(args: Any) -> str:
    """Stable string form of arguments, used as the key for loop detection.

    Sorted keys and no whitespace, so two calls differing only in key order or spacing hash the
    same. Loop detection that could be defeated by reordering keys would be useless.
    """
    try:
        return json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return repr(args)


def extract_call_from_text(text: str) -> tuple[str, dict[str, Any], str | None] | None:
    """Find a tool call in free text. The last resort when native tool calling fails.

    Recognises a JSON object naming a tool (``name``/``tool`` plus ``arguments``/``args``/
    ``parameters``) and the ``tool_name({...})`` form models sometimes emit instead of using the
    tool-calling API at all.
    """
    if not text:
        return None

    fenced = _FENCE_RE.search(text)
    body = fenced.group(1) if fenced else text

    for blob in _iter_json_objects(body):
        if not isinstance(blob, dict):
            continue
        name = blob.get("name") or blob.get("tool") or blob.get("tool_name")
        if not isinstance(name, str):
            continue
        for key in ("arguments", "args", "parameters", "input"):
            raw = blob.get(key)
            if isinstance(raw, dict):
                return name, raw, None
            if isinstance(raw, str):
                parsed, err = parse_tool_arguments(raw)
                return name, parsed, err
        return name, {}, f"tool {name!r} was named with no arguments object"

    match = _CALL_RE.search(body)
    if match:
        parsed, err = parse_tool_arguments(match.group(2))
        return match.group(1), parsed, err

    return None


def _iter_json_objects(text: str) -> list[Any]:
    """Every decodable JSON object in ``text``, outermost first."""
    found: list[Any] = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start == -1:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        found.append(value)
        index = start + max(end, 1)
    return found


def build_repair_prompt(
    *,
    tool: str,
    schema: dict[str, Any],
    raw_arguments: str,
    errors: Sequence[str],
) -> str:
    """The prompt sent back after a validation failure.

    Contains the three things the model needs and nothing it does not: the exact error, the
    schema it violated, and the value it produced. Re-asking without the specific error is the
    failure mode this exists to prevent -- it burns an attempt and usually reproduces the same
    mistake.
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


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    """What the ladder produced, and how much work it took."""

    response: LLMResponse
    strategy: ParseStrategy
    repair_attempts: int
    ladder_exhausted: bool


class CallParser:
    """Walks the parsing ladder until it has a schema-valid tool call, or gives up honestly.

    Order, per ``config/providers.yaml``:

    1. ``NATIVE_TOOLS`` -- the provider's function calling.
    2. ``JSON_MODE`` -- the same request with ``tools`` **removed** and a JSON-object
       ``response_format``. The removal is not optional: Groq rejects structured outputs and
       tool use in one request, so a rung that merely added ``response_format`` would fail for a
       reason that has nothing to do with the model.
    3. ``CONSTRAINED_TEXT`` -- no schema on the wire; recover the call from the text locally.

    Before descending a rung it spends up to ``max_repairs`` attempts asking the model to fix its
    own output, since that is cheaper and likelier to succeed than changing strategy.
    """

    def __init__(
        self,
        client: LLMClient,
        *,
        ladder: Sequence[ParseStrategy] = (
            ParseStrategy.NATIVE_TOOLS,
            ParseStrategy.JSON_MODE,
            ParseStrategy.CONSTRAINED_TEXT,
        ),
        max_repairs: int = 2,
        validator: Callable[[str, dict[str, Any]], list[str]] | None = None,
    ) -> None:
        self._client = client
        self._ladder = tuple(ladder)
        self._max_repairs = max_repairs
        self._validator = validator

    def obtain_call(self, request: LLMRequest) -> ParseOutcome:
        """Return the first response whose tool calls are all usable."""
        attempts = 0
        last: LLMResponse | None = None

        for strategy in self._ladder:
            response = self._client.complete(self._request_for(strategy, request))
            last = response

            if strategy is ParseStrategy.CONSTRAINED_TEXT:
                recovered = self._from_text(response)
                if recovered is not None:
                    return ParseOutcome(recovered, strategy, attempts, False)
                continue

            if response.wants_tools and self._all_valid(response):
                return ParseOutcome(response, strategy, attempts, False)

            # Nothing usable: spend the repair budget before changing strategy.
            for _ in range(self._max_repairs):
                attempts += 1
                response = self._client.complete(self._repair_request(request, response))
                last = response
                if response.wants_tools and self._all_valid(response):
                    return ParseOutcome(response, strategy, attempts, False)

        assert last is not None, "the ladder must contain at least one strategy"
        return ParseOutcome(last, self._ladder[-1], attempts, True)

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _request_for(strategy: ParseStrategy, request: LLMRequest) -> LLMRequest:
        if strategy is ParseStrategy.JSON_MODE:
            return dataclasses.replace(
                request,
                disable_native_tools=True,
                response_format={"type": "json_object"},
                tool_choice="none",
                tools=(),
            )
        if strategy is ParseStrategy.CONSTRAINED_TEXT:
            return dataclasses.replace(
                request,
                disable_native_tools=True,
                response_format=None,
                tool_choice="none",
                tools=(),
            )
        return request

    def _all_valid(self, response: LLMResponse) -> bool:
        if self._validator is None:
            return all(tc.is_parsed for tc in response.tool_calls)
        for call in response.tool_calls:
            if not call.is_parsed or self._validator(call.name, call.arguments):
                return False
        return True

    def _repair_request(self, request: LLMRequest, previous: LLMResponse) -> LLMRequest:
        broken = previous.tool_calls[0] if previous.tool_calls else None
        tool_name = broken.name if broken else "unknown"
        raw = broken.arguments_raw if broken else previous.content[:400]

        schema: dict[str, Any] = {}
        for tool in request.tools:
            fn = tool.get("function", {}) if isinstance(tool, dict) else {}
            if fn.get("name") == tool_name:
                schema = fn.get("parameters", {}) or {}
                break

        errors: list[str] = []
        if broken is not None and broken.parse_error:
            errors.append(f"arguments were not valid JSON: {broken.parse_error}")
        elif broken is not None and self._validator is not None:
            errors = self._validator(broken.name, broken.arguments)
        if not errors:
            errors = ["the previous response did not contain a usable tool call"]

        messages = tuple(request.messages) + (
            ChatMessage(role="assistant", content=previous.content or ""),
            ChatMessage(
                role="user",
                content=build_repair_prompt(
                    tool=tool_name, schema=schema, raw_arguments=raw, errors=errors
                ),
            ),
        )
        return dataclasses.replace(request, messages=messages)

    def _from_text(self, response: LLMResponse) -> LLMResponse | None:
        found = extract_call_from_text(response.content)
        if found is None:
            return None
        name, args, err = found
        if self._validator is not None and not err and self._validator(name, args):
            return None
        call = ToolCall(
            call_id=f"text-{abs(hash(name)) % 10_000:04d}",
            name=name,
            arguments_raw=json.dumps(args, sort_keys=True),
            arguments=args,
            parse_error=err,
        )
        return dataclasses.replace(
            response, tool_calls=(call,), finish_reason=FinishReason.TOOL_CALLS
        )
