# Brief — FOUNDATION ENGINEER (config, registry, events, providers, CLI)

You are building the load-bearing layer of a Python agent "Brain" for a hackathon project.
Repo root: `D:\College\Hack With Hyd\jarvis`. All paths below are relative to it.

## READ FIRST (the frozen contract — do not edit these)
- `brain/contracts.py` — all shared dataclasses, enums and Protocols. **Do not edit.**
- `brain/errors.py` — the error taxonomy. **Do not edit.**
- `docs/brain/CONTRACTS.md` — sections 1, 3, 4, 5, 7 are your spec.
- `docs/brain/schemas/tool.schema.json` and `docs/brain/schemas/event.schema.json` — validate against these, do not re-invent them.
- Inputs you load: `config/providers.yaml`, `config/tools/*.yaml`, `config/profiles/*.yaml`, `config/soul.md`, `config/agents.md`.

## YOUR FILES (you own these; create or edit nothing else)
```
brain/__init__.py                # re-export Brain, RunConfig, RunResult for tests
brain/util/__init__.py
brain/util/text.py               # estimate_tokens, normalize_ws, content_words, jaccard, truncate_middle
brain/redact.py
brain/config/__init__.py
brain/config/schema.py           # config dataclasses + jsonschema loading/validation helpers
brain/config/overrides.py        # deep-merge layering
brain/config/loader.py           # ConfigLoader + ResolvedConfig
brain/tools/__init__.py
brain/tools/registry.py          # ToolRegistry: YAML -> ToolSpec
brain/tools/validate.py          # JSON-Schema argument validation
brain/events/__init__.py
brain/events/emitter.py          # EventEmitter
brain/events/sinks.py            # MemorySink, JsonlSink, StdoutSink, MultiSink
brain/docs/__init__.py
brain/docs/gen_tools_md.py       # generates config/tools.md from the registry
brain/providers/__init__.py
brain/providers/registry.py      # ProviderRegistry: capability -> built instance
brain/cli.py                     # `python -m brain.cli ...`
brain/requirements.txt
config/tools.md                  # GENERATED — run the generator to produce it
```
Do NOT create anything under `brain/loop/`, `brain/prompt/`, `brain/llm/`, `brain/memory/`,
`brain/tools/executor.py`, `brain/providers/mock/`, `brain/providers/llm/`, `tests/`, or
`config/fixtures/` — peer agents own those and are working in parallel right now.

## EXACT API YOU MUST PROVIDE (peers code against this)

### `brain/config/schema.py`
```python
@dataclass(frozen=True, slots=True)
class MemoryConfig:
    enabled: bool = True
    recall_limit: int = 8
    retain_kinds: tuple[MemoryKind, ...] = ()      # default: all five kinds
    always_recall_kinds: tuple[MemoryKind, ...] = ()

def load_json_schema(path: Path) -> dict
def load_yaml(path: Path) -> Any
def validate_against_schema(schema: dict, instance: Any, *, label: str) -> list[str]
    # [] == valid; otherwise human-readable messages that name the offending JSON path
```

### `brain/config/loader.py`
```python
@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    soul_markdown: str
    agents_markdown: str
    profile: str
    role: str
    autonomy: Autonomy
    budgets: Budgets
    memory: MemoryConfig
    policy: dict[str, Any]
    tools: tuple[ToolSpec, ...]
    providers: dict[str, dict[str, Any]]   # capability -> {"impl": str, "settings": dict}
    workflow: str
    profile_prompts: dict[str, str]        # e.g. {"objective_hint": "..."}
    soul_additions: str
    demo: dict[str, Any]
    fingerprint: str                       # sha256[:16] over the canonical resolved config
    sources: dict[str, str]                # section -> originating file, for error messages

class ConfigLoader:
    def __init__(self, root: Path) -> None: ...
    def load(self, profile: str = "devops", *, workspace: str | None = None,
             user: str | None = None) -> ResolvedConfig: ...
    def reload(self) -> ResolvedConfig: ...            # re-resolve with the last arguments
    def current(self) -> ResolvedConfig | None: ...
    def list_profiles(self) -> list[str]: ...
    def write_layer(self, layer: str, key: str, value: Any) -> None:   # layer: workspace|user
```
Layering, lowest precedence first: `config/` defaults < profile < `.brain/workspace/` <
`.brain/user/`. Merge **per key**, deepest wins. Env var `BRAIN_PROVIDER__<CAPABILITY>=<impl>`
overrides a provider's `impl` only. On any validation failure raise `ConfigError` naming the
offending key path and **keep the previously loaded good config in force** — never half-apply.
`fingerprint` must be stable across runs for identical inputs and change when any effective
value changes; hash a canonical (sorted-key, no-whitespace) JSON dump.

### `brain/tools/registry.py`
```python
class ToolRegistry:
    def __init__(self, tools: Sequence[ToolSpec]) -> None: ...
    @classmethod
    def from_yaml_dir(cls, directory: Path) -> ToolRegistry: ...
    def get(self, name: str) -> ToolSpec | None: ...
    def all(self) -> tuple[ToolSpec, ...]: ...
    def names(self) -> tuple[str, ...]: ...
    def for_profile(self, include: Sequence[str]) -> tuple[ToolSpec, ...]: ...
    def api_schemas(self, names: Sequence[str]) -> list[dict]: ...
```
Also enforce, beyond the schema, the cross-field rules the schema cannot express cleanly: a
`destructive` tool may not be `auto`; a `deny` tool's `retry.max_attempts` must be 1; tool
names must be globally unique across all files. Raise `ConfigError` naming the file and field.

### `brain/tools/validate.py`
```python
def validate_args(spec: ToolSpec, args: dict) -> list[str]   # [] == ok
```
Must reject: missing required fields, wrong types, values outside `enum`/`minimum`/`maximum`,
and **unexpected keys** (our schemas set `additionalProperties: false`). Messages must name
the field and be actionable, e.g. `window_minutes: 5000 is greater than the maximum of 1440`.
These strings are fed verbatim into a repair prompt for the model, so vague messages cost real
recovery attempts.

### `brain/events/emitter.py`
```python
class EventEmitter:
    def __init__(self, sink: EventSink, run_id: str, clock: Clock, ids: IdFactory, *,
                 schema: dict | None = None, validate: bool = False) -> None: ...
    def emit(self, type: str, data: dict[str, Any], *,
             state: State | None = None, step_id: str | None = None) -> BrainEvent: ...
    @property
    def events(self) -> tuple[BrainEvent, ...]: ...
    @property
    def seq(self) -> int: ...
    def emit_error(self, err: BrainError) -> BrainEvent: ...
```
`seq` starts at 0 and increments by exactly 1 per event. Hand the event to the sink **before**
returning, so the trace is causally ordered rather than merely timestamped. With
`validate=True`, validate `event.to_dict()` against the event schema and raise `ContractError`
on mismatch. A sink that raises must not kill the run: catch it, count it, and surface it on
the next `emit_error` — the contract in `contracts.py` says a failing sink degrades to
dropping events rather than aborting a run.

### `brain/events/sinks.py`
`MemorySink()` with `.events`, `.since(seq)`, `.tail(n)`; `JsonlSink(path)` (append, creates
parents, never raises); `StdoutSink(stream=None, compact=True)`; `MultiSink(*sinks)`.

### `brain/redact.py`
```python
SECRET_PATTERNS: tuple[re.Pattern[str], ...]
def redact_text(text: str) -> str
def redact_paths(value: Any, paths: Sequence[str]) -> Any    # dotted paths, also "*" for any key
def redact_args(args: dict[str, Any], paths: Sequence[str]) -> dict[str, Any]
```
Cover at least: `Bearer <token>`, `sk-`/`gsk_`/`hsk_` prefixed keys, AWS `AKIA...`, long
hex/base64 blobs, and `password=`/`token=`/`api_key=`/`secret=` assignments. Replace with
`[REDACTED]`. Redaction must run **before** an event is constructed — never at serialisation
time, because by then the secret is already in a structure that a crash dump or a debug log
can capture.

### `brain/providers/registry.py`
```python
@dataclass(frozen=True, slots=True)
class ProviderChoice:
    capability: str
    impl: str
    settings: dict[str, Any]

class ProviderRegistry:
    def __init__(self, choices: Mapping[str, ProviderChoice], *, root: Path,
                 factories: Mapping[str, Callable[..., Any]] | None = None) -> None: ...
    @classmethod
    def from_config(cls, providers_cfg: Mapping[str, Any], *, root: Path,
                    env: Mapping[str, str] | None = None) -> ProviderRegistry: ...
    def get(self, capability: str) -> Any: ...          # built once, then cached
    def tool_provider(self, capability: str) -> ToolProvider: ...
    def llm(self) -> LLMClient: ...
    def memory(self) -> MemoryProvider: ...
    def human(self) -> HumanProvider: ...
    def clock(self) -> Clock: ...
    def ids(self) -> IdFactory: ...
    def sink(self) -> EventSink: ...
    def artifacts(self) -> ArtifactStore: ...
```
Factory resolution — this convention is what makes the mock→real swap a one-line change, so
get it right:
- For loop plumbing (`clock`, `ids`): module `brain.providers.<impl>` will not fit; use
  `brain.providers.mock.clock` / `brain.providers.mock.ids` and select the impl inside them
  (each exposes `build(settings, *, root)` and reads `settings["impl"]` or is given the impl).
  Simplest correct approach: pass the impl to the factory as `build(settings, *, root, impl)` if
  the callable accepts it, else `build(settings, *, root=root)`.
- For tool providers (`observability`, `incident`, `remediation`, `comms`, `crm`, `support`):
  module `brain.providers.<capability>.<impl>`.
- For `llm`: module `brain.providers.llm.<impl>`.
- For `human`: `brain.providers.mock.human`. For `events`: map `memory|stdout|jsonl` to the
  sink classes in `brain/events/sinks.py` directly. For `artifacts`: `brain.providers.filesystem`.
- Every factory module exposes `def build(settings: dict, *, root: Path) -> <object>`.
- **Import factory modules lazily inside the factory callable, never at module import time**, so
  your module imports cleanly even before a peer agent has created theirs.
- An unknown impl raises `ConfigError` naming both the capability and the impl.

### `brain/docs/gen_tools_md.py`
```python
def render_tools_md(registry: ToolRegistry, *, profile: str | None = None) -> str
def write_tools_md(registry: ToolRegistry, out: Path, *, profile: str | None = None) -> None
def main(argv: Sequence[str] | None = None) -> int      # python -m brain.docs.gen_tools_md
```
Group by provider. A summary table (name / permission / side effects / idempotent / timeout),
then per tool: the full description, an argument table (name, type, required, constraints), and
the retry policy. Output must be **deterministic** (stable ordering everywhere) so a test can
assert the committed file is current.

### `brain/cli.py`
`python -m brain.cli tools | config show | config reload | run --profile X --objective "..."`.
`run` may import `brain.loop.engine` lazily and print a clear message if it is not built yet.
Use `argparse` only. Ctrl-C must exit cleanly without a traceback.

### `brain/requirements.txt`
Runtime pins: `httpx>=0.27,<1`, `PyYAML>=6.0.1,<7`, `jsonschema>=4.22,<5`. Dev, as a comment:
`pytest>=8.2,<9`. No pydantic, no langchain, no langgraph.

## RULES
- Python 3.12. `from __future__ import annotations` in every module. Full type hints.
- Dependencies are **stdlib + httpx + PyYAML + jsonschema only**.
- Docstrings explain *why*, not what the name already says. Comment the non-obvious calls:
  why redaction happens pre-emission, why a bad layer keeps the old config, why a config
  fingerprint exists at all.
- No dead code, no unused imports, no `print()` outside the CLI and `StdoutSink`.
- Never read, log, or commit a secret. `GROQ_API_KEY` comes from the environment only.
- Deterministic output anywhere a test might snapshot it.

## DEFINITION OF DONE — run each of these and keep the real output
1. `python -m brain.cli config show --profile devops` prints the resolved config and its fingerprint.
2. `python -m brain.docs.gen_tools_md` writes `config/tools.md` covering all 29 tools from the 6 tool YAML files.
3. `python -c "from pathlib import Path; from brain.tools.registry import ToolRegistry; r=ToolRegistry.from_yaml_dir(Path('config/tools')); print(len(r.all()))"` prints `29`.
4. All 6 tool YAML files validate against `docs/brain/schemas/tool.schema.json`.
5. A deliberately broken tool file is rejected with a `ConfigError` naming the field. Write the
   bad file into the system temp directory (`tempfile`), **not** into the repo, and show the error.
6. Every capability in `config/providers.yaml` resolves without error (the mock modules may not
   exist yet — if so, state exactly which ones failed and why, rather than working around it).
7. Layering actually works: a `.brain/workspace/` override changes one nested key and leaves its
   siblings intact. Demonstrate both halves.
8. `python -c "import brain.config.loader, brain.tools.registry, brain.events.emitter, brain.redact, brain.providers.registry"` is clean.

Do not report success for anything you did not execute.

## REPORT BACK (under 30 lines, plain text, no preamble)
Status per definition-of-done item with trimmed real output. The devops config fingerprint.
Any contract ambiguity you had to resolve, and how. Anything you could NOT do. Files created
with line counts.