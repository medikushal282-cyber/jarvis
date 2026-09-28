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

Phases 0-5 are implemented and tested. 84 runtime tests pass; the backend
suite went from 77 to 161 passing with no regressions.

| Phase | State | Where |
| :--- | :--- | :--- |
| 0 Contracts + legacy adapter | done | `runtime/protocols.py`, `runtime/ids.py`, `runtime/adapters/` |
| 1 Event infrastructure | done | `runtime/events/` |
| 2 Sessions and persistence | done | `runtime/sessions/`, `api/sessions.py` |
| 3 Results | done | `runtime/results/builder.py` |
| 3.4 Artifact capture | **not done** | nothing writes to `runs/<id>/artifacts/` |
| 4 Voice plumbing | done, unproven | `runtime/voice/`, `api/voice.py` |
| 5 Frontend client + components | built, **not wired** | `frontend/src/lib/runtime/` |

### Known gaps

1. **Artifact capture is not implemented.** `ARTIFACT_CAPTURE`,
   `ARTIFACT_MAX_BYTES` and `RunStore.artifacts_dir()` exist, and the serve
   endpoint looks in the run's artifact directory first -- but nothing ever
   populates it. Artifacts are path references only, so a file the agent
   overwrites later in the run loses the version the run produced.
2. **`voice_transcribed` / `voice_spoken` are never emitted.** They are in the
   catalog and documented; no code fires them.
3. **Voice has never run against real audio.** No Groq Whisper round trip has
   happened, so the model ids in `config.STT_MODEL` are unverified defaults.
   Confirm them against the live catalog before relying on them.
4. **Auth is not wired.** `AUTH_SERVICE_URL` is defined and unused;
   `current_user_id()` trusts an `X-User-Id` header or falls back to
   `usr_local`. Fine for a single-user demo, not a real identity boundary.
5. **`page.tsx` does not import any of this.** The client, the voice button
   and the result panel exist and compile, but nothing renders them -- the app
   behaves exactly as before. This is the gap that matters most: none of the
   voice or result work is visible to a user yet.

The shim in `app/events.py` keeps every legacy event flowing, so the existing
page keeps working untouched.

Run the tests:

```bash
cd backend && python -m pytest tests/test_runtime_*.py -q
```
