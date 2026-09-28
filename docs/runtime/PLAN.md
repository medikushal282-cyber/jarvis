# Runtime Layer — Implementation Plan

**Owner:** Farhan · **Scope:** voice, sessions, event infrastructure, run results
**Status:** Phases 0-5 implemented. See [README.md](README.md#status) for what
remains (page.tsx migration, replay mode).

Read [INTERFACES.md](../INTERFACES.md) first — it defines the boundaries this
plan builds against.

---

## 0. Where we are starting from

The repo already contains a working agent (`backend/app/graph/`), a live UI
(`frontend/`), an SSE stream, and file-backed conversations. None of it is
wasted. But the four concerns Farhan owns are currently tangled into the agent:

- Run lifecycle lives inside `execute_run_task` in
  `backend/app/graph/workflow.py:80-360`, interleaved with planning logic.
- The event bus is 21 lines with no ordering, replay, persistence or cleanup
  (`backend/app/events.py`).
- Run state is a module-level dict lost on restart (`backend/app/api/runs.py:38`).
- Sessions exist but have no user, and their ids are unsanitised filesystem
  paths (`backend/app/api/sandbox.py:67`).
- There is no voice layer at all.

The work is therefore mostly **extraction**, not greenfield. That is good news
for the schedule and bad news for anyone who wants to skip the refactor.

### Target package layout

```
backend/app/runtime/            <- Farhan owns everything under here
  __init__.py
  protocols.py                  AgentRunner, EventEmitter, RunRequest, RunOutcome
  ids.py                        id generation, safe_slug, resolve_within
  models.py                     Session, Turn, Run, RunResult, Artifact
  config.py                     feature flags, limits, provider selection
  events/
    catalog.py                  canonical event names + payload schemas
    bus.py                      fan-out, seq, ring buffer, ndjson log, cleanup
    emitter.py                  the sync emit() everyone calls
    sse.py                      SSE framing, Last-Event-ID resume, heartbeat
  sessions/
    store.py                    SessionStore, RunStore (atomic file IO)
    service.py                  the run lifecycle orchestration
    summarizer.py               background context compression
  results/
    builder.py                  events -> RunResult (pure reducer)
    artifacts.py                artifact capture and serving
  voice/
    stt.py                      SpeechToText + Groq Whisper impl
    tts.py                      TextToSpeech + browser/Groq impls
    speakable.py                reply -> short spoken form
  adapters/
    legacy_graph.py             wraps app/graph/workflow.py as an AgentRunner

backend/app/api/
  sessions.py   events.py   voice.py   runs.py (slimmed)

frontend/src/
  lib/runtime/                  typed client: events, sessions, results, voice
  components/Voice/             mic button, VAD, transcript, playback
  components/RunResult/         artifacts, actions, memory panel
```

---

## Phase 0 — Contracts and the legacy adapter

**Goal: unblock Nikunj on day one.** Nothing else in this plan matters if the
brain workstream is blocked waiting on the runtime.

| # | Task | Files |
| :-- | :--- | :--- |
| 0.1 | Write `protocols.py`: `AgentRunner`, `EventEmitter`, `RunRequest`, `RunOutcome` | `runtime/protocols.py` |
| 0.2 | Write `ids.py`: `new_user_id/session_id/run_id/turn_id`, `safe_slug`, `resolve_within` | `runtime/ids.py` |
| 0.3 | Write `catalog.py` with the full event list from [EVENTS.md](EVENTS.md) | `runtime/events/catalog.py` |
| 0.4 | Wrap the existing graph as `LegacyGraphRunner(AgentRunner)` | `runtime/adapters/legacy_graph.py` |
| 0.5 | Register the runner in `config.py` behind `JARVIS_AGENT=legacy\|core` | `runtime/config.py` |
| 0.6 | Give Nikunj a `NullAgentRunner` + an in-memory emitter he can unit-test against | `runtime/testing.py` |

**Done when:** Nikunj can write `class JarvisBrain(AgentRunner)` against a stable
type, run it with a fake emitter, and see his events in a test — with zero
runtime code finished beyond this phase.

Do not gold-plate here. A day, at most.

---

## Phase 1 — Event infrastructure

The load-bearing piece. Everything downstream (results, observability UI, the
demo's credibility) reads from this.

| # | Task | Notes |
| :-- | :--- | :--- |
| 1.1 | `bus.py`: per-run fan-out with per-subscriber bounded queues | drops oldest, marks `_dropped` |
| 1.2 | Monotonic `seq` assigned at publish | never trust caller ordering |
| 1.3 | Ring buffer (last 1000) per run for instant replay | |
| 1.4 | Durable `events.ndjson` append on a batched background task | never blocks `emit` |
| 1.5 | `emitter.py`: sync `emit()`, `scoped()`, never raises | `call_soon_threadsafe` when off-loop |
| 1.6 | Secret redaction + payload truncation | 8 KB per string, 64 KB per payload |
| 1.7 | `sse.py`: `id:` = seq, `Last-Event-ID` resume, `?from_seq=`, 15 s heartbeat | |
| 1.8 | Subscriber-count-based cleanup, 60 s after terminal | fixes the queue leak |
| 1.9 | **Shim `app/events.py`** onto the new bus, keeping `await emit(...)` working | ~100 call sites keep working untouched |
| 1.10 | `GET /api/runs/{id}/events/log` for finished runs | |
| 1.11 | `GET /api/sessions/{id}/events` merged stream | needed by voice in Phase 4 |

**Done when:** the seven acceptance criteria in [EVENTS.md](EVENTS.md#7-acceptance-criteria)
pass. The one to demo: start a run, hit refresh, timeline is intact.

Task 1.9 is what makes this phase safe. The legacy graph never learns that the
bus changed.

---

## Phase 2 — Sessions, runs and persistence

| # | Task | Notes |
| :-- | :--- | :--- |
| 2.1 | **P0 security**: `safe_slug` + `resolve_within` on every path built from request input | see [SESSIONS.md](SESSIONS.md#6-p0-security-fix-do-this-first) |
| 2.2 | `models.py`: `Session`, `Turn`, `Run` | |
| 2.3 | `store.py`: atomic writes, per-session lock, write-through cache | |
| 2.4 | Migrate `sandbox/<ws>/conversations/*.json` to `sessions/*.json` | one-shot script, add `user_id`, `id`, `run_ids` |
| 2.5 | `service.py`: the eight-step run lifecycle, with the `finally` block | |
| 2.6 | `user_id` resolution from the auth cookie, `usr_local` in dev | the Node service at `server/` already has `GET /api/auth/me` |
| 2.7 | New API: `/api/sessions/*`, `/api/runs/*`; deprecate `/api/sandbox/*` as aliases | |
| 2.8 | Delete `RUNS_DB` and `SESSION_HISTORY` | `api/runs.py:38-39` |
| 2.9 | Move summarisation to a background task | it currently blocks every reply |
| 2.10 | Frontend: session list, switcher, transcript reads from `/api/sessions` | |

**Done when:** the criteria in [SESSIONS.md](SESSIONS.md#7-acceptance-criteria)
pass. The one to demo: two runs in one session, second one knows about the
first, and everything survives a backend restart.

---

## Phase 3 — Results and artifacts

| # | Task | Notes |
| :-- | :--- | :--- |
| 3.1 | `builder.py`: pure `List[Event] -> RunResult` reducer | table in [RESULTS.md](RESULTS.md#3-reducer-table) |
| 3.2 | Unit tests from fixture ndjson files, no agent involved | cheapest insurance in the repo |
| 3.3 | Incremental building during the run; snapshot on request | live artifact panel |
| 3.4 | Artifact capture: hard-link into the run dir, fall back to copy | 10 MB cap |
| 3.5 | `GET /api/runs/{id}/result`, `/artifacts`, `/artifacts/{id}` | traversal-safe, CSP on HTML |
| 3.6 | `GET /api/sessions/{id}/artifacts` | |
| 3.7 | Frontend `RunResult` panel: summary, artifacts, actions, memory, errors, timeline | |
| 3.8 | Replace `page.tsx:499`'s reach into `state.artifacts` with `/result` | stops the UI depending on brain internals |

**Done when:** the criteria in [RESULTS.md](RESULTS.md#7-acceptance-criteria)
pass, and a killed run still renders a sensible report.

---

## Phase 4 — Voice

Deliberately after the plumbing. Voice on top of a broken event stream is a demo
that fails loudly.

| # | Task | Notes |
| :-- | :--- | :--- |
| 4.1 | `stt.py`: `SpeechToText` Protocol + Groq Whisper impl | confirm the model id against the live catalog, do not hardcode a guess |
| 4.2 | `POST /api/voice/transcribe` with mime allowlist, 25 MB cap, rate limit | |
| 4.3 | `tts.py`: Protocol + browser backend; server backend behind a flag | |
| 4.4 | `speakable.py`: strip code, shorten paths, cap ~40 words | |
| 4.5 | `GET /api/voice/config` so the UI degrades instead of throwing | |
| 4.6 | Frontend `useVoiceCapture`: getUserMedia, MediaRecorder, energy VAD | |
| 4.7 | Push-to-talk UI, live waveform, editable transcript on low confidence | |
| 4.8 | Playback + **barge-in** | non-negotiable, talking over JARVIS must work |
| 4.9 | Store the clip, set `Turn.audio_url` | makes the demo video easy to cut |
| 4.10 | `voice_transcribed` / `voice_spoken` events | |

**Done when:** the criteria in [VOICE.md](VOICE.md#7-acceptance-criteria) pass.
The one to demo: speak an objective, hear the answer, speak a follow-up that
depends on the first.

---

## Phase 5 — Observability UI

Polishing the thing judges actually look at. 15% of the score is UX and the demo
story.

| # | Task |
| :-- | :--- |
| 5.1 | Migrate the SSE consumer in `page.tsx` off the legacy event names onto the catalog |
| 5.2 | Timeline component grouped by phase, collapsible, with durations |
| 5.3 | **Memory panel**: recalled hits, and the `memory_applied` sentences verbatim |
| 5.4 | Connection state indicator: live / reconnecting / replaying |
| 5.5 | Run history in the session sidebar with status chips |
| 5.6 | `?replay=run_...` — replay a stored run's timeline at speed, for the demo video |

5.6 is worth more than it looks. A deterministic replay of a real run means the
demo cannot fail live, and it makes recording the submission video trivial.

---

## Sequencing and dependencies

```
Phase 0  ──────────►  unblocks Nikunj immediately
   │
   ▼
Phase 1 (events) ──►  unblocks Lohith's tool progress events
   │                  unblocks Kushal's memory_* events
   ▼
Phase 2 (sessions) ─► unblocks multi-turn behaviour for everyone
   │
   ├──► Phase 3 (results)   ─┐
   │                         ├──► Phase 5 (UI)
   └──► Phase 4 (voice)     ─┘
```

Phases 3 and 4 are independent and can be interleaved. Phase 5 needs both.

**If time runs short, cut in this order:** 5.6, then 4.3's server TTS (keep
browser TTS), then 3.4 artifact copying (keep path references), then 5.2. Do
not cut Phase 1 or the Phase 2 security fix.

---

## Risks

| Risk | Mitigation |
| :--- | :--- |
| Refactoring the event bus breaks the working demo | Phase 1.9 shim keeps every existing call site working; the legacy graph is never touched |
| Nikunj's brain lands late or unfinished | `JARVIS_AGENT=legacy` keeps the current graph as the demo path; the runtime is agnostic |
| Voice fails on demo day (mic, network, API key) | Every failure mode degrades to text (VOICE.md section 6); `?replay=` gives a no-network fallback |
| Four people editing `frontend/src/app/page.tsx` (1723 lines) | Split it into components early in Phase 2; assign ownership per component |
| Groq speech model ids are wrong or change | Read them from the live catalog via the existing fetch in `llm/router.py`; never hardcode |
| Merge conflicts across four workstreams | The package boundaries in INTERFACES.md are per-directory; conflicts should only occur in `page.tsx`, `main.py` and `requirements.txt` |

---

## Out of scope for Farhan

Stated so nobody waits on the wrong person:

- What the agent decides to do — Nikunj
- Tool implementations, sandboxing, browser automation — Lohith
- Hindsight integration, memory recall quality, OKF — Kushal
- Auth itself (login, email verification) — already built in `server/`; the
  runtime only consumes `GET /api/auth/me`
- The landing site in `client/`

---

## First commit

Smallest change that makes the boundary real and unblocks a teammate:

1. `runtime/protocols.py`, `runtime/ids.py`, `runtime/events/catalog.py`
2. `runtime/adapters/legacy_graph.py` wrapping the current workflow
3. `runtime/testing.py` with a fake emitter and a null runner
4. `docs/INTERFACES.md` referenced from the repo README

No behaviour change, no risk, and Nikunj can start the same afternoon.
