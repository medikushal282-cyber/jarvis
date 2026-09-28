# Runtime — Event Infrastructure

**Owner:** Farhan · **Package:** `backend/app/runtime/events/`

Farhan owns *how events get delivered*. He does not own *what causes them*.
Nikunj, Lohith and Kushal decide when something interesting happened; this layer
guarantees it reaches the browser, in order, exactly once, and survives a page
refresh.

---

## 1. What exists today, and why it is not enough

`backend/app/events.py` is 21 lines:

```python
event_bus: Dict[str, asyncio.Queue] = {}

def get_queue(run_id): ...
async def emit(run_id, event_type, node="", data=None): ...
```

It works for a happy-path demo. Seven things break it:

| # | Problem | Consequence |
| :-- | :--- | :--- |
| 1 | Queues are created on first access and **never deleted** (`events.py:8`) | Every run leaks a queue plus its events for the process lifetime |
| 2 | **One queue per run, consumed destructively** | Two browser tabs on the same run split the stream between them; both show half a timeline |
| 3 | **No sequence numbers** | No way to detect a gap or resume |
| 4 | **No replay buffer** | Refresh the page mid-run and the run continues invisibly; the UI is stuck on "running" forever |
| 5 | **Nothing is persisted** | A finished run has no timeline. `GET /api/runs/{id}` returns raw agent state instead |
| 6 | **`emit` is `async`** | Lohith's sync tool code and any threadpool work cannot emit without plumbing a loop reference through |
| 7 | **No heartbeat** | An idle SSE connection is dropped by proxies and by some browsers; a long planning phase looks like a hang |

There is also a naming split: the executor emits `approval_requested`
(`executor.py:604`) while the workflow emits `approval_required`
(`workflow.py:289`) for the same concept, and the frontend only handles one of
them.

---

## 2. Event envelope

Every event on the wire has exactly this shape. Nothing is optional.

```jsonc
{
  "seq": 47,                                  // monotonic per run, starts at 1
  "event": "tool_completed",                  // from the catalog, section 4
  "run_id": "run_9f3c21a8",
  "session_id": "ses_4b1e77c0d219",
  "user_id": "usr_local",
  "node": "executor",                         // who emitted it; "" if unscoped
  "ts": "2026-09-29T11:04:22.418Z",           // ISO 8601, UTC, ms precision
  "data": { }                                 // event-specific, see catalog
}
```

`seq` is assigned by the bus at publish time, not by the caller. It is the only
ordering guarantee — do not order by `ts`, clocks are not that precise and
several events can land in the same millisecond.

---

## 3. Emitter API

Defined in `runtime/events/emitter.py`. This is what everyone else imports.

```python
emit = get_emitter(run_id)            # runtime hands this to AgentRunner.run()

emit("planning", {"objective": obj})
emit("tool_started", {"tool": "create_file", "args": {"path": "app.py"}})

tool_emit = emit.scoped("executor")   # stamps node="executor" on everything
tool_emit("tool_completed", {"tool": "create_file", "ok": True})
```

Guarantees the implementation must provide:

- **Synchronous.** Callable from a thread, from `asyncio.to_thread`, from sync
  tool code. Internally it uses `loop.call_soon_threadsafe` when off-loop.
- **Never raises.** A full queue, a dead loop, a non-serialisable payload — all
  swallowed and logged. An event pipe failure must never fail a run.
- **Redacts secrets** before publish: any value matching a configured API key,
  plus keys named `authorization`, `api_key`, `token`, `password`, `secret`.
- **Truncates** any string field over 8 KB and any payload over 64 KB, marking
  `"_truncated": true`, so one `cat` of a large file cannot stall the stream.

The old `await emit(run_id, type, node, data)` signature stays working:
`app/events.py` becomes a thin shim that forwards to the new bus. The ~100
existing call sites in `app/graph/` keep working unchanged and get migrated
opportunistically, not in a big-bang rewrite.

---

## 4. Event catalog

Canonical list lives in `runtime/events/catalog.py` as a frozen enum plus a
payload schema per event. The SSE endpoint validates against it in dev and logs
a warning (never rejects) in prod.

### 4.1 Run lifecycle — emitted by the runtime and the brain

| Event | Emitted by | `data` |
| :--- | :--- | :--- |
| `run_started` | brain (first event, mandatory) | `objective`, `model`, `provider`, `input_mode` |
| `run_completed` | brain (terminal) | `status`, `summary`, `reply` |
| `run_failed` | brain or runtime (terminal) | `error_type`, `message`, `node` |
| `run_cancelled` | runtime | `reason` |

### 4.2 Reasoning — emitted by the brain

| Event | `data` |
| :--- | :--- |
| `planning` | `objective` — "I am now working out what to do" |
| `plan_created` | `steps: [{id, title, tool, depends_on, status}]` |
| `plan_updated` | `steps` — after a replan |
| `agent_thinking` | `summary` — one line of narration |
| `thought_generated` | `phase`, `title`, `thought`, `model` — the expandable reasoning block |
| `step_started` / `step_completed` / `step_failed` | `step_id`, `status` |
| `decision` | `decision`, `reason` — controller routing, useful for debugging |

### 4.3 Tools — emitted by the brain around `ToolExecutor.execute`

| Event | `data` |
| :--- | :--- |
| `tool_started` | `tool`, `args` (redacted), `call_id` |
| `tool_progress` | `call_id`, `message`, `percent?` — optional, for long tools |
| `tool_completed` | `call_id`, `tool`, `ok`, `duration_ms`, `preview` |
| `tool_failed` | `call_id`, `tool`, `error`, `duration_ms` |
| `command_started` | `command`, `cwd` |
| `command_output` | `stream` (`stdout`/`stderr`), `chunk` — streamed, optional |
| `command_completed` | `command`, `exit_code`, `stdout`, `stderr`, `duration_ms` |
| `browser_action` | `action` (`open`/`click`/`type`/`screenshot`), `url`, `selector?` |

### 4.4 Filesystem — drives the artifact panel

| Event | `data` |
| :--- | :--- |
| `file_created` | `path`, `bytes`, `lines` |
| `file_updated` | `path`, `bytes`, `lines`, `diff_summary?` |
| `file_deleted` | `path` |
| `file_read` | `path`, `bytes` |

### 4.5 Memory — the Hindsight visibility events

These are the ones that make the memory layer legible to a judge. Kushal
supplies the data, Nikunj emits them.

| Event | `data` |
| :--- | :--- |
| `memory_recalled` | `query`, `hits: [{id, kind, content, score, age_days}]`, `latency_ms` |
| `memory_applied` | `experience_id`, `how` — one sentence: "skipped pip install, failed last time on this project" |
| `memory_recorded` | `experience_id`, `summary`, `kind` |

`memory_applied` is worth insisting on. `memory_recalled` proves retrieval
happened; `memory_applied` proves it *changed the behaviour*, which is the
25% judging criterion.

### 4.6 Verification and approval

| Event | `data` |
| :--- | :--- |
| `verification_started` | `target`, `method` |
| `verification_completed` | `valid`, `reason`, `checks: [{name, passed, detail}]` |
| `approval_requested` | `tool`, `path`, `reason`, `request_id` |
| `approval_granted` / `approval_rejected` | `request_id` |

Note: `approval_required` is **retired**. Use `approval_requested`.

### 4.7 Transport-only — emitted by the runtime, never by anyone else

| Event | `data` |
| :--- | :--- |
| `stream_ready` | `run_id`, `resumed_from_seq` — first frame on every connection |
| `heartbeat` | `ts` — every 15 s of silence |

`node_started` / `node_completed` / `context_loaded` / `observation_created` /
`research_finding` / `validation_result` / `chat_response` are **legacy**. The
shim keeps emitting them so today's UI keeps working; they map onto the table
above and get removed once the frontend is migrated.

---

## 5. Bus semantics

`runtime/events/bus.py`

- **Fan-out, not hand-off.** Each subscriber gets its own queue. N tabs, N
  queues, same stream. Publishing to a slow subscriber never blocks the
  publisher — its queue is bounded (256) and drops oldest with a
  `"_dropped": n` marker on the next event.
- **Ring buffer per run**, last 1000 events in memory, for instant replay.
- **Durable log per run**: newline-delimited JSON appended at
  `sandbox/<workspace>/runs/<run_id>/events.ndjson`. Replay beyond the ring
  buffer reads from there. This is also what the result builder consumes
  (see [RESULTS.md](RESULTS.md)) and what lets a finished run still render a
  full timeline.
- **Cleanup**: 60 s after a terminal event with no subscribers, the ring buffer
  and queues are dropped. The ndjson stays.
- **Backpressure on the writer**: the ndjson append happens on a background
  task, batched, so a slow disk cannot stall `emit`.

---

## 6. HTTP surface

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/api/runs/{run_id}/events` | SSE stream. `?from_seq=N` replays from N then goes live. Honours the `Last-Event-ID` header automatically. |
| `GET` | `/api/runs/{run_id}/events/log` | The whole event list as JSON, for a finished run or for debugging. `?since=N`, `?types=a,b`. |
| `GET` | `/api/sessions/{session_id}/events` | Merged stream across every run in the session — what the voice UI subscribes to, so a follow-up run appears without re-subscribing. |

SSE framing sets `id:` to `seq`, so a browser reconnect sends `Last-Event-ID`
and resumes with no gap and no duplicates. That single detail is what makes
refresh-during-a-run stop being a bug.

The endpoint terminates on a terminal event **only if** no further runs are
expected on that connection. For the session stream it stays open across runs.

---

## 7. Acceptance criteria

The event layer is done when all of these hold:

1. Start a run, refresh the browser mid-run, and the timeline is complete with
   no gaps and no duplicates.
2. Open the same run in two tabs; both show the identical, complete timeline.
3. Kill and restart the backend after a run finished; `GET .../events/log`
   still returns the full timeline.
4. A tool that emits 10,000 events in a tight loop does not stall the run and
   does not exhaust memory.
5. `emit` called from inside `asyncio.to_thread` delivers.
6. A payload containing `GROQ_API_KEY`'s value arrives redacted.
7. Load test: 5 concurrent runs, 200 events each, no event loss.
