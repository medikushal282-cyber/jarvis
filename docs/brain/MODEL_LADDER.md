# Groq model ladder — verified 2026-09-29

Every claim here was read from official Groq documentation on 2026-09-29. Unlike the earlier
`EXTERNAL_DOCS.md`, nothing in this file is inherited from a previous session or inferred.

Sources:
- https://console.groq.com/docs/models
- https://console.groq.com/docs/deprecations
- https://console.groq.com/docs/tool-use
- https://console.groq.com/docs/structured-outputs
- https://console.groq.com/docs/reasoning

---

## 1. Shutdown models — two are in the hackathon brief and are already dead

| Model | Shut down | Official replacement |
|---|---|---|
| `qwen/qwen3-32b` | 07/17/26 | `openai/gpt-oss-120b` |
| `qwen/qwen3.6-27b` | 09/14/26 | `qwen/qwen3.8-27b` |
| `llama-3.1-8b-instant` | 08/16/26 | `openai/gpt-oss-20b` |
| `llama-3.3-70b-versatile` | 08/16/26 | `openai/gpt-oss-120b` or `qwen/qwen3.6-27b` |
| `groq/compound`, `groq/compound-mini` | 09/21/26 | — |

The hackathon problem statement recommends `openai/gpt-oss-120b` and `qwen/qwen3-32b`. The second
has been shut down since 17 July 2026. Anyone following the brief literally is calling a model that
does not exist, which is why the brief's own warning — "make sure to have your agent ready to
handle function calling errors" — is load-bearing rather than decorative.

**Unresolved contradiction, recorded rather than smoothed over.** The deprecations page lists
`llama-3.3-70b-versatile` and `llama-3.1-8b-instant` as shut down on 08/16/26, i.e. in the past.
The models page still lists both under *production*. Two official pages disagree. The ladder below
therefore **avoids llama-3.x entirely** — building a fallback on a model the vendor's own docs
contradict each other about is not a risk worth taking for a two-day hackathon. If a `llama` rung is
wanted later, resolve this first by calling `GET https://api.groq.com/openai/v1/models`, which is
authoritative for the account in question.

## 2. The ladder

| Rung | Model | Why | Caveat |
|---|---|---|---|
| 1 | `openai/gpt-oss-120b` | Production on both pages; tool use; 131,072 ctx / 65,536 max out | **No parallel tool calls** |
| 2 | `openai/gpt-oss-20b` | Production; same family, so identical tool-calling and prompt-format semantics — a fallback that behaves like the primary is worth more than a larger unrelated model | **No parallel tool calls** |
| 3 | `qwen/qwen3.8-27b` | Only other model supporting tools *and* strict structured outputs; supports parallel tool calls | **Preview — Groq states these are "intended for evaluation purposes only" and "should not be used in production"** |

Rung 2 is deliberately the same family as rung 1. A fallback exists to survive a transient outage,
and a cross-family fallback changes tool-call formatting and argument style at exactly the moment
the system is already degraded. Rung 3 is a genuinely different implementation, kept last, and
flagged preview so a reader knows what they are relying on.

## 3. Hard constraints that shape the client

**Tools and structured outputs cannot be combined.** Verbatim from the structured-outputs page:
*"Streaming and tool use are not currently supported with Structured Outputs."*

The consequence for the parse ladder is specific, and the obvious implementation gets it wrong: the
`json_mode` rung **cannot** be "the same request plus `response_format`". It must be a **separate
call with `tools` omitted entirely**, asking for a JSON object that *describes* the call.
`LLMRequest.disable_native_tools` in the frozen contract exists for exactly this and nothing else.

**`reasoning_effort` for gpt-oss accepts exactly three values:** `low`, `medium`, `high`. Not
`none` (Qwen-only). Only `gpt-oss-20b`, `gpt-oss-120b` and `qwen3.8-27b` accept them at all. A config
passing anything else to a gpt-oss model is a 400 waiting to happen, so the value is validated as an
enum in the client rather than trusted.

**Parallel tool calls:**

| Model | Parallel tool use |
|---|---|
| `openai/gpt-oss-120b` | No |
| `openai/gpt-oss-20b` | No |
| `qwen/qwen3.8-27b` | Yes |
| `llama-3.3-70b-versatile` | Yes (but see the contradiction above) |

With the chosen ladder, rungs 1 and 2 cannot emit parallel calls but rung 3 can — so the loop must
handle N calls in one response regardless. It does; the cap is `max_parallel_calls`, applied by us
rather than assumed of the provider.

**Strict `json_schema` is supported only by** `gpt-oss-20b`, `gpt-oss-120b`, `qwen/qwen3.8-27b` —
and strict mode has requirements our tool schemas do not meet:

> every property must be listed in `required`, and every object needs `additionalProperties: false`;
> optional values are handled via union types with `"null"`, because fields cannot simply be omitted.

Our `config/tools/*.yaml` schemas use *partial* `required` lists (e.g. `search_logs` requires only
`service`) and rely on `additionalProperties: false` alone. That is correct and idiomatic for **tool
calling**, and it is **incompatible with `strict: true`**. The JSON-mode rung must therefore use
`response_format: {"type": "json_object"}` (best-effort) and must **not** attempt `json_schema` with
these schemas. If strict mode is ever wanted, the tool schemas need a generated strict variant with
null-unions — real work, not a flag flip.

## 4. How this is expressed in configuration

The ladder is a list, not a `primary`/`fallback` pair, in `config/providers.yaml`. A two-slot shape
would need reshaping the first time a third rung was wanted, and a list also lets the client degrade
deterministically rather than by special-casing.

A 404 or "model decommissioned" response advances to the next rung rather than failing the run, and
the rung that actually served the request is recorded in the response's `raw` so the trace shows it.
That behaviour turns a dead model ID from an outage into a degradation — and given that the
hackathon brief itself ships a dead model ID, it is worth having.
