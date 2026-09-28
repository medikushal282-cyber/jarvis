# JARVIS — Cross-Team Interface Contract

**Status:** Draft v1 · Owner: Farhan (runtime layer) · Applies to: all four workstreams

This is the single source of truth for the boundaries between the four JARVIS
workstreams. If you are about to import a module owned by someone else, it must
be through an interface defined in this document. If the interface you need is
not here, add it here first and tell the owner.

---

## 1. Ownership map

| Layer | Owner | Package | Answers the question |
| :--- | :--- | :--- | :--- |
| **Runtime / Edge** | Farhan | `backend/app/runtime/` | How does a human talk to JARVIS, and how do they see what it did? |
| **Agent Brain** | Nikunj | `backend/app/agent/` | What should JARVIS do next? |
| **Tools / Capability** | Lohith | `backend/app/tools/` | How does JARVIS actually touch the computer? |
| **Memory** | Kushal | `backend/app/memory/` | What does JARVIS remember? |

**Frontend:** `frontend/` is shared. Farhan owns the session shell, the event
stream consumer, the transcript/voice UI, and the run-result panel. Anyone may
add a panel, but only Farhan changes how events arrive.

---

## 2. The dependency rule

Each workstream depends on the one below it, never sideways, never upward.

```
        Human (voice / text)
                |
                v
   +----------------------------+
   |  RUNTIME          (Farhan) |  sessions - runs - events - results - voice
   +-------------+--------------+
                 | AgentRunner.run(RunRequest, EventEmitter)
                 v
   +----------------------------+
   |  AGENT BRAIN      (Nikunj) |  plan - decide - call tools - recover - stop
   +--------+----------+--------+
            |          |
   ToolExecutor    MemoryProvider
            |          |
            v          v
   +------------+ +------------+
   |   TOOLS    | |   MEMORY   |
   |  (Lohith)  | |  (Kushal)  |
   +------------+ +------------+
```

Consequences worth stating out loud:

- **Runtime never imports the agent's internals.** It holds an `AgentRunner` and
  an `EventEmitter`. It does not know what a "plan" or a "node" is.
- **The brain never writes to disk, never opens a socket, never touches the
  event queue directly.** It calls tools and it calls `emit`.
- **Tools and memory never emit events themselves.** They return results; the
  brain decides what is worth telling the user. (Exception: long-running tools
  may be handed a scoped emitter — see section 3.3.)
- **Nothing outside the runtime knows that SSE exists.**

---

## 3. The four interfaces

### 3.1 `AgentRunner` — Runtime to Brain

Nikunj implements this. Farhan calls it. Defined in
`backend/app/runtime/protocols.py`.

```python
from typing import Protocol, Optional, List, Dict, Any
from dataclasses import dataclass, field

@dataclass
class RunRequest:
    run_id: str
    session_id: str
    user_id: str
    workspace_id: str
    objective: str                                  # the user's words, verbatim
    model: str
    provider: str
    input_mode: str = "text"                        # "text" | "voice"
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    conversation: List[Dict[str, Any]] = field(default_factory=list)  # recent turns
    context_summary: str = ""                       # compressed session memory

@dataclass
class RunOutcome:
    status: str                                     # "completed" | "failed" | "rejected"
    reply: str                                      # what JARVIS says back, prose
    error: Optional[Dict[str, Any]] = None

class AgentRunner(Protocol):
    async def run(self, request: RunRequest, emit: "EventEmitter") -> RunOutcome:
        ...
```

Rules:

- The brain **must** emit `run_started` first and exactly one terminal event
  (`run_completed` or `run_failed`) last. The runtime enforces this — if `run()`
  returns or raises without a terminal event, the runtime synthesises one.
- The brain **must not** swallow exceptions silently. Raise, and the runtime
  will convert it to `run_failed` with a sanitised message.
- Everything the UI shows is derived from events, not from the return value.
  `RunOutcome.reply` is only the spoken or printed sentence.
- `run()` may block for minutes. It runs in its own task; do not sleep the
  event loop, use `asyncio.to_thread` for sync work.

### 3.2 `EventEmitter` — Brain/Tools to Runtime

Farhan implements this. Everyone calls it. See
[EVENTS.md](runtime/EVENTS.md) for the full catalog.

```python
class EventEmitter(Protocol):
    def emit(self, event: str, data: dict | None = None, *, node: str = "") -> None:
        """Fire-and-forget. Safe from sync and async code. Never raises."""

    def scoped(self, node: str) -> "EventEmitter":
        """Returns an emitter that stamps every event with this node name."""
```

Rules:

- `emit` is **synchronous and never raises**. A broken event pipe must never
  fail a run. This is a deliberate change from today's `await emit(...)`.
- Event names come from the catalog. Inventing a name is fine during
  development; adding it to `runtime/events/catalog.py` before merge is not
  optional.
- Payloads must be JSON-serialisable and must not contain secrets. The runtime
  redacts known API keys, but do not rely on that.

### 3.3 `ToolExecutor` — Brain to Tools

Lohith implements this. Nikunj calls it. Lohith's SDK already has
`ToolRegistry` / `ToolContext` / `ToolResult`; this is the narrow view the brain
uses.

```python
class ToolExecutor(Protocol):
    def describe(self) -> List[Dict[str, Any]]:
        """Tool schemas, in the shape the LLM's tool-calling API expects."""

    async def execute(self, name: str, args: dict, ctx: "ToolContext") -> "ToolResult":
        ...
```

`ToolContext` carries `run_id`, `session_id`, `user_id`, `workspace_root`, and
an optional `emit` for tools that stream progress (a long `run_command`, a
browser session). A tool that is handed `emit` may only send `tool_progress`,
`command_output`, and `browser_action`.

`ToolResult` must expose at minimum: `success: bool`, `data: dict`,
`error: str | None`, and — for anything that touches the filesystem or the
network — an `artifacts: list` so the runtime's result builder can pick it up
without understanding the tool.

### 3.4 `MemoryProvider` — Brain to Memory

Kushal implements this. Nikunj calls it.

```python
class MemoryProvider(Protocol):
    async def recall(self, user_id: str, objective: str, *,
                     session_id: str | None = None,
                     workspace_id: str | None = None,
                     limit: int = 5) -> Dict[str, Any]:
        """Returns {"experiences": [...], "observations": [...],
                    "user_knowledge": str, "project_knowledge": str}"""

    async def record(self, user_id: str, run_id: str, objective: str,
                     outcome: Dict[str, Any]) -> str:
        """Persists what happened. Returns an experience id."""
```

The brain emits `memory_recalled` after `recall()` and `memory_recorded` after
`record()` so the UI can show the memory layer working. That event is how
Hindsight becomes visible to a judge — see [EVENTS.md](runtime/EVENTS.md).

---

## 4. Shared identifiers

Every request, event, log line, and stored record carries the same keys.

| Field | Format | Meaning |
| :--- | :--- | :--- |
| `user_id` | `usr_<hex12>` | The human. Sourced from the auth service (`GET /api/auth/me`), or `usr_local` in dev. |
| `session_id` | `ses_<hex12>` | One continuous conversation. Survives restarts. |
| `run_id` | `run_<hex8>` | One objective. A session has many runs. |
| `workspace_id` | slug | The directory the run may touch. |

"JARVIS, create a presentation" and the follow-up "make slide 4 darker" are
**two runs in one session**. Nothing in the system may assume one run per
session.

---

## 5. Rules of engagement

1. **Changing a shared interface requires editing this file in the same commit.**
2. **Do not edit `backend/app/runtime/` if you do not own it.** Need an event, a
   field, an endpoint? Open it as a task, Farhan lands it, usually same day.
3. **The legacy graph in `backend/app/graph/` is frozen.** It stays as the
   default `AgentRunner` implementation so the demo never goes dark while Nikunj
   builds the real brain. Bug fixes only; no new features.
4. **Never import `app.api.*` from `app.agent.*`, `app.tools.*`, or
   `app.memory.*`.** If you find yourself wanting to, you want an interface.
5. **New Python deps go in `backend/requirements.txt` with a pinned floor**, and
   you tell the group chat, because everyone runs the same venv.

---

## 6. Known contract violations in the current code

These exist today and are scheduled for removal in Phase 0 to 2 of
[PLAN.md](runtime/PLAN.md). Listed so nobody builds on them.

| Violation | Location | Fix |
| :--- | :--- | :--- |
| Graph nodes import `app.events.emit` directly and `await` it | `backend/app/graph/nodes/*.py` (~100 sites) | `app/events.py` becomes a shim over the new emitter; call sites migrate gradually |
| Run state lives in a module-level dict, lost on restart | `backend/app/api/runs.py:38` | Run store in `runtime/sessions/` |
| `workflow.py` conflates run lifecycle, transport, and agent logic | `backend/app/graph/workflow.py:80-360` | Lifecycle moves to `runtime/`, the rest stays behind `AgentRunner` |
| No `user_id` anywhere in the session model | `backend/app/api/sandbox.py` | Added in Phase 2 |
| Two names for one concept: `approval_requested` vs `approval_required` | `executor.py:604` / `workflow.py:289` | Single name `approval_requested` in the catalog |
| Workspace ids are unsanitised user input used as filesystem paths | `backend/app/api/sandbox.py:67` | P0 security fix, Phase 2 |
