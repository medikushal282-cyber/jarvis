# EXTERNAL_DOCS.md — Facts sheet for the Agent Brain

**Scope:** Groq API (native function calling), Hindsight by Vectorize (memory layer), Anthropic Messages API tool use (reference only).
**Compiled:** 2026-09-29. Sources are official docs unless a line says otherwise.
**Confidence tags:** `[VERIFIED-DOCS]` = read directly on an official doc page; `[INFERRED]` = derived by reasoning from verified facts; `[UNCERTAIN]` = plausible but not confirmed.

> **Headline finding, read this first:** the problem statement recommends `qwen/qwen3-32b`, but Groq **decommissioned that model on 2026-07-17** and the official replacement is `openai/gpt-oss-120b`. `openai/gpt-oss-120b` is also the model the Hindsight docs recommend as the extraction LLM. Do not build against `qwen/qwen3-32b`. See §A.4.

---

## FACTS WE DEPEND ON

### F1. Groq chat-completions tool-calling — request

Source: https://console.groq.com/docs/tool-use and https://console.groq.com/docs/api-reference — `[VERIFIED-DOCS]`

```json
{
  "model": "openai/gpt-oss-120b",
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user", "content": "What is the weather in SF?" }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
          "type": "object",
          "properties": {
            "location": { "type": "string", "description": "City and state" },
            "unit": { "type": "string", "enum": ["celsius", "fahrenheit"] }
          },
          "required": ["location"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "parallel_tool_calls": true,
  "max_completion_tokens": 4096
}
```

Exact parameter names and semantics — all `[VERIFIED-DOCS]` on the API reference page:

| Param | Type | Values / notes |
|---|---|---|
| `tools` | array | Each entry `{"type":"function","function":{"name","description","parameters"}}`. `parameters` is a **JSON Schema object**. |
| `tool_choice` | string \| object | `"none"`, `"auto"`, `"required"`, or `{"type":"function","function":{"name":"my_function"}}`. Defaults: `none` when no tools are present, `auto` if tools are present. |
| `parallel_tool_calls` | boolean | Defaults **`true`**. "Whether to enable parallel function calling during tool use." |
| `max_completion_tokens` | integer | Preferred. `max_tokens` still accepted but **deprecated in favor of `max_completion_tokens`**. |
| `reasoning_effort` | string | `none, default, minimal, low, medium, high, xhigh, max`. An unsupported value for a model is **rejected with a 400**. |
| `stream` | boolean | Defaults `false`. Data-only SSE, terminated by `data: [DONE]`. |
| `response_format` | object | See F3. |

### F2. Groq tool-calling — response and how to feed results back

Source: https://console.groq.com/docs/tool-use — `[VERIFIED-DOCS]`

Assistant response (non-streaming):

```json
{
  "role": "assistant",
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "get_weather",
        "arguments": "{\"location\": \"San Francisco, CA\", \"unit\": \"fahrenheit\"}"
      }
    }
  ]
}
```

Critical: `function.arguments` is a **JSON string**, not a nested object. It must be `json.loads()`-ed (and may fail — see G1).

Feeding the result back — append to `messages` and call the API again:

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "name": "get_weather",
  "content": "{\"temperature\": 72, \"condition\": \"sunny\"}"
}
```

Rules stated by the docs `[VERIFIED-DOCS]`:
- `tool_call_id` **must match the `id`** from the assistant's `tool_calls` entry.
- `content` "can be any string value" — different tools may return different data shapes, so serialise whatever your function returned into a string.
- If the assistant emitted **multiple** `tool_calls` (parallel), you must return **one `role: "tool"` message per call**, each carrying its own `tool_call_id`.
- The loop continues while the model keeps emitting `tool_calls`; it ends when the model returns a normal assistant message.

### F3. Groq JSON mode / structured outputs

Source: https://console.groq.com/docs/structured-outputs and https://console.groq.com/docs/api-reference — `[VERIFIED-DOCS]`

```json
// json_object mode — valid JSON syntax only, no schema compliance. Works on all models.
{ "response_format": { "type": "json_object" } }

// json_schema (structured outputs)
{ "response_format": { "type": "json_schema", "json_schema": { "name": "schema_name", "strict": true, "schema": { } } } }
```

- Strict schema support (`strict: true`): `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`.
- Best-effort (`strict: false`, the default): the same three plus `openai/gpt-oss-safeguard-20b`.
- **CANNOT be combined with tools.** The docs state verbatim: *"Streaming and tool use are not currently supported with Structured Outputs."* `[VERIFIED-DOCS]`
- Strict-mode schema requirements: every property must appear in `required`; all objects need `additionalProperties: false`; optional values are expressed as union types with `null` (e.g. `"type": ["string","null"]`) while still being listed in `required`. Supported: primitives, `object`, `array`, `enum`, `anyOf`, `$defs`/`$ref`.
- Best-effort failure surfaces as HTTP 400: `Generated JSON does not match the expected schema. Please adjust your prompt.` Strict mode is described as never producing invalid JSON.

### F4. Hindsight — REST endpoint paths

Source: https://hindsight.vectorize.io/openapi.json and https://hindsight.vectorize.io/llms.txt — `[VERIFIED-DOCS]`

All paths are prefixed `/v1/default/banks/{bank_id}`. The literal segment `default` is the tenant/namespace slot.

| Operation | Method + path | Confidence |
|---|---|---|
| Retain (store memory) | `POST /v1/default/banks/{bank_id}/memories` | `[VERIFIED-DOCS]` (listed in llms.txt endpoint list) |
| Recall (query memory) | `POST /v1/default/banks/{bank_id}/memories/recall` | `[VERIFIED-DOCS]` (openapi.json) |
| Reflect (LLM answer over memory) | `POST /v1/default/banks/{bank_id}/reflect` | `[VERIFIED-DOCS]` (openapi.json) |
| List banks | `GET /v1/default/banks?q=&limit=100&offset=0` | `[VERIFIED-DOCS]` (openapi.json) |
| Create bank | `POST /v1/default/banks` | `[VERIFIED-DOCS]` (llms.txt) |
| Poll async operation | `GET /v1/default/banks/{bank_id}/operations` | `[VERIFIED-DOCS]` |
| Observation scopes | `GET /v1/default/banks/{bank_id}/observations/scopes` | `[VERIFIED-DOCS]` |
| MCP endpoint | `http://localhost:8888/mcp/{bank_id}/` | `[VERIFIED-DOCS]` |

Auth header, from the curl samples on https://hindsight.vectorize.io/developer/api/memory-banks — `[VERIFIED-DOCS]`:

```
-H "Authorization: Bearer $API_KEY"
-H "Content-Type: application/json"
```

The OpenAPI spec declares `authorization` as an **optional** header param on each operation and defines no `securitySchemes` block — consistent with auth being optional self-hosted and required on Cloud. `[VERIFIED-DOCS]`

### F5. Hindsight — retain request/response

Source: https://hindsight.vectorize.io/developer/api/retain — `[VERIFIED-DOCS]`

```json
{
  "items": [
    {
      "content": "Alice works at Google",
      "document_id": "conv_123"
    }
  ],
  "async": true,
  "operation_id": "3f2b8c1a-9d4e-4a7b-9c2f-1e6d5a4b3c2d"
}
```

Item fields:

| Field | Type | Notes |
|---|---|---|
| `content` | string | **Only required field.** Stored facts are LLM-extracted from this, not stored verbatim. |
| `timestamp` | string \| null | ISO 8601, e.g. `"2024-01-15T10:30:00Z"`. Omit/null = ingestion time; `"unset"` = store with no timestamp. |
| `context` | string | Short source label (e.g. `"team meeting"`); injected into the extraction prompt. |
| `metadata` | object (string values) | e.g. source, channel, thread_id. A `null` value drops the key. |
| `document_id` | string | Groups items into a document; enables upsert/idempotency. Omitted = random UUID per request. |
| `update_mode` | enum | `"replace"` (default) or `"append"`. `append` requires a `document_id`. |
| `entities` | array | Each `{"text": string, "type": "PERSON"｜"ORG"｜"CONCEPT"}`; type defaults `"CONCEPT"`. |
| `resolve_entities` | boolean | `false` keeps caller-supplied names exact. |
| `tags`, `document_tags` | array of strings | Visibility scoping used for recall filtering. |
| `observation_scopes` | string or array | Presets `"combined"`, `"shared"`, `"per_tag"`, `"all_combinations"`, `"custom"`, or explicit scope lists. |

Top-level: `async` (boolean, returns immediately), `operation_id` (UUID, caller-supplied for safe retries).

Sync response: `success`, `bank_id`, `items_count`, `async`, `usage{input_tokens, output_tokens, total_tokens}`. Usage is present **only** for synchronous calls.

### F6. Hindsight — recall request/response

Source: https://hindsight.vectorize.io/developer/api/recall — `[VERIFIED-DOCS]`

```json
{ "query": "What does Alice do?" }
```

Request fields: `query` (required; **queries exceeding 500 tokens are rejected**), `types` (`world`｜`experience`｜`observation`, omitted = all three), `prefer_observations` (opt-in, default off), `budget` (`low`｜`mid`(default)｜`high`), `max_tokens` (default `4096`; `0` = return chunks only), `query_timestamp` (ISO 8601 anchor for relative time), `temporal_window{start,end}`, `include{chunks, source_facts, entities}`, `tags` + `tags_match` (`any`(default)｜`any_strict`｜`all`｜`all_strict`｜`exact`), `tag_groups`, `trace`, `min_scores{semantic, keyword, reranker, final}`.

There is **no metadata filter parameter** on recall — `metadata` only appears as a returned field.

Response: `results[]` where each entry has `id`, `text`, `type`, `context`, `metadata`, `tags`, `entities`, `occurred_start`, `occurred_end`, `mentioned_at`, `document_id`, `chunk_id`, `source_fact_ids`, `scores{final, reranker, semantic, keyword}`. Top-level also returns `source_facts`, `source_facts_truncated`, `chunks`, `entities`, `trace`.

Scores are described as **relative signals within a single query**, not absolute cross-query confidence. Any score may be `null` when that retrieval arm did not surface the fact.

### F7. Hindsight — Python SDK

Source: https://hindsight.vectorize.io/sdks/python and https://github.com/vectorize-io/hindsight — `[VERIFIED-DOCS]`

```bash
pip install hindsight-client -U
```

```python
from hindsight_client import Hindsight

client = Hindsight(base_url="http://localhost:8888", timeout=30.0, api_key="hsk_...")
```

Documented signatures:

```python
retain(bank_id, content, context, timestamp, document_id, metadata, retain_async=False)
retain_batch(bank_id, items, document_id, retain_async=False)   # items: list of {content, context}
recall(bank_id, query, types, max_tokens=4096, budget, include_chunks=True, max_chunk_tokens=500)
reflect(bank_id, query, budget, context)
create_bank(bank_id, name, mission, disposition)
list_memories(bank_id, type, search_query, limit, offset)
get_version()   # -> .api_version, .features.mcp
```

- `recall` returns a `RecallResponse`; read `response.results` (each has `.text`, `.type`, `.chunk_id`) and `response.chunks` (dict keyed by chunk id).
- `reflect` result exposes `.text`.
- Every method has an `a`-prefixed async counterpart: `aretain`, `arecall`, `areflect`, `aclose`.
- Context-manager form is supported: `with Hindsight(base_url=...) as client:`.
- `pub` packages: `hindsight-client` (HTTP client, needs a running server), `hindsight-all` (embedded, no server; Intel Macs use `hindsight-all-slim`), `hindsight-api` (run the server), `hindsight-litellm`.
- Node: `npm install @vectorize-io/hindsight-client`. Go: `go get github.com/vectorize-io/hindsight/hindsight-clients/go`.

**SDK vs REST divergence — stated explicitly:** the SDK pages document method signatures only; the REST pages document JSON only. They agree on field semantics but the SDK renames things (`retain_async` ↔ REST `async`). Also, the SDK page **does not name any environment variable** the client reads; `api_key` is shown only as an explicit constructor argument, while the **CLI** documents `HINDSIGHT_API_URL` / `HINDSIGHT_API_KEY`. Assume the SDK requires explicit arguments unless you verify otherwise.

### F8. Hindsight — Cloud vs self-hosted, auth, env vars

Sources: https://hindsight.vectorize.io/sdks/cli and https://github.com/vectorize-io/hindsight — `[VERIFIED-DOCS]`

| Thing | Value |
|---|---|
| Self-hosted API base URL | `http://localhost:8888` (UI/control plane on `http://localhost:9999`) |
| Cloud base URL | `https://api.hindsight.vectorize.io` |
| Cloud signup | `https://ui.hindsight.vectorize.io/signup` |
| Cloud API key format | starts with `hsk_` |
| Auth header | `Authorization: Bearer <key>` |

Environment variables — split by which process reads them:

- **Client / CLI:** `HINDSIGHT_API_URL`, `HINDSIGHT_API_KEY`, `HINDSIGHT_PROFILE` (named profile at `~/.hindsight/cli-profiles/<name>.toml`). Env vars take highest priority and always override profile values.
- **Server (self-hosted):** `HINDSIGHT_API_LLM_API_KEY`, `HINDSIGHT_API_LLM_PROVIDER` (e.g. `openai`, `anthropic`, `ollama`, `litellm`), `HINDSIGHT_DB_PASSWORD`, `HINDSIGHT_API_WORKER_ID`, plus `OPENAI_API_KEY` in the quickstart's setup flow.

Self-host, docker one-liner (from the repo README): ports `8888` (API) and `9999` (UI), image `ghcr.io/vectorize-io/hindsight:latest`, mounting `hindsight-data`. Compose path: `cd docker/docker-compose && docker compose up` with `HINDSIGHT_DB_PASSWORD` set. Helm: `oci://ghcr.io/vectorize-io/charts/hindsight`.

Promo/credits flow (source: the hackathon problem statement, **not** a vendor doc — `[UNCERTAIN]` as to mechanics): promo code `MEMHACK99` gives $50 in free credits on Hindsight Cloud, applied **after** registering, in the **billing** section.

### F9. Hindsight — data model and recall ranking

Sources: https://hindsight.vectorize.io/ (overview) and the retain/recall pages — `[VERIFIED-DOCS]`

- **Bank** = isolated memory namespace. All three operations are scoped to a `bank_id`. Banks auto-create on write; **reads of a missing bank return `404`, not empty results**.
- **Memory types**, in the order `reflect` consults them (Mental Models → Observations → Raw Facts):
  - `world` — objective facts received (e.g. "Alice works at Google")
  - `experience` — the bank's own actions/interactions (e.g. "I recommended Python to Bob")
  - `observation` — automatically consolidated knowledge from facts
  - mental model — user-curated summaries for common queries
- **Recall ranking ("TEMPR")**: four parallel retrieval arms — Semantic, Keyword BM25, Graph (entities/indirect connections), Temporal — fused with Reciprocal Rank Fusion `Σ 1/(60 + rank)`, then a cross-encoder that reads query+memory, then boosts for recency/time/proof, and finally a token budget controlled by `max_tokens`.
- **Bank configuration** (Mission, Directives, Disposition) affects **only `reflect`, not `recall`**.
- **Limits found:** recall query > 500 tokens rejected; `max_tokens` default 4096; reflect with **no evidence gathered fails with a 500** rather than answering.
- Rate limits / quotas for Hindsight Cloud: **not documented on any page I could read — `UNVERIFIED`.**

### F10. Anthropic Messages API tool use — REFERENCE ONLY

**We are NOT using Anthropic's API.** This section exists only to harvest interface-design lessons. Sources: the bundled Claude API skill (`shared/tool-use-concepts.md`, language `README.md`/`tool-use.md`) and https://docs.anthropic.com.

```json
{
  "model": "claude-opus-5-5",
  "max_tokens": 1024,
  "tools": [
    {
      "name": "get_weather",
      "description": "Get current weather for a location",
      "input_schema": {
        "type": "object",
        "properties": { "location": { "type": "string" } },
        "required": ["location"],
        "additionalProperties": false
      },
      "strict": true
    }
  ],
  "tool_choice": { "type": "auto" }
}
```

Response — tool use arrives as a **content block**, and `input` is a **parsed object**, not a string:

```json
{ "role": "assistant", "content": [
  { "type": "tool_use", "id": "toolu_01A...", "name": "get_weather", "input": { "location": "SF" } }
],
  "stop_reason": "tool_use" }
```

Tool result is sent back as a `tool_result` block inside a **user** message:

```json
{ "role": "user", "content": [
  { "type": "tool_result", "tool_use_id": "toolu_01A...", "content": "72F sunny", "is_error": false }
] }
```

Documented reasons a tool call can fail, and the design responses:

| Failure | How Anthropic's design handles it |
|---|---|
| Malformed / unparseable input | `strict: true` on the tool definition constrains decoding so `input` always validates. Without it, you must validate yourself. |
| Schema mismatch | Same — `strict` requires `additionalProperties: false` + `required` on every object. |
| Unknown tool | The API validates against the declared tool set; if you drive the loop, your dispatcher raises an unknown-tool error. |
| Tool ran but failed | Return the `tool_result` with **`is_error: true`** and a readable message — do **not** drop the block. The model then sees the failure and can adapt. |
| JSON escaping variance | Tool input JSON escaping may vary; always `json.loads()`, **never** string-match the serialised input. |

Design lessons to port to our Groq brain `[INFERRED]`:
1. A **strictness flag per tool** (Groq has no per-tool `strict`; the nearest analogue is `strict: true` structured outputs, which is incompatible with tools — so we must validate ourselves).
2. An **explicit error channel** so the model sees tool failure rather than silence. Groq's `role: "tool"` `content` is a free string, so we can encode `{"error": "..."}` inside it.
3. **Batch parallel results into one turn** — Anthropic's docs warn that splitting parallel results across messages trains the model out of parallel calls.
4. **Never string-match tool arguments.**
5. **Forced tool choice is fragile** — Anthropic removed `tool_choice: any`/`tool` on its newest models (returns 400); Groq still documents `"required"`, but treat forced choice as a fallback path, not the default.

---

## A) Groq API — function/tool calling (detail)

### A.1 Consumption patterns
The docs describe three patterns `[VERIFIED-DOCS]`: **built-in tools** (executed on Groq servers — only `openai/gpt-oss-20b` / `openai/gpt-oss-120b` support these; includes browser search and code execution), **remote MCP** (URL + auth headers, Groq orchestrates, one round trip), and **local function calling** (we supply definitions *and* implementations and run the 2+-call loop ourselves). Our Brain uses **local function calling**.

### A.2 Streaming
`stream: true` sends "partial message deltas" as data-only server-sent events, ending with a `data: [DONE]` message `[VERIFIED-DOCS]`. **The chunk-level `delta.tool_calls` sub-schema is NOT documented on any Groq page I could retrieve** (see Open Questions). Non-streaming is the safe default for the hackathon.

### A.3 Errors and rate limits
Source: https://console.groq.com/docs/errors and https://console.groq.com/docs/rate-limits — `[VERIFIED-DOCS]`

Error body shape — note there is **no documented `code` field**:

```json
{ "error": { "message": "String - description of the specific error", "type": "invalid_request_error" } }
```

Status codes: `200`, `206` (partial content), `400` (parse failure), `401` (missing/invalid credentials), `403` (permission), `404`, `413` (request entity too large — **reduce body size**), `422` (well-formed but semantically invalid, e.g. model hallucination — "verify data or retry"), `424` (dependent request failed — seen with Remote MCP auth), `429`, `498` (Groq custom: Flex Tier capacity exceeded), `499` (Groq custom: request cancelled, logs only), `500`, `502`, `503`. Groq states you are **not billed** for 5xx.

Rate-limit headers:

| Header | Meaning |
|---|---|
| `retry-after` | seconds; **present only on a 429** |
| `x-ratelimit-limit-requests` / `-remaining-requests` / `-reset-requests` | **always Requests Per Day (RPD)** |
| `x-ratelimit-limit-tokens` / `-remaining-tokens` / `-reset-tokens` | **always Tokens Per Minute (TPM)** |

All headers other than `retry-after` are always included. Limits apply at the **organization level, not per user**, and cached tokens are excluded from counting. Free-tier `openai/gpt-oss-120b`: **30 RPM, 1K RPD, 8K TPM, 200K TPD**. Some orgs get split ITPM/OTPM caps. The docs warn that a burst of requests can exhaust the RPM long before TPM is touched (50 requests × 100 tokens = RPM 50).

Retry guidance in the docs is qualitative only — honour `retry-after` on 429 and "wait before retrying" on 503; **no numeric backoff schedule is documented** `[VERIFIED-DOCS]`.

### A.4 The two models

| Model | Context | Max output | Tool use | Parallel tool calls | JSON mode | Structured outputs | Reasoning |
|---|---|---|---|---|---|---|---|
| `openai/gpt-oss-120b` | 131,072 | 65,536 | Yes | **No** | Yes | Yes (strict) | low/medium/high, default **medium** |
| `qwen/qwen3-32b` | — | — | — | — | — | — | **DECOMMISSIONED 2026-07-17** |
| `qwen/qwen3.8-27b` (current Qwen, preview) | 131,072 | 16,384 | Yes | **Yes** | Yes | Yes (strict) | `none` default; low/medium/high |
| `qwen/qwen3.6-27b` | 131,072 | — | Yes | Yes | Yes | — | **DECOMMISSIONED 2026-09-14** |

All rows `[VERIFIED-DOCS]` from https://console.groq.com/docs/deprecations, https://console.groq.com/docs/models, https://console.groq.com/docs/tool-use and the per-model page https://console.groq.com/docs/model/openai/gpt-oss-120b.

**Model-specific caveats that matter to us:**

1. **`qwen/qwen3-32b` is gone.** Deprecated row: `qwen/qwen3-32b` → shutdown `07/17/26` → recommended replacement `openai/gpt-oss-120b`. `[VERIFIED-DOCS]` Any code targeting it will 404/400.
2. **`openai/gpt-oss-120b` does NOT support parallel tool calls.** The tool-use table's "Parallel Tool Use Support?" column answers **No** for `openai/gpt-oss-20b`, `openai/gpt-oss-120b` and `openai/gpt-oss-safeguard-20b`. Combined with `parallel_tool_calls` defaulting to `true`, set `parallel_tool_calls: false` explicitly for this model. `[VERIFIED-DOCS]`
3. **`openai/gpt-oss-120b` does support built-in tools** (browser search, code execution) — the only production models that do. `[VERIFIED-DOCS]`
4. **Reasoning control is `reasoning_effort`** with `low`/`medium`/`high` (default `medium`) for the gpt-oss models. Note a documentation inconsistency: the API reference documents this fully, while the per-model page only says "variable reasoning modes (low, medium, high)" and never names the parameter. `[VERIFIED-DOCS]` with the inconsistency noted.
5. **Harmony chat format.** The model page's best-practices list says to "Follow the Harmony chat format with the role hierarchy System > Developer > User > Assistant" and to "Define tools clearly when using browsing, Python execution, or function calling." `[VERIFIED-DOCS]` The implication that gpt-oss emits a separate `analysis` channel which can interleave with tool calls if the serving path is not Harmony-aware is `[INFERRED]` — Groq's API abstracts this when you use the OpenAI-compatible endpoint, but it is a plausible source of the "function calling errors" the problem statement warns about.
6. **Preview models are "intended for evaluation purposes only."** `qwen/qwen3.8-27b` is a preview model. `[VERIFIED-DOCS]`

### A.5 Not documented by Groq
Groq's docs contain **no** guidance on malformed JSON arguments, markdown-fenced arguments, prose-wrapped arguments, or model behaviour under `tool_choice: "required"`. See Gotchas G1 and Open Questions.

---

## B) Hindsight (Vectorize) memory (detail)

### B.1 The three operations
`retain()` stores, `recall()` searches, `reflect()` reasons over memory with an LLM. All are scoped to a **bank** (`bank_id`). For recall, "every arm that applies runs" — no search type is pre-selected per query. `[VERIFIED-DOCS]`

### B.2 Retain semantics worth knowing
- `content` is **LLM-extracted**, not stored verbatim. What you get back from recall is extracted facts, not your raw string. `[VERIFIED-DOCS]`
- `context` is injected into the extraction prompt — use it to steer extraction quality. `[VERIFIED-DOCS]`
- `document_id` gives you **upsert/idempotency**: with `update_mode: "append"` you can grow one document across many calls. `[VERIFIED-DOCS]`
- `operation_id` lets you retry safely: reusing an id returns the original operation; reusing it with conflicting content returns **409**. `[VERIFIED-DOCS]`
- `async: true` returns immediately with an `operation_id` and **omits usage metrics**. Poll with `GET /v1/default/banks/{bank_id}/operations`. `[VERIFIED-DOCS]`

### B.3 Reflect
Request fields: `query` (only required field), `budget` (`low` default, `mid`, `high`), `max_tokens` (default 4096), `response_schema` (JSON Schema with non-empty `properties`), `tags`/`tag_groups`, `include.facts`, `include.tool_calls`, `reflect_search_observations_max_tokens` (default 5000), `reflect_search_observations_include_entities` (default true). Response: `text`, `structured_output`, `structured_output_error`, `based_on{memories, mental_models, directives}`, `usage`, `trace`. A run that gathers no evidence **fails with a 500**. `[VERIFIED-DOCS]`

### B.4 Serving LLM requirement
Hindsight requires an LLM that supports **structured output**, and the docs recommend **Groq with `gpt-oss-20b`** for speed/cost. Note this is the *self-hosted server's* extraction model — unrelated to our Brain's tool-calling model, but convenient: one provider key covers both. `[VERIFIED-DOCS]`

---

## Gotchas & edge cases

1. **`qwen/qwen3-32b` no longer exists.** Decommissioned 2026-07-17; replacement is `openai/gpt-oss-120b`. A hardcoded model string is an immediate 400/404. `[VERIFIED-DOCS]`
2. **`function.arguments` is a STRING, not an object.** `json.loads()` it, and wrap that call in try/except — a malformed-arguments error is exactly the failure mode the problem statement warns about. Groq does not document this failure mode, so we must defend against it blind. `[VERIFIED-DOCS]`
3. **You cannot use `response_format` (strict structured outputs) and `tools` at the same time.** Groq says so explicitly. If you want typed tool arguments, you must validate them yourself in Python (pydantic) — there is no server-side guarantee. `[VERIFIED-DOCS]`
4. **`parallel_tool_calls` defaults to `true`, but `openai/gpt-oss-120b` does not support parallel calls.** Set it to `false` explicitly for that model, and still write a loop that can handle N tool calls, because the request can be validated-then-ignored. `[VERIFIED-DOCS]`
5. **Every `tool_calls` entry needs its own `role: "tool"` reply with a matching `tool_call_id`.** Reply for only the first call, or drop one, and the next request is malformed. `[VERIFIED-DOCS]`
6. **Rate limits are org-level and RPM bites before TPM.** Under hackathon load across a team you can exhaust the 30 RPM free-tier limit while using almost no tokens. Read `x-ratelimit-remaining-requests` (RPD) and `x-ratelimit-remaining-tokens` (TPM) — they are not the same window — and honour `retry-after` on 429. `[VERIFIED-DOCS]`
7. **The Groq error body has no `code` field** — only `message` and `type`. Do not write `error["code"]` in your handler; it will raise KeyError while you are handling an error. `[VERIFIED-DOCS]`
8. **`max_tokens` is deprecated in favour of `max_completion_tokens`.** `[VERIFIED-DOCS]`
9. **`reasoning_effort` values are model-specific and rejected with a 400.** Do not send `qwen`-style values (`none`, `minimal`, `xhigh`) to gpt-oss, which accepts only `low`/`medium`/`high`. `[VERIFIED-DOCS]`
10. **Hindsight recall rejects queries over 500 tokens.** Long conversational turns pasted straight into `recall(query=...)` will fail. Truncate or summarise first. `[VERIFIED-DOCS]`
11. **Hindsight reading a missing bank returns 404, not empty results.** Initialise banks before first read, or treat 404 as "no memories yet" explicitly. Writes auto-create, reads do not. `[VERIFIED-DOCS]`
12. **`async: true` on retain returns no usage metrics, and reflect with no evidence returns 500.** Both break naive "call and read the field" code. `[VERIFIED-DOCS]`
13. **Recall has no metadata filter parameter** — only `tags` / `tag_groups`. If you want to scope recall by, say, `session_id`, put it in `tags`, not `metadata`. `[VERIFIED-DOCS]`
14. **Two different env-var namespaces.** Client-side (`HINDSIGHT_API_URL`, `HINDSIGHT_API_KEY`) is not the same as server-side (`HINDSIGHT_API_LLM_API_KEY`, `HINDSIGHT_API_LLM_PROVIDER`). Setting the wrong one silently falls back to `http://localhost:8888`. `[VERIFIED-DOCS]`
15. **The Python SDK page names no env vars.** Pass `base_url` and `api_key` explicitly to `Hindsight(...)`; only the CLI documents reading `HINDSIGHT_API_URL`/`HINDSIGHT_API_KEY`. `[VERIFIED-DOCS]`
16. **Groq 422 is not a validation error** — the docs describe it as a semantically-valid but model-hallucinated result and suggest retrying. A retry loop keyed only on 429/5xx will give up on a recoverable case. `[VERIFIED-DOCS]`
17. **Groq 424 appears with Remote MCP auth failures** — a distinct code you will not see with plain local function calling. `[VERIFIED-DOCS]`
18. **Hindsight recall scores are relative, not absolute.** Do not threshold on `scores.semantic` across different queries as if it were a confidence value; scores may also be `null` when an arm did not fire. `[VERIFIED-DOCS]`

---

## Open questions / could not verify

- **UNVERIFIED — Groq streaming tool-call deltas.** I could not retrieve a page documenting the streamed chunk shape for `tool_calls` (whether deltas carry `index`/`id`/`function.name`/`function.arguments` fragments, how to accumulate them, or that `finish_reason` is `"tool_calls"`). The Groq API reference page I fetched was truncated before the chunk schema, and the streaming docs do not cover tool use. Groq's API is OpenAI-compatible, so the OpenAI delta shape is the likely pattern, but **I am not asserting it**. Recommendation: use non-streaming tool calls.
- **UNVERIFIED — how `openai/gpt-oss-120b` fails on malformed arguments.** Groq documents no behaviour for malformed JSON, markdown-fenced JSON, or prose-wrapped JSON in `function.arguments`. Empirical testing is the only way to answer this. This is the single largest unknown for the "handle function calling errors" requirement.
- **UNVERIFIED — `tool_choice: "required"` behaviour per model.** The parameter and its `"required"` value are documented, but no model-specific behaviour or caveats are given.
- **UNVERIFIED — Hindsight Cloud rate limits, quotas, and pricing.** No page I could read documents request limits, per-bank caps, or what $50 of credits buys. Sign up and read the billing page in the console.
- **UNVERIFIED — Hindsight Cloud API-key creation flow.** Signup URL is known (`https://ui.hindsight.vectorize.io/signup`) and the key prefix is `hsk_`, but no doc page describes the console step to mint a key.
- **UNVERIFIED — the retain endpoint's exact OpenAPI operation.** `POST /v1/default/banks/{bank_id}/memories` comes from the docs' endpoint list; the OpenAPI JSON I could retrieve was truncated before the retain operation. Treat the path as high-confidence but re-confirm against `https://hindsight.vectorize.io/openapi.json` if a call 404s.
- **UNVERIFIED — Hindsight `RetainRequest` / `RecallRequest` schema *names* and required-vs-optional distinction in OpenAPI.** The spec references `#/components/schemas/RetainRequest` and `RecallRequest`, but the `components` section was truncated in every fetch. Field lists above come from the prose/SDK pages, which are authoritative for names but do not mark which fields are required beyond `content`/`query`.
- **UNVERIFIED — whether the `hindsight-client` Python SDK reads `HINDSIGHT_API_URL` / `HINDSIGHT_API_KEY`.** The CLI does; the SDK page does not say. Pass explicitly.
- **UNVERIFIED — Hindsight bank "name" field.** The memory-banks page documents `bank_id` but states a bank `name` is not documented for the bank itself, while `create_bank(bank_id, name, mission, disposition)` takes one in the SDK. Reconcile empirically.
- **UNVERIFIED — exact SDK version numbers.** I did not read a changelog or PyPI page for either SDK, so I cannot justify a specific version bound (see below).
- **[UNCERTAIN] — the promo code mechanics.** `MEMHACK99` / $50 credits is from the hackathon problem statement, not a vendor page. The statement says it is applied after registration, in the billing section.
- **[UNCERTAIN] — Groq free-tier numbers.** The published table I read is the Free plan. Developer-plan limits were not in the page content; check https://console.groq.com/settings/limits for your actual org.

---

## Minimal pinned dependency list (Python)

Package **names** below are `[VERIFIED-DOCS]`. **Version constraints could not be justified** — I did not read a changelog, release page, or PyPI page for any of these, so every constraint is marked and should be replaced by an exact pin from `pip index versions <pkg>` at install time.

```
# --- required ---
groq>=0.9,<1.0          # [UNCERTAIN version] official Groq Python SDK. Docs use the OpenAI-compatible
                        # client surface; the api-reference examples are chat.completions.create-style.
hindsight-client         # [VERIFIED name] official Hindsight HTTP client (`pip install hindsight-client -U`).
                        # [UNCERTAIN version] no version documented. Needs a running Hindsight server.

# --- strongly recommended ---
pydantic>=2,<3          # [INFERRED] required to validate tool arguments ourselves, since Groq
                        # structured outputs cannot be combined with tools.
python-dotenv>=1.0      # [INFERRED] load GROQ_API_KEY / HINDSIGHT_API_KEY / HINDSIGHT_API_URL.
httpx>=0.27             # [INFERRED] raw-REST fallback for Hindsight endpoints the SDK does not expose
                        # (e.g. GET /operations), and for reading rate-limit headers on Groq.
tenacity>=8.2           # [INFERRED] retry/backoff. Groq documents no backoff schedule, so we own it:
                        # honour `retry-after` on 429, retry 5xx and 422, never retry 400/401/403/413.

# --- optional ---
hindsight-all           # [VERIFIED name] embedded Hindsight, no server. Intel Macs: hindsight-all-slim.
hindsight-api           # [VERIFIED name] run the Hindsight server locally (`hindsight-api`).
```

Never pin `qwen/qwen3-32b` in a model list — it is decommissioned `[VERIFIED-DOCS]`.

---

## Source index

- Groq tool use — https://console.groq.com/docs/tool-use
- Groq tool use overview — https://console.groq.com/docs/tool-use/overview
- Groq API reference — https://console.groq.com/docs/api-reference
- Groq models — https://console.groq.com/docs/models
- Groq model page, gpt-oss-120b — https://console.groq.com/docs/model/openai/gpt-oss-120b
- Groq structured outputs — https://console.groq.com/docs/structured-outputs
- Groq errors — https://console.groq.com/docs/errors
- Groq rate limits — https://console.groq.com/docs/rate-limits
- Groq deprecations — https://console.groq.com/docs/deprecations
- Hindsight overview — https://hindsight.vectorize.io/
- Hindsight quick start — https://hindsight.vectorize.io/developer/api/quickstart
- Hindsight retain — https://hindsight.vectorize.io/developer/api/retain
- Hindsight recall — https://hindsight.vectorize.io/developer/api/recall
- Hindsight reflect — https://hindsight.vectorize.io/developer/api/reflect
- Hindsight memory banks — https://hindsight.vectorize.io/developer/api/memory-banks
- Hindsight Python SDK — https://hindsight.vectorize.io/sdks/python
- Hindsight CLI — https://hindsight.vectorize.io/sdks/cli
- Hindsight OpenAPI — https://hindsight.vectorize.io/openapi.json
- Hindsight llms.txt — https://hindsight.vectorize.io/llms.txt
- Hindsight repo — https://github.com/vectorize-io/hindsight
- Anthropic tool use (reference only) — https://docs.anthropic.com (see `shared/tool-use-concepts.md` in the bundled Claude API skill)
- Local (non-vendor): `HackwithHyderabad 3.0 Problem Statament.txt` — model recommendation, promo code, quoting the function-calling-error warning.
