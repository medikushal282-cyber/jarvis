# Farhan — Interface, Voice, Sessions, Events: Plan

**Owner:** Farhan · **Code:** `frontend/`, `backend/app/runtime/`, and the
session / run / voice / worker API routes · **Contract:** [INTERFACES.md](../INTERFACES.md)

Farhan turns JARVIS's execution into something a person can see and hear. He
does not decide what JARVIS does (Nikunj), how actions run or whether they are
allowed (Lohit), or what it remembers (Kushal).

**Definition of done:** the user speaks or types, sees progress, approves or
denies actions, can switch on Turbo, sees worker status, opens artifacts and
previews, and hears the reply.

---

## How the work is sequenced

The UI is built against the **event contract**, not against teammates' code.
`JARVIS_AGENT=scripted` runs a fake brain that emits every event in a
realistic order, so each phase can be finished and tested before the real
brain, tools and gateway emit everything. When their code lands, switching
back to `core` needs no UI change.

| Phase | Goal | Status |
| :--- | :--- | :--- |
| 0 | Safety and shared contracts | **Done** |
| 1 | One event flow in the frontend | **Done** |
| 2 | Permissions and Turbo | Next — needs 3.5 sign-off from Nikunj and Lohit |
| 3 | Worker panel and switching | **Done** |
| 4 | Artifacts and preview | **Done** |
| 5 | Voice end to end | **Done** |
| 6 | Acceptance tests | |

---

## Phase 0 — Safety and shared contracts (done)

- `backend/data/workers.json` (plain-text worker API keys) untracked and
  git-ignored; `sync.bat` would have pushed the first key anyone added.
- Catalog: `permission_required` / `permission_granted` / `permission_denied`,
  `worker_switching`, `artifact_created`. The old `approval_*` names still
  arrive, renamed.
- `execution_mode` ("normal" | "turbo") on `RunRequest`, `ToolContext` and the
  run record, accepted by both run APIs and validated.
- Artifact ids made deterministic, so a link handed out mid-run keeps working.
- Scripted runner (`runtime/adapters/scripted.py`) with four scenarios, plus 12
  tests.
- Contract written up in INTERFACES.md sections 3.5 to 3.7.

## Phase 1 — One event flow in the frontend (done)

The refactor everything else sits on.

Shipped: `lib/runtime/runReducer.ts` (14 unit tests), `useRun`, `useSessions`,
`components/Workspace/*`, `components/Voice/VoiceDock.tsx`; `page.tsx` went
from 1,411 lines to about 250. Verified in a real browser with
`backend/scripts/e2e_ui.py` (18 checks). The UI tolerates the current brain's
event shapes (`arguments`, no `call_id`, tool names in `browser_action`),
listed for Nikunj in INTERFACES.md section 6.

- `runReducer`: one pure function from events to a single run state (status,
  progress steps, artifacts, pending permission, worker, reply, error). It
  understands both the new event names and the old ones. Unit tested.
- Split the 1,400-line `page.tsx` into components that only read that state:
  `Conversation`, `ProgressSteps`, `Composer`, `PermissionPrompt`,
  `ArtifactCards`, `WorkerPanel`.
- Show high-level progress ("Reading project files…"), never model reasoning.
  Remove the inspector and the raw-thought display.
- One API base URL instead of 19 hard-coded ones; move from `/api/sandbox/*`
  to `/api/sessions`.

## Phase 2 — Permissions and Turbo

- Backend approval channel (`runtime/approvals.py`): request, emit, wait in the
  same run, resolve from `POST /api/runs/{run_id}/permissions/{request_id}`,
  time out to "deny".
- `PermissionPrompt` (Allow / Deny) and a Turbo switch labelled "Automatically
  approve actions covered by your permissions".
- Scripted "permission" scenario; tests for allow, deny, timeout and Turbo.

## Phase 3 — Workers (done)

Shipped: the worker panel shows READY / COOLDOWN (with countdown) /
DISABLED, and can add, test, pause, reorder, reset and remove workers; the
badge reflects pool health. The test endpoint passes the key to the call
instead of the process environment and returns a plain reason, never the
raw provider error. Inputs are validated. The UI shows a worker switch only
when the worker actually changes (the gateway announces one before every
call). 9 API tests; `scripts/e2e_ui.py` now covers the panel (25 checks),
run through `scripts/e2e_backend.py`, which isolates the worker file.

- Check `WorkerPoolControl` against the brief: provider, model, key hint only,
  priority, enabled, test connection.
- Live status: READY / COOLDOWN / ERROR / DISABLED.
- `worker_switching` shown inline as "Switching worker… continuing".

## Phase 4 — Artifacts and preview (done)

Shipped: one compact artifact card (kind, name, size, Open / Download)
replacing three overlapping components. Produced files are located wherever
the tools wrote them (sandbox folder or the tool workspace root, containment
checked), and a copy is captured into the run folder when the run ends, so a
later overwrite does not change what the run shows. Every API response goes
through `public_result` / `public_artifact`: no filesystem paths. Artifacts
announced by the tool registry (`url`/`download_url`) merge with the file
event into one card. 9 backend tests, 2 reducer tests, 27 browser checks.
Blocked on others: the filesystem tool's `artifact_created` never arrives
(INTERFACES.md section 6).

- One artifact card, driven by `artifact_created`, replacing the three
  overlapping components.
- Strip filesystem paths from every API response; secure URLs only.
- "Open Preview" for sites, opening `BrowserPreview` inside JARVIS.

## Phase 5 — Voice end to end (done)

Shipped: Whisper model ids verified against Groq's live list (dead fallback
removed); server TTS repointed from the retired PlayAI to Orpheus (needs a
one-time terms acceptance by the Groq org admin); a visible voice indicator
LISTENING → TRANSCRIBING → EXECUTING → SPEAKING → IDLE; `voice_transcribed`
on voice runs with the transcript's confidence kept on the turn. Fixed: run
attachments were accepted and then dropped before reaching the brain.
Verified with a real Whisper call and `scripts/e2e_voice.py` (a WAV as the
browser microphone, 10 checks); a headless browser's missing TTS voices do
not fail the run. `voice_spoken` is not emitted (speech is client-side).

- A real Whisper round trip with a real key; confirm the model ids.
- Visible LISTENING → EXECUTING → SPEAKING → IDLE state.
- A speech failure never marks the run failed; the text reply always shows.
- Emit `voice_transcribed` / `voice_spoken`; keep mic state out of `page.tsx`.

## Phase 6 — Acceptance

The brief's tests, run against the scripted runner, then one real run: text,
voice, permission allow and deny, Turbo, worker failover, artifact and preview.

---

## Working rules

- Only touch `frontend/`, `backend/app/runtime/` and the session, run, voice
  and worker routes. Changes to shared contracts go through INTERFACES.md.
- One commit per phase; merge `main` in before every push.
- Frontend checks use `tsc --noEmit`. `next build` only after confirming no
  `npm run dev` is running in `frontend/`. If the UI ever loads unstyled: stop
  Next, delete `frontend/.next`, restart dev.
- The older backend tests write into the repo root. After a full test run,
  restore `autonomy_recovery_test.py` and `script.js` before committing.
