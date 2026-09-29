"""Groq LLM Client Implementation."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping

import groq
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from brain.contracts import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    TokenUsage,
    ToolCall,
)
from brain.errors import ErrorClass, LLMError

# Meta-branded models are banned due to licensing dispute. Map to Mixtral/Gemma.
_MODEL_MAP = {
    "gpt-4o": "openai/gpt-oss-120b",
    "claude-3-5-sonnet": "openai/gpt-oss-120b",
}

def _map_model(model: str) -> str:
    return _MODEL_MAP.get(model, model)


class GroqClient:
    """A real Groq client fulfilling brain.contracts.LLMClient."""

    def __init__(self, settings: Mapping[str, Any] | None = None, _client: Any = None) -> None:
        self.settings = settings or {}
        api_key = os.environ.get("GROQ_API_KEY") or self.settings.get("api_key")
        if not api_key:
            raise LLMError("GROQ_API_KEY environment variable is not set", error_class=ErrorClass.PERMISSION)
        if _client:
            self.client = groq.Groq(api_key=api_key, http_client=_client)
        else:
            self.client = groq.Groq(api_key=api_key)

    @retry(
        retry=retry_if_exception_type((groq.RateLimitError, groq.InternalServerError)),
        wait=wait_exponential_jitter(initial=1, max=10),
        stop=stop_after_attempt(5),
    )
    def complete(self, request: LLMRequest) -> LLMResponse:
        messages = [m.to_api() for m in request.messages]
        
        # Tools
        kwargs: dict[str, Any] = {
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        
        if request.tools and not request.disable_native_tools:
            kwargs["tools"] = list(request.tools)
            if request.tool_choice:
                kwargs["tool_choice"] = request.tool_choice
        
        if request.response_format:
            kwargs["response_format"] = request.response_format

        models = [request.model] if request.model else self.settings.get("model_ladder", ["openai/gpt-oss-120b"])
        
        for i, model in enumerate(models):
            kwargs["model"] = _map_model(model)
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except groq.NotFoundError as exc:
                if self.settings.get("model_fallback_on_404", True) and i < len(models) - 1:
                    continue
                raise LLMError(f"Model not found: {exc}", error_class=ErrorClass.NOT_FOUND) from exc
            except groq.APIConnectionError as exc:
                raise LLMError(f"Connection error: {exc}", error_class=ErrorClass.TRANSIENT) from exc
            except groq.RateLimitError as exc:
                raise LLMError(f"Rate limit: {exc}", error_class=ErrorClass.RATE_LIMIT) from exc
            except groq.BadRequestError as exc:
                try:
                    err_data = exc.response.json().get("error", {})
                    if err_data.get("code") == "tool_use_failed" and "failed_generation" in err_data:
                        # Groq intercepted JSON mode as a tool call. Just return the generated JSON text.
                        return LLMResponse(
                            content=err_data["failed_generation"],
                            tool_calls=(),
                            finish_reason=FinishReason.STOP,
                            model=kwargs["model"],
                            usage=TokenUsage(),
                            raw=err_data,
                        )
                except Exception:
                    pass
                raise LLMError(f"Bad request: {exc}", error_class=ErrorClass.VALIDATION) from exc
            except groq.APIStatusError as exc:
                # 413 rate_limit_exceeded means TPM bucket is full. Must retry with backoff.
                if exc.status_code == 413 and "rate_limit_exceeded" in str(exc):
                    raise LLMError(f"Rate limited (TPM): {exc}", error_class=ErrorClass.RATE_LIMITED) from exc
                # 404 is NOT_FOUND but it is caught by NotFoundError above. For others:
                raise LLMError(f"API error ({exc.status_code}): {exc}", error_class=ErrorClass.PROVIDER_5XX if exc.status_code >= 500 else ErrorClass.PROVIDER_ERROR) from exc
            except Exception as exc:
                raise LLMError(f"Unexpected error: {exc}", error_class=ErrorClass.UNKNOWN) from exc

        choice = response.choices[0]
        
        # Parse finish reason
        fr_str = choice.finish_reason
        finish_reason = FinishReason.STOP
        if fr_str == "tool_calls":
            finish_reason = FinishReason.TOOL_CALLS
        elif fr_str == "length":
            finish_reason = FinishReason.LENGTH

        # Parse tool calls
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                # Groq returns arguments as a JSON string
                args_raw = tc.function.arguments
                try:
                    args_parsed = json.loads(args_raw)
                    parse_error = None
                except json.JSONDecodeError as exc:
                    args_parsed = {}
                    parse_error = str(exc)
                
                tool_calls.append(
                    ToolCall(
                        call_id=tc.id,
                        name=tc.function.name,
                        arguments_raw=args_raw,
                        arguments=args_parsed,
                        parse_error=parse_error,
                    )
                )

        # Parse usage
        usage = TokenUsage()
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                estimated=False,
            )

        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tuple(tool_calls),
            finish_reason=finish_reason,
            model=response.model,
            usage=usage,
            raw=response.model_dump(),
        )


def build(settings: dict[str, Any], *, root: Any = None) -> GroqClient:
    """Factory for ProviderRegistry."""
    return GroqClient(settings)
