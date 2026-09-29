# UI Notes — extracted from the design reference

Scope: what of the design reference is usable for a **Python agent brain with an optional
lightweight UI**. Written for whoever builds the trace viewer (and, if there is time, the
settings panel and the demo surface).

---

## 1. Applicability verdict

The reference is a working brief for an *artifact-producing design agent* — its core subject is
how to research a design context, propose variations, and ship a single HTML deliverable. Large
parts of it (starter components, deck scaling, tweak protocols, PPTX/PDF export, asset review
plumbing) are irrelevant to us and should be ignored outright. What **does** transfer is its
craft layer: color-and-system discipline, scale minimums, density rules, an explicit list of
AI-generated visual tells, a strict no-filler content policy, and a "verify it loads clean"
finish ritual. Those are enough to define a credible visual language for a trace viewer, and they
are worth following precisely because they are a list of things *not* to do — which is exactly
where a rushed hackathon UI goes wrong.

---

## 2. Extracted, actionable guidance

### 2.1 Color & theming

- **Do not invent a palette from nothing.** Prefer values lifted from an existing system. If none
  exists, derive harmonious steps *in a perceptual color space* (`oklch`) rather than hand-picking
  hexes: fix a base hue and vary lightness/chroma to produce the hover, active, and soft/tint
  variants. This guarantees the family reads as related instead of as four random blues.
- **One hue per meaning, and never two meanings per hue.** Reserve the accent for interaction,
  and — our addition, but in the same spirit — reserve a *dedicated* hue for memory and never
  reuse it for anything else. That single decision does more for the demo than any layout work.
- **Cap decorative color.** The reference limits a deck to one or two background treatments to
  create rhythm. Same rule here: at most one alternate surface tone for grouping, and no
  per-phase rainbow (see §5).
- **Contrast is a floor, not a preference.** 4.5:1 for body text, 3:1 for large text, icons and
  meaningful borders. Verify the token set in §3 with a contrast checker before shipping.
- **Theme from one source of truth.** Define tokens once; redefine only the values under a dark
  selector. Never let a color exist solely inside a dark block.

### 2.2 Typography & scale

- **Scale minimums the reference sets:** nothing below 24px on a 1920×1080 canvas; 12pt floor for
  print; 44px minimum hit target on touch. Translated for us: a dense console legitimately runs
  13–14px, but **anything that will be projected at the demo needs a presentation mode** that
  bumps the base to ~18–20px and event labels to ~24px. Do not demo a 12px log to a projector.
- **Avoid the default fonts.** The reference explicitly flags a set of overused families and
  generic system stacks. Pick a pairing with character — one technical sans for UI prose, one
  monospace for ids, payloads, timings and tool args. Mono is not decoration here; it is the
  correct type class for machine output, and it also makes columns align.
- **Tabular figures everywhere numbers stack** (token counts, latency, memory scores). Use
  `font-variant-numeric: tabular-nums`.
- **Tracking:** tighten large display sizes slightly; leave body near 0; open up small caps/labels.
- **Line height inversely with size:** ~1.6 for 13–16px prose, ~1.15–1.25 for 25px+.

### 2.3 Spacing, layout & density

- **4px base grid.** Every gap, pad and row height is a multiple of 4. This alone prevents the
  misaligned look that reads as unfinished.
- **Commit to a system before building.** The reference insists on choosing your few layouts and
  header/body treatments up front and then varying *within* them, rather than inventing per screen.
- **Two densities, deliberately.** Dense for the event stream (28–36px rows), generous for the
  single hero element on a screen (48–96px padding). One surface should be calm; the stream may
  be tight.
- **Fixed-size canvases scale themselves.** If we build anything with a fixed aspect (a demo
  board, a slide-like comparison), wrap it in a viewport-filling stage, letterbox it, and keep
  the controls *outside* the scaled element so they stay usable. Never rely on browser zoom.
- **Use CSS grid** for the multi-pane trace layout; it handles the collapse to one column at
  narrow widths far better than floats or flex gymnastics.
- **Use `text-wrap: pretty`** on prose blocks (final answers, plan text) to avoid orphaned words.
- **Keep files small.** The reference caps files around a thousand lines and splits rather than
  growing one monolith. For us: one HTML file plus a couple of small JS/CSS files, not one
  3000-line page.

### 2.4 Component patterns

- **Buttons:** three weights only — primary (accent fill), secondary (surface + border), ghost
  (text only). Three sizes. Visible focus ring at 2px offset in the accent. Minimum 44px hit area
  on anything touch-sized; 32–36px is acceptable for mouse-only console chrome.
- **Inputs:** label above the field (never placeholder-as-label), helper text below, error text
  below that in the danger token *plus* a glyph so the state is not carried by color alone.
- **Cards / event rows:** flat surfaces, hairline borders, one small radius family. The reference
  names the rounded-container-with-a-left-accent-bar as a tell — do not use it (§5).
- **Tables and lists:** dense rows, right-align numerics, monospace for ids and durations. If a
  table can exceed the viewport width, put it in its own horizontal scroll container rather than
  letting the page scroll sideways.
- **Empty states:** say what to do next in one line ("No events yet — run the agent to populate
  the trace"), never a joke, never an illustration. An empty pane is a layout problem, not a
  prompt to invent content.
- **Loading:** skeleton rows at the exact final row height so nothing shifts when data lands.
  Avoid long spinners.
- **Error states:** three parts — what failed, what it means, the action ("Tool `http_get` timed
  out after 5s. The agent retried once. [Show raw event]"). Collapse the raw payload behind a
  disclosure rather than dumping JSON into the main flow.

### 2.5 Motion

- **UI motion is CSS transitions and simple state, not a timeline engine.** The reference reserves
  keyframe/timeline tooling for video output. Keep interaction motion in the **120–280ms** band
  with a decelerating ease. Do not bounce, do not overshoot, do not chain.
- **The live event stream is the one place an entrance animation earns its keep.** A new row
  fading/settling in over ~180ms makes "the agent is doing something right now" legible. Everything
  else should be still.
- **Never animate something the user did not trigger, repeatedly, forever.** No infinite pulses on
  status dots.
- **Honor reduced-motion:** `@media (prefers-reduced-motion: reduce)` collapses durations to ~1ms.

### 2.6 Accessibility

The source is largely silent here beyond sizing, so treat the following as our own floor, adopted
consistently with its scale discipline:

- 44px minimum touch targets; visible focus; full keyboard reachability (the trace viewer should be
  navigable with `j`/`k` or arrows, not mouse-only).
- **Never let color carry meaning alone.** Memory-influenced steps, errors and successes each get a
  glyph *and* a text label on top of the hue. This matters doubly at a demo, where the projector
  washes out subtle tints.
- Respect `prefers-reduced-motion` and the OS light/dark preference.
- Do not scroll the whole document programmatically to reveal a new event (see §5).

### 2.7 Content & tone of UI copy

- **No filler. No invented numbers.** The reference is emphatic that padding a layout with dummy
  sections or decorative stats is a design failure, not a safety net. If a metric is not something
  the backend actually computed, it does not go on screen. This kills "AI confidence: 94%",
  decorative sparklines, and stat tiles nobody reads.
- **Ask before adding material.** Extra panels and copy are a product decision, not a build step.
- **Write copy past-tense and operational**, matching an instrument rather than an assistant:
  "Recalled 3 memories", "Calling http_get", "Tool failed — retrying (1/2)", "Wrote 2 memories".
  Short verb + object. No greetings, no personality chrome, no emoji, no exclamation marks.
- **A sparse screen is a layout problem to solve with composition** — not by adding content.

---

## 3. Design tokens we could ship

Copy-pasteable starter set. Light is the base definition; dark redefines values only. `--memory-*`
is our addition — a hue reserved exclusively for memory evidence.

```css
/* ============================================================
   JARVIS Brain UI — tokens
   Base grid 4px · type scale ~1.25 · tabular figures for numerics
   ============================================================ */

:root {
  color-scheme: light;

  /* --- surfaces --- */
  --bg:            #F7F8FA;  /* app background, cool off-white */
  --surface:       #FFFFFF;  /* cards, panels, event rows */
  --surface-2:     #F1F3F7;  /* alternate grouping surface, insets */
  --surface-3:     #E8EBF1;  /* pressed state, table header */

  /* --- borders --- */
  --border:        #DDE1E8;  /* hairlines, dividers */
  --border-strong: #C3C9D4;  /* inputs, focus-adjacent, table rules */

  /* --- text --- */
  --text:          #14171F;  /* 16.9:1 on --bg */
  --text-muted:    #5A6273;  /* 5.8:1  on --bg */
  --text-faint:    #8A92A3;  /* labels, timestamps — never for body */

  /* --- accent (interaction only) --- */
  --accent:        #3B4FD8;  /* 6.4:1 on white */
  --accent-hover:  #3243BC;
  --accent-active: #29379E;
  --accent-soft:   #EAEDFC;  /* tinted fills, selected row */
  --accent-text:   #FFFFFF;  /* text on --accent */

  /* --- memory (reserved hue — nothing else may use it) --- */
  --memory:        #7C3AED;  /* 5.7:1 on white */
  --memory-soft:   #F3EEFE;  /* memory-influenced step surface */
  --memory-line:   #C9B6FA;  /* influence connectors */

  /* --- semantic status --- */
  --success:       #157F52;  /* 5.0:1 */
  --success-soft:  #E4F4EC;
  --warning:       #9A5B00;  /* 5.4:1 */
  --warning-soft:  #FBF0DC;
  --danger:        #C42B2B;  /* 5.6:1 */
  --danger-soft:   #FCEAEA;

  /* --- typography --- */
  --font-ui:   "IBM Plex Sans", "Helvetica Neue", sans-serif;
  --font-mono: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace;

  --fs-2xs:  0.6875rem; /* 11px — badges only */
  --fs-xs:   0.75rem;   /* 12px — labels, timestamps */
  --fs-sm:   0.8125rem; /* 13px — dense rows, tool args */
  --fs-base: 0.875rem;  /* 14px — default body in the console */
  --fs-md:   1rem;      /* 16px — prose, plan text */
  --fs-lg:   1.25rem;   /* 20px — section headers */
  --fs-xl:   1.5625rem; /* 25px — pane titles */
  --fs-2xl:  1.9375rem; /* 31px — screen title */
  --fs-3xl:  2.4375rem; /* 39px — demo numerals, projected */

  --lh-tight: 1.2;      /* 25px and up */
  --lh-snug:  1.4;      /* 16–20px */
  --lh-body:  1.6;      /* 11–14px */

  --fw-regular: 400;
  --fw-medium:  500;
  --fw-semibold:600;

  /* --- spacing (4px base) --- */
  --sp-1:  4px;
  --sp-2:  8px;
  --sp-3:  12px;
  --sp-4:  16px;
  --sp-5:  20px;
  --sp-6:  24px;
  --sp-8:  32px;
  --sp-10: 40px;
  --sp-12: 48px;
  --sp-16: 64px;
  --sp-24: 96px;

  /* --- radii (restrained; an instrument, not a bubble) --- */
  --r-xs:   2px;   /* badges, micro chips */
  --r-sm:   4px;   /* inputs, buttons */
  --r-md:   6px;   /* event rows, cards */
  --r-lg:   10px;  /* panels */
  --r-full: 999px; /* status pills only */

  /* --- elevation (minimal; borders carry the work) --- */
  --shadow-1: 0 1px 2px rgba(16, 20, 28, 0.06);
  --shadow-2: 0 4px 12px rgba(16, 20, 28, 0.10);

  /* --- density --- */
  --row-h:        32px;  /* dense event row */
  --row-h-comfy:  44px;  /* expanded event row, touch-legal */
  --control-h:    32px;
  --control-h-lg: 44px;  /* touch / presentation mode */

  /* --- motion --- */
  --dur-fast: 120ms;
  --dur-base: 180ms;  /* new event row entrance */
  --dur-slow: 280ms;
  --ease-standard: cubic-bezier(0.2, 0, 0, 1);
  --ease-exit:     cubic-bezier(0.4, 0, 1, 1);

  --focus-ring: 0 0 0 2px var(--bg), 0 0 0 4px var(--accent);
}

/* ---- dark: values only, no new semantics ---- */
:root[data-theme="dark"] {
  color-scheme: dark;

  --bg:            #0E1116;
  --surface:       #161A21;
  --surface-2:     #1D222B;
  --surface-3:     #252B36;

  --border:        #2A303B;
  --border-strong: #3B4351;

  --text:          #E6E9EF;  /* 15.7:1 on --bg */
  --text-muted:    #A0A8B8;
  --text-faint:    #6E7787;

  --accent:        #8B9CFF;  /* 7.5:1 on --bg */
  --accent-hover:  #A5B2FF;
  --accent-active: #BCC5FF;
  --accent-soft:   #1C2140;
  --accent-text:   #0E1116;  /* dark text on the light accent fill */

  --memory:        #B39DFF;  /* 8.3:1 on --bg */
  --memory-soft:   #221A3D;
  --memory-line:   #4B3A80;

  --success:       #46C98A;
  --success-soft:  #10281F;
  --warning:       #F0B45A;
  --warning-soft:  #2C2314;
  --danger:        #FF7B7B;
  --danger-soft:   #331B1B;

  --shadow-1: 0 1px 2px rgba(0, 0, 0, 0.40);
  --shadow-2: 0 4px 14px rgba(0, 0, 0, 0.55);
}

/* ---- optional: presentation mode for the demo projector ---- */
:root[data-mode="present"] {
  --fs-sm:   0.9375rem; /* 15px */
  --fs-base: 1.125rem;  /* 18px */
  --fs-md:   1.25rem;   /* 20px */
  --fs-lg:   1.5rem;    /* 24px */
  --fs-xl:   2rem;      /* 32px */
  --row-h:   44px;
}
```

**Phase coloring rule (do not give nine phases nine hues):**

| Phase group | Token |
|---|---|
| RECALL, RETAIN | `--memory` |
| UNDERSTAND, PLAN, SELECT, DECIDE | `--text-muted` / `--accent` for the active one |
| CALL, OBSERVE | `--text` (neutral; these are just facts) |
| FINISH (ok) | `--success` |
| RECOVER | `--warning` |
| RECOVER (failed) / terminal error | `--danger` |

Only the *current* phase gets accent weight. History stays neutral so the eye finds the live edge.

---

## 4. Highest-value surface: the trace / event viewer

### 4.1 Why this is the one to build

Memory is a quarter of the score, and memory is invisible in a final answer. This surface is the
only artifact that makes causation visible: *this recalled fact changed this decision at step 7.*
Build it before anything else.

### 4.2 Layout: three columns, one top bar, one optional bottom rail

- **Top bar (fixed, 48–56px):** product mark, active profile name, a prominent **MEMORY ON/OFF**
  switch, run id + timestamp, and a live/paused indicator. Right side: pause, replay, compare.
- **Left rail (220–260px):** the run list — `run 01`, `run 05`, `run 12`, `run 20` with a one-line
  outcome each. Below it, event-type filters and a **lens** switch (Memory lens / Plain).
- **Center (flex, the spine):** the vertical event timeline. Newest at the **bottom**, with
  auto-follow pinned to the bottom edge — this reads like a live process, which is what it is.
  When the user scrolls up, unpin and show a "jump to live" affordance. Never programmatically
  scroll the page to chase a new row.
- **Memory lane (24–28px, immediately left of the spine):** a dedicated gutter holding small
  memory-lane nodes. This is the whole trick — see 4.4.
- **Right inspector (320–400px):** everything about the selected step — the phase, the tool and
  args, the raw event JSON (collapsed), and for memory-influenced steps, the exact recalled items
  with their scores and the text that was injected into the prompt.
- **Bottom rail (optional, collapsible):** compare mode summary — a compact numeric strip.

At narrow widths, drop the left rail first, then the inspector (move it to a bottom sheet).
The spine is the last thing to go.

### 4.3 Rendering the state machine

Draw it as a **single continuous spine**, not nine boxes. Each event is one node on the spine with
a phase chip, a one-line summary, and a duration. The spine line itself is the state machine:
it is always visible, so the reader sees the loop, not a diagram of the loop.

- **Phase chip:** uppercase, `--fs-2xs`, letter-spaced, in the group color from the table in §3.
- **Node glyph:** hollow ring for neutral, filled ring for memory-influenced, small chevron for
  LOOP back-edges.
- **Recovery is a back-edge:** when the machine loops or retries, do not draw a straight line down.
  Offset the returning segment to a second, indented track (≈16px right) so a retry is *visible*
  as a loop rather than as another row. A run that retried three times should look like it.
- **DECIDE is a branch point:** show the chosen edge inline ("continue → LOOP", "done → FINISH")
  and grey the untaken branches at `--text-faint`.
- **RETAIN closes the loop:** draw a faint connector from the RETAIN node back up to the RECALL
  node of the same run when an item written at the end is one that was recalled at the start —
  the "it learned" moment. This is the single most demo-worthy line in the UI.
- **Current phase:** the live node gets the accent and a subtle pulsing-free highlight (opacity
  step, not an animation loop). History never re-animates.
- **Run the machine events as the primary row type.** Tool calls and memory operations are
  children indented under their phase row, so the phase skeleton is always readable at a glance
  even if every child row is collapsed.

### 4.4 Making "memory influenced this step" unmistakable

Four redundant signals, because at a demo the projector kills subtlety:

1. **A memory-lane node** — a small diamond in the gutter, in `--memory`, at the y of the RECALL
   event (and again at any step that consumed a recalled item).
2. **An influence connector** — a curved SVG path from the lane node to the target step's node, in
   `--memory-line`. It is the only curve in the layout, so it draws the eye immediately.
3. **A tinted row surface** — the influenced step's row uses `--memory-soft`.
   *Explicitly not* a rounded card with a colored left border; that combination is called out in
   the reference as a generated-looking tell (§5).
4. **A glyph plus a text label** — a small ring mark and the words `memory · 3 items` in `--memory`
   at `--fs-xs`. Color is never the sole carrier.

**Hover/interaction:** hovering a memory-lane node dims every step except the ones it influenced
and thickens its connectors. This is the "watch one memory change the run" interaction and is worth
the build time on its own.

**The counterfactual line:** for each influenced step, the inspector shows one sentence of what the
step would have done without the memory, generated from the memory-off run when available. If it
is not computed, do not invent it — show nothing.

### 4.5 Memory OFF vs ON, side by side

- **Compare mode** replaces the center column with **two spines**, both driven from the same seed
  prompt: left = memory OFF, right = memory ON. A vertical rule splits them.
- **Align by step index, not by time.** Both spines start at the same y. The first index at which
  they differ gets a full-width divergence bar labeled `divergence @ step 03` — this is the moment
  judges should be looking at.
- **Lock the scroll.** One scroll container drives both spines so they cannot drift apart.
- **Scan for difference, don't read for it:** influenced rows tinted on the right, plain on the
  left. Divergence bars at each further fork.
- **Summary strip below**, numbers right-aligned with tabular figures:

  | | memory OFF | memory ON |
  |---|---|---|
  | steps | 19 | 14 |
  | tool calls | 6 | 4 |
  | retries | 3 | 1 |
  | elapsed | 4.9s | 3.4s |
  | answer | "Tomorrow 3pm. (no timezone)" | "Tomorrow 3pm IST" |

  Only include rows you actually measure. Delete the rest.

- **Three-run narrative is a run selector, not a second app.** `run 01 / run 05 / run 20` live in
  the left rail and load the corresponding trace. Selecting two of them turns on compare mode.
  That collapses the "demo UI" surface entirely into this one.

### 4.6 ASCII wireframe

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ JARVIS · BRAIN TRACE    profile: analyst ▾    MEMORY [ ●ON ]    run 05 · 12:04:11    ● LIVE│
│ step 14/22   elapsed 3.4s   tokens 8.1k          [ ⏸ pause ] [ ↺ replay ] [ ⇄ COMPARE ]    │
├──────────┬─────┬────────────────────────────────────────────┬─────────────────────────────┤
│ RUNS     │ MEM │  EVENT SPINE                               │  INSPECTOR                  │
│          │ LANE│                                            │                             │
│ run 01   │     │  ○ RECALL                                  │  step 14 · OBSERVE          │
│  generic │  ◆──┼─▶ recalled 3 items                         │  ─────────────────────────  │
│          │     │     · prefers terse replies      0.91      │  tool    http_get           │
│ run 05 ◀ │     │     · works in IST               0.84      │  args    { url, tz: "IST" } │
│  personal│     │     · dislikes emoji             0.77      │  status  200 · 412ms        │
│          │     │                                            │  ─────────────────────────  │
│ run 12   │     │  ○ UNDERSTAND                              │  MEMORY USED IN THIS STEP   │
│          │     │     intent: check_schedule                 │   ◉ prefers terse replies   │
│ run 20   │     │                                            │     0.91 · injected L4      │
│  knows   │     │  ○ PLAN                                    │   ◉ works in IST  0.84      │
│  you     │     │     1. read calendar                       │     0.84 · injected L7      │
│          │  ◆──┼─▶ 2. resolve timezone   ◀ memory           │  ─────────────────────────  │
│ FILTER   │     │     3. summarize                           │  raw event JSON        ▾    │
│ ☑ recall │     │                                            │  { "type": "tool_result",   │
│ ☑ plan   │     │  ○ SELECT    http_get                      │    "ok": true, "ms": 412 }  │
│ ☑ tool   │     │  ● CALL      http_get(?tz=IST)             │                             │
│ ☑ memory │     │  ● OBSERVE   200 · 412ms · 3 events        │                             │
│ ☐ raw    │     │  ○ DECIDE    continue → LOOP               │                             │
│          │     │  ⤸ RECOVER   retry #1 (timeout)  ↰         │                             │
│ LENS     │     │  ○ FINISH    answer ready                  │                             │
│ ● memory │  ◆──┼─▶ ● RETAIN   wrote 2 items                  │                             │
│ ○ plain  │     │                                            │                             │
├──────────┴─────┴────────────────────────────────────────────┴─────────────────────────────┤
│ ⇄ COMPARE   MEMORY OFF ─────────────────┬─ divergence @ step 03 ─┬────── MEMORY ON         │
│  steps 19   tools 6   retries 3   4.9s  │                        │  steps 14  tools 4  1 rot│
│  "Tomorrow 3pm. (no timezone)"          │                        │  "Tomorrow 3pm IST"      │
└───────────────────────────────────────────────────────────────────────────────────────────┘

LEGEND   ○ neutral step    ● memory-influenced step    ◆ memory-lane node
         ─▶ influence connector (drawn as a curve in the real UI)
         ⤸  back-edge / retry, offset to the right so loops read as loops
```

### 4.7 Implementation notes that save time

- **One event schema, one renderer.** If the brain already emits structured events (state
  transition, plan, tool call, tool result, memory recalled, memory influenced, recovery, answer),
  the viewer is a list component plus a reducer. Give every event a stable `id`, `step`, `phase`,
  `ts`, `parent_id`, and an optional `memory_refs: [{id, score, text}]` array. The `memory_refs`
  field is what makes 4.4 trivial — insist on it in the backend.
- **Transport:** a Server-Sent Events endpoint or a `GET /events?since=` poll over the JSONL run
  log. SSE is a few lines in FastAPI and gives the "live" feel for free.
- **Replay is the same code path** as live: feed historical events through the same reducer with a
  timer. Do not write two viewers.
- **Reuse the token block in §3 verbatim** so the viewer, the settings panel and anything else
  look like one product.

---

## 5. What NOT to do

Tempting, and wrong:

1. **Rounded card + colored left accent bar** to mark memory-influenced steps. Named in the
   reference as a generated-looking tell. Use a tinted surface plus a gutter glyph and a connector.
2. **Glow, neon and heavy gradients.** "JARVIS-style" invites a holographic HUD with radial glows
   and scanlines. The reference explicitly warns against aggressive gradient backgrounds.
   Restraint reads as competence; glow reads as a template.
3. **Emoji as event icons or status marks.** The reference confines emoji to brands that already
   use them. A robot or sparkle glyph per event is the single most recognizable tell in a
   generated UI. Use typographic marks or nothing.
4. **Drawing illustrations in SVG** to fill a pane. The reference prefers an honest placeholder to
   a bad imitation. (Small single-color functional glyphs for node types are fine — they are an
   affordance, not illustration.)
5. **Filler content and decorative metrics.** No invented confidence scores, no stat tiles, no
   sparklines that no one reads. If the backend did not compute it, it does not appear.
6. **A title screen or splash.** The reference says to resist adding a title screen. A live tool
   opens on the live thing.
7. **Overused typefaces and the generic system stack.** Pick a real pairing.
8. **A nine-color state machine.** One hue per phase is color slop and destroys the "current step"
   emphasis. Group the phases (§3).
9. **A marketing landing page for the hackathon.** Nobody is buying anything; build the instrument.
10. **Animating everything.** Status dots that pulse forever, rows that slide in on a loop, hover
    effects with long durations. Motion should be short, purposeful, and user-triggered.
11. **Programmatic scroll jumps to reveal new content.** The reference bans a specific
    scroll-into-view call for good reason — it hijacks the reader's position. Manage the scroll
    container's own offset instead, and only when the user has not scrolled away.
12. **One giant HTML file.** Split it before it passes ~1000 lines.
13. **Nine phases rendered as nine separate boxes in a flowchart.** That is an architecture
    diagram, not a live view. The spine is the state machine.
14. **Screenshots as the source of truth for how something should look.** Work from tokens and
    code, not from a picture.

---

## 6. Honest effort estimate and cut line

Estimates assume one person who knows the codebase, working inside a hackathon.

### Surface 1 — Trace / event viewer

| Version | Effort | Contents |
|---|---|---|
| Minimum viable | **2–3 h** | One HTML file, SSE or poll endpoint, vertical event list, phase chips, live tail, raw JSON drawer |
| Strong | **+2–3 h** | Memory lane + influence connectors, tinted influenced rows, inspector pane with memory scores, replay scrubber |
| Demo-grade | **+2–3 h** | Compare mode (OFF vs ON, aligned spines, divergence bar, summary strip), run selector, presentation mode |

**Verdict: build it.** Even the 2–3 hour version beats having no UI. If only one thing ships, this
is it.
**Insurance:** a `rich`-based terminal renderer is roughly **1 hour** of work and covers maybe 60%
of the storytelling. Build it as a fallback for when the browser or the venue's projector fails
mid-demo — but do not use it as the primary.

### Surface 2 — Settings panel

Reality check: the panel is the *thin* part. Real work is config parsing, validation, hot reload
and profile switching — all backend. A real editor with validation, per-file error surfacing and
atomic reload is **5–7 h** for a surface no judge will score.

| Version | Effort | Verdict |
|---|---|---|
| `GET /config` + `POST /config/reload` + a CLI command | **1 h** | Do this regardless |
| Read-only viewer of current config in the trace UI | **+1 h** | Cheap if the shell exists |
| Full editing panel with validation | **5–7 h** | Skip |

**Verdict: cut the panel.** Ship the endpoint and the CLI. If there is spare time at the very end,
a read-only config viewer tab is the only part worth adding.

### Surface 3 — Demo UI (run 1 vs run 5 vs run 20)

A standalone scripted demo app is **6–10 h** and is the most fragile artefact you can build: it
needs seeded state, deterministic runs, and choreography, and it breaks on stage.

**Do not build it as a separate surface.** Collapse it into Surface 1: the run list in the left
rail *is* the run-1/5/20 narrative, and compare mode *is* the side-by-side. Cost of that collapse:
**about +1 h** on top of Surface 1's strong version, because it is a selector and a second spine,
not a new app.

### Recommended cut line

```
MUST SHIP ── Surface 1: minimum viable + memory lane + influence connectors + inspector
             Backend config-reload endpoint + CLI   (replaces Surface 2)
             Run selector 01 / 05 / 20 in the left rail   (replaces Surface 3)
             ── roughly 5–7 h total

IF TIME   ── Surface 1 compare mode (OFF vs ON, divergence bar, summary strip)   +2–3 h
             Rich terminal fallback renderer (insurance)                          +1 h

CUT       ── Settings panel UI
             Standalone demo app
             Any dashboard, chart, or extra pane not listed above

NEVER     ── Auth, routing, a build step, a marketing page, extra dependencies
```

The one non-negotiable: **the memory lane and its influence connectors.** Everything else in
Surface 1 is a nice log viewer. Those two elements are the argument.
