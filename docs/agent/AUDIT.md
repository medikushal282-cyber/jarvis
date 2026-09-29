# JARVIS Agent Codebase Audit

> Written: 2026-09-29. Branch: agent/core. Author: Nikunj (Brain/Agent lead).

---

## 1. Entry Point and Run Start

**Two competing entry paths exist today:**

| Path | File | Function | Status |
|------|------|----------|--------|
| **A – Newer (Brain)** | `backend/app/agent/brain.py` | `JarvisBrain.run(request, emit)` -> `run_agent_loop(...)` | KEEP - canonical |
| **B – Older (Graph/Workflow)** | `backend/app/graph/workflow.py` | `execute_run_task(...)` | RETIRE from call path |

**Objective representation:** `RunRequest.objective` (str, from `backend/app/runtime/protocols.py`).

### JarvisBrain.run flow (Path A)
1. `memory_bridge.recall(user_id, objective, session_id, workspace_id)` -> Dict
2. `run_agent_loop(request, emit, memory_context)` -> RunOutcome
3. If `outcome.ok`: `memory_bridge.record(user_id, run_id, objective, outcome)` -> str

---

## 2. LLM Call Chain

```
run_agent_loop()
  -> asyncio.to_thread(call_llm, system, user, model, provider, tools, emit)
     -> call_llm() [backend/app/llm/router.py]
        -> load_workers() from backend/data/workers.json
        -> for healthy worker (sorted by priority, cooldown_until <= now):
             call_litellm(system, user, w_model, w_prov, tools)
               -> litellm.completion(**kwargs)
               -> renders native tool_calls as <tool_call>JSON</tool_call>
```

### Tool schema exposure
- `select_tools_for_objective(objective, has_attachments, active_tools_history)`
- Returns OpenAI-format tool definitions, filtered subset from ToolRegistry
- Core always included: `list_directory, read_file, create_file, update_file, run_command`

### Model requests a tool
Model outputs: `<tool_call>\n{"name": "...", "arguments": {...}}\n</tool_call>`
`_parse_tool_calls(response_text)` extracts via: tag extraction -> markdown block -> raw JSON

### Result returns
```python
res: ToolResult = await asyncio.to_thread(tool_reg.execute, tool_name, tool_args, tool_ctx)
messages.append({"role": "assistant", "content": "Action: Called tool `name`..."})
messages.append({"role": "user", "content": "Observation from `name`:\n{result_str}\n..."})
```

### Termination
- No tool calls returned -> break with final_reply
- Turn limit (MAX_TURNS=15) -> synthesize summary
- LLM exception -> run_failed, RunOutcome(status="failed")

---

## 3. Provider/Model Settings

| Setting | Location |
|---------|----------|
| Default model | `RunRequest.model` = "openai/gpt-oss-120b" |
| Default provider | `RunRequest.provider` = "groq" |
| Workers config | `backend/data/workers.json` |
| Rate-limit handling | `call_llm()`: parses retry-after, `mark_worker_error(wid, err, cooldown_s)`, tries next worker |

### Groq model facts
- `qwen/qwen3-32b` -> SHUT DOWN
- Primary: `openai/gpt-oss-120b` (128k), Secondary: `openai/gpt-oss-20b` (128k), Tertiary: `qwen/qwen3.8-27b` (32k)
- gpt-oss: reasoning_effort=low|medium|high only; no parallel tool calls; tools+structured_outputs cannot combine
- EXCLUDED: llama-3.3-70b-versatile, llama-3.1-8b-instant

---

## 4. Competing Orchestration Paths

### Path A: backend/app/agent/ (JarvisBrain + ReAct loop)
**KEEP - canonical.** Model-driven, single loop. Memory via AgentMemoryBridge. Tools via ToolRegistry.

### Path B: backend/app/graph/workflow.py (Multi-agent DAG)
**RETIRE FROM CALL PATH.** Hardcoded Orchestrator->Researcher->Executor->Validator->Recovery.
Problems: brittle regex routing, hardcoded deprecated model, fixed workflow not model-driven.
Keep file, exclude from API routing.

### Path C: brain/ standalone package
**REFERENCE-ONLY after porting key algorithms.**
Port: CallParser+repair ladder, redaction, loop detection, budget enforcement.
After porting: mark as "reference implementation - not in call path".

### Path D: brain/loop/engine.py
**REFERENCE-ONLY.**
Port: StateMachine transition table, PolicyEngine.decide(), budget triage, injection detection regex.

---

## 5. Real Interfaces Today

### Memory (backend/app/memory/api.py)
```python
def build_context(user_id, objective, project_id, session_id) -> Dict
  # {"experiences": [...], "observations": [...], "user_knowledge": str, "project_knowledge": str}
def record_experience(user_id, objective, execution_state, project_id, session_id) -> str  # exp_id
```

### Memory Bridge (backend/app/agent/memory_bridge.py)
```python
async def recall(user_id, objective, *, session_id, workspace_id, limit=5) -> Dict
async def record(user_id, run_id, objective, outcome: Dict) -> str
```

### Tool Registry (backend/app/tools/registry.py)
```python
def execute(tool_name, arguments, context) -> ToolResult
def get_tool_definitions(tool_names=None, categories=None, as_openai=False) -> List[Dict]
def validate_schema(tool, arguments) -> Optional[Dict]  # None = valid
```

### Runtime Protocols (backend/app/runtime/protocols.py)
```python
EventEmitter.__call__(event, data, *, node) -> None   # sync, never raises
AgentRunner.run(request, emit) -> RunOutcome           # async
MemoryProvider.recall/record                           # async
RunRequest.{run_id,session_id,user_id,workspace_id,objective,model,provider,...}
RunOutcome.{status,reply,error}, .ok -> bool
```

### LLM Router (backend/app/llm/router.py)
```python
def call_llm(system, user, model, provider, tools, emit) -> Tuple[str, Optional[str]]
def call_litellm(system, user, model, provider, tools) -> str
def extract_thoughts(raw_text) -> Tuple[str, Optional[str]]
```

### Workers (backend/app/llm/workers.py)
```python
def load_workers() -> List[Dict]    # reads backend/data/workers.json
def mark_worker_error(worker_id, error_msg, cooldown_s) -> None
def mark_worker_used(worker_id) -> None
```

---

## 6. Reuse Plan

| From brain/ | To backend/app/agent/ | How |
|-------------|----------------------|-----|
| brain/llm/parsing.py (CallParser + repair ladder) | agent/llm/parsing.py | Direct port |
| brain/redact.py | agent/redact.py | Direct copy + gsk_ pattern |
| engine.py loop detection | agent/loop.py | Port _detect_loop() |
| engine.py budget triage | agent/state.py | Port step/token/time budgets |
| engine.py _INJECTION_RE | agent/redact.py | Port regex |
| brain/loop/engine.py StateMachine | agent/state.py | Use as AgentState model |
| engine.py PolicyEngine | agent/permissions.py | Port + mock adapter |

**Do NOT port:** brain/providers/ (replaced by llm/router.py+workers), brain/memory/ (replaced by app/memory/api.py)

**Retire from call path (keep files):**
- backend/app/graph/workflow.py -> execute_run_task() excluded from routing
- backend/app/graph/nodes/* -> all node implementations
- backend/app/graph/controller.py -> replaced by loop.py

---

## 7. End State: One Canonical Path

```
HTTP/Session -> RunRequest -> JarvisBrain.run(request, emit)
                               -> AgentMemoryBridge.recall()
                               -> run_agent(request, emit, memory_ctx)
                               -> AgentMemoryBridge.record()
                               -> RunOutcome
```

graph/workflow.py: RETIRED header, excluded from routes.
brain/: REFERENCE-ONLY comment in README.
One entry path regression test asserts exactly one `run_agent` entrypoint.
