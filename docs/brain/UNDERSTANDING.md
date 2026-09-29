# UNDERSTANDING — the task, the scope, the gaps

Written after Step 0. The problem statement had been read in full by the orchestrator, so rules and
judging were analysed directly rather than delegated; a subagent would have duplicated work. The
freed slot went to the external-docs analyst, which researches live APIs nobody can guess.

## The task, in my words

Build an agent that, given an objective from a working professional, decides *what to do next* —
recalls what it already knows, plans, chooses tools, calls them, reads the results, decides whether
it is done, recovers when it is not, and writes back what it learned. The judged property is not that
it works once but that it **improves across runs because it remembers**. Memory is 25% of the score
and is the only criterion that is invisible unless the system volunteers evidence for it.

Constraints that shaped the design: Hindsight is required as the memory layer; Groq is the LLM and
the brief explicitly warns that function-calling errors must be handled; the use case must be a real
business workflow, not a student tool.

## Scope

**In scope (mine).** `config/soul.md`, `config/agents.md`, `config/tools/*.yaml`,
`config/profiles/*.yaml`, the agent identity, the state machine, planning, the reasoning loop, tool
selection and parsing, multi-step decisions, retry and recovery, stopping conditions, agent policies,
and the architecture connecting them.

**Out of scope (teammates own; consumed via interfaces).** Hindsight, OKF, browser, terminal,
filesystem, STT, TTS, SSE transport, artifact storage. Each has a typed Protocol in
`brain/contracts.py` plus a mock adapter, so the brain runs end to end before any of them ships.

## Interfaces found in the friend's repo

From `REPO_MAP.md`. The repo is a real, working system with real defects, and it is an interface
reference only — its root is cluttered and its `soul.md` / `tools.md` are auto-generated placeholders
containing the user's own prompts.

| Interface | Shape | Our approach |
|---|---|---|
| SSE events (`backend/app/events.py`) | `{"event","run_id","node","ts","data"}` on unnamed frames, terminating on `run_completed` | Project onto it via `brain/events/compat.py`. Not adopted as canonical. |
| Run API (`backend/app/api/runs.py`) | `POST /api/runs/`, `GET /{id}/events`, approval with `{"decision":"approve"\|"reject"}` | Same verbs; `CONTRACTS.md` §6 adds `since_seq` for reconnect. |
| LLM router (`backend/app/llm/router.py`) | `call_llm(system, user, model, provider)` — **text only, no tools parameter** | Insufficient for tool calling. We use our own raw-`httpx` client. |
| Hindsight (`backend/app/memory/hindsight/`) | `store_experience`, `search`, plus an adapter with `record_execution_experience` / `recall_relevant_experiences` | Wrapped behind `MemoryProvider`. Real HTTP is a TODO in their repo, so `EXTERNAL_DOCS.md` carries the documented REST shapes. |
| Tool registry (`backend/app/workspace/tools.py`) | `TOOL_SCHEMAS` as prose, `validate_action_schema`, `execute_action` | Prose, not JSON Schema, so not reusable for provider-side validation. Ours are real JSON Schema. |
| Command policy (`backend/app/workspace/policy.py`) | `check_command_policy` → `SAFE\|APPROVAL_REQUIRED\|DENIED`, deny-by-default | Same three-way split, named `auto\|confirm\|deny`. |

### Traps flagged, and what we did about them

- `workspace/tools.py:449` uses `re.` without `import re`, so two tools raise `NameError` on every
  call — swallowed into an error dict. Not our file; noted as evidence that a tool "returning an
  error" is not the same as a tool that works.
- Sync-in-async: blocking calls made from async handlers. Our loop is synchronous by decision (D1),
  which sidesteps the class of bug rather than reproducing it.
- A live plaintext `GROQ_API_KEY` sits in the repo-root `.env`. Never read, printed, copied or
  reused. Our own key comes from the environment.
- Hardcoded, mutually contradictory model defaults across five files.

## Gaps and risks

| Risk | Severity | Mitigation |
|---|---|---|
| `qwen/qwen3-32b` is shut down; the brief recommends it | **High** | Verified 2026-09-29, recorded in `MODEL_LADDER.md`. The ladder is a config list, not hardcoded, and a 404 advances to the next rung. |
| Groq forbids tools + structured outputs in one request | **High** | The `json_mode` rung is a separate call with `tools` omitted. Verified fact, not inference. |
| `gpt-oss-120b` does not support parallel tool calls despite the API defaulting them on | Medium | We send `false` explicitly and still handle N calls, because a provider ignoring our flag is not a reason to crash. |
| Strict `json_schema` is incompatible with our tool schemas (partial `required`) | Medium | JSON-mode rung uses `json_object`, not `json_schema`. Documented in `MODEL_LADDER.md`. |
| The flagship vertical may diverge from the team's final demo | Medium | The vertical is config, not code. Changing it touches `config/profiles/` only. |
| `llama-3.x` appears as both production and shut-down on two official Groq pages | Low | Avoided entirely rather than guessed at. |
| Hindsight's real HTTP API is unimplemented in the teammate repo | Medium | `MemoryProvider` plus `MockMemory`; `EXTERNAL_DOCS.md` has the documented REST shapes. |
| **No code has been executed** | **Blocking** | The shell classifier was unavailable all session. Verification is the first outstanding task. |

## Skills, plugins and agents used

Step 0 dispatched four analysts (repo cartographer, pattern analyst, design analyst, external-docs
analyst). `ecc:contract-first` was read before writing `CONTRACTS.md` and shaped the freeze-then-build
ordering and the "one canonical artifact per boundary" rule. The GateGuard hook required a stated fact
block before creating each new file; that was complied with rather than disabled, because on a repo
with a leaked credential the gate is doing real work.

Available but unused, and why: `langgraph` / `langchain` (declared in the teammate's requirements but
never imported there either; a 20-line transition table is easier to test and to explain on stage),
`pydantic` (config and tool arguments both validate against the published JSON Schemas, so a second
validation mechanism would be a second source of truth).
