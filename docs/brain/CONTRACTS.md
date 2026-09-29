# CONTRACTS — Agent Brain ↔ everything else

**Contract version: 1.0.0 — FROZEN.** Frozen at the start of the build so teammates can code
against it before the brain exists. Additive changes bump the minor; anything that renames,
removes or changes the meaning of an existing field bumps the major and requires consumer
sign-off. Schema files live in `docs/brain/schemas/` and are the authority; this document
explains them and must not contradict them.

Owner of this boundary: Nikunj (brain). Consumers: the SSE/streaming layer, the frontend
trace viewer, the Hindsight adapter owner, the tool-provider owners.

---

## 1. What the brain owns, and what it only consumes

The brain **owns**: the state machine, planning, tool selection and parsing, the prompt
assembler, policy and permission enforcement, recovery, stopping, events, and the memory
*policy* (what to retain, what to recall, and when).

The brain **consumes** through the interfaces in §3, and never imports a teammate module
directly:

| Capability | Owner | Our interface | Ships today as |
|---|---|---|---|
| Memory (Hindsight) | teammate | `MemoryProvider` | `MockMemory` |
| LLM (Groq) | teammate/infra | `LLMClient` | `FakeLLM`, `GroqClient` |
| Browser, terminal, filesystem | teammates | `ToolProvider` | `MockToolProvider` |
| Artifact storage | teammate | `ArtifactStore` | `FilesystemArtifacts` |
| SSE transport | teammate | `EventSink` | `MemorySink`, `JsonlSink` |
| Human approval | teammate/UI | `HumanProvider` | `ScriptedHuman` |
| Clock, ids | ours | `Clock`, `IdFactory` | system/uuid, or frozen/sequential |

**The swap rule.** Every one of these is selected by name in `config/providers.yaml`.
Changing `impl:` on one line is the entire mock→real migration. No brain source file changes,
and no teammate module is imported by name anywhere in `brain/`.

---

## 2. The event stream — the primary integration surface

Every transition and every observation is emitted as one `BrainEvent`. This is what the SSE
layer relays and what the trace viewer renders, and it is how a judge sees the agent think.

Machine-readable authority: `docs/brain/schemas/event.schema.json`.

### Envelope (every event)

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | `"1.0.0"`. Reject a major you do not know; do not guess. |
| `event_id` | string | Opaque, unique in the run. Never parse. |
| `run_id` | string | Opaque **string**, not an integer. |
| `seq` | integer | Monotonic from 0 within a run. Use for ordering and gap detection. |
| `ts` | string | RFC 3339 UTC. Frozen clock ⇒ identical across replays. |
| `type` | enum | 22 values, listed below. |
| `state` | enum\|null | The loop state at emission. |
| `step_id` | string\|null | The plan step, when one applies. |
| `data` | object | Type-specific. Validated by the schema's `allOf` branches. |

### Event types and what consumes them

| Type | Consumer's job |
|---|---|
| `run.started` | Render run header. Carries `memory_enabled` — the A/B toggle — and `config_fingerprint`. |
| `state.entered` | Advance the state-machine spine. `from`/`to`/`reason`. |
| `recall.performed` | Populate the **memory lane**. Carries the query and the returned memories with stable ids. |
| `understand.completed` | Show goal, success criteria, and `unknowns`. |
| `plan.created` / `plan.revised` | Render the plan; `revision` > 1 means a replan happened. |
| `step.selected` | Show the chosen tool and its rationale. |
| `policy.decided` | Show auto/confirm/deny and `reason_code`. This is the safety story. |
| `approval.requested` / `approval.resolved` | Drive the human-in-the-loop UI. |
| `tool.called` / `tool.result` / `tool.failed` | Show the call, its result, and its error class. |
| `observation.extracted` | Show what the result does *and does not* establish. |
| `memory.influenced` | **Draw the connector** from a memory to a step. See §2.1. |
| `recovery.started` | Show which rung of the ladder fired. |
| `budget.exhausted` | Show why the run stopped early. |
| `verification.performed` | Show the criteria checked before finishing. |
| `metric.updated` | Feed the learning-curve chart. |
| `run.finished` | Render the final report. |
| `memory.retained` | Show what the run wrote, **and what it deliberately refused to write**. |
| `error.raised` | Surface internal faults. |

### 2.1 `memory.influenced` — the field that carries the 25%

Memory centrality is 25% of the score and is invisible unless the trace attributes it. The
contract therefore requires every memory influence to be *typed by how it was established*:

- `explicit_citation` — the planner named the memory id in the step's `cites`. Strong claim,
  render as a solid connector.
- `entity_overlap` — a recalled memory shares a named entity with the step's arguments.
  Weaker, render as a dashed connector.
- `lexical_overlap` — content-word overlap only. Weakest, render as a dotted connector.

A viewer must render these differently. Collapsing them would let the trace overclaim, which
is worse than showing no attribution at all. When memory is off, no `memory.influenced`
event may be emitted — an empty memory lane is the honest signal, and the OFF/ON comparison
depends on it being truthful.

---

## 3. Typed interfaces

These are the seams. Full signatures live in `brain/contracts.py`; this is the summary a
consumer needs. Every one is a `typing.Protocol`, so an implementation is validated
structurally and a mock is a first-class citizen rather than a test double.

### `LLMClient`

```python
def complete(self, request: LLMRequest) -> LLMResponse: ...
```

`LLMRequest`: `messages`, `tools` (rendered JSON Schema), `tool_choice`, `response_format`,
`temperature`, `max_tokens`, `model`, `parallel_tool_calls`.
`LLMResponse`: `content`, `tool_calls: list[ToolCall]`, `finish_reason`, `model`,
`usage: TokenUsage`, `raw`.

`ToolCall` carries `call_id`, `name`, and **`arguments_raw: str`** alongside the parsed
`arguments`. The raw string is part of the contract on purpose: malformed-argument repair is
a scored requirement (R6), and a client that pre-parses and discards the raw text makes
repair impossible. `finish_reason` distinguishes `tool_calls`, `stop`, `length`, and
`content_filter` so the loop can treat a truncated response differently from a refusal.

Raises `LLMError` with a `class` from the shared taxonomy (§5) — never a bare exception.

### `MemoryProvider`

```python
def recall(self, query: RecallQuery) -> list[MemoryItem]: ...
def retain(self, items: list[MemoryItem]) -> RetainResult: ...
```

`RecallQuery`: `text`, `entities`, `kinds`, `limit`.
`MemoryItem`: `id`, `kind`, `text`, `entities`, `confidence`, `observed_at`, `source_run_id`,
`score`.
`RetainResult`: `written: list[str]`, `skipped: list[Skipped]`, `deduplicated: list[str]`.

`id` must be **stable across recalls** — `memory.influenced` points at it, and a provider that
mints a new id per query breaks attribution. `retain` must be idempotent per item: re-running
a completed run must not duplicate its memories, or the benchmark will drift upward on
replays.

### `ToolProvider`

```python
def invoke(self, method: str, args: dict[str, Any]) -> ToolResult: ...
```

`ToolResult`: `ok`, `data`, `error_class`, `error_message`, `duration_ms`, `truncated`,
`raw_bytes`.

Implementations must not raise for expected failure; return `ok=False` with an
`error_class`, so the recovery ladder can classify it. Raising is reserved for programmer
error. The brain — not the provider — applies the timeout and the retry policy, so a
provider must not retry internally.

### `HumanProvider`

```python
def confirm(self, request: ApprovalRequest) -> ApprovalDecision: ...
def ask(self, question: ClarificationRequest) -> ClarificationAnswer: ...
```

`ApprovalRequest` carries `tool`, `args`, `blast_radius`, `reversible`, `reversal_cost` — the
same fields the `approval.requested` event carries, so a UI can be built from the event alone
without a second call.

### `EventSink`

```python
def emit(self, event: BrainEvent) -> None: ...
```

Must not raise on a healthy sink, and must never block the loop for longer than the run
budget allows. A sink that fails should degrade to dropping events and record that on the
next `error.raised`, not abort a run in progress. Emission happens **before** the loop
continues, so the trace is causally ordered rather than merely timestamped.

### `Clock` / `IdFactory` / `ArtifactStore`

`Clock.now() -> datetime` (always timezone-aware UTC); `IdFactory.new(prefix) -> str`;
`ArtifactStore.write(name, data) -> str` / `read(ref) -> bytes`. The clock and id factory are
interfaces so that traces are byte-reproducible in tests and benchmarks.

---

## 4. Configuration contract

Layering, lowest precedence first, each layer overriding the one before **per key**:

1. `config/` defaults on disk
2. the selected profile — `config/profiles/<name>.yaml`
3. workspace override — `.brain/workspace/` (deployment-specific)
4. user override — `.brain/user/` (per-operator)

Environment overrides beat all four for provider selection only:
`BRAIN_PROVIDER__<CAPABILITY>=<impl>`.

Rules a consumer can rely on:

- **Fail loud, never half-apply.** A layer that fails schema validation is rejected with the
  offending key path, and the previously loaded good config stays in force. Hot-reload never
  leaves the brain in a partially-updated state.
- **Tools are additive by name, not by file.** A profile lists tool *names* in
  `tools.include`. Availability is a profile decision; permission is a tool decision; both
  must pass. A tool absent from the profile is unavailable regardless of its tier.
- **`config/tools.md` is generated, never hand-edited.** `brain/docs/gen_tools_md.py`
  regenerates it from the registry; a test asserts the committed file matches, so docs cannot
  drift from the registry.
- **`config_fingerprint`** in `run.started` is a hash of the resolved config, so any trace can
  be tied to the exact soul, policies and tool set that produced it.

---

## 5. Shared error taxonomy

One vocabulary, used identically by the parser, the retry policy, the recovery ladder and the
event stream. A consumer may switch on `error_class` without knowing which layer produced it.

| `error_class` | Retryable | Recovery rung |
|---|---|---|
| `timeout` | yes | retry |
| `rate_limited` | yes (with backoff) | retry |
| `provider_5xx` | yes | retry |
| `malformed_args` | no | repair |
| `validation` | no | repair |
| `unknown_tool` | no | substitute |
| `not_found` | no | replan |
| `permission` | no | escalate |
| `provider_error` | depends | substitute |

`malformed_args`, `validation` and `unknown_tool` are **model-output** failures and are the
ones the hackathon brief calls out. They must always be repaired and retried at least once
before the step is allowed to fail, and each repair attempt is visible in the trace.

---

## 6. HTTP surface (for the streaming layer)

If a teammate hosts the brain behind FastAPI, these are the shapes to build. The brain ships
them behind an optional extra so the core loop never depends on a web framework.

```
POST /runs                     -> { run_id, stream_url }
       body: { profile, objective, memory_enabled, autonomy?, budgets?, provider_overrides? }
GET  /runs/{run_id}/events     -> text/event-stream of BrainEvent (SSE)
       query: since_seq?  (replay from a sequence number after a reconnect)
GET  /runs/{run_id}            -> { run, metrics, plan, final }
GET  /runs/{run_id}/trace      -> the full event list, for the trace viewer
POST /runs/{run_id}/approvals/{request_id} -> { approved, answer? }
GET  /config                   -> resolved config + fingerprint
PUT  /config/{layer}/{key}     -> write a config layer, then hot-reload
POST /config/reload            -> force reload; returns validation errors or the new fingerprint
GET  /tools                    -> the registry as loaded (same data as config/tools.md)
POST /profiles/{name}/activate -> switch profile for subsequent runs
```

`GET /runs/{run_id}/events` must support `since_seq` so a reconnecting viewer can resume
without replaying a run from the beginning, and must send a heartbeat comment so proxies do
not close an idle stream.

---

## 7. What a teammate must do to go live

1. Implement the `Protocol` in §3 against your real system. Do not import or subclass brain
   code; structural typing is the whole point.
2. Add a module under `brain/providers/<name>.py` exposing a `build(settings) -> <Protocol>`
   factory.
3. Point `config/providers.yaml` at it: `impl: <name>`. One line.
4. Run `python -m brain.tools.conformance --provider <capability> --impl <name>` to check the
   contract behaves (this runs the same suite the mocks pass).
5. Only if you need a new *configuration* shape, open a contract change per §8.

Your implementation must satisfy the conformance suite, which covers: the error taxonomy
(return, never raise, for expected failure), idempotent retain, stable memory ids, redaction
before emission, and no blocking beyond the declared timeout.

---

## 8. Change protocol

Never change an implementation and update the contract afterwards.

1. Propose the consumer need and the compatibility impact.
2. Change the schema or `brain/contracts.py` first.
3. Review the diff with affected consumers.
4. Regenerate derived artifacts (`config/tools.md`, fixtures, any generated types).
5. Update implementations.
6. Run the conformance suite and the integration test.
7. Merge only when every affected side passes **against the same artifact**.

Additive changes (a new event type, a new optional field) are minor bumps and must keep old
consumers working. A consumer that ignores an unknown event `type` must not crash — skip
unknown types, do not fail the stream.
