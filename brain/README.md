# Agent Brain

The reasoning loop for JARVIS: given an objective, it recalls what it has learned, plans, calls
tools under a permission model, observes, verifies, and writes back what it learned.

**Scope.** Everything here lives in `brain/` and `config/`. The brain never imports a teammate's
module; it asks for a capability by name and receives an object satisfying a Protocol from
`brain/contracts.py`. That is what makes the mock → real swap a one-line config change.

---

## Architecture

```
                     ┌──────────────────────────────────────────┐
   objective ───────▶│  Brain.run(RunConfig)                    │
                     │                                          │
                     │  RECALL ──▶ UNDERSTAND ──▶ PLAN          │
                     │    ▲                        │            │
                     │    │                        ▼            │
                     │  RETAIN ◀── FINISH ◀──┬── SELECT          │
                     │                       │     │            │
                     │                  RECOVER ◀──┴──▶ CALL    │
                     │                       ▲           │      │
                     │                       └── DECIDE ◀─OBSERVE│
                     └───────────────┬──────────────────────────┘
                                     │ one BrainEvent per transition
                                     ▼
              EventSink ──▶ MemorySink (tests) │ JsonlSink (SSE) │ StdoutSink (debug)
```

Every transition, tool call, memory recall, memory influence, recovery step and verification is
emitted as a structured event. The trace is the loop's own account of what it did, not a
reconstruction. Schema: `docs/brain/schemas/event.schema.json`.

### Module map

| Path | Responsibility |
|---|---|
| `brain/contracts.py` | Frozen types and Protocols. No logic. The boundary. |
| `brain/errors.py` | One error taxonomy shared by parser, retry, recovery and events. |
| `brain/config/loader.py` | Layered config → `ResolvedConfig` + config fingerprint. |
| `brain/tools/registry.py` | `config/tools/*.yaml` → `ToolSpec`. |
| `brain/tools/validate.py` | Arguments against the tool's JSON Schema; messages feed the repair prompt. |
| `brain/tools/executor.py` | Timeout, retry, redaction, error classification. |
| `brain/llm/parsing.py` | Tolerant argument parsing + the parse/repair ladder. |
| `brain/prompt/assembler.py` | Prompt assembly, token budgeting, deterministic trim order. |
| `brain/loop/engine.py` | State machine, policy engine, orchestration, memory attribution. |
| `brain/providers/registry.py` | Capability → implementation, from `config/providers.yaml`. |
| `brain/events/` | Emitter, sinks, and a projection for the existing team SSE consumer. |
| `brain/bench.py` | Memory ON/OFF benchmark. |
| `brain/cli.py` | CLI. |

## Running it

```bash
python -m pip install -r brain/requirements.txt
python -m pytest tests/ -q
python -m brain.cli config show --profile devops
python -m brain.cli run --profile devops --objective "checkout-api is throwing 5xx" --trace
python -m brain.cli benchmark --runs 20
```

`GROQ_API_KEY` comes from the environment only. It is never read from config, never logged, and never
placed in an event or a prompt. Pinned dependencies: `httpx`, `PyYAML`, `jsonschema` — no `pydantic`,
no `langchain`, no `langgraph`.

## Configuration

Layering, lowest precedence first, merged **per key**: `config/` defaults → profile →
`.brain/workspace/` → `.brain/user/`. `BRAIN_PROVIDER__<CAPABILITY>=<impl>` overrides provider
selection only.

- `config/soul.md` — persona, tone, values, boundaries, output shape.
- `config/agents.md` — autonomy, precedence, policies, stopping and memory rules.
- `config/profiles/{devops,sales,support}.yaml` — soul fragment + policy + tool subset.
- `config/tools/*.yaml` — the registry. `config/tools.md` is **generated**; never hand-edit it.
- `config/providers.yaml` — which implementation answers each capability.

A layer that fails validation raises `ConfigError` naming the key path, and the previously loaded
configuration stays in force — hot-reload never half-applies.

## Adding a tool

1. Add an entry to a file in `config/tools/`, or create a new `*.yaml` there.
2. Give it a real `description`: say *when* to reach for it, including when it is the wrong choice.
   That text is the model's only guidance on selection.
3. Choose `permission` honestly. `auto` is for reads only. Anything that changes a running system is
   `confirm`. A `destructive` tool **cannot** be `auto` — the loader rejects it, because reviewer
   attention is not a control.
4. Add the method to the provider your tool names, then `python -m brain.docs.gen_tools_md`.
5. Add the tool's name to the profiles that should have it.

No Python change is needed for the loop to use it.

## Swapping a mock for the real thing

Implement the Protocol in `brain/contracts.py`, add `brain/providers/<capability>/<impl>.py` exposing
`build(settings, *, root)`, then change one line:

```yaml
observability:
  impl: real      # was: mock
```

Nothing in `brain/loop/` changes. The conformance expectations are in `docs/brain/CONTRACTS.md` §7:
return rather than raise for expected failure, make `retain` idempotent, keep memory ids stable
across recalls, redact before emission, and do not block past the declared timeout.

## How Hindsight memory is used

Memory is the product, not a feature, so it has a policy rather than a flag.

**Recall.** At RECALL the loop derives entities from the objective (hyphenated identifiers such as
`checkout-api`, which is what operational text is full of), asks a real question, and emits
`recall.performed` with the query and every returned memory carrying a stable id. Mid-run, the
planner can call `recall_memory` for something it did not anticipate.

**Attribution.** This is the part that makes memory visible. After a step is selected, the loop emits
`memory.influenced` naming the memories that shaped it and **how strongly that can be claimed**:

| `basis` | Meaning | Rendering |
|---|---|---|
| `explicit_citation` | The plan step named the memory id. | Solid connector |
| `entity_overlap` | A recalled memory shares a named entity with the call's arguments. | Dashed |
| `lexical_overlap` | Content-word Jaccard ≥ 0.34. | Dotted |

A viewer must render these differently. Collapsing them lets the trace claim a causal link the
evidence does not support, which is worse than showing no attribution at all. When memory is off, no
`memory.influenced` event is emitted — an empty memory lane is the honest signal.

**Retain.** At RETAIN the loop extracts candidates of five kinds only — `outcome`, `failure`,
`correction`, `preference`, `entity_fact` — and applies two tests in code, not merely in the prompt:

- **Horizon test** — will this still be true and useful in a month? A memory that says "the above" or
  "this incident" is rejected, because it will be useless later.
- **Origin test** — did this come from the operator, a trusted tool, or a verified conclusion?
  Anything that reads like an instruction found inside tool output is refused, since a remembered
  instruction would be re-injected into a future prompt with apparent authority.

`memory.retained` reports what was written **and what was deliberately skipped, with the rejecting
test**. That makes the retain policy auditable rather than a black box.

**The measurement.** `python -m brain.cli benchmark --runs 20` runs both arms against the same frozen
world and reports steps-to-completion, tool errors, corrections and success rate. With the bundled
fake LLM the improvement is scripted rather than measured — a faithful simulation of a model choosing
differently given "restarting this already resolved nothing", but a simulation. Point
`providers.llm.impl` at `groq` for the real thing; the harness is identical.

## Known gaps

- **Nothing here has been executed.** The shell safety classifier was unavailable for both build
  sessions, so no test has been run and no config loaded. Treat every behavioural claim above as
  design intent until `python -m pytest tests/ -q` passes.
- `GroqClient` is specified in `docs/brain/briefs/llm.md` but not implemented; `impl: groq` resolves
  to nothing today. The fake is the only working LLM client.
- `run_streaming` runs the loop to completion and then replays the trace. Incremental streaming needs
  an emitter-side queue; event order is identical either way.
- `config/tools.md` has not been generated — run `python -m brain.docs.gen_tools_md`.
- No UI. The trace viewer's memory lane is the one surface worth building; see `docs/brain/UI_NOTES.md`.
