"""Integration and unit tests for the agent brain.

Written against the frozen contract in `docs/brain/CONTRACTS.md` and the published JSON Schemas
rather than against the implementation, so a passing test means the contract holds rather than
that the code agrees with itself.

The integration tests drive the full loop with the scripted fake LLM and the bundled mocks. Both
are real implementations of the frozen Protocols, so what is exercised is the actual reasoning
path -- assembler, parser, policy engine, recovery, memory attribution -- and not a stubbed
approximation of it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from brain.config.loader import ConfigLoader, deep_merge
from brain.contracts import (
    Autonomy,
    FinishReason,
    InfluenceBasis,
    LLMRequest,
    LLMResponse,
    MemoryItem,
    MemoryKind,
    RecallQuery,
    RunStatus,
    State,
    ToolCall,
)
from brain.errors import ConfigError, ContractError
from brain.events.emitter import EventEmitter
from brain.events.sinks import MemorySink
from brain.llm.parsing import CallParser, parse_tool_arguments
from brain.loop.engine import Brain, PolicyEngine, RunConfig, StateMachine, TRANSITIONS
from brain.prompt.assembler import PromptAssembler, extract_section
from brain.providers.mock.memory import MockMemory
from brain.providers.mock.plumbing import FrozenClock, SequentialIds
from brain.providers.registry import ProviderRegistry
from brain.redact import redact_args, redact_text
from brain.tools.registry import ToolRegistry
from brain.tools.validate import validate_args

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def loader() -> ConfigLoader:
    return ConfigLoader(ROOT)


@pytest.fixture()
def devops(loader: ConfigLoader):
    return loader.load("devops")


@pytest.fixture(autouse=True)
def fresh_world():
    """Reset every bundled mock world so no test can pass on another test's mutations."""
    from brain.providers.mock import business, devops as devops_mock

    devops_mock.world().reset()
    business.world().reset()
    yield
    devops_mock.world().reset()
    business.world().reset()


def _registry() -> ToolRegistry:
    return ToolRegistry.from_yaml_dir(ROOT / "config/tools", root=ROOT)


def _emitter() -> tuple[MemorySink, EventEmitter]:
    sink = MemorySink()
    clock = FrozenClock(datetime(2026, 3, 14, 9, 12, tzinfo=UTC))
    return sink, EventEmitter(sink, "run-1", clock, SequentialIds())


# ======================================================================================
# Configuration
# ======================================================================================


def test_all_tool_files_validate_and_load() -> None:
    assert len(_registry().all()) == 29


def test_every_declared_tool_method_exists_on_its_provider(devops) -> None:
    """A tool whose provider has no such method is a runtime failure no schema catches."""
    providers = ProviderRegistry.from_config(devops.providers, root=ROOT)
    missing: list[str] = []
    for spec in _registry().all():
        try:
            provider = providers.tool_provider(spec.provider)
        except ConfigError as exc:
            missing.append(f"{spec.provider}: {exc}")
            continue
        if not hasattr(provider, spec.method):
            missing.append(f"{spec.provider}.{spec.method} (declared by {spec.name})")
    assert not missing, f"tools declared with no matching provider method: {missing}"


def test_destructive_auto_tool_is_rejected(tmp_path: Path) -> None:
    """The cross-field rule the JSON Schema cannot express: irreversible must reach a human."""
    bad = tmp_path / "config" / "tools"
    bad.mkdir(parents=True)
    (bad / "bad.yaml").write_text(
        """
version: 1
tools:
  - name: nuke_everything
    description: Performs an irreversible operation with no human involved, which must not load.
    provider: remediation
    method: restart_service
    parameters:
      type: object
      properties: {}
      additionalProperties: false
    permission: auto
    timeout_s: 5
    idempotent: false
    side_effects: destructive
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="destructive"):
        ToolRegistry.from_yaml_dir(bad, root=tmp_path)


def test_layering_overrides_one_key_and_keeps_siblings() -> None:
    """A shallow merge would erase siblings, which is what makes overrides useless in practice."""
    merged = deep_merge(
        {"agents": {"budgets": {"max_steps": 24, "max_tokens": 100}, "memory": {"enabled": True}}},
        {"agents": {"budgets": {"max_steps": 5}}},
    )
    assert merged["agents"]["budgets"]["max_steps"] == 5
    assert merged["agents"]["budgets"]["max_tokens"] == 100, "sibling budget was lost"
    assert merged["agents"]["memory"]["enabled"] is True, "unrelated section was lost"


def test_unknown_profile_names_the_alternatives(loader: ConfigLoader) -> None:
    with pytest.raises(ConfigError, match="available"):
        loader.load("does-not-exist")


def test_fingerprint_is_stable_and_value_sensitive(loader: ConfigLoader) -> None:
    assert loader.load("devops").fingerprint == loader.load("devops").fingerprint
    assert loader.load("sales").fingerprint != loader.load("devops").fingerprint


# ======================================================================================
# Tool argument validation
# ======================================================================================


def test_validate_args_reports_actionable_errors() -> None:
    spec = _registry().require("fetch_metrics")
    assert validate_args(spec, {"service": "checkout-api", "metric": "db_pool_active"}) == []

    assert any(
        "not one of" in p
        for p in validate_args(spec, {"service": "checkout-api", "metric": "invented_metric"})
    )
    assert any(
        "greater than the maximum" in p
        for p in validate_args(
            spec,
            {"service": "checkout-api", "metric": "db_pool_active", "window_minutes": 5000},
        )
    )
    assert any("required field is missing" in p for p in validate_args(spec, {"metric": "x"}))
    assert any(
        "unexpected field" in p
        for p in validate_args(spec, {"service": "x", "metric": "db_pool_active", "surprise": 1})
    )


# ======================================================================================
# Tool-call parsing
# ======================================================================================


@pytest.mark.parametrize(
    ("raw", "expected_keys"),
    [
        ('{"service": "checkout-api"}', {"service"}),
        ('```json\n{"service": "checkout-api"}\n```', {"service"}),
        ('Here you go: {"service": "checkout-api"} - done.', {"service"}),
        ("{'service': 'checkout-api'}", {"service"}),
        ('{"service": "checkout-api",}', {"service"}),
        ('{"service": "checkout-api", "limit": 5', {"service", "limit"}),
    ],
)
def test_parse_survives_real_malformations(raw: str, expected_keys: set[str]) -> None:
    parsed, error = parse_tool_arguments(raw)
    assert error is None, f"failed to parse {raw!r}: {error}"
    assert expected_keys <= set(parsed)


def test_parse_reports_what_it_tried() -> None:
    parsed, error = parse_tool_arguments("this is not json at all")
    assert parsed == {}
    assert error and "could not parse" in error


def test_ladder_repairs_then_drops_tools_for_json_mode() -> None:
    """The rung that matters: JSON mode must omit `tools`, since Groq rejects both together."""
    from brain.providers.llm.fake import FakeLLM

    class BadThenGood(FakeLLM):
        def __init__(self) -> None:
            super().__init__({}, strict=False)
            self.seen: list[LLMRequest] = []

        def complete(self, request: LLMRequest) -> LLMResponse:
            self.seen.append(request)
            # Fail on native-tools calls (1st call + 1 repair attempt).
            # Succeed only when the ladder has dropped to JSON mode (disable_native_tools=True).
            if not request.disable_native_tools:
                return LLMResponse(
                    tool_calls=(ToolCall("c1", "get_service_health", "{not json", {}, "bad json"),),
                    finish_reason=FinishReason.TOOL_CALLS,
                )
            return LLMResponse(
                tool_calls=(
                    ToolCall(
                        "c2",
                        "get_service_health",
                        '{"service": "checkout-api"}',
                        {"service": "checkout-api"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            )

    registry = _registry()

    def validator(name: str, args: dict) -> list[str]:
        spec = registry.get(name)
        return [f"unknown tool {name}"] if spec is None else validate_args(spec, args)

    client = BadThenGood()
    parser = CallParser(client, max_repairs=1, validator=validator)
    outcome = parser.obtain_call(
        LLMRequest(messages=(), tools=registry.api_schemas(["get_service_health"]))
    )
    assert outcome.response.tool_calls[0].is_parsed
    assert outcome.repair_attempts >= 1, "a malformed call must be repaired, not silently retried"

    json_rung = [r for r in client.seen if r.disable_native_tools]
    assert json_rung, "the ladder never reached the JSON-mode rung"
    assert json_rung[0].tools == (), "JSON mode must drop tools entirely"


# ======================================================================================
# Policy
# ======================================================================================


def _widened(config, *names: str):
    """The profile config with extra tools added, to test tier behaviour independent of inclusion."""
    import dataclasses

    registry = _registry()
    extra = tuple(registry.require(n) for n in names)
    return dataclasses.replace(config, tools=config.tools + extra)


def test_deny_tier_never_runs_at_any_autonomy(devops) -> None:
    spec = _registry().require("run_diagnostic_command")
    assert spec.permission.value == "deny"
    engine = PolicyEngine(_widened(devops, "run_diagnostic_command"))
    for autonomy in (Autonomy.SUPERVISED, Autonomy.STANDARD, Autonomy.AUTONOMOUS):
        decision = engine.decide(spec, autonomy)
        assert decision.decision == "deny", f"deny tier was allowed under {autonomy}"


def test_tool_absent_from_profile_is_unavailable(devops) -> None:
    spec = _registry().require("run_diagnostic_command")
    decision = PolicyEngine(devops).decide(spec, Autonomy.AUTONOMOUS)
    assert decision.decision == "deny"
    assert decision.reason_code == "profile_not_included"


def test_confirm_budget_exhausts_rather_than_looping(devops) -> None:
    spec = _registry().require("rollback_deploy")
    engine = PolicyEngine(devops)
    limit = int((devops.policy or {}).get("max_confirm_requests", 6))

    for _ in range(limit):
        assert engine.decide(spec, Autonomy.STANDARD).decision == "confirm"
        engine.record_confirmation()

    exhausted = engine.decide(spec, Autonomy.STANDARD)
    assert exhausted.decision == "deny"
    assert exhausted.reason_code == "confirm_budget_exhausted"


def test_read_only_tool_is_auto_under_standard_autonomy(devops) -> None:
    decision = PolicyEngine(devops).decide(
        _registry().require("search_logs"), Autonomy.STANDARD
    )
    assert decision.decision == "allow"
    assert decision.reason_code == "tier_auto"


def test_policy_reason_is_a_principle_not_the_matched_rule(devops) -> None:
    """Explaining the tripwire teaches how to route around it."""
    decision = PolicyEngine(devops).decide(
        _registry().require("rollback_deploy"), Autonomy.STANDARD
    )
    assert decision.reason_code == "tier_confirm"
    assert "tier_confirm" not in decision.reason


# ======================================================================================
# Memory
# ======================================================================================


def test_memory_ids_are_stable_across_recalls() -> None:
    store = MockMemory(seed=ROOT / "config/fixtures/memory/devops_seed.yaml")
    query = RecallQuery(text="checkout-api connection pool exhaustion", entities=("checkout-api",))
    first = [m.id for m in store.recall(query)]
    second = [m.id for m in store.recall(query)]
    assert first and first == second, "unstable ids silently empty the trace's memory lane"


def test_memory_ranks_the_failure_highly() -> None:
    """The failure memory is what stops a repeat of a dead end, so it must surface."""
    store = MockMemory(seed=ROOT / "config/fixtures/memory/devops_seed.yaml")
    hits = store.recall(
        RecallQuery(
            text="checkout-api connection pool exhaustion restart",
            entities=("checkout-api",),
            limit=8,
        )
    )
    by_id = {m.id: m for m in hits}
    assert "mem-0001" in by_id, "the restart-failure memory was not recalled at all"
    assert by_id["mem-0001"].kind is MemoryKind.FAILURE


def test_retain_is_idempotent() -> None:
    store = MockMemory()
    item = MemoryItem(id="mem-x", kind=MemoryKind.OUTCOME, text="A durable lesson about pooling.")
    assert store.retain([item]).written == ("mem-x",)
    second = store.retain([item])
    assert second.written == ()
    assert second.deduplicated == ("mem-x",)
    assert len(store) == 1, "replaying a run must not inflate the store"


def test_memory_off_recalls_nothing_and_reports_the_skip() -> None:
    store = MockMemory(enabled=False)
    assert store.recall(RecallQuery(text="anything")) == []
    result = store.retain([MemoryItem(id="m", kind=MemoryKind.OUTCOME, text="x")])
    assert result.written == ()
    assert result.skipped[0].reason == "memory_disabled"


# ======================================================================================
# Redaction
# ======================================================================================


def test_redaction_catches_credentials_in_free_text() -> None:
    cleaned = redact_text("Authorization: Bearer gsk_abcdefghijklmnop1234 api_key=supersecret99")
    assert "gsk_abcdefghijklmnop1234" not in cleaned
    assert "supersecret99" not in cleaned


def test_redaction_removes_declared_paths_at_any_depth() -> None:
    cleaned = redact_args({"service": "checkout-api", "config": {"env": {"TOKEN": "hunter2"}}}, ["env"])
    assert cleaned["config"]["env"] == "[REDACTED]"
    assert cleaned["service"] == "checkout-api"


# ======================================================================================
# Prompt assembly
# ======================================================================================


def test_non_negotiables_are_reinjected_at_head_and_tail(devops) -> None:
    prompt = PromptAssembler(devops, token_budget=60_000).build(
        task="PLAN", objective="Resolve the checkout-api 5xx spike."
    )
    marker = "Never call a tool whose permission tier is `deny`"
    assert marker in prompt.messages[0].content, "non-negotiables missing from the head"
    assert marker in prompt.messages[-1].content, "non-negotiables missing from the tail"
    assert "TASK: PLAN" in prompt.messages[-1].content


def test_protected_sections_survive_a_tiny_budget(devops) -> None:
    prompt = PromptAssembler(devops, token_budget=1200).build(
        task="DECIDE",
        objective="A short objective.",
        current_step="s1: act",
        observations=["Establishes: something"] * 60,
    )
    assert "A short objective." in prompt.messages[-1].content
    assert "observations" in prompt.trimmed, "the documented trim order should fire first"
    assert prompt.token_estimate > 0


def test_extract_section_stops_at_the_next_heading() -> None:
    assert extract_section("# Alpha\nline one\n# Beta\nline two\n", "# Alpha") == "# Alpha\nline one"


# ======================================================================================
# State machine
# ======================================================================================


def test_illegal_transition_is_refused() -> None:
    _, emitter = _emitter()
    machine = StateMachine(emitter)
    with pytest.raises(ContractError):
        machine.enter("understood", "not legal from RECALL")


def test_transition_table_covers_the_happy_path() -> None:
    expected = [
        (State.RECALL, "recalled", State.UNDERSTAND),
        (State.UNDERSTAND, "understood", State.PLAN),
        (State.PLAN, "planned", State.SELECT),
        (State.SELECT, "tool_chosen", State.CALL),
        (State.CALL, "called", State.OBSERVE),
        (State.OBSERVE, "observed", State.DECIDE),
        (State.DECIDE, "finish", State.FINISH),
        (State.FINISH, "finished", State.RETAIN),
    ]
    for source, outcome, target in expected:
        assert TRANSITIONS[(source, outcome)] is target


# ======================================================================================
# The full loop
# ======================================================================================

_OBJECTIVE = (
    "checkout-api is returning 5xx errors since this morning. Find out why and fix it if you can."
)

_CORE_EVENTS = (
    "run.started",
    "state.entered",
    "recall.performed",
    "understand.completed",
    "plan.created",
    "step.selected",
    "policy.decided",
    "tool.called",
    "tool.result",
    "observation.extracted",
    "verification.performed",
    "metric.updated",
    "run.finished",
    "memory.retained",
)


def test_full_run_completes_and_emits_the_core_events() -> None:
    brain = Brain(root=ROOT)
    result = brain.run(RunConfig(objective=_OBJECTIVE, profile="devops", memory_enabled=True))

    assert result.run_id
    assert result.status in {RunStatus.COMPLETED, RunStatus.PARTIAL}, result.answer
    assert result.answer.strip()

    assert brain._last_events is not None
    types = {e.type for e in brain._last_events.events}
    missing = [t for t in _CORE_EVENTS if t not in types]
    assert not missing, f"missing from the trace: {missing}"


def test_sequence_numbers_are_contiguous_from_zero() -> None:
    brain = Brain(root=ROOT)
    brain.run(RunConfig(objective=_OBJECTIVE, profile="devops"))
    assert brain._last_events is not None
    seqs = [e.seq for e in brain._last_events.events]
    assert seqs == list(range(len(seqs))), "seq must be monotonic and gapless"


def test_trace_is_deterministic_under_a_frozen_clock() -> None:
    """Sequential ids plus a frozen clock are what make two runs comparable at all."""
    first = Brain(root=ROOT).run(RunConfig(objective=_OBJECTIVE, profile="devops"))
    second = Brain(root=ROOT).run(RunConfig(objective=_OBJECTIVE, profile="devops"))
    assert first.metrics.steps_to_completion == second.metrics.steps_to_completion
    assert first.status == second.status


def test_memory_on_produces_attributed_influence() -> None:
    """The most important assertion here: memory must be visibly load-bearing."""
    brain = Brain(root=ROOT)
    brain.run(RunConfig(objective=_OBJECTIVE, profile="devops", memory_enabled=True))
    assert brain._last_events is not None

    recall = brain._last_events.of_type("recall.performed")
    assert recall and recall[0].data["memory_enabled"] is True
    assert recall[0].data["hit_count"] > 0, "the seed fixture should surface memories"

    influenced = brain._last_events.of_type("memory.influenced")
    assert influenced, "memory was on, memories were recalled, yet nothing was attributed"
    valid_bases = {str(b) for b in InfluenceBasis}
    for event in influenced:
        assert event.data["memory_ids"]
        assert event.data["basis"] in valid_bases


def test_memory_off_emits_no_influence_and_still_completes() -> None:
    """The A/B baseline: with memory off the loop still finishes and claims nothing."""
    brain = Brain(root=ROOT)
    result = brain.run(RunConfig(objective=_OBJECTIVE, profile="devops", memory_enabled=False))
    assert result.answer.strip(), "a memory-off run must still produce a report"
    assert brain._last_events is not None

    recall = brain._last_events.of_type("recall.performed")
    assert recall and recall[0].data["memory_enabled"] is False
    assert recall[0].data["hit_count"] == 0
    assert not brain._last_events.of_type("memory.influenced"), "memory off, yet influence claimed"

    retained = brain._last_events.of_type("memory.retained")
    assert retained and retained[0].data["written"] == []
    assert retained[0].data["skipped"][0]["reason"] == "memory_disabled"


def test_all_three_profiles_load_and_resolve_their_tools(loader: ConfigLoader) -> None:
    for profile in ("devops", "sales", "support"):
        config = loader.load(profile)
        assert config.tools, f"profile {profile} resolved no tools"
        assert config.fingerprint
