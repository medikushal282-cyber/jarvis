# REPO_MAP — frAIday / JARVIS interface reference for the Agent Brain

Scope: read-only survey of the teammate repo at `jarvis/` (git remote `medikushal282-cyber/jarvis`).
Purpose: pin down the **real** shapes of the interfaces our `brain/` must consume, and the junk we
must not build on. Every claim below names the file it came from. Verbatim identifiers, signatures
and JSON keys are quoted for interoperability accuracy; all explanation is mine.

Owner of this doc: Repo Cartographer (Phase 0). Do not treat anything here as a spec to copy —
treat it as ground truth about what already exists on disk.

---

## 1. Stack verdict

**One line:** a Windows-first Python 3.12 / FastAPI service whose "agent" is a hand-rolled blocking
`while` state machine over a plain dict (LangGraph is declared but never imported), talking to Groq
through `litellm` text completion, with a mock-only Hindsight memory layer that nothing imports.

### Languages / runtimes

| Layer | What it is | Evidence |
|---|---|---|
| Backend core | Python 3.12.7, FastAPI + uvicorn + pydantic v2 | `backend/app/main.py:16`, `start.bat:8-13` |
| Dev host | Windows 11; `.bat` launchers, `Scripts\python.exe`, drive-letter path guards | `start.bat`, `backend/app/workspace/runtime.py:9-14` |
| Web UI | Next.js + React + Tailwind on `:3000` (hardcoded `http://localhost:8000` fetches) | `frontend/src/app/page.tsx:348,367` |
| Auth UI | separate Vite/React app (`client/`) | `client/src/services/api.ts:1` |
| Auth gateway | Node + Express + TypeScript + MySQL, `/api/auth` | `server/src/app.ts`, `docs/API_REFERENCE.md:3` |

### Dependencies (pinned / declared)

`backend/requirements.txt` (the real manifest):
`fastapi>=0.111.0`, `uvicorn>=0.30.1`, `pydantic>=2.9.0`, `langgraph>=0.1.1`, `langchain-core>=0.2.9`,
`langchain-groq>=0.1.5`, `docker>=7.1.0`, `python-dotenv>=1.0.1`, `groq`, `litellm`, `PyYAML>=6.0.1`.

`requirements.txt` at repo root is **not a manifest** — it is three lines of sample prose. Ignore it.

**Actually imported at runtime:** `fastapi` / `uvicorn` / `pydantic` (`backend/app/api/*.py`),
`litellm` (`backend/app/llm/router.py:278`), `groq` SDK (`backend/app/llm/router.py:7` — used *only*
for `client.models.list()`), `python-dotenv` (`backend/app/main.py:5`), `PyYAML`
(`backend/app/memory/okf/manager.py:2`), `docker` (`backend/app/sandbox/docker_env.py:1`, optional/environment-dependent).

**Declared but never imported:** `langgraph`, `langchain-core`, `langchain-groq`. The execution
"graph" is a literal `while state["current_step"] != "end":` loop
(`backend/app/graph/workflow.py:233-301`) dispatching into a hand-written `nodes` dict
(`workflow.py:29-35`). Searching the repo for `langgraph|StateGraph|langchain` hits only
`backend/requirements.txt` and `docs/brain/BUILD_LOG.md`. **Do not model our brain on LangGraph
because it is in the requirements file — it is not in the code.**

### Entry points / how it runs

- ASGI app: `backend/app/main.py:16` — `app = FastAPI(title="JARVIS Orchestration API", version="1.0.0")`.
- Launch: from `backend/`, `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
  (`start.bat:10-12`). `main.py:102-103` runs the same with `reload=True` if invoked directly.
- Routers mounted under `/api`: `runs`, `workspace`, `preview`, `sandbox` (`main.py:43-46`).
- Extra endpoints: `GET /api/models` (`main.py:48-50`), `GET /health`, `GET /health/groq` (`main.py:52-100`).
- CORS is an explicit localhost allowlist for `:3000`, `:3001`, `:5173` (`main.py:28-41`).
- Tests: `backend/tests/*.py` are `unittest.TestCase` modules (run with `python -m unittest`).
  `pytest` is **not installed** in the verified env. Root `tests/e2e/auth-flow.spec.ts` is Playwright
  for the Node auth service, unrelated to the agent.

---

## 2. Interface inventory

Each entry: path → what it does → exact shape → real or stub → consume via.

### 2.1 SSE event stream — `backend/app/events.py` (+ producer at `backend/app/graph/workflow.py`)

**What it is.** A process-global dict of `asyncio.Queue`s keyed by run id, plus one `emit()` helper.
Node code calls `emit(...)`; the HTTP layer drains the queue into an SSE response. There is no event
bus class, no persistence, no fan-out, no replay.

**Exact shape** (`events.py:5-21`, quoted verbatim):

```python
event_bus: Dict[str, asyncio.Queue] = {}
def get_queue(run_id: str) -> asyncio.Queue
async def emit(run_id: str, event_type: str, node: str = "", data: dict = None)
```

The envelope pushed on the queue (`events.py:14-20`):

```python
{
    "event": event_type,          # str, e.g. "node_started"
    "run_id": run_id,             # str, e.g. "run_1a2b3c4d"
    "node": node,                 # str, "" if omitted
    "ts": datetime.now(timezone.utc).isoformat(),   # ISO-8601 with tz
    "data": data if data is not None else {}
}
```

Wire format (`backend/app/api/runs.py:164-172`): `media_type="text/event-stream"`, each frame is
`f"data: {json.dumps(event)}\n\n"` — **unnamed `message` frames only** (no `event:` line, no `id:`,
no heartbeat), terminated when `event["event"]` is `"run_completed"` or `"run_failed"`.

**Event-type vocabulary actually emitted** (grep of `emit(` in `backend/app/`):

`context_loaded`, `thought_generated`, `chat_response`, `agent_thinking`, `node_started`,
`node_completed`, `plan_created`, `step_started`, `step_completed`, `step_failed`,
`tool_call_started`, `tool_call_completed`, `observation_created`, `command_started`,
`command_completed`, `file_created`, `file_updated`, `file_read`, `file_deleted`,
`browser_opened`, `research_finding`, `validation_result`, `approval_requested`,
`approval_required`, `approval_granted`, `approval_rejected`, `run_completed`, `run_failed`.

Representative `data` payloads (verbatim keys):
- `node_started` → `{"step": current_node_name}` (`workflow.py:264`)
- `node_completed` → `{"next": ...}` plus node-specific `"plan" | "research" | "observations" | "artifacts" | "validation_results"` (`workflow.py:268-279`)
- `plan_created` → `{"steps": steps}` (`orchestrator.py:444`)
- `thought_generated` → `{"node","phase","title","thought","model","provider","timestamp"}` (`orchestrator.py:431-441`)
- `agent_thinking` → `{"summary": str}` (`workflow.py:241` and many)
- `tool_call_started` → `{"tool","path"}` or `{"tool","command"}` or `{"tool","url","path"}` (`executor.py:417,544,656`)
- `tool_call_completed` → the whole tool result envelope (`executor.py:424`)
- `observation_created` → the structured observation dict (`controller.py:56-69`)
- `validation_result` → `{"valid": bool, "reason": str, "status": str?}` (`validator.py:29-34,129`)
- `run_completed` → `{"status","type","reply","summary"}` for chat, `{"final_status","summary"}` for executions (`workflow.py:224-229,321`)
- `run_failed` → `{"error_type","message","node"}` or `{"message": ...}` (`workflow.py:308,355-361`)
- `approval_required` → `{"status":"pending","request": {...}}` (`workflow.py:289-297`)

**Real or stub.** Real and working (in-memory, single process). **Consume via:** *mirror the shape*
— our brain should expose its own emitter Protocol that produces the identical envelope
(`event`/`run_id`/`node`/`ts`/`data`) and the same event names, so a teammate frontend that already
parses these names renders our trace unchanged. Do not import `event_bus` (global, unpruned).

### 2.2 Run API — `backend/app/api/runs.py`

**What it is.** The only public control surface for an execution: create a run, stream its events,
poll final state, approve/reject a pending destructive action.

**Exact shapes** (`runs.py`):

```python
class AttachmentItem(BaseModel): name: str; content: str; size: Optional[int] = 0

class RunRequest(BaseModel):
    objective: str
    model: Optional[str] = "qwen/qwen3.8-27b"
    provider: Optional[str] = "groq"
    workspace_id: Optional[str] = None
    conversation_id: Optional[str] = None
    attachments: Optional[List[AttachmentItem]] = None

class RunResponse(BaseModel): run_id: str; status: str
class ApprovalRequest(BaseModel): decision: str      # "approve" | "reject"
```

Routes (router prefix `/runs`, mounted at `/api`):

| Method + path | Behaviour |
|---|---|
| `POST /api/runs/` | creates `run_id = f"run_{uuid.uuid4().hex[:8]}"`, stores in `RUNS_DB`, fires `asyncio.create_task(execute_run_task(...))`, returns `{"run_id","status":"pending"}` (`runs.py:51-101`) |
| `GET /api/runs/{run_id}/events` | SSE stream (see 2.1) |
| `GET /api/runs/{run_id}` | returns the whole `RUNS_DB[run_id]` dict |
| `POST /api/runs/{run_id}/approval` **and** `POST /api/runs/{run_id}/approve` | both aliases; 404 unknown run, 400 bad decision, 409 not-paused / nothing pending; returns `{"run_id","status":"resuming"}` (`runs.py:103-157`) |

`GET /api/runs/{run_id}` document keys (`runs.py:69-78`): `run_id`, `objective`, `model`, `provider`,
`workspace_id`, `conversation_id`, `status`, `state` (plus `type: "chat"` added at
`workflow.py:146` for conversational runs). Observed `status` values: `"pending"`, `"running"`,
`"paused"`, `"completed"`, `"failed"`.

**Real or stub.** Real. **Consume via:** *HTTP* if we want to be a drop-in replacement behind the
teammate UI; *mirror the shape* for our own in-process API. We should not import `runs.py` (its
module-level `RUNS_DB` / `SESSION_HISTORY` globals are shared mutable state).

### 2.3 LLM / Groq router — `backend/app/llm/router.py`

**What it is.** A thin `litellm` wrapper plus a live model catalogue. **It is a text-completion
router, not a tool-calling client.**

**Exact signatures** (`router.py:101,159,205,268,277,304`):

```python
def fetch_live_groq_models() -> List[Dict[str, Any]]
def fetch_live_ollama_models() -> List[Dict[str, Any]]
def get_models_catalog() -> List[Dict[str, Any]]
def extract_thoughts(raw_text: str) -> Tuple[str, Optional[str]]      # (cleaned_text, thought|None)
def call_litellm(system: str, user: str, model: str, provider: str = "groq") -> str
def call_llm(system: str, user: str,
             model: str = "openai/gpt-oss-120b",
             provider: str = "groq") -> Tuple[str, Optional[str]]
```

`call_llm` **has no `tools=`, `tool_choice=`, `messages=` or `max_tokens` parameter** — it takes one
system string + one user string, calls `litellm.completion(model=<prov>/<model>, messages=[system,user])`
(`router.py:295-302`), extracts `<thought>`/`<think>` via regex, and on failure falls back through
a hardcoded ladder `openai/gpt-oss-120b` → `qwen/qwen3.8-27b` (`router.py:316-329`).

Model catalogue item keys (`router.py:126-138`): `id`, `name`, `provider`, `provider_name`,
`context_window`, `badge`, `tags`, `description`, `available`, `status_text`, `priority`.
Server-side `priority` ordering promotes `openai/gpt-oss-120b` (100) → `openai/gpt-oss-20b` (95) →
`qwen/qwen3.8-27b` (90). Served at `GET /api/models` as `{"models": [...]}` (`main.py:48-50`).

Thought extraction contract: `extract_thoughts` returns `(cleaned_text, thought_text_or_None)` for
`<thought>…</thought>` **or** `<think>…</think>` (both stripped from the returned text).

**Real or stub.** Real (Groq path needs `GROQ_API_KEY`; Ollama path probes `http://localhost:11434/api/tags`
with a 1s timeout). **Consume via:** *wrap* — define our own Groq tool-calling client in `brain/`
(raw `httpx` per `BUILD_LOG.md` D2) and keep this router only as a fallback for plain-text
sub-tasks. Do **not** build our planner on `call_llm`, because it cannot emit or receive tool calls.

### 2.4 Hindsight memory (retain + recall) — `backend/app/memory/hindsight/{client,adapter}.py`

**What it is.** The "experiential memory" layer. `HindsightClient` is documented as talking to a
Hindsight service, but the HTTP path is a TODO and it **always** uses a local JSON file. The
`HindsightAdapter` maps JARVIS concepts (execution experience, observation) onto it.

**Exact signatures** (`client.py:15,49,71`):

```python
class HindsightClient:
    def __init__(self, endpoint_url: Optional[str] = None,   # defaults to env HINDSIGHT_URL
                 storage_dir: Optional[str] = None)           # defaults to backend/data/hindsight_mock
    def store_experience(self, user_id: str, content: str, metadata: Dict[str, Any]) -> str
    def search(self, user_id: str, query: str, limit: int = 5,
               filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]
```

Stored record shape (`client.py:60-66`): `{"id","user_id","content","metadata","timestamp"}` with
`id = f"exp_{uuid.uuid4().hex[:8]}"` and `timestamp` a float epoch. On-disk file is
`<storage_dir>/hindsight_db.json` shaped `{"experiences": [...]}`. `search` is **keyword overlap
plus substring scoring**, not vector search, and it matches `metadata` keys exactly via `filters`
(`client.py:86-129`).

**Exact signatures** (`adapter.py:11,40,60,76`):

```python
class HindsightAdapter:
    def __init__(self, client: Optional[HindsightClient] = None)   # default: HindsightClient()
    def record_execution_experience(self, user_id: str, objective: str, summary: str,
                                    status: str, project_id: Optional[str] = None,
                                    session_id: Optional[str] = None,
                                    error_msg: Optional[str] = None) -> str
    def record_observation(self, user_id: str, observation: str,
                           source_experience_id: Optional[str] = None,
                           project_id: Optional[str] = None) -> str
    def recall_relevant_experiences(self, user_id: str, objective: str,
                                    project_id: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]
    def recall_observations(self, user_id: str, objective: str,
                            project_id: Optional[str] = None, limit: int = 3) -> List[Dict[str, Any]]
```

Metadata the adapter writes (verbatim keys): `type` ∈ `{"execution","observation"}`, `objective`,
`status`, and optionally `project_id`, `session_id`, `source_experience_id` (`adapter.py:28-56`).
The recall filters are therefore `{"type": "execution"}` / `{"type": "observation"}` (+ `project_id`).

Note the asymmetry to preserve in any mock: `record_*` returns an **id string**; `recall_*` returns
**full record dicts**, and `ContextBuilder` is what flattens them to content strings.

**Real or stub.** **Stub/mock**, and honest about it: with `endpoint_url` set it logs
`"Real Hindsight HTTP store not fully implemented, using mock."` and still writes local JSON
(`client.py:53-55`, `76-78`). The ranking is keyword-based, not semantic.

**Consume via:** *wrap behind our own Protocol* and *direct import* of the concrete client for the
mock implementation. Recommended adapter body:
`HindsightClient(storage_dir=<brain-owned dir>)` → `HindsightAdapter(client=...)` → call
`record_execution_experience(...)` / `recall_relevant_experiences(...)` (+ the observation pair).
Do **not** import `app.memory.api` (see trap 6.13): its singletons are built at import time and
hardcode paths/side effects.

### 2.5 OKF durable knowledge — `backend/app/memory/okf/manager.py`

**What it is.** "Open Knowledge Format" = Markdown files with YAML frontmatter, per user and per
project. This is the *durable, structured* half of memory (preferences, project overviews) as
opposed to Hindsight's episodic half.

**Exact signatures** (`manager.py:11,63,71,80,88`):

```python
class OKFManager:
    def __init__(self, storage_dir: Optional[str] = None)   # default backend/data/knowledge
    def get_user_knowledge(self, user_id: str, topic: str = "preferences") -> Dict[str, Any]
    def update_user_knowledge(self, user_id: str, topic: str, content: str,
                              metadata: Optional[Dict[str, Any]] = None)
    def get_project_knowledge(self, user_id: str, project_id: str, topic: str = "overview") -> Dict[str, Any]
    def update_project_knowledge(self, user_id: str, project_id: str, topic: str, content: str,
                                 metadata: Optional[Dict[str, Any]] = None)
```

Return shape is **always** `{"metadata": dict, "content": str}` (`manager.py:28-50`), with
`{"metadata": {}, "content": ""}` for a missing file — never `None`, never an exception.
On-disk layout: `<storage_dir>/<user_id>/<topic>.md` and
`<storage_dir>/<user_id>/projects/<project_id>/<topic>.md`. Frontmatter always gains
`last_updated: <float epoch>`; project writes also stamp `project_id`; both stamp `topic`
(`manager.py:52-61,71-96`).

**Real or stub.** Real, working, tiny (pure file IO + `yaml.safe_load`/`yaml.dump`). A malformed
frontmatter silently degrades to `metadata={}` and the raw text as content (`manager.py:46-50`).
**Consume via:** direct import, or mirror the `{metadata, content}` shape in our own
knowledge-store Protocol.

### 2.6 Memory facade + context builder + extractor — `backend/app/memory/{api,context_builder,extractor}.py`

**What it is.** The intended single entry point for memory, plus the prompt-time assembler and the
experience summarizer.

**Exact facade signatures** (`api.py:14,30,54,70,76,82,88`):

```python
def build_context(user_id: str, objective: str, project_id: Optional[str] = None,
                  session_id: Optional[str] = None) -> Dict[str, Any]
def record_experience(user_id: str, objective: str, execution_state: Dict[str, Any],
                      project_id: Optional[str] = None, session_id: Optional[str] = None) -> str
def record_observation(user_id: str, observation: str, source_experience_id: Optional[str] = None,
                       project_id: Optional[str] = None) -> str
def get_user_knowledge(user_id: str, topic: str = "preferences") -> Dict[str, Any]
def update_user_knowledge(user_id: str, topic: str, content: str, metadata: Optional[Dict] = None)
def get_project_knowledge(user_id: str, project_id: str, topic: str = "overview") -> Dict[str, Any]
def update_project_knowledge(user_id: str, project_id: str, topic: str, content: str,
                             metadata: Optional[Dict] = None)
```

`build_context` return keys, verbatim (`context_builder.py:45-50`):

```python
{
    "user_preferences": str,          # OKF user topic "preferences" content
    "project_knowledge": str,         # OKF project topic "overview" content ("" if no project_id)
    "relevant_experiences": [str],    # Hindsight execution contents, limit 3
    "relevant_observations": [str],   # Hindsight observation contents, limit 3
}
```

`MemoryExtractor.extract_experience(objective, execution_state) -> str` (`extractor.py:8-40`) reads
`execution_state["status"|"error"|"artifacts"|"tool_calls"]` and builds a newline text with lines
`Task:`, `Outcome:`, optional `Encountered Error:`, `Produced Artifacts:`, `Tool Failures:`.

**Real or stub.** Real but **orphaned**: nothing in `app/graph/**` or `app/api/**` imports
`app.memory` (verified by grep — only `backend/tests/test_memory.py` and the package's own
`__init__.py` reference it). The live run loop's only "memory" is the conversation JSON in
`api/sandbox.py` plus the keyword store in `workspace/knowledge.py`.
**Consume via:** *wrap*. Use the four `build_context` keys as our prompt-assembly contract, but call
`HindsightAdapter`/`OKFManager` directly with a brain-owned `storage_dir` rather than the facade's
import-time singletons.

### 2.7 Tool registry — `backend/app/workspace/tools.py`

**What it is.** The plan-execution surface: a hand-written schema table, a dispatch table, an
argument validator, and a uniform result envelope. Schemas are **not JSON Schema** — they are prose
strings, so any real tool-calling client must derive its own schema from them.

**Exact shapes** (`tools.py:10-50,595-615,617-696`):

```python
TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "<tool_name>": {"description": str, "parameters": {"<arg>": "type (required|optional...)"}},
    ...
}
DISPATCH_TABLE: Dict[str, Callable[..., Dict[str, Any]]] = {"<tool_name>": tool_<name>, ...}

def validate_action_schema(action: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]
def execute_action(action: Dict[str, Any]) -> Dict[str, Any]
def execute_tool(tool: Union[str, Dict[str, Any]], **kwargs) -> Dict[str, Any]
```

Action envelope (`tools.py:648-659`): `{"tool": "<name>", "arguments": { ... }}`. Validation error
codes: `INVALID_ACTION_FORMAT`, `UNKNOWN_TOOL`, `INVALID_ARGUMENTS` (`tools.py:617-646`).

Registered tool names (keys of `TOOL_SCHEMAS` / `DISPATCH_TABLE`, `tools.py:10-50,595-615`) and their
argument names:
`list_directory(path=".")`, `read_file(path)`, `create_file(path, content)`,
`update_file(path, content)`, `delete_file(path)`, `run_command(command, timeout=30)`,
`inspect_runtime()`, `search_files(pattern, path=".", regex=False)`, `search_web(query)`,
`append_file(path, content)`, `rename_file(old_path, new_path)`, `copy_file(src, dest)`,
`get_file_info(path)`, `list_directory_tree(path, max_depth)`, `diff_files(path_a, path_b)`,
`install_package(name, manager)`, `patch_file(path, find, replace)`, `preview_browser(path)`.
`DISPATCH_TABLE` additionally aliases `"open_browser": tool_preview_browser` (`tools.py:614`).

**Uniform result envelope** (every tool returns this, e.g. `tools.py:381-392`):

```python
{
  "success": bool,
  "tool": str,
  "result": dict | None,        # tool-specific payload
  "error": None | {"code": str, "message": str},
  # plus tool-specific keys hoisted to top level, e.g. path/lines/bytes_written/exit_code/stdout/stderr
}
```

Error codes seen: `PATH_SECURITY_ERROR`, `FILE_NOT_FOUND`, `TOOL_EXECUTION_ERROR`,
`ARTIFACT_EXTRACTION_ERROR`, `APPROVAL_REQUIRED`, `COMMAND_DENIED`, `PROCESS_EXECUTION_ERROR`,
`INVALID_ACTION_FORMAT`, `UNKNOWN_TOOL`, `INVALID_ARGUMENTS`, `NOT_A_DIRECTORY`, `TOOL_ERROR`.

Helper validators worth mirroring: `validate_python_source(rel_path) -> {"valid","kind","path","message",...}`
(`tools.py:698-780`) and `classify_failure(exit_code, stdout, stderr, obj_reason) -> str`
(`tools.py:782-817`) returning one of `syntax_ok` / `syntax_error` / `runtime_error` / `missing_file`
/ `missing_arguments` / `permission_error` / `validation_error` / `command_error`.

**Real or stub.** Real for the filesystem subset; several "advanced" tools are thin or broken (see
traps). **Consume via:** *mirror the shape* — adopt the `{"tool","arguments"}` action envelope, the
`{success, tool, result, error:{code,message}}` result envelope, and the `classify_failure`
vocabulary in our own tool registry, so trace rendering and recovery logic line up. Import individual
`tool_*` functions only if we deliberately adopt the workspace; prefer our own providers.

### 2.8 Permission tiers — `backend/app/workspace/policy.py`

**What it is.** Pre-execution command classification into three tiers. This is the only real policy
engine in the repo, and its tier names are the vocabulary a human-approval UI already understands.

**Exact shape** (`policy.py:6-8,60`):

```python
POLICY_SAFE = "SAFE"
POLICY_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
POLICY_DENIED = "DENIED"

def check_command_policy(command: Union[str, List[str]]) -> Tuple[str, str]   # (policy, reason)
```

Rules, in evaluation order (`policy.py:60-107`): `DENIED_PATTERNS` regexes first
(`format`, `shutdown`, `reg add|delete`, `mkfs`, `dd if=`, `powershell -enc`, `:> /dev/sd`,
`[a-zA-Z]:\Windows\`, `/etc/shadow`, `/etc/passwd`, deep `cd ..\..`), then
`APPROVAL_PATTERNS` (`pip install`, `npm install|i|add`, `pnpm`, `yarn add`, `del /f`, `rm -rf`,
`rmdir /s`, `git push|reset --hard|clean`), then `SAFE_COMMAND_PREFIXES`
(`python`, `python3`, `py`, `node`, `npm test`, `npm run`, `pnpm test`, `pnpm run`, `git status|diff|log|branch|show`,
`dir`, `ls`, `type`, `cat`, `echo`, `pwd`) plus a quoted-exe fallback and an
"ends in `.py`/`.js`/`.ts`" fallback. **Default for anything unclassified is `APPROVAL_REQUIRED`**
(`policy.py:107`).

Tool-level tiers are separate and argument-driven, not name-driven:
`tool_delete_file(path, approved: bool = False)` returns `status: "approval_required"` with
`policy: POLICY_APPROVAL_REQUIRED` until called with `approved=True` (`tools.py:264-287`);
`tool_install_package(name, manager="pip", approved=False)` is the same (`tools.py:563-568`).
`run_command` returns `status: "approval_required"` + `error.code: "APPROVAL_REQUIRED"` when the
policy says so (`tools.py:344-360`).

**Real or stub.** Real and load-bearing. **Consume via:** *mirror the shape* — reuse exactly the
three tier strings and the `{"status": "approval_required", "reason": ..., "policy": ...}` payload,
because the frontend already keys off them (`frontend/src/app/page.tsx:423-428,465-471`).
Deny-by-default is the right posture to copy.

### 2.9 Workspace + runtime — `backend/app/workspace/{manager,runtime}.py`

**What it is.** Path-contained filesystem + process execution, rooted at a per-workspace sandbox dir,
plus runtime discovery.

**Exact signatures** (`manager.py:9,44,97,102,162,196,233,266,325,329,332,349`):

```python
active_workspace_id = contextvars.ContextVar('active_workspace_id', default='default')

class PathSecurityError(ValueError)          # raised on escape attempts
class CommandDeniedError(PermissionError)

class WorkspaceManager:
    def __init__(self, root_path: Optional[str] = None, workspace_id: str = "ws_default", name: str = "JARVIS")
    def resolve_path(self, target_path: str) -> str
    def get_relative_path(self, full_path: str) -> str
    def list_directory(self, rel_path: str = "") -> Dict[str, Any]
    def read_file(self, rel_path: str, max_bytes: int = 1024 * 1024) -> Dict[str, Any]
    def write_file(self, rel_path: str, content: str) -> Dict[str, Any]
    def create_directory(self, rel_path: str) -> Dict[str, Any]
    def delete_file(self, rel_path: str) -> Dict[str, Any]
    def get_python_executable(self) -> str
    def execute_process(self, command: Union[str, List[str]], timeout: int = 30) -> Dict[str, Any]
    async def execute_process_async(self, command, timeout: int = 30) -> Dict[str, Any]
    def get_runtime_info(self) -> Dict[str, Any]
    def get_workspace_info(self) -> Dict[str, Any]

def get_workspace_manager(workspace_id: str = None) -> WorkspaceManager
```

`get_workspace_manager` resolves the root to `<repo_root>/sandbox/<workspace_id>` and memoizes in a
module-global dict (`manager.py:349-360`). Filesystem results use
`{"success": bool, "path": rel, "operation": "<op>", ...}` with `error` as a plain string
(not the tool envelope). `execute_process` returns
`{"command","exit_code","stdout","stderr","duration","timeout","working_directory","policy"}`
with `exit_code: 124` on timeout (`manager.py:279-311`).

Runtime discovery (`runtime.py:7,97,130`): `detect_python(root)`, `detect_cli_tool(name)`,
`detect_all_runtimes(root)` → `{"python": {...}, "node": {...}, "npm": {...}, "pnpm": {...}, "git": {...}}`.

**Real or stub.** Real. `docker_env.DockerSandbox` is the only optional piece (see 2.12).
**Consume via:** *wrap* — our terminal/fs providers can delegate to `WorkspaceManager` for the
"real" provider, but the brain should own its own `resolve_path`-style guard and not depend on the
process-global manager cache.

### 2.10 Artifacts

**There is no artifact API or module.** "Artifacts" is only (a) a list inside run state and (b) a
directory convention:
- State entries are appended by `record_artifact(state, path, operation)` as
  `{"type": "file", "path": str, "operation": "created"|"updated"}` (`executor.py:55-61`), and later
  read by the UI from `GET /api/runs/{id}` → `state.artifacts` (`frontend/src/app/page.tsx:503-504`).
- `POST /api/sandbox/workspaces` creates `<sandbox>/<ws_id>/artifacts/` (`api/sandbox.py:75`), but
  the workspace manager roots at `<sandbox>/<ws_id>`, so the `artifacts/` subdir is unused by the
  tools (`manager.py:357-359`).
- `backend/app/workspace/artifact_cleaner.py` is a **content sanitizer**, not storage:
  `remove_tool_protocol_markup(text)`, `extract_code_fence(text, ext)`,
  `extract_and_validate_artifact(rel_path, raw_content) -> Tuple[bool, str, Optional[str]]`
  (`artifact_cleaner.py:6,28,83`).

**Consume via:** *define our own* artifact-store Protocol and emit `{"type":"file","path","operation"}`
entries in run state so the existing UI panel keeps working.

### 2.11 Sandbox / workspace HTTP API — `backend/app/api/{sandbox,workspace,preview}.py`

**What it is.** Workspace + conversation CRUD on top of `sandbox/<ws_id>/` JSON files, and a
live-reload HTML preview server.

`backend/app/api/sandbox.py` (prefix `/sandbox`):

| Route | Notes |
|---|---|
| `GET /api/sandbox/workspaces` | `{"workspaces": [{"id","name","description","created_at","conversation_count"}]}` |
| `POST /api/sandbox/workspaces` | body `{name, description?}` → creates `workspace.json` + `conversations/` + `artifacts/` |
| `DELETE /api/sandbox/workspaces/{ws_id}` | `shutil.rmtree` |
| `GET/POST /api/sandbox/workspaces/{ws_id}/conversations` | conversation list / create |
| `GET/DELETE .../conversations/{conv_id}` | read / delete |
| `POST .../conversations/{conv_id}/messages` | body `{role, content, metadata?}`; re-summarizes every 6th message |
| `GET .../conversations/{conv_id}/context` | `{"context_summary","message_count"}` |

Conversation file schema (`api/sandbox.py:137-143,176-181`):
`{"id","title","created_at","messages":[{"role","content","timestamp","metadata"}],"context_summary"}`.
`context_summary` is produced by `_summarize_context(messages)` (`api/sandbox.py:216-261`) which calls
`call_llm` with the hardcoded ladder `["llama-3.1-8b-instant", "openai/gpt-oss-20b"]` and caps the
result at `[:400]`, else falls back to joining the last 4 messages.
Module functions used by the run loop: `get_or_create_default_session() -> tuple[str, str]`,
`get_conversation_memory(ws_id, conv_id) -> dict` → `{"context_summary","recent_messages"}` (last 4),
`save_conversation_turn(ws_id, conv_id, user_text, assistant_text, metadata=None) -> str`.

`backend/app/api/workspace.py` (prefix `/workspace`): `GET /api/workspace` (info),
`GET /api/workspace/runtime`, `GET /api/workspace/files?path=`, `GET /api/workspace/file?path=`,
`POST /api/workspace/file` with body `{path, content}`. All delegate to the manager and translate
`PathSecurityError` → HTTP 403.

`backend/app/api/preview.py` (prefix `/preview`): `GET /api/preview/{workspace_id}/{file_path:path}`
serves the file, injecting a live-reload script into HTML (`preview.py:21-44,119-126`);
`GET /api/preview/{workspace_id}/reload-check?since=<float>` → `{"reload": bool, "timestamp": float}`;
`POST /api/preview/notify-update`; `POST /api/preview/{workspace_id}/open` body `{file_path, browser?}`
→ launches the system browser via `webbrowser.open`.

**Real or stub.** Real (file-based, single-machine). **Consume via:** *HTTP* for workspace/
conversation state if we want to share sessions with the teammate UI; otherwise *mirror the shape*
for our own session store.

**Browser reality check:** there is no browser automation. "open browser" is
`webbrowser.open(url)` (`executor.py:547`, `preview.py:72`) and the "browser" tool is an HTTP GET of
the preview HTML (`tools.py:583-593`). If our brain's browser tool needs real automation (screenshot,
DOM, click), it is new work behind our own Protocol.

### 2.12 Docker sandbox — `backend/app/sandbox/docker_env.py`

**What it is.** An isolated Python execution helper (not wired into any API route).

```python
class DockerSandbox:
    def __init__(self, image="python:3.11-slim")            # calls docker.from_env(), pulls if missing
    def execute_python(self, code: str, timeout: int = 30,
                       memory_limit: str = "512m", network: bool = False) -> dict
```
Returns `{"exit_code": int, "stdout": str, "error": None | str}` (`docker_env.py:43-60`). Note the
host temp dir is mounted **read-only** (`docker_env.py:33`), so the script cannot write next to
itself. **Real but dormant; unused by the run loop. Consume via:** IGNORE for the hackathon unless a
Docker daemon is guaranteed on the demo machine — prefer our own terminal provider.

### 2.13 Agent state machine + controller — `backend/app/graph/{state,controller,workflow}.py`

Not an interface we consume, but the shape we should deliberately diverge from or align with.

- State is a loose dict, typed only by `FraidayState(TypedDict)` (`state.py:3-28`): keys
  `run_id`, `objective`, `workspace`, `conversation_context`, `plan`, `current_step`, `research`,
  `tool_calls`, `observations`, `artifacts`, `validation_results`, `status`, `error`, `retry_count`,
  `approval_required`, `approval_status`, `approval_request`. The runtime dict in
  `execute_run_task` adds `model`, `provider`, `workspace_id`, `conversation_id`,
  `session_context_summary`, `thoughts`, `attachments`, `autonomous_iteration_count`,
  `replan_count`, `recovery_attempts`, `mode` (`workflow.py:101-130`).
- Controller decisions are string constants plus one pure function:

```python
MAX_AUTONOMOUS_ITERATIONS = 12; MAX_REPLANS = 3; MAX_RECOVERY_ATTEMPTS = 2
DECISION_CONTINUE / DECISION_RECOVER / DECISION_REPLAN / DECISION_VALIDATE /
DECISION_WAIT_FOR_APPROVAL / DECISION_COMPLETE / DECISION_FAIL     # controller.py:12-18
def evaluate_next_decision(state: Dict[str, Any]) -> Tuple[str, str]   # (decision, reason), controller.py:106
def create_structured_observation(action, target, success, result_data=None, step_id=None,
                                  exit_code=0, stdout="", stderr="", failure_type=None) -> Dict[str, Any]   # controller.py:20
```

- Observation shape (`controller.py:56-69`): `{"action","target","success","summary","step_id",
  "exit_code","stdout","stderr","kind"}` with stdout/stderr hard-truncated to `[:300]` and `kind`
  defaulting to `"syntax_ok"` on success / `"command_error"` on failure, plus `"entries"` for
  `LIST_DIRECTORY`.
- Plan step shape (produced by the orchestrator, `orchestrator.py:392-403`):
  `{"id","description","agent","action","target","arguments","depends_on","status","reason","result"}`
  where `action` ∈ `LIST_DIRECTORY|READ_FILE|CREATE_FILE|UPDATE_FILE|DELETE_FILE|RUN_COMMAND|OPEN_BROWSER|INSPECT_RUNTIME`
  and `status` ∈ `pending|running|completed|failed|blocked|skipped`.
- The loop itself (`workflow.py:232-321`): evaluate decision → route to one of
  `nodes = {orchestrator, researcher, executor, validator, recovery}` → emit `node_started` /
  `node_completed` → pause (`status="paused"`) if `approval_required and approval_status == "pending"`
  → `run_completed` / `run_failed`.
- Two distinct modes: `is_code_execution_objective(objective) -> bool` (`workflow.py:37-67`) splits
  conversational chat (single LLM call, emits `chat_response`) from the DAG path.

**Consume via:** *MIRROR-SHAPE only* — reuse the event names, the plan-step and observation dicts
(the frontend and any future trace viewer already understand them). Do **not** import the loop; it is
a blocking, global-state, template-fallback machine.

### 2.14 Keyword knowledge store — `backend/app/workspace/knowledge.py`

`KnowledgeStore` persists research findings to `backend/data/knowledge_base.json` shaped
`{"findings": [...]}`. API: `load_findings()`, `save_finding(finding) -> bool` (dedupes on exact
`query`/`finding` text; requires a `finding` key), `find_relevant(objective) -> Optional[Dict]`
(keyword match, with a hardcoded csv+json special case), `clear()`, and the module singleton
`get_knowledge_store()`. This is the only memory actually used by the run loop (via the researcher
node). **Real but crude; consume via:** IGNORE, or MIRROR-SHAPE if we want a zero-dependency
fallback recall.

### 2.15 Auth

- The Python core has **no authentication**. `main.py:18-26` only reads a header
  `X-Workspace-Id` (default `"default"`) into `active_workspace_id`. No dependency, no token check.
- Real auth lives in a separate Node/Express/TypeScript service under `server/src` with routes
  under `/api/auth` (register, verify-email, resend-verification, login, forgot/reset/change
  password, `GET /me`, logout, `PATCH /profile`, `GET /workspace/status`), returning
  `{"success": true|false, "message"?, "user"?, "error"?: {"code","message","details"?}}` and
  setting an `HttpOnly` cookie `fraiday_session` (`docs/API_REFERENCE.md`, `client/src/services/api.ts:21`).
  It is **never called by the FastAPI backend** — the two services are disjoint.
- **Consume via:** IGNORE for the brain. Our run API must carry its own `user_id`/`session_id`
  through to memory calls; do not assume an authenticated principal exists.

### 2.16 STT / TTS

**Absent.** Grep for `stt|tts|speech|voice|whisper` across `backend/app` finds nothing; the only
mention of "voice streaming pipeline" is an unchecked box in `docs/agents/TASKS.md:13`. There is no
audio endpoint, no transcription call, no streaming socket. **Consume via:** *define our own
Protocol + mock* — there is no teammate interface to consume here, so `brain/` must supply the
contract and the mock, and treat "real" as a future adapter.

---

## 3. Reusable vs trap

| Path | Verdict | Reason |
|---|---|---|
| `backend/app/events.py` | MIRROR-SHAPE | Envelope `{event,run_id,node,ts,data}` is the contract every consumer already reads; the global queue itself is not reusable. |
| `backend/app/api/runs.py` (routes/shapes) | MIRROR-SHAPE | Route names + `RunRequest`/`ApprovalRequest` fields are what the UI calls; `RUNS_DB`/`SESSION_HISTORY` globals are not. |
| `backend/app/llm/router.py` | MIRROR-SHAPE | Model-catalogue item keys and `extract_thoughts` are reusable; `call_llm` has no tool-calling and must not back our planner. |
| `backend/app/memory/hindsight/client.py` | REUSE | Small, dependency-free, deterministic JSON store with the exact retain/recall signatures we need for a mock. |
| `backend/app/memory/hindsight/adapter.py` | REUSE | `record_execution_experience` / `recall_relevant_experiences` (+ observation pair) map cleanly onto a memory Protocol. |
| `backend/app/memory/okf/manager.py` | REUSE | `{metadata, content}` file-backed durable knowledge, no side effects, trivially callable. |
| `backend/app/memory/api.py` | IGNORE | Import-time singletons that create directories and compute fixed paths; bypass in favour of direct construction. |
| `backend/app/memory/context_builder.py` | MIRROR-SHAPE | Its four output keys are a good prompt-assembly contract; the class itself hardcodes limits (3/3). |
| `backend/app/memory/extractor.py` | MIRROR-SHAPE | The `Task:/Outcome:/Produced Artifacts:` summary format is a reasonable cheap baseline; it is not LLM-backed. |
| `backend/app/workspace/policy.py` | REUSE | Three real permission tiers with deny-by-default; the safest thing in the repo to copy verbatim. |
| `backend/app/workspace/manager.py` | MIRROR-SHAPE | `resolve_path` containment logic is genuinely careful; the module-global manager cache and Windows specifics are not. |
| `backend/app/workspace/runtime.py` | REUSE (with care) | Runtime discovery is honest and useful; it probes venv `Scripts\python.exe` and Windows `py`, so it is not OS-neutral. |
| `backend/app/workspace/tools.py` | MIRROR-SHAPE | Adopt the action/result envelopes and `classify_failure` vocabulary; do not build on the tools themselves (broken `search_web`, template `generate_smart_file_content`). |
| `backend/app/workspace/artifact_cleaner.py` | MIRROR-SHAPE | Good idea (strip `<tool_call>`/fences/preambles before writing) but its validator is regex/template-driven; keep our own. |
| `backend/app/workspace/knowledge.py` | IGNORE | Keyword matcher with a hardcoded csv+json branch; superseded by our own recall. |
| `backend/app/graph/state.py`, `controller.py` | MIRROR-SHAPE | The typed observation/plan/decision vocabulary is worth keeping in our trace; the implementation is not. |
| `backend/app/graph/workflow.py`, `nodes/*.py` | IGNORE | Blocking sync LLM calls inside async paths, template fallbacks (`generate_smart_file_content`), single `retry_count` loop. Reference how the team's loop behaves; do not extend it. |
| `backend/app/api/sandbox.py` | MIRROR-SHAPE | Conversation/context JSON schema is the session memory shape the UI reads; the summarizer inside it is a trap. |
| `backend/app/api/preview.py` | REUSE (HTTP) | Live-reload preview is a real, working capability a trace viewer can embed via iframe. |
| `backend/app/api/workspace.py` | REUSE (HTTP) | Clean REST facade over the workspace manager with 403 on path escape. |
| `backend/app/sandbox/docker_env.py` | IGNORE | Dormant, needs a Docker daemon, mounts read-only; adds risk with no payoff at hackathon time. |
| `backend/app/graph/agent_docs.py` + `docs/agents/*.md` | REUSE | `load_all_agent_docs()` is a working prompt file loader; `SOUL/HEAD/PLANNING/TOOLS/WORKFLOW/TASKS` are the team's personality/planning prompt, useful as a reference for our own prompt assembler. |
| `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`, `docs/SECURITY_CHECKLIST.md` | IGNORE | All three document the **Node auth service only**; they say nothing about the agent. |
| `backend/requirements.txt` | REUSE | The real dependency list (minus the unused LangChain stack). |
| root `requirements.txt` | IGNORE | Not a manifest; three lines of sample prose. |
| `app.py`, `tool_test.py`, `csv_*.py`, `*.html`, `soul.md`, `tools.md`, `add_numbers.py`, `verify_result.py`, `serve_dashboard.py`, `server.js`, `script.js`, `scratch/`, `data/movies.json` | IGNORE | Scratch/demo clutter at repo root (see section 4 note). |
| `server/` | IGNORE (for the brain) | A separate Node auth service; no agent logic. |
| `client/` | IGNORE (for the brain) | Vite/React auth UI for the Node service. |
| `frontend/` | REUSE as *contract* | `frontend/src/app/page.tsx` is the authoritative consumer of our event stream — treat its `switch (type)` as the rendering spec. |

**Root-level junk (do not build on, no detail needed):** `app.py`, `tool_test.py`, `add_numbers.py`,
`csv_kb_test_one.py`, `csv_kb_test_two.py`, `csv_to_json.py`, `csv_to_json_fourth.py`,
`csv_to_json_third.py`, `advanced_csv_converter.py`, `employee_summary_final.py`,
`final_autonomy_test.py`, `autonomy_recovery_test.py`, `verify_result.py`, `serve_dashboard.py`,
`script.js`, `server.js`, `soul.md`, `tools.md`, all root `*.html`/`*.css`, `college_data.json`,
`output.json`, `demo.csv`, `sample_data.csv`, `employee_input.csv`, `install_deps`, `install_flask`,
`FRAIDAY_FEATURES_REPORT.{md,html}` (self-describing marketing report, not a spec), `scratch/`,
`data/`. Also `tests/` (Playwright, auth-only).

---

## 4. Traps — concrete landmines

1. **No native tool calling anywhere.** `call_llm` (`llm/router.py:304-331`) takes two strings and
   returns text; there is no `tools=`, no `tool_choice=`, no message list. Every "tool call" in the
   repo is *the model printing JSON that we parse* (`orchestrator.py:384`) or *a template*
   (`executor.py:89-304`). Our brain must ship its own Groq tool-calling client; do not try to
   extend this router.
2. **Hardcoded, inconsistent model defaults.** `qwen/qwen3.8-27b` is the default in
   `api/runs.py:23,55`, `workflow.py:87,104`, `orchestrator.py:371`, `researcher.py:107`,
   `recovery.py:95`; but `executor.py:408,477` and `router.py:280,307` default to
   `openai/gpt-oss-120b`; and `api/sandbox.py:239` hardcodes the summarizer ladder
   `["llama-3.1-8b-instant", "openai/gpt-oss-20b"]`. A run's model therefore depends on which node
   runs. Our config must own the model id(s) in one place (`config/`).
3. **`re` is never imported in `workspace/tools.py`** yet used at lines 449, 479, 480. So
   `search_files(regex=True)` and `search_web(query)` always raise `NameError`, which the broad
   `except Exception` converts into a `success: False` result with `message: "name 're' is not defined"`.
   Silent-broken, not crash-visible.
4. **Silent excepts — 68 `except ...:` blocks under `backend/app/`.** The costly ones:
   `orchestrator.py:385-386` swallows a bad plan JSON and silently substitutes a template plan;
   `recovery.py:98-99` swallows a failed repair LLM call and silently writes template content;
   `router.py:183-184` swallows Ollama probe failures; `manager.py:137-139` swallows stat errors;
   `workflow.py:218-219,339-340` swallow conversation-persist failures with a `print`.
5. **Sync-in-async.** `workflow.py:217` and `:332` call `save_conversation_turn(...)` — a sync
   function that can call a blocking Groq `call_llm` (`api/sandbox.py:216-252`) — directly from the
   async run coroutine. `api/runs.py:65` calls `get_conversation_memory(...)` on the event loop from
   an `async def` handler, which can trigger the same blocking summarizer. One slow Groq call stalls
   every concurrent run.
6. **Module-global mutable state.** `events.py:5` `event_bus` (queues are created per run and
   **never removed** — a leak per run); `api/runs.py:39-40` `RUNS_DB` and `SESSION_HISTORY` (the
   latter is a *single shared* 10-entry list across all users/conversations, `runs.py:45-49`);
   `workspace/manager.py:347` `_workspace_managers`; `workspace/knowledge.py:80`
   `_knowledge_store_instance`. All of it is single-process, non-persistent, and shared across
   workspaces. Do not let `brain/` import these.
7. **Live secret on disk.** `.env` at the repo root contains a real `GROQ_API_KEY` in plaintext
   (one key, `GROQ_API_KEY=...`). It is listed in `.gitignore:15`, so it is not part of the tracked
   tree, but it is present in the working copy and must never be copied into `brain/`, `config/`, a
   prompt, or a log. Read it from the environment only. The repo already sanitizes keys out of error
   messages in one place (`workflow.py:69-76` `sanitize_error_message`) — that pattern is worth
   keeping, but it only covers two env vars.
8. **Windows-shaped everything.** `policy.py:11-23` mixes POSIX and Windows deny patterns and
   basename `.exe` stripping (`policy.py:94-96`); `runtime.py:9-14` probes
   `.venv/Scripts/python.exe`; `manager.py:59-90` does drive-letter and junction-escape reasoning;
   `list_directory_tree` walks with `os.sep` (`tools.py:538-547`); `executor.py:616-629`
   builds quoted `"<python_exe>" "<script>"` command strings. Any POSIX-only assumption in our tool
   providers will diverge from what the team actually runs.
9. **`tool_preview_browser` URL is wrong.** `tools.py:587` fetches
   `http://localhost:8000/api/preview/<path>` but the real route is
   `/api/preview/{workspace_id}/{file_path:path}` (`api/preview.py:77`). The missing workspace id
   means that tool never returns the intended HTML (it hits the not-found page or 404).
10. **The backend is unauthenticated.** `main.py:18-26` trusts an `X-Workspace-Id` header with
    default `"default"`; there is no auth dependency on any route. Anything we expose that touches a
    workspace is reachable by anyone who can reach port 8000.
11. **The SSE stream is single-subscriber and lossy.** `api/runs.py:164-172` drains one shared queue;
    two tabs opened on the same run compete for frames, there is no `id:`/replay/heartbeat, and
    events emitted *before* the client connects sit in the queue but events after the terminal frame
    are dropped. No keep-alive means proxies may close idle streams.
12. **`HINDSIGHT_URL` gives a false positive.** If someone sets `HINDSIGHT_URL`, `HindsightClient`
    logs "not fully implemented" and *still* writes the local JSON file (`client.py:53-55,76-78`).
    A configured URL looks like real remote memory but is not.
13. **`import app.memory` has import-time side effects.** `memory/api.py:9-12` constructs the
    Hindsight adapter, OKF manager and extractor at import, and `HindsightClient.__init__` runs
    `os.makedirs(...)` and writes `hindsight_db.json` when no endpoint is set (`client.py:24-32`).
    Importing the facade mutates disk. `OKFManager.__init__` also `makedirs` (`okf/manager.py:16`).
14. **Template "intelligence" will fool a demo.** `executor.py:89-304`
    `generate_smart_file_content(target, objective, research, observations)` returns canned
    employees.csv / notes.txt / HTML / CSS / employee_report.py / word_stats.py content, and
    `orchestrator.py:48-284` `build_dynamic_fallback_plan` is a keyword→plan lookup with hardcoded
    `factorial.py` / `fibonacci.py` / `csv_to_json.py` names. If the LLM path fails, the run still
    "succeeds" with fake work. Our validation must not treat these as evidence.
15. **Validation is regex/template-based, not LLM-verified.** `validator.py:8-15`
    `extract_expected_outputs(objective)` only extracts quoted strings after
    `print|output|say|display|log|echo`, then checks them as substrings of stdout
    (`validator.py:111-122`); the HTML branch hardcodes phrases like `"hello from fraiday"` and
    `"autonomous workspace test"` (`validator.py:43,59-64`).
16. **No context/token budget management.** Observations are hand-truncated to 300 chars
    (`controller.py:63-65`) and the whole plan + research is re-serialized into prompts every
    iteration (`orchestrator.py:327-367`, `executor.py:398-406`). There is no token counter and no
    compaction.
17. **Recovery is bounded but narrow.** `recovery.py:26-30` hard-caps at 2 attempts and
    `controller.py:7-9` caps iterations at 12 / replans at 3; recovery branches on `failure_kind`
    and for the fallback case rewrites the file from `generate_smart_file_content`
    (`recovery.py:189-196`) — i.e. it "repairs" by substituting canned content.
18. **`backend/data` is the de-facto memory root but is not per-user or per-run.**
    `knowledge_base.json`, `hindsight_mock/hindsight_db.json`, `knowledge/<user_id>/...` all share
    one directory; `user_id` is only a path segment. Concurrent users on one process interleave.
19. **`get_workspace_manager()` is workspace-id-cached but the ContextVar is set per HTTP request**
    (`main.py:20-23`) while `execute_run_task` runs in a *detached* `asyncio.create_task`
    (`api/runs.py:85-99`). The task inherits the context at creation, and the code defensively
    re-sets it (`workflow.py:91-93`), but any tool call made from a different task/thread after that
    point resolves against whatever the ambient context says.
20. **Frontend hardcodes `http://localhost:8000`.** `frontend/src/app/page.tsx:348,367,499,513` use
    absolute URLs rather than a proxy base, so any brain server we stand up must live on port 8000
    to be rendered by that page unmodified.

---

## 5. Recommended event / contract alignment

Goal: whatever our brain emits, the teammate frontend at `frontend/src/app/page.tsx` should render it
with **zero changes**, and our run API should be callable by the existing client code.

### 5.1 Event envelope — keep it byte-compatible

Emit exactly the existing envelope, and keep the `data` / `node` split the UI relies on:

```json
{"event": "<type>", "run_id": "<id>", "node": "<node>", "ts": "<ISO-8601 UTC>", "data": { ... }}
```

Rules to hold:
- Frame as `data: <compact json>\n\n` (unnamed `message` events). The UI uses `evtSource.onmessage`
  and reads `payload.event` — a named `event:` line would be ignored (`page.tsx:369-372`).
- Always include `run_id` (the UI does not currently need it, but it makes multi-run traces possible
  without breaking single-run parsing).
- Terminate the stream on `run_completed` **and** `run_failed` (`api/runs.py:169`, `page.tsx:493,536`).
- Emit `node` **lowercase** as one of the five names the UI's graph panel hardcodes in its render
  loop: `orchestrator | researcher | executor | validator | recovery` (`page.tsx:1302`). The panel
  looks the state up by that raw string (`setNodes(prev => ({ ...prev, [node]: 'running' }))`,
  `page.tsx:394-396`), so an uppercase or unknown node name simply never lights up. The workflow
  also emits `controller` and `chat` as `node` values (`workflow.py:241,201`), which are not in the
  panel — safe but invisible. Any new node name must be additive and lowercase.

### 5.2 Event types to guarantee (the UI's switch cases)

Minimum set for a rendered trace, in the order the UI expects them:
`context_loaded` → `plan_created` → (`step_started` → `tool_call_started` → `tool_call_completed` →
`observation_created` → `step_completed`|`step_failed`)* → `validation_result` →
`run_completed`|`run_failed`, with `agent_thinking` (payload `{"summary": str}`) available at any
point as the free-text activity line, and the optional `thought_generated`
(`{"node","phase","title","thought","model","provider","timestamp"}`) for the thinking panel.

If we add memory to the trace (the memory-lane visualisation in `docs/brain/UI_NOTES.md`), add **new**
event types rather than overloading existing ones — e.g. `memory_recall` / `memory_retain` with
`data: {"records": [...], "influenced_steps": [...]}` — so unknown types degrade to a no-op in the
current UI (`page.tsx:551` wraps every case in try/catch and simply ignores unknown `type`).

### 5.3 Run API — same verbs, same bodies

Serve, under the same paths, with the same payloads:

| Verb | Path | Body / Response |
|---|---|---|
| POST | `/api/runs/` | request `{objective, model?, provider?, workspace_id?, conversation_id?, attachments?: [{name,content,size?}]}` → `{"run_id": "run_xxxxxxxx", "status": "pending"}` |
| GET | `/api/runs/{run_id}/events` | `text/event-stream` per 5.1 |
| GET | `/api/runs/{run_id}` | run document containing at least `run_id`, `objective`, `model`, `provider`, `workspace_id`, `conversation_id`, `status`, `state`; the UI reads `state.artifacts` after completion (`page.tsx:503-504`) |
| POST | `/api/runs/{run_id}/approval` (alias `/approve`) | `{"decision": "approve" \| "reject"}` → `{"run_id", "status": "resuming"}`; 409 if nothing pending |

`status` vocabulary to preserve: `pending`, `running`, `paused`, `completed`, `failed`.
Emit `approval_required` with `{"status": "pending", "request": {...}}` and then **stop** the stream
frame loop without terminating the SSE connection abruptly — the existing implementation returns from
the loop and leaves the client connected (`workflow.py:283-299`), so the client polls
`GET /api/runs/{run_id}` and then posts the decision. Keep that pause semantics; a `run_completed`
must NOT be emitted while paused.

### 5.4 Tool and policy payloads to preserve

- Tool activity: `tool_call_started` `data` must contain `tool` (UI uppercases it) and, when
  relevant, `path` / `command` / `url` (`page.tsx:414-420`).
- Tool result: `tool_call_completed` `data` must carry `tool`, `success` (default true), and
  `error` as either a string or `{"code","message"}`; the UI reads
  `eventData.error.message` (`page.tsx:421-429`).
- Approval states on results: `status === "approval_required"` and a `reason` string — the UI renders
  a distinct approval badge and never marks it failed (`page.tsx:423-428,465-471`).
- Permission vocabulary: reuse `SAFE` / `APPROVAL_REQUIRED` / `DENIED` and the
  `{"status": "approval_required", "reason": ..., "policy": ...}` payload from
  `workspace/policy.py` + `workspace/tools.py`, so our tiers land in the same UI states.
- Failure taxonomy: reuse `classify_failure`'s strings (`syntax_error`, `runtime_error`,
  `missing_file`, `missing_arguments`, `permission_error`, `validation_error`, `command_error`) as
  our observation `kind`, so recovery and validation reasoning is comparable across both systems.

### 5.5 Where the brain should deliberately differ

- **One model id, one config file.** Do not inherit the per-node hardcoded defaults (trap 4.2).
- **Real tool calling.** Our planner must use Groq native tool calling; the existing JSON-plan hack
  is a fallback, not the target (trap 4.1).
- **Real remote memory behind a Protocol.** Wrap `HindsightAdapter`/`OKFManager` as the *mock*
  provider in our registry, and put the HTTP Hindsight client behind the same Protocol so the
  mock→real swap is a config line (`BUILD_LOG.md` D5) — the teammate's HTTP path is a TODO
  (trap 4.12).
- **Do not import `app.memory`, `app.events`, or `app.api.runs`.** All three carry import-time side
  effects or process globals (traps 4.6, 4.13).
- **Bring our own browser/STT/TTS providers.** There is no browser automation and no audio anywhere
  in the Python backend (sections 2.11, 2.16) — define the Protocols and ship mocks.
