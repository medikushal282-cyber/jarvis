# Runtime — Sessions, Runs and Turns

**Owner:** Farhan · **Package:** `backend/app/runtime/sessions/`

JARVIS is not a request/response API. A person says something, JARVIS does it,
then the person says *"actually, make slide 4 darker"* and expects JARVIS to
know what "slide 4" refers to. That continuity is this layer's whole job.

---

## 1. Entity model

```
User  (usr_...)                     from the auth service, or usr_local in dev
 |
 +-- Workspace  (slug)              a directory JARVIS is allowed to touch
      |
      +-- Session  (ses_...)        one continuous conversation
           |
           +-- Turn                 one user utterance + one JARVIS reply
           |    |
           |    +-- run_id?         a turn may or may not spawn a run
           |
           +-- Run  (run_...)       one objective, start to finish
                |
                +-- Event[]         the timeline (see EVENTS.md)
                +-- RunResult       the report (see RESULTS.md)
```

The distinction that matters: **a session has many runs**. Today's code assumes
one run per request and keeps conversation state in a separate place from run
state. Unifying them is the point of this phase.

### Why "session" and not "conversation"

The current code calls it a conversation and stores messages. A session is
broader: it also owns the workspace binding, the voice state, the accumulated
context summary, and the list of runs. Turns are the message log inside it. The
existing `sandbox/<ws>/conversations/<conv>.json` files map onto sessions
one-to-one, so migration is a rename plus added fields, not a rewrite.

---

## 2. Schemas

```python
@dataclass
class Session:
    id: str                       # ses_<hex12>
    user_id: str
    workspace_id: str
    title: str
    created_at: str               # ISO 8601 UTC
    updated_at: str
    turns: List[Turn]
    run_ids: List[str]
    context_summary: str = ""     # compressed memory, maintained by the runtime
    status: str = "active"        # "active" | "archived"

@dataclass
class Turn:
    id: str                       # trn_<hex8>
    role: str                     # "user" | "assistant" | "system"
    content: str
    ts: str
    input_mode: str = "text"      # "text" | "voice"
    run_id: Optional[str] = None
    audio_url: Optional[str] = None   # set for voice turns, see VOICE.md
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Run:
    id: str                       # run_<hex8>
    session_id: str
    user_id: str
    workspace_id: str
    objective: str
    model: str
    provider: str
    input_mode: str
    status: str                   # pending|running|paused|completed|failed|cancelled
    created_at: str
    started_at: Optional[str]
    ended_at: Optional[str]
    event_count: int = 0
    result: Optional[Dict[str, Any]] = None   # RunResult, see RESULTS.md
```

---

## 3. Storage

File-backed, same as today. A database is not worth the hackathon time, and
file-backed storage demos well because you can open the JSON on stage.

```
sandbox/
  <workspace_id>/
    workspace.json
    sessions/
      <session_id>.json                  # Session + Turn[]
    runs/
      <run_id>/
        run.json                         # Run
        events.ndjson                    # append-only event log
        result.json                      # RunResult, written on terminal event
        artifacts/                       # copies of produced files, if any
```

Rules for the store implementation:

- **All writes go through `SessionStore` / `RunStore`.** No other module opens
  these files.
- **Atomic writes**: write to `<name>.tmp`, `os.replace`. A crash mid-write must
  not corrupt a session.
- **One `asyncio.Lock` per session id** to serialise concurrent turn appends.
  Two runs in one session can finish at the same time.
- **An in-memory write-through cache** keyed by id, so the hot path does not hit
  the disk on every event.
- `RUNS_DB` and `SESSION_HISTORY` in `backend/app/api/runs.py:38-39` are deleted
  and replaced by these stores.

---

## 4. HTTP surface

Replaces `/api/sandbox/*`. The old routes stay as deprecated aliases for one
milestone so the frontend can migrate in its own commit.

### Sessions

| Method | Path | Notes |
| :--- | :--- | :--- |
| `GET` | `/api/sessions` | `?workspace_id=&status=` — list for the current user |
| `POST` | `/api/sessions` | `{workspace_id, title?}` — create |
| `GET` | `/api/sessions/{id}` | Full session with turns and run summaries |
| `PATCH` | `/api/sessions/{id}` | `{title?, status?}` |
| `DELETE` | `/api/sessions/{id}` | Archives by default, `?hard=true` to remove |
| `GET` | `/api/sessions/{id}/turns` | `?limit=&before=` — paginated |
| `POST` | `/api/sessions/{id}/turns` | Append a turn without starting a run |
| `GET` | `/api/sessions/{id}/context` | `{context_summary, turn_count, recent_turns}` |

### Runs

| Method | Path | Notes |
| :--- | :--- | :--- |
| `POST` | `/api/sessions/{id}/runs` | **The main entry point.** `{objective, model?, provider?, input_mode?, attachments?}` → `{run_id, status}` |
| `GET` | `/api/runs/{id}` | The `Run` record |
| `GET` | `/api/runs/{id}/result` | The `RunResult` — see [RESULTS.md](RESULTS.md) |
| `POST` | `/api/runs/{id}/cancel` | Cooperative cancel |
| `POST` | `/api/runs/{id}/approval` | `{decision: "approve"\|"reject", request_id}` |
| `GET` | `/api/runs/{id}/events` | SSE — see [EVENTS.md](EVENTS.md) |

`POST /api/runs/` (no session) is kept as a convenience: it resolves or creates
a default session, so curl and the existing frontend keep working.

---

## 5. What the runtime does on each run

This is the sequence `runtime/sessions/service.py` owns. Note how little it
knows about the agent.

1. Resolve `user_id` (auth cookie, else `usr_local`), `session_id`,
   `workspace_id`. Reject if the workspace does not belong to the user.
2. Append the user `Turn`.
3. Build `RunRequest`: objective, recent turns, `context_summary`, attachments.
4. Create the `Run` record, status `pending`; create the event stream.
5. `emit("run_started", ...)` is the brain's job, but the runtime arms a watchdog
   for it.
6. `await agent_runner.run(request, emit)` in a task.
7. On terminal event: build the `RunResult` from the event log, persist it,
   append the assistant `Turn`, update `context_summary`, mark the run.
8. If the brain returned without a terminal event, synthesise `run_failed`.

Step 7 is the part worth protecting. It must run even when the agent raises,
even when it hangs and gets cancelled, even on `run_cancelled`. Put it in a
`finally`.

### Context summary

Keep the existing approach — a small fast model compressing recent turns
(`app/api/sandbox.py:214`). Two changes:

- It moves into `runtime/sessions/summarizer.py` and runs **on a background
  task after the turn is appended**, not inline. Today it blocks
  `save_conversation_turn`, which means every single reply pays an extra LLM
  round-trip before the user sees anything.
- It is a *session* summary, deliberately distinct from Kushal's Hindsight
  memory. Session summary = "what are we doing right now". Hindsight = "what
  did we learn across sessions". Do not merge them; the demo needs both to be
  visible and distinguishable.

---

## 6. P0 security fix, do this first

`backend/app/api/sandbox.py` derives filesystem paths from unsanitised input:

```python
ws_id = req.name.lower().replace(" ", "_").replace("-", "_")   # line 67
ws_dir = sandbox / ws_id
```

Path separators and `..` survive this. A workspace named `../../etc` escapes the
sandbox root. Worse, every other endpoint takes `ws_id` straight from the URL
and does `sandbox / ws_id` — including:

```python
@router.delete("/workspaces/{ws_id}")     # line 88
    shutil.rmtree(sandbox / ws_id)        # arbitrary directory deletion
```

Evidence it is already producing broken data: `sandbox/kushal/workspace.json`
contains `"id": "kushal\\"`.

Required fix, in `runtime/ids.py`, applied to every id that becomes a path:

```python
_SLUG = re.compile(r"[^a-z0-9_-]+")

def safe_slug(raw: str, *, max_len: int = 48) -> str:
    slug = _SLUG.sub("_", raw.strip().lower()).strip("_")[:max_len]
    if not slug or slug in {".", ".."}:
        raise ValueError("invalid identifier")
    return slug

def resolve_within(root: Path, *parts: str) -> Path:
    target = (root / Path(*parts)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("path escapes root")
    return target
```

Every path built from a request parameter goes through `resolve_within`. This is
the same containment rule `WorkspaceManager` already enforces for agent file
operations (`backend/app/workspace/manager.py`); the session API simply never
got it.

---

## 7. Acceptance criteria

1. Two runs in one session; the second run's `RunRequest.conversation` contains
   the first run's outcome.
2. `POST /api/workspaces {"name": "../../evil"}` returns 400.
3. `DELETE /api/sandbox/workspaces/..%2F..%2Ffoo` returns 400 and deletes
   nothing.
4. Restart the backend; every session, run, timeline and result is still there.
5. A run that raises still produces a persisted `RunResult` with
   `status: "failed"` and an assistant turn explaining the failure.
6. Two runs completing simultaneously in one session both land in `turns`.
7. Replying to the user is not blocked on the summariser.
