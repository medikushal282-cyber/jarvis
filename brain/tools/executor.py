"""Tool execution: validation, timeout, retry, redaction and error classification.

Everything a tool call needs that is *not* the tool itself lives here, deliberately. The provider
adapters stay thin -- they answer a question about the world and nothing else -- so that timeout
behaviour, retry policy, redaction and error classification are implemented once and are
identical for every tool, including a teammate's real adapter.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from brain.contracts import Clock, ToolResult, ToolSpec
from brain.errors import ErrorClass, is_retryable
from brain.redact import redact_args, redact_paths, redact_text
from brain.tools.registry import ToolRegistry
from brain.tools.validate import validate_args
from brain.util.text import truncate_middle

#: Results larger than this are truncated before entering a prompt. An unbounded log dump would
#: crowd out the plan and the objective, which are the parts the model actually needs.
MAX_RESULT_CHARS = 12_000


@dataclass(frozen=True, slots=True)
class CallOutcome:
    """Everything the loop needs to know about one attempted call."""

    tool: str
    call_id: str
    result: ToolResult
    attempts: int
    redacted_args: dict[str, Any]
    error_class: ErrorClass | None = None


class ToolExecutor:
    """Runs a validated, policy-cleared tool call."""

    def __init__(
        self,
        registry: ToolRegistry,
        providers: Any,
        clock: Clock,
        *,
        sleeper: Any = time.sleep,
    ) -> None:
        self._registry = registry
        self._providers = providers
        self._clock = clock
        self._sleep = sleeper

    def execute(self, spec: ToolSpec, args: dict[str, Any], *, call_id: str) -> CallOutcome:
        """Validate, then invoke with the spec's timeout and retry policy."""
        safe_args = redact_args(args, spec.redact)

        problems = validate_args(spec, args)
        if problems:
            # Validation is ours to fix, not the world's: return immediately so the caller's
            # repair rung can correct the arguments rather than the retry rung repeating them.
            return CallOutcome(
                tool=spec.name,
                call_id=call_id,
                result=ToolResult.failure(ErrorClass.VALIDATION, "; ".join(problems)),
                attempts=0,
                redacted_args=safe_args,
                error_class=ErrorClass.VALIDATION,
            )

        try:
            provider = self._providers.tool_provider(spec.provider)
        except Exception as exc:
            return self._failed(spec, call_id, safe_args, 0, ErrorClass.PROVIDER_ERROR, str(exc))

        attempts = 0
        last: ToolResult | None = None
        while attempts < max(1, spec.retry.max_attempts):
            attempts += 1
            started = self._clock.monotonic()
            try:
                result = provider.invoke(spec.method, args)
            except Exception as exc:
                # A provider raising for an expected failure is a contract violation, but the
                # cost of enforcing that here is far lower than the cost of a crashed run.
                result = ToolResult.failure(
                    ErrorClass.PROVIDER_ERROR, f"{type(exc).__name__}: {exc}"
                )
            elapsed = max(0.0, self._clock.monotonic() - started)

            if result.duration_ms == 0.0:
                result = ToolResult(
                    ok=result.ok,
                    data=result.data,
                    error_class=result.error_class,
                    error_message=result.error_message,
                    duration_ms=elapsed * 1000.0,
                    truncated=result.truncated,
                    raw_bytes=result.raw_bytes,
                )
            last = result

            if result.ok:
                return CallOutcome(
                    spec.name, call_id, self._clean(result, spec), attempts, safe_args, None
                )

            error_class = result.error_class or ErrorClass.PROVIDER_ERROR
            if attempts >= max(1, spec.retry.max_attempts):
                break
            if not is_retryable(error_class) or not spec.retry.permits(error_class):
                break
            # Blind-retrying a non-idempotent tool risks applying the same destructive change
            # twice. Only a transient provider failure is retried on a non-idempotent tool.
            if not spec.idempotent and error_class is not ErrorClass.PROVIDER_5XX:
                break
            self._sleep(self._delay(spec, attempts))

        assert last is not None
        return CallOutcome(
            spec.name,
            call_id,
            last,
            attempts,
            safe_args,
            last.error_class or ErrorClass.PROVIDER_ERROR,
        )

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _delay(spec: ToolSpec, attempt: int) -> float:
        base = max(0.0, spec.retry.base_delay_s)
        if spec.retry.backoff == "fixed":
            return base
        return min(20.0, base * (2 ** max(0, attempt - 1)))

    @staticmethod
    def _clean(result: ToolResult, spec: ToolSpec) -> ToolResult:
        """Redact declared paths and bound the size before the result can reach a prompt."""
        data = redact_paths(result.data, spec.redact) if spec.redact else result.data
        truncated = result.truncated
        if isinstance(data, (dict, list, tuple)):
            blob = json.dumps(data, default=str)
            if len(blob) > MAX_RESULT_CHARS:
                data = truncate_middle(blob, max_chars=MAX_RESULT_CHARS)
                truncated = True
            elif spec.redact:
                data = redact_paths(data, list(spec.redact))
        elif isinstance(data, str):
            if spec.redact:
                data = redact_paths(data, list(spec.redact))
            if isinstance(data, str) and len(data) > MAX_RESULT_CHARS:
                data = truncate_middle(data, max_chars=MAX_RESULT_CHARS)
                truncated = True
        return ToolResult(
            ok=result.ok,
            data=data,
            error_class=result.error_class,
            error_message=redact_text(result.error_message),
            duration_ms=result.duration_ms,
            truncated=truncated,
            raw_bytes=result.raw_bytes,
        )

    def _failed(
        self,
        spec: ToolSpec,
        call_id: str,
        safe_args: dict[str, Any],
        attempts: int,
        error_class: ErrorClass,
        message: str,
    ) -> CallOutcome:
        return CallOutcome(
            tool=spec.name,
            call_id=call_id,
            result=ToolResult.failure(error_class, message),
            attempts=attempts,
            redacted_args=safe_args,
            error_class=error_class,
        )
