# Agent Interface Contracts

> Interfaces I need that are missing or mocked. Defined here; mock->real is a config change.

---

## Interfaces I Consume (Do Not Implement)

### Memory (Kushal's ownership)
File: `backend/app/memory/api.py`
Status: EXISTS - real implementation

```python
def build_context(user_id, objective, project_id, session_id) -> Dict
def record_experience(user_id, objective, execution_state, project_id, session_id) -> str
```

### Tool Registry (Lohit's ownership)
File: `backend/app/tools/registry.py`
Status: EXISTS - real implementation

```python
def execute(tool_name, arguments, context) -> ToolResult
def get_tool_definitions(tool_names, categories, as_openai) -> List[Dict]
```

### Permission Engine (Lohit's ownership)
File: Protocol defined in `backend/app/agent/permissions.py`
Status: MOCK ADAPTER (real engine not merged)

```python
class PermissionEngineProtocol(Protocol):
    def check(self, tool_name: str, args: dict, ctx: PermissionContext) -> PermissionDecision: ...
    def is_turbo_pre_authorized(self, tool_name: str, scope: str) -> bool: ...
    def is_hard_blocked(self, tool_name: str) -> bool: ...
```

### Event Emitter (Farhan's ownership)
File: `backend/app/runtime/protocols.py` - EventEmitter
Status: EXISTS - real SSE implementation in runtime

---

## Interfaces I Define (Agent ownership)

### AgentState
File: `backend/app/agent/state.py`
```python
@dataclass class AgentState:
    run_id, session_id, objective, messages (bounded), memory_context,
    current_goal, current_action, tool_calls, observations (bounded),
    artifacts, verification, errors, recovery_attempts, status,
    turn, prompt_tokens_last, completion_tokens_last, start_time
```

### PermissionContext
File: `backend/app/agent/permissions.py`
```python
@dataclass class PermissionContext:
    run_id, user_id, workspace_id, turbo_mode: bool, pre_authorized_scope: List[str]
```

### PermissionDecision
File: `backend/app/agent/permissions.py`
```python
@dataclass class PermissionDecision:
    decision: Literal["allow", "confirm", "deny"]
    reason: str
    tier: str  # "auto" | "confirm" | "deny"
```

### TurnDiagnostics
File: `backend/app/agent/state.py`
```python
@dataclass class TurnDiagnostics:
    turn: int, model: str, tool_count: int,
    prompt_tokens: int, completion_tokens: int, total_tokens: int
```

---

## Mock Adapters

### MockPermissionEngine
Location: `backend/app/agent/permissions.py`
Config: `JARVIS_PERMISSION_ENGINE=mock` (env var) uses mock; `=real` loads Lohit's engine
```python
class MockPermissionEngine:
    # Returns "confirm" for destructive tools, "allow" for read-only, "deny" for blocked
    def check(self, tool_name, args, ctx) -> PermissionDecision: ...
```

### MockMemory (for offline tests only)
Location: `tests/mocks/memory.py`
```python
class MockMemory:
    async def recall(...) -> Dict  # returns empty/fixture data
    async def record(...) -> str   # records to in-memory dict for assertion
```
