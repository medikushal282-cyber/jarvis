import pytest
from pathlib import Path
from typing import Any

from brain.contracts import ParseStrategy
from brain.llm.parsing import CallParser
from brain.providers.mock.memory import MockMemory
from brain.providers.registry import ProviderChoice, ProviderRegistry
from brain.loop.engine import StateMachine, State
from brain.events.emitter import EventEmitter
from brain.events.sinks import MemorySink
from brain.providers.llm.fake import FakeLLM


def test_yaml_seed_loads_properly(tmp_path: Path) -> None:
    seed_file = tmp_path / "seed.yaml"
    seed_file.write_text("version: 1\nmemories:\n  - id: m1\n    kind: outcome\n    text: some text\n", encoding="utf-8")
    memory = MockMemory(seed=seed_file)
    assert len(memory) == 1
    assert memory.all()[0].id == "m1"


def test_events_provider_resolves_via_build() -> None:
    registry = ProviderRegistry.from_config({
        "events": {"impl": "memory"}
    }, root=Path("."))
    sink = registry.sink()
    assert isinstance(sink, MemorySink)


def test_mock_memory_tool_provider_methods(tmp_path: Path) -> None:
    memory = MockMemory(store_path=tmp_path / "store.json")
    result = memory.invoke("save_memory", {"text": "hello", "kind": "outcome"})
    assert result.ok
    assert result.data["stored"] is True
    
    result2 = memory.invoke("recall_memory", {"query": "hello"})
    assert result2.ok
    assert len(result2.data["memories"]) == 1
    assert result2.data["memories"][0]["text"] == "hello"


def test_json_mode_drops_tools() -> None:
    from brain.contracts import LLMRequest
    
    parser = CallParser(FakeLLM({}), validator=lambda n, a: [])
    request = LLMRequest(messages=(), tools=({"type": "function", "function": {"name": "test"}},))
    
    # Internal _request_for isn't directly exposed, but we can access it
    json_req = parser._request_for(ParseStrategy.JSON_MODE, request)
    assert json_req.disable_native_tools is True
    assert json_req.tools == ()
    assert json_req.tool_choice == "none"


def test_state_machine_legal_transitions() -> None:
    class FakeClock:
        def now(self) -> Any: return None
        def monotonic(self) -> float: return 0.0
    class FakeIds:
        def new(self, prefix: str) -> str: return f"{prefix}-1"
        
    sink = MemorySink()
    emitter = EventEmitter(sink, "run-1", FakeClock(), FakeIds())
    machine = StateMachine(emitter)
    
    # Happy path to SELECT
    machine.enter("recalled", "ok")
    machine.enter("understood", "ok")
    machine.enter("planned", "ok")
    assert machine.state == State.SELECT
    
    # Decline path: SELECT -> RECOVER -> PLAN -> SELECT
    machine.enter("denied", "human declined")
    assert machine.state == State.RECOVER
    machine.enter("replanned", "replan complete")
    assert machine.state == State.PLAN
    machine.enter("planned", "plan updated")
    assert machine.state == State.SELECT
    
    # Replan from DECIDE path: SELECT -> CALL -> OBSERVE -> DECIDE -> PLAN -> SELECT
    machine.enter("tool_chosen", "ok")
    machine.enter("called", "ok")
    machine.enter("observed", "ok")
    assert machine.state == State.DECIDE
    machine.enter("replan", "needs new plan")
    assert machine.state == State.PLAN
    machine.enter("planned", "plan updated")
    assert machine.state == State.SELECT
    
    # Budget exhausted from DECIDE
    machine.enter("tool_chosen", "ok")
    machine.enter("called", "ok")
    machine.enter("observed", "ok")
    machine.enter("exhausted", "tokens exhausted")
    assert machine.state == State.FINISH


def test_memory_on_ends_completed_and_off_ends_partial() -> None:
    from brain.loop.engine import Brain, RunConfig
    
    # Memory ON
    result_on = Brain(root=Path(".")).run(
        RunConfig(
            objective="checkout-api is returning 5xx errors",
            profile="devops",
            memory_enabled=True,
        )
    )
    assert str(result_on.status) == "completed"
    
    # Memory OFF
    result_off = Brain(root=Path(".")).run(
        RunConfig(
            objective="checkout-api is returning 5xx errors",
            profile="devops",
            memory_enabled=False,
        )
    )
    assert str(result_off.status) == "partial"

def test_tools_md_not_drifted() -> None:
    """Ensure config/tools.md matches the registry exactly."""
    import sys
    import subprocess
    
    root = Path(__file__).parent.parent
    tools_md = root / "config" / "tools.md"
    before = tools_md.read_text(encoding="utf-8")
    
    subprocess.run([sys.executable, "-m", "brain.docs.gen_tools_md"], cwd=root, check=True)
    
    after = tools_md.read_text(encoding="utf-8")
    assert before == after, "config/tools.md has drifted! Run python -m brain.docs.gen_tools_md to fix."
