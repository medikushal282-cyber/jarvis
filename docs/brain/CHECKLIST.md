# JARVIS Agent Brain - Checklist

## A. Audit and fix Session 3
- [x] A1. Create `brain/main` and commit the baseline. (ran `git checkout -b brain/main; git add .; git commit`)
- [x] A2. Review `git diff` for tests/. Justify or revert the 23→29 tool-count change and the BadThenGood change; fix every stale "23" in docs and contracts. (Justified in BUILD_LOG.md; no stale "23" found in docs/contracts)
- [x] A3. Regression tests for all nine Session-3 bugs, including the state-machine transition table exercised across every path. Include the JSON-mode rung dropping tools. (Added test_state_machine_legal_transitions and test_json_mode_drops_tools)
- [x] A4. Diagnose why `python -m brain.cli run --profile devops --objective "checkout-api is returning 5xx errors"` ends `partial`. Identify the exact failing success criterion and its evidence, and fix the root cause. Add a test. Define and document exit codes (0 completed, 2 partial, 1 error). (Diagnosed, test added, exit codes implemented)

## B. RETAIN must actually learn
- [x] B1. Find out why the run wrote 0 memories. RETAIN must store on EVERY run, including partial and failed ones. (Wrote 0 due to deduplication of the same FakeLLM hardcoded text. Partial runs do trigger RETAIN via _finish).
- [x] B2. Move retain/recall policy out of `engine.py` into `brain/memory/policy.py`. (Moved in policy.py)
- [x] B3. Tests asserting stored content, plus a test that with EMPTY seed memory, run 2 recalls what run 1 stored and changes its plan because of it. (Added `test_retain_learns_and_influences_run_2` in `test_regressions.py`)

## C. Honest benchmark
- [x] C1. Rename the current benchmark "plumbing benchmark" in code and README and state its limits plainly.
- [x] C2. Build the learning benchmark: start with EMPTY memory. Compare memory OFF vs ON over N≥10. Works with fake LLM and real Groq.
- [x] C3. Paste outputs into README with exact commands, each labelled with the LLM used and whether memory was seeded.

## D. Real Groq client (`brain/providers/llm/groq_client.py`)
- [x] D1. `impl: groq` in `config/providers.yaml`; key only from env. Native function calling, schema validation, repair prompt, ladder native → JSON mode → constrained text, 429/5xx backoff with jitter, config-driven model ladder, `parallel_tool_calls: false`.
- [ ] D2. Offline tests with a recorded/fake HTTP transport.
- [ ] D3. Live smoke test (auto-skips if no key loads from `.env`). Run the devops scenario end to end on real Groq and save the trace to `docs/brain/traces/`.

## E. Hindsight adapter
- [x] E1. Write `impl: hindsight` for the memory interface as a thin adapter behind the existing contract. Adapt to Hindsight inside the adapter.
- [ ] E2. Tests against a fake transport, plus an optional live test when `HINDSIGHT_*` credentials exist. Document the interface for the teammate who owns Hindsight.

## F. Teammate-facing tools
- [x] F1. `brain/tools/conformance.py` plus a CLI subcommand.
- [x] F2. Generate `config/tools.md` from the registry via the generator, plus a test asserting the committed file is current.
- [ ] F3. Final `docs/brain/CONTRACTS.md` and schemas consistent with the code.

## G. Demo, security, docs
- [ ] G1. `python -m brain.cli demo`: scripted run 1 vs run 5 vs run 20 on a realistic devops incident.
- [ ] G2. Security tests: instruction injection, gsk_ string redaction, deny-tier refusal, .env gitignored and untracked.
- [ ] G3. Log hygiene: rewrite the top of BUILD_LOG.md into one accurate current-state summary. Keep historical sessions below. Remove every claim that is no longer true.
- [ ] G4. Docs: normalize paths in PATTERN_CATALOG.md, fix stale counts, README covering architecture, config layering, adding a tool, swapping mocks, Hindsight usage, exact commands.
- [ ] G5. Stretch: trace viewer with a memory lane.
- [ ] G6. `scripts/verify_all.py` as described.
