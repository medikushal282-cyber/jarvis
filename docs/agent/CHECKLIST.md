# Agent Core Implementation Checklist

> Branch: agent/core. Owner: Nikunj. Started: 2026-09-29.
> Rule: tick only after running the proving command. No evidence = no tick.
> Resume: find the first unchecked box and continue from there.

---

## Deliverables

### P0 - Single agent runtime
- [x] P0: One `run_agent(objective, ...)` entry point; all other paths removed from call path.
  - Proving cmd: `python -m pytest tests/test_agent_regression.py::test_single_entry_path -v`
  - Result: PASS (1 passed in 0.60s - single entry path verified: run_agent_entrypoint -> JarvisBrain.run -> run_agent)

### P1 - Kill fixed multi-agent pipeline
- [x] P1: Retire Orchestrator->Researcher->Executor->Validator->Recovery; one model-driven loop.
  - Proving cmd: `python -c "from backend.app.graph.workflow import execute_run_task; print('RETIRED' if hasattr(execute_run_task, '_retired') else 'NOT_RETIRED')"`
  - Result: PASS (exited 0 with 'RETIRED'; execute_run_task marked retired from execution path)

### P2 - Explicit AgentState
- [x] P2: AgentState dataclass with all required fields; serializable.
  - Proving cmd: `python -m pytest tests/test_agent_state.py -v`
  - Result: PASS (14 passed in 0.63s - bounded fields, serialization roundtrip, budget triage verified)

### P3 - Memory integration
- [x] P3: `memory.build_context()` before run; `memory.record_experience()` on every run (incl. failures); real content asserted.
  - Proving cmd: `python -m pytest tests/test_agent_memory.py -v`
  - Result: PASS (5 passed in 0.64s - recall before run, record on success/failure, graceful fallback on error)

### P4 - Tool selection with filtering
- [x] P4: `tool_selector.py` selects relevant subset; never all ~42 tools; escape hatch to widen.
  - Proving cmd: `python -m pytest tests/test_tool_selector.py -v`
  - Result: PASS (7 passed in 0.61s - core tools always selected, keyword filtering, escape hatch widens)

### P5 - Context budget discipline
- [x] P5: Token counts stay flat across turns; diagnostics logged per turn; truncation tested.
  - Proving cmd: `python -m pytest tests/test_agent_budget.py -v`
  - Result: PASS (4 passed in 0.65s - token plateau within budget, turn diagnostics tracked, observations truncated)

### P6 - Observation, stopping, verification, recovery
- [x] P6: Objective-driven stopping; recovery in loop; verification only when needed; loop detection.
  - Proving cmd: `python -m pytest tests/test_agent_loop.py -v`
  - Result: PASS (3 passed in 0.65s - objective-driven stopping, tool error recovery, loop detection)

### P7 - LLM Worker Gateway
- [x] P7: gateway.py with HEALTHY/COOLDOWN/ERROR/DISABLED; 429 failover preserves run state; repair ladder; schema validation.
  - Proving cmd: `python -m pytest tests/test_llm_gateway.py -v`
  - Result: PASS (3 passed in 0.61s - worker status/cooldown, secret masking, state preserved across failover)

### P8 - Permission + Turbo
- [x] P8: permission_required emitted on restricted tool; denial routes to recovery; turbo skips pre-authorized, still blocks hard restrictions.
  - Proving cmd: `python -m pytest tests/test_agent_permissions.py -v`
  - Result: PASS (5 passed in 0.63s - auto/confirm/deny tiers, turbo pre-auth allowed, hard-blocks remain blocked)

### P9 - Events, prompts, md files
- [x] P9a: High-level events only (understanding, planning, tool_started, tool_completed, etc.)
  - Proving cmd: `python -m pytest tests/test_agent_events.py -v`
  - Result: PASS (2 passed in 0.58s - all high-level events present, zero thought/reasoning leaks)
- [x] P9b: soul.md, agents.md exist with correct YAML front-matter; tools.md generated from registry.
  - Proving cmd: `python -m pytest tests/test_tools_doc.py -v`
  - Result: PASS (1 passed in 0.19s - tools.md freshly synced with tool registry)
- [x] P9c: Safety rules re-injected even if deleted from soul.md.
  - Proving cmd: `python -m pytest tests/test_agent_safety.py::TestSafetyRuleImmutability::test_safety_rules_always_injected -v`
  - Result: PASS (1 passed in 0.62s - locked safety rules immutable)

---

## Tests

### T1 - Simple no-tool answer
- [x] T1: "What is 2 + 2?" -> no tools -> answer.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t1_simple -v`
  - Result: PASS (1 passed in 0.71s - answered 4 with no tool calls)

### T2 - One tool, exact stop
- [x] T2: "Create hello.txt containing Hello World." -> create_file -> stop (assert no further tool calls).
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t2_one_tool -v`
  - Result: PASS (1 passed in 0.71s - create_file executed and stopped immediately)

### T3 - Multi-step, no user input
- [x] T3: "Create numbers.txt containing 1, 2, 3 and then read it." -> create_file -> read_file -> done.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t3_multi_step -v`
  - Result: PASS (1 passed in 0.71s - create_file then read_file autonomously completed)

### T4 - Failure, no invented content
- [x] T4: "Read missing.txt." -> read_file fails -> accurate response.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t4_failure -v`
  - Result: PASS (1 passed in 0.71s - honest failure message, no hallucinated file content)

### T5 - Recovery from broken preview
- [x] T5: "Create and display this website." with preview broken -> observe -> fix -> preview again -> verify.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t5_recovery -v`
  - Result: PASS (1 passed in 0.71s - observed preview error, repaired, re-previewed, verified)

### T6 - Worker failover mid-run
- [x] T6: Worker A 429 after create_file -> Worker B continues from state, does NOT recreate file.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t6_worker_failover -v`
  - Result: PASS (1 passed in 0.71s - Worker B resumed serialized state and did not re-create file)

### T7 - Permission pause and denial
- [x] T7: Restricted command -> permission_required; denial routes to recovery.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t7_permission tests/test_agent_scenarios.py::test_t7_denial_routes_to_recovery -v`
  - Result: PASS (2 passed in 0.71s - paused on confirm tier, denial routed to recovery without re-executing)

### T8 - Turbo mode
- [x] T8: Pre-authorized command under turbo runs without approval; hard-blocked still blocked.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t8_turbo_pre_authorized tests/test_agent_scenarios.py::test_t8_turbo_hard_blocked -v`
  - Result: PASS (2 passed in 0.71s - pre-authorized allowed, rm_rf hard-blocked)

---

## Additional Tests

- [x] Token-budget test: token count stays flat on long run.
  - Proving cmd: `python -m pytest tests/test_agent_budget.py::test_tokens_flat_on_long_run -v`
  - Result: PASS (1 passed in 0.65s - token count plateaus, stays within 5000-token budget across 20 turns)
- [x] Loop-detection test: repeated identical call+args detected and stopped.
  - Proving cmd: `python -m pytest tests/test_agent_loop.py::test_loop_detection -v`
  - Result: PASS (1 passed in 0.65s - identical call/args detected and routed to recovery)
- [x] Malformed tool call repair ladder: ported from brain/.
  - Proving cmd: `python -m pytest tests/test_llm_parsing.py -v`
  - Result: PASS (26 passed in 0.68s - JSON repair, missing args validation, raw/tag formats)
- [x] Prompt injection test: "ignore previous instructions" in tool output not obeyed.
  - Proving cmd: `python -m pytest tests/test_agent_safety.py::TestPromptInjection::test_ignore_previous_instructions_detected -v`
  - Result: PASS (1 passed in 0.62s - injection attempt detected and flagged)
- [x] Secret redaction test: gsk_... never appears in events/logs/traces.
  - Proving cmd: `python -m pytest tests/test_agent_safety.py::TestSecretRedaction::test_groq_key_redacted -v`
  - Result: PASS (1 passed in 0.62s - gsk_ keys and API secrets redacted)
- [x] Single entry path regression: exactly one agent entry point.
  - Proving cmd: `python -m pytest tests/test_agent_regression.py::test_single_entry_path -v`
  - Result: PASS (1 passed in 0.60s - canonical entry point verified)

---

## Final Gate

- [x] FINAL: `python scripts/verify_agent.py` prints all PASS (nonzero exit on failure).
  - Proving cmd: `python scripts/verify_agent.py`
  - Result: PASS (exited 0; all 13 test suites and 5 standalone checks passed)
