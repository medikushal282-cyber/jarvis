# Runtime — Results and Artifacts

**Owner:** Farhan · **Package:** `backend/app/runtime/results/`

> "I tell it what I want, it does it, then I can see what it completed."

The last clause is this layer. When a run ends, the user gets one screen that
answers: what did you do, what did you make, what went wrong.

---

## 1. The core idea: results are derived, not reported

The result is **built by replaying the run's event log**. The agent does not
assemble it and hand it over.

This is what keeps the dependency arrow clean. The brain's only obligation is to
emit honest events; the report follows for free. Three practical wins:

- Nikunj can rewrite the brain entirely and the result panel keeps working.
- Lohith can add a tool and its artifacts appear without touching this code, as
  long as it emits `file_created` or returns `ToolResult.artifacts`.
- A run that crashed halfway still produces a result, because the events up to
  the crash are on disk.

```
events.ndjson  ──►  ResultBuilder (a reducer)  ──►  result.json
```

---

## 2. `RunResult` schema

```jsonc
{
  "run_id": "run_9f3c21a8",
  "session_id": "ses_4b1e77c0d219",
  "status": "completed",              // completed | failed | cancelled | rejected
  "objective": "Create a presentation on IPsec",
  "summary": "Created a 12-slide IPsec deck from 14 project files.",

  "started_at": "2026-09-29T11:02:10.004Z",
  "ended_at":   "2026-09-29T11:04:51.882Z",
  "duration_ms": 161878,

  "actions": [
    { "kind": "read",    "label": "Read 14 project files",       "count": 14 },
    { "kind": "memory",  "label": "Recalled 3 past experiences", "count": 3  },
    { "kind": "create",  "label": "Generated presentation",      "count": 1  },
    { "kind": "verify",  "label": "Validated 12 slides",         "count": 12 },
    { "kind": "command", "label": "Ran 2 commands",              "count": 2  }
  ],

  "artifacts": [
    {
      "id": "art_1a2b3c",
      "type": "file",                 // file | url | image | data
      "name": "IPsec-Sentinel.pptx",
      "path": "decks/IPsec-Sentinel.pptx",
      "bytes": 482113,
      "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      "action": "created",            // created | modified | deleted
      "preview_url": "/api/runs/run_9f3c21a8/artifacts/art_1a2b3c",
      "created_at": "2026-09-29T11:04:40.119Z"
    }
  ],

  "files_created":  ["decks/IPsec-Sentinel.pptx"],
  "files_modified": ["README.md"],
  "files_deleted":  [],
  "urls_opened":    ["http://localhost:8000/api/preview/default/index.html"],
  "commands":       [ { "command": "python build_deck.py", "exit_code": 0, "duration_ms": 8412 } ],

  "memory": {
    "recalled": 3,
    "applied":  [ "Skipped pip install; it failed on this workspace last time." ],
    "recorded": "exp_77ab21c9"
  },

  "verification": { "valid": true, "reason": "12 slides present, opens cleanly",
                    "checks": [ { "name": "file_exists", "passed": true } ] },

  "errors": [],
  "event_count": 184
}
```

`files_created` and friends are flat convenience lists for the UI; `artifacts`
is the rich view. Both are derived from the same events.

---

## 3. Reducer table

`runtime/results/builder.py` is a pure function: `List[Event] -> RunResult`.
Pure means testable with a fixture ndjson and no running agent — write those
tests, they are the cheapest insurance in this project.

| Event | Effect on the result |
| :--- | :--- |
| `run_started` | `objective`, `started_at`, model/provider |
| `file_created` | append artifact (`action: created`), append `files_created` |
| `file_updated` | append artifact (`action: modified`), append `files_modified` |
| `file_deleted` | append `files_deleted` |
| `file_read` | increment the `read` action counter |
| `command_completed` | append to `commands`; increment `command` counter |
| `browser_action` where `action == "open"` | append `urls_opened`, artifact of type `url` |
| `tool_completed` | increment the counter for that tool's action kind |
| `tool_failed` | append to `errors` |
| `memory_recalled` | `memory.recalled += len(hits)` |
| `memory_applied` | append to `memory.applied` |
| `memory_recorded` | `memory.recorded = experience_id` |
| `verification_completed` | set `verification` |
| `run_completed` | `status`, `summary`, `ended_at` |
| `run_failed` | `status: failed`, append to `errors`, `ended_at` |

Action labels are generated from counters by a small pluralisation helper, so
"Read 14 project files" is not hand-written by the agent. Keep them in a single
`ACTION_LABELS` dict so wording stays consistent.

### Dedupe rules

- Same path created then updated twice → one artifact, `action: created`,
  latest size. Do not show three rows.
- A file created then deleted in the same run → keep it, `action: deleted`, so
  the user sees it happened.
- Artifacts are keyed by normalised relative path.

---

## 4. Artifact storage

For a hackathon demo, a path reference is usually enough — the file is in the
workspace and the preview server can serve it. But two cases need a copy:

- The agent overwrote the file later in the run and the user wants the version
  the run produced.
- The workspace is a scratch sandbox that gets cleaned.

So: artifacts under a configurable size (default 10 MB) are **hard-linked**
(falling back to copy) into `sandbox/<ws>/runs/<run_id>/artifacts/`. Hard links
cost nothing on the same volume and survive later overwrites of the original.

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/api/runs/{id}/result` | The `RunResult` |
| `GET` | `/api/runs/{id}/artifacts` | Just the artifact list |
| `GET` | `/api/runs/{id}/artifacts/{artifact_id}` | Download/serve the bytes, correct `Content-Type` |
| `GET` | `/api/sessions/{id}/artifacts` | Everything produced across the session |

Serving artifacts goes through `resolve_within` (see [SESSIONS.md](SESSIONS.md))
— it is a file-serving endpoint keyed by user input, which is exactly the shape
of a directory-traversal bug.

`Content-Disposition: inline` for previewable types, `attachment` otherwise, and
a strict `Content-Security-Policy` on any HTML artifact, since the agent
generates HTML and it is served from our origin.

---

## 5. Live results, not just final ones

The result builder runs **incrementally** as events arrive, not only at the end.
`GET /api/runs/{id}/result` on a running run returns the partial result. This
makes the artifact panel fill in live rather than appearing all at once at the
end, which is a meaningfully better demo for 15% of the judging weight.

Implementation: keep a `ResultBuilder` instance per active run, feed it each
event as it is published, snapshot on request, persist on terminal.

---

## 6. UI contract

The run-result panel in `frontend/` renders from `RunResult` alone. It must not
read agent state. Today `page.tsx:499` does
`fetch('/api/runs/{id}')` and reads `state.artifacts` — that is reaching into
the brain's internals and it breaks the moment Nikunj's implementation lands.
Replace it with `/api/runs/{id}/result`.

Panel layout, in priority order:

1. **Summary line** — status chip, one-sentence summary, duration.
2. **Artifacts** — the "here is what I made" row, with click-to-open.
3. **Actions** — the plain-language bullet list.
4. **Memory** — recalled / applied / recorded, with the `applied` sentences
   shown verbatim. This is the panel that earns the Hindsight marks.
5. **Errors** — collapsed unless non-empty.
6. **Full timeline** — collapsed, the raw event list for the curious.

---

## 7. Acceptance criteria

1. `ResultBuilder` has unit tests driven by fixture ndjson files, no agent.
2. A run killed mid-flight still yields a result with partial artifacts.
3. Creating then twice updating one file yields exactly one artifact row.
4. `GET /api/runs/{id}/artifacts/../../../etc/passwd` returns 400.
5. The artifact panel fills in during the run, not only at the end.
6. Replaying a stored `events.ndjson` reproduces `result.json` byte-identically.
