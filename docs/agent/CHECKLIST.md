# Agent Core Implementation Checklist

> Branch: agent/core. Owner: Nikunj. Started: 2026-09-29.
> Rule: tick only after running the proving command. No evidence = no tick.
> Resume: find the first unchecked box and continue from there.

---

## Deliverables

### P0 - Single agent runtime
- [ ] P0: One `run_agent(objective, ...)` entry point; all other paths removed from call path.
  - Proving cmd: `python -m pytest tests/test_agent_regression.py::test_single_entry_path -v`
  - Result: PENDING

### P1 - Kill fixed multi-agent pipeline
- [ ] P1: Retire Orchestrator->Researcher->Executor->Validator->Recovery; one model-driven loop.
  - Proving cmd: `python -c "from backend.app.graph.workflow import execute_run_task; print('RETIRED' if hasattr(execute_run_task, '_retired') else 'NOT_RETIRED')"`
  - Result: PENDING

### P2 - Explicit AgentState
- [ ] P2: AgentState dataclass with all required fields; serializable.
  - Proving cmd: `python -m pytest tests/test_agent_state.py -v`
  - Result: PENDING

### P3 - Memory integration
- [ ] P3: `memory.build_context()` before run; `memory.record_experience()` on every run (incl. failures); real content asserted.
  - Proving cmd: `python -m pytest tests/test_agent_memory.py -v`
  - Result: PENDING

### P4 - Tool selection with filtering
- [ ] P4: `tool_selector.py` selects relevant subset; never all ~42 tools; escape hatch to widen.
  - Proving cmd: `python -m pytest tests/test_tool_selector.py -v`
  - Result: PENDING

### P5 - Context budget discipline
- [ ] P5: Token counts stay flat across turns; diagnostics logged per turn; truncation tested.
  - Proving cmd: `python -m pytest tests/test_agent_budget.py -v`
  - Result: PENDING

### P6 - Observation, stopping, verification, recovery
- [ ] P6: Objective-driven stopping; recovery in loop; verification only when needed; loop detection.
  - Proving cmd: `python -m pytest tests/test_agent_loop.py -v`
  - Result: PENDING

### P7 - LLM Worker Gateway
- [ ] P7: gateway.py with HEALTHY/COOLDOWN/ERROR/DISABLED; 429 failover preserves run state; repair ladder; schema validation.
  - Proving cmd: `python -m pytest tests/test_llm_gateway.py -v`
  - Result: PENDING

### P8 - Permission + Turbo
- [ ] P8: permission_required emitted on restricted tool; denial routes to recovery; turbo skips pre-authorized, still blocks hard restrictions.
  - Proving cmd: `python -m pytest tests/test_agent_permissions.py -v`
  - Result: PENDING

### P9 - Events, prompts, md files
- [ ] P9a: High-level events only (understanding, planning, tool_started, tool_completed, etc.)
  - Proving cmd: `python -m pytest tests/test_agent_events.py -v`
  - Result: PENDING
- [ ] P9b: soul.md, agents.md exist with correct YAML front-matter; tools.md generated from registry.
  - Proving cmd: `python -m pytest tests/test_tools_doc.py -v`
  - Result: PENDING
- [ ] P9c: Safety rules re-injected even if deleted from soul.md.
  - Proving cmd: `python -m pytest tests/test_agent_safety.py::test_safety_rules_immutable -v`
  - Result: PENDING

---

## Tests

### T1 - Simple no-tool answer
- [ ] T1: "What is 2 + 2?" -> no tools -> answer.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t1_simple -v`
  - Result: PENDING

### T2 - One tool, exact stop
- [ ] T2: "Create hello.txt containing Hello World." -> create_file -> stop (assert no further tool calls).
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t2_one_tool -v`
  - Result: PENDING

### T3 - Multi-step, no user input
- [ ] T3: "Create numbers.txt containing 1, 2, 3 and then read it." -> create_file -> read_file -> done.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t3_multi_step -v`
  - Result: PENDING

### T4 - Failure, no invented content
- [ ] T4: "Read missing.txt." -> read_file fails -> accurate response.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t4_failure -v`
  - Result: PENDING

### T5 - Recovery from broken preview
- [ ] T5: "Create and display this website." with preview broken -> observe -> fix -> preview again -> verify.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t5_recovery -v`
  - Result: PENDING

### T6 - Worker failover mid-run
- [ ] T6: Worker A 429 after create_file -> Worker B continues from state, does NOT recreate file.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t6_worker_failover -v`
  - Result: PENDING

### T7 - Permission pause and denial
- [ ] T7: Restricted command -> permission_required; denial routes to recovery.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t7_permission -v`
  - Result: PENDING

### T8 - Turbo mode
- [ ] T8: Pre-authorized command under turbo runs without approval; hard-blocked still blocked.
  - Proving cmd: `python -m pytest tests/test_agent_scenarios.py::test_t8_turbo -v`
  - Result: PENDING

---

## Additional Tests

- [ ] Token-budget test: token count stays flat on long run.
  - Proving cmd: `python -m pytest tests/test_agent_budget.py::test_tokens_flat -v`
  - Result: PENDING
- [ ] Loop-detection test: repeated identical call+args detected and stopped.
  - Proving cmd: `python -m pytest tests/test_agent_loop.py::test_loop_detection -v`
  - Result: PENDING
- [ ] Malformed tool call repair ladder: ported from brain/.
  - Proving cmd: `python -m pytest tests/test_llm_parsing.py -v`
  - Result: PENDING
- [ ] Prompt injection test: "ignore previous instructions" in tool output not obeyed.
  - Proving cmd: `python -m pytest tests/test_agent_safety.py::test_prompt_injection -v`
  - Result: PENDING
- [ ] Secret redaction test: gsk_... never appears in events/logs/traces.
  - Proving cmd: `python -m pytest tests/test_agent_safety.py::test_secret_redaction -v`
  - Result: PENDING
- [ ] Single entry path regression: exactly one agent entry point.
  - Proving cmd: `python -m pytest tests/test_agent_regression.py::test_single_entry_path -v`
  - Result: PENDING

---

## Final Gate

- [ ] FINAL: `python scripts/verify_agent.py` prints all PASS (nonzero exit on failure).
  - Result: PENDING
