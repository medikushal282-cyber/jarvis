# Brief — LLM LAYER ENGINEER (Groq client, parse/repair ladder, tool executor, conformance)

You are building the model-integration and tool-execution layer of a Python agent "Brain" for a
hackathon project. Repo root: `D:\College\Hack With Hyd\jarvis`. All paths below are relative to it.

## READ FIRST (frozen contract — do not edit these)
- `brain/contracts.py` — `LLMClient`, `LLMRequest`, `LLMResponse`, `ToolCall`, `ChatMessage`,
  `TokenUsage`, `FinishReason`, `ParseStrategy`, `ToolResult`, `ToolSpec`, `RetryPolicy`, and the
  `ToolProvider` Protocol. Read it fully.
- `brain/errors.py` — `ErrorClass`, `LLMError`, `is_retryable`, `is_model_output_error`.
- `docs/brain/CONTRACTS.md` — sections 3 (`LLMClient`, `ToolProvider`), 5 (error taxonomy), 7 (conformance).
- `docs/brain/EXTERNAL_DOCS.md` — **read the Groq sections carefully.** It contains verified API
  shapes and 18 gotchas. Several of them invalidate the obvious implementation.
- `config/providers.yaml` — the `llm` settings block is your configuration surface.
- `config/tools/*.yaml` — the tools whose arguments you validate and whose calls you execute.

## YOUR FILES (you own these; create or edit nothing else)
```
brain/llm/__init__.py
brain/llm/backoff.py         # exponential backoff with jitter; honours Retry-After
brain/llm/parsing.py         # argument parsing + the parse/repair ladder (CallParser)
brain/llm/client.py          # shared LLMClient helpers
brain/providers/llm/__init__.py
brain/providers/llm/groq_client.py   # GroqClient (httpx) + build() factory
brain/providers/llm/fake.py          # FakeLLM (scripted) + build() factory
brain/tools/executor.py      # ToolExecutor: timeout, retry, redaction, classification
brain/tools/conformance.py   # `python -m brain.tools.conformance` contract suite
```
Do NOT create or edit anything else. Peers own `brain/config/*`, `brain/tools/registry.py`,
`brain/tools/validate.py`, `brain/events/*`, `brain/providers/registry.py`, `brain/loop/*`,
`brain/prompt/*`, `brain/redact.py`, `brain/util/*`, `brain/providers/mock/*`, `tests/*`,
`config/fixtures/*`. They are working in parallel right now.

## APIs YOU CONSUME (peer-owned, being written concurrently)
```python
from brain.tools.registry import ToolRegistry
from brain.tools.validate import validate_args        # -> list[str], [] == ok
from brain.redact import redact_args, redact_text
from brain.util.text import estimate_tokens
```
You do NOT emit events; the loop does. Keep this layer emit-free so it stays testable in isolation.

## EXACT API YOU MUST PROVIDE

### `brain/llm/parsing.py`
```python
def parse_tool_arguments(raw: str) -> tuple[dict[str, Any], str | None]
    # (parsed, error). Must survive: valid JSON; markdown-fenced JSON; JSON with leading or
    # trailing prose; single quotes; trailing commas; truncated JSON; empty string.

def canonicalise_args(args: Mapping[str, Any]) -> str
    # stable, sorted, whitespace-free — used for loop-detection hashing

def extract_call_from_text(text: str) -> tuple[str, dict[str, Any], str | None] | None
    # last resort: find a tool name + args in free text, e.g. a JSON object with "name"/"tool"
    # and "arguments"/"args"/"parameters", or a `tool_name({...})` shape. None if absent.

def build_repair_prompt(*, tool: str, schema: dict[str, Any], raw_arguments: str,
                        errors: Sequence[str]) -> str
    # Sent back to the model after a validation failure. MUST include the exact validation
    # error text and the tool's JSON Schema, and must state that only a corrected argument
    # object is wanted. This is the mechanism the hackathon brief calls out as mandatory.

@dataclass(frozen=True, slots=True)
class ParseOutcome:
    response: LLMResponse
    strategy: ParseStrategy
    repair_attempts: int
    ladder_exhausted: bool

class CallParser:
    def __init__(self, client: LLMClient, *, ladder: Sequence[ParseStrategy],
                 max_repairs: int = 2,
                 validator: Callable[[str, dict], list[str]] | None = None) -> None: ...
    def obtain_call(self, request: LLMRequest) -> ParseOutcome: ...
```
`obtain_call` walks the ladder in order and returns the moment it has a **schema-valid** call:
1. `NATIVE_TOOLS` — normal request with `tools`.
2. `JSON_MODE` — **must set `disable_native_tools=True` and `response_format={"type":"json_object"}`**,
   because Groq forbids structured outputs and `tools` in the same request. Do not send both.
3. `CONSTRAINED_TEXT` — no schema hints on the wire; parse locally with `extract_call_from_text`.
Between rungs, and before moving down, send at most `max_repairs` repair prompts built by
`build_repair_prompt`. Never retry an identical malformed request unchanged. Record which rung
succeeded — the loop puts it in the trace.

### `brain/llm/backoff.py`
```python
def compute_delay(attempt: int, *, base_s: float, max_s: float, jitter: bool,
                  retry_after_s: float | None = None) -> float
def should_retry(status_code: int | None, error_class: ErrorClass, attempt: int, max_attempts: int) -> bool
```
`compute_delay` uses full jitter (`random.uniform(0, min(max_s, base_s * 2**attempt))`) and
returns `retry_after_s` when the server supplied one. `should_retry`: retry 429 and 5xx, and
**also retry 422** — the docs note Groq returns 422 for some transient conditions, and it is not
a validation error of ours. Never retry 400/401/403/404.

### `brain/providers/llm/groq_client.py`
```python
class GroqClient:
    def __init__(self, settings: Mapping[str, Any], *, root: Path,
                 http: httpx.Client | None = None, api_key: str | None = None,
                 sleeper: Callable[[float], None] = time.sleep) -> None: ...
    def complete(self, request: LLMRequest) -> LLMResponse: ...

def build(settings: dict, *, root: Path) -> GroqClient
```
All of these are load-bearing:
- POST `{api_base}/chat/completions`. `model` from `request.model` or `primary_model`.
- **`function.arguments` is a JSON string.** Parse it in `try/except`, keep it raw in
  `ToolCall.arguments_raw`, and set `parse_error` on failure. Never discard the raw text.
- **Send `parallel_tool_calls: false` explicitly** (gpt-oss-120b does not support it) but
  **still handle N tool calls** in a response, capping at `max_parallel_calls` and recording the
  cap in the response's `raw`. A provider ignoring our flag is not a reason to crash.
- Map `finish_reason` faithfully. A `length` finish carrying tool calls must not be collapsed
  into a valid `tool_calls` response — the loop needs to see the truncation.
- **Groq error bodies have no `code` field** (only `message` and `type`). Handle that shape
  without a `KeyError`. Classify to `ErrorClass`: 429 → `rate_limited`; 5xx → `provider_5xx`;
  408/timeout → `timeout`; others → `provider_error`. Raise `LLMError` with the class set —
  never leak an `httpx` exception.
- Retry via `backoff.py` up to `max_attempts`, honouring `Retry-After` on 429.
- Read the key from `os.environ[settings["api_key_env"]]`. **Never** accept a key from the config
  file, never log it, never put it in an error message or in `raw`. If missing, raise `LLMError`
  naming the env var — never the value.
- Use whichever completion-length parameter `EXTERNAL_DOCS.md` confirms, and send only that one.
- **Model deprecation handling:** if the configured model returns 404 or a "decommissioned"
  error, fall back to `primary_model` rather than failing the run, and record it in `raw`. The
  hackathon brief's recommended `qwen/qwen3-32b` is dead — do not hardcode it.

### `brain/providers/llm/fake.py`
```python
class FakeLLM:
    def __init__(self, script: Sequence[Mapping[str, Any]], *, strict: bool = True) -> None: ...
    def complete(self, request: LLMRequest) -> LLMResponse: ...
    @classmethod
    def from_yaml(cls, path: Path, *, scenario: str | None = None) -> FakeLLM: ...
def build(settings: dict, *, root: Path) -> FakeLLM
```
A **scripted, deterministic** client — a real implementation of `LLMClient`, not a mock object.
It pops one scripted step per call. Each step may declare `content`, `tool_calls` (name plus
`arguments` as a **raw string**, so malformed JSON can be scripted deliberately),
`finish_reason`, `usage`. Support `if_tool_result_contains` / `if_called` guards so a script can
branch on what actually happened. If the script runs out: raise a clear `LLMError` in `strict`
mode, else return a plain `stop` response. Ship fixtures for the malformed cases — fenced JSON,
prose-wrapped JSON, truncated JSON, an unknown tool name, a missing required argument, and a
`length` finish — because those are what the parse ladder exists for.

### `brain/tools/executor.py`
```python
@dataclass(frozen=True, slots=True)
class CallOutcome:
    tool: str
    call_id: str
    result: ToolResult
    attempts: int
    redacted_args: dict[str, Any]
    error_class: ErrorClass | None = None

class ToolExecutor:
    def __init__(self, registry: ToolRegistry, providers: ProviderRegistry, clock: Clock, *,
                 sleeper: Callable[[float], None] = time.sleep) -> None: ...
    def execute(self, spec: ToolSpec, args: dict[str, Any], *, call_id: str) -> CallOutcome: ...
```
- Validate first with `validate_args`. On failure return a `CallOutcome` carrying
  `ErrorClass.VALIDATION` and the messages — **do not call the provider**.
- Resolve via `providers.tool_provider(spec.provider)`. Unknown capability or method →
  `ErrorClass.UNKNOWN_TOOL` / `provider_error`, never an exception.
- Apply `spec.timeout_s` and the spec's `RetryPolicy`. Retry only classes listed in `retry_on`,
  and only when `spec.idempotent`, or when the failure was a connection-class failure that
  happened before any work. Never blind-retry a non-idempotent tool — say so in a comment.
- Redact args with `redact_args(args, spec.redact)` **before** they can reach an event.
- Truncate oversized result data (set `truncated=True`) and redact strings with `redact_text`.
- Providers must never raise for expected failure; if one does anyway, catch it and convert to
  `ToolResult.failure(ErrorClass.PROVIDER_ERROR, ...)` so a misbehaving provider cannot kill a run.

### `brain/tools/conformance.py`
```python
def run_suite(*, root: Path, provider: str | None = None, impl: str | None = None) -> int
def main(argv: Sequence[str] | None = None) -> int
```
Check what `CONTRACTS.md` section 7 promises: error taxonomy respected (return, don't raise),
`retain` idempotent, memory ids stable across recalls, redaction before emission, no blocking
beyond the declared timeout. Print a per-check pass/fail table; exit non-zero on failure.

## RULES
- Python 3.12, `from __future__ import annotations`, full type hints, docstrings explaining *why*.
- **stdlib + httpx only** in `brain/llm/*` and `brain/providers/llm/*`. No `groq` SDK (we need raw
  control over malformed responses and retries), no pydantic, no langchain.
- No `print()` outside the conformance CLI. No dead code, no unused imports.
- Inject `sleeper` rather than calling `time.sleep` directly, so retry tests run instantly and a
  test can assert the backoff sequence.
- Never log or embed a secret.

## DEFINITION OF DONE — run each and keep the real output
1. `python -c "import brain.llm.parsing, brain.llm.backoff, brain.tools.executor, brain.providers.llm.fake"` is clean.
2. `parse_tool_arguments` handles all of: valid JSON, fenced JSON, prose-wrapped JSON, single
   quotes, trailing commas, truncated JSON, empty string. Print the (input → parsed, error) table.
3. `compute_delay` with jitter disabled produces the expected monotonic sequence and clamps at
   `max_s`; with `retry_after_s` set it returns that value. Show the numbers.
4. `FakeLLM` drives a scripted malformed-then-corrected tool call, and `CallParser` is shown to
   walk `NATIVE_TOOLS → JSON_MODE` and return a valid call, reporting `strategy` and
   `repair_attempts`. Print the outcome.
5. `build_repair_prompt` output contains the validation error verbatim and the tool schema — show an excerpt.
6. `ToolExecutor` with a fake provider: a timeout is retried per policy, and a non-idempotent
   destructive tool is **not** retried. Show both.
7. `python -m brain.tools.conformance --provider memory --impl mock` runs and prints a table (it
   may fail if a peer's mock does not exist yet — if so, say exactly that).
8. Construct a `ToolResult` whose payload contains `"api_key=abcdef123456"` and show it comes out redacted.

Do not report success for anything you did not execute. Test `GroqClient` only against
`httpx.MockTransport` — never the live API.

## REPORT BACK (under 35 lines, plain text, no preamble)
Per-item status with trimmed real output. The parse table. The ladder walk. Every place you had to
guess at a peer's API and what you assumed. Anything you could not do. Files created with line counts.