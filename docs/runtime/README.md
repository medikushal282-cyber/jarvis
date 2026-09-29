# JARVIS Runtime Layer

**Owner:** Farhan · **Package:** `backend/app/runtime/` + `frontend/src/lib/runtime/`

The runtime is the edge of JARVIS — everything between a human and the agent's
brain. It answers two questions and deliberately no others:

1. **How does a person talk to JARVIS?** (voice, sessions, turns)
2. **How does a person see what JARVIS did?** (events, results, artifacts)

It does not plan, does not choose tools, does not remember across sessions. It
carries messages in, and it carries evidence back out.

```
   Human ──► Session ──► Run ──► [ Agent Brain ] ──► Events ──► Result
     ▲                                                             │
     └─────────────────────── voice / UI ──────────────────────────┘
```

---

## Documents

| Doc | What it covers |
| :--- | :--- |
| [../INTERFACES.md](../INTERFACES.md) | **Read first.** The four-way contract between Farhan, Nikunj, Lohith and Kushal |
| [PLAN.md](PLAN.md) | Phased implementation plan, sequencing, risks, first commit |
| [EVENTS.md](EVENTS.md) | Event envelope, full catalog, bus semantics, SSE and replay |
| [SESSIONS.md](SESSIONS.md) | User / session / run / turn model, storage, API, the P0 security fix |
| [RESULTS.md](RESULTS.md) | `RunResult` schema, the event-to-result reducer, artifact serving |
| [VOICE.md](VOICE.md) | STT and TTS contracts, provider choices, VAD, barge-in, failure modes |

---

## The one design decision worth knowing

**Results are derived from the event stream, not reported by the agent.**

The brain's only obligation to this layer is to emit honest events. The
timeline, the artifact list, the action summary, the memory panel — all of it is
a reducer over `events.ndjson`. That keeps the dependency arrow pointing one
way, lets Nikunj rewrite the brain without touching the UI, and means a run that
crashed halfway still produces a usable report.

---

## Quick reference

**Emitting an event** (Nikunj, Lohith):

```python
emit("tool_started", {"tool": "create_file", "args": {"path": "app.py"}})
```

**Implementing the brain** (Nikunj):

```python
class JarvisBrain(AgentRunner):
    async def run(self, request: RunRequest, emit: EventEmitter) -> RunOutcome:
        emit("run_started", {"objective": request.objective})
        ...
        emit("run_completed", {"status": "completed", "summary": summary})
        return RunOutcome(status="completed", reply=reply)
```

**Starting a run** (frontend):

```
POST /api/sessions/{session_id}/runs   { objective, input_mode }
GET  /api/runs/{run_id}/events         SSE, resumable
GET  /api/runs/{run_id}/result         RunResult
```

---

## Status

See [PLAN.md](PLAN.md) for the current phase and what is left.

Run the tests:

```bash
cd backend && python -m pytest tests/test_runtime_*.py -q
```

Try the UI without the real brain or an API key: set `JARVIS_AGENT=scripted`
before starting the backend.
