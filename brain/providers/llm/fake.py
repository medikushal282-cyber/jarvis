"""A scripted, deterministic LLM client.

A real implementation of :class:`brain.contracts.LLMClient`, not a mock object. That distinction
is the point: because the loop cannot tell it apart from the real client, every test and every
offline demo exercises the actual reasoning path -- the prompt assembler, the parser, the ladder,
the policy engine -- rather than a stubbed-out approximation of it.

Dispatch is by task marker. The assembler writes a line ``TASK: <PHASE>`` into the user message,
and this client serves the scripted reply for that phase. Keying on an explicit marker rather
than fuzzy prompt matching means a change to prompt wording cannot silently break the fake and
turn a real failure into a passing test.

The devops script branches on **whether a specific memory was injected into the prompt**. That is
not a trick to flatter the demo; it is the honest simulation of what a language model does. Given
the text "restarting checkout-api for this signature resolved nothing", a well-behaved model
chooses differently than it would without it. Scripting that branch is what lets the memory
ON/OFF comparison produce a real difference offline -- in tool choice and in steps-to-completion
-- rather than in a number invented for a slide.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from brain.contracts import (
    ChatMessage,
    FinishReason,
    LLMRequest,
    LLMResponse,
    TokenUsage,
    ToolCall,
)
from brain.errors import ErrorClass, LLMError

_TASK_RE = re.compile(r"TASK:\s*([A-Z_]+)")

#: The memory whose presence in the prompt flips the scripted agent from the naive path to the
#: informed one. Named rather than positional so the fixture and this file cannot drift apart
#: silently.
PIVOTAL_MEMORY_ID = "mem-0001"

#: Tool plan taken when the failure memory is visible: correlate the onset with a deploy and undo
#: the change, rather than restarting something that a restart cannot fix.
_INFORMED_PLAN: tuple[dict[str, Any], ...] = (
    {"name": "get_service_health", "arguments": {"service": "checkout-api"}},
    {"name": "get_recent_deploys", "arguments": {"service": "checkout-api", "window_hours": 96}},
    {
        "name": "fetch_metrics",
        "arguments": {"service": "checkout-api", "metric": "db_pool_active", "window_minutes": 240},
    },
    {
        "name": "rollback_deploy",
        "arguments": {
            "service": "checkout-api",
            "to_deploy_id": "dep-8790",
            "reason": "Onset at 08:41Z aligns with v2.31.0 (dep-8841), which lowered db_pool_max 60 to 10. Undoing the change rather than masking it.",
        },
    },
    {"name": "get_service_health", "arguments": {"service": "checkout-api"}},
)

#: Tool plan taken with no memory available: read the obvious signal, restart, hope.
_NAIVE_PLAN: tuple[dict[str, Any], ...] = (
    {"name": "get_service_health", "arguments": {"service": "checkout-api"}},
    {
        "name": "search_logs",
        "arguments": {"service": "checkout-api", "query": "connection pool", "window_minutes": 60},
    },
    {
        "name": "restart_service",
        "arguments": {
            "service": "checkout-api",
            "replicas": "one",
            "reason": "Connection pool timeouts with all connections active; cycling a replica to clear the condition.",
        },
    },
    {"name": "get_service_health", "arguments": {"service": "checkout-api"}},
)

_UNDERSTAND = {
    "goal": "Find why checkout-api is returning 5xx errors and resolve the customer-visible impact.",
    "success_criteria": [
        "The failing dependency or change responsible for the 5xx rate is identified with evidence",
        "checkout-api error rate is back below 1% and verified by a fresh health check",
    ],
    "out_of_scope": ["Fixing the underlying capacity planning process", "Other services not currently degraded"],
    "unknowns": ["Whether a change was deployed in the last 96 hours", "Whether the pool is actually saturated"],
    "ambiguity": None,
}

_PLAN_INFORMED = {
    "steps": [
        {
            "id": "s1",
            "intent": "Confirm the current impact and blast radius on checkout-api",
            "success_criterion": "A health reading exists showing checkout-api error rate and replica readiness",
            "suggested_tool": "get_service_health",
            "cites": [],
        },
        {
            "id": "s2",
            "intent": "Check whether a deploy boundary explains the onset, before theorising about novel causes",
            "success_criterion": "Deploy history for checkout-api covering the onset is retrieved",
            "suggested_tool": "get_recent_deploys",
            "cites": ["mem-0002", "mem-0007"],
        },
        {
            "id": "s3",
            "intent": "Confirm or disprove connection-pool saturation quantitatively",
            "success_criterion": "db_pool_active is measured against db_pool_max",
            "suggested_tool": "fetch_metrics",
            "cites": ["mem-0003"],
        },
        {
            "id": "s4",
            "intent": "Undo the change implicated by the onset rather than restarting the service",
            "success_criterion": "The implicated deploy is rolled back and the action reports completion",
            "suggested_tool": "rollback_deploy",
            "cites": ["mem-0001", "mem-0002"],
        },
        {
            "id": "s5",
            "intent": "Verify recovery against the success criterion rather than assuming the fix worked",
            "success_criterion": "A fresh health check shows error rate below 1%",
            "suggested_tool": "get_service_health",
            "cites": [],
        },
    ]
}

_PLAN_NAIVE = {
    "steps": [
        {
            "id": "s1",
            "intent": "Confirm the current impact on checkout-api",
            "success_criterion": "A health reading exists showing checkout-api error rate",
            "suggested_tool": "get_service_health",
            "cites": [],
        },
        {
            "id": "s2",
            "intent": "Find the error signature in the logs",
            "success_criterion": "Log entries containing the failing signature are retrieved",
            "suggested_tool": "search_logs",
            "cites": [],
        },
        {
            "id": "s3",
            "intent": "Clear the condition by cycling a replica",
            "success_criterion": "A restart completes and reports a resulting status",
            "suggested_tool": "restart_service",
            "cites": [],
        },
        {
            "id": "s4",
            "intent": "Confirm the service recovered",
            "success_criterion": "A fresh health check shows error rate below 1%",
            "suggested_tool": "get_service_health",
            "cites": [],
        },
    ]
}


class FakeLLM:
    """Serves scripted responses keyed by the ``TASK:`` marker in the prompt."""

    def __init__(
        self,
        script: Mapping[str, Any] | None = None,
        *,
        strict: bool = False,
        scenario: str = "devops_pool_exhaustion",
    ) -> None:
        self.script: dict[str, Any] = dict(script or {})
        self.strict = strict
        self.scenario = scenario
        self.calls: list[LLMRequest] = []
        self._tool_cursor = 0
        self._plan_choice: str | None = None
        self._memory_seen: bool | None = None

    @classmethod
    def from_yaml(cls, path: Path, *, scenario: str | None = None) -> FakeLLM:
        if not Path(path).exists():
            return cls(scenario=scenario or "devops_pool_exhaustion")
        with Path(path).open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        return cls(loaded, scenario=scenario or str(loaded.get("scenario", "devops")))

    # ------------------------------------------------------------------ protocol

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        task = self._task_of(request)
        prompt_text = "\n".join(m.content for m in request.messages)

        if task == "SELECT":
            return self._select(prompt_text)
        if task == "UNDERSTAND":
            return self._json(_UNDERSTAND)
        if task == "PLAN":
            informed = self._informed(prompt_text)
            return self._json(_PLAN_INFORMED if informed else _PLAN_NAIVE)
        if task == "DECIDE":
            return self._decide()
        if task == "FINISH":
            return self._finish()
        if task == "RETAIN":
            return self._retain(prompt_text)

        if self.strict:
            raise LLMError(
                f"FakeLLM has no script for task {task!r}; prompt began: {prompt_text[:160]!r}",
                error_class=ErrorClass.VALIDATION,
            )
        return LLMResponse(content="", finish_reason=FinishReason.STOP, model="fake")

    # ------------------------------------------------------------------ phases

    def _select(self, prompt_text: str) -> LLMResponse:
        informed = self._informed(prompt_text)
        plan = _INFORMED_PLAN if informed else _NAIVE_PLAN
        if self._tool_cursor >= len(plan):
            # Plan exhausted. An empty response with `stop` is what the loop interprets as
            # "no further tool needed", which routes it to DECIDE -- the same thing a real model
            # signals when it stops asking for tools.
            return LLMResponse(
                content="", finish_reason=FinishReason.STOP, model="fake", usage=self._usage()
            )
        step = plan[self._tool_cursor]
        self._tool_cursor += 1
        call = ToolCall(
            call_id=f"call_{self._tool_cursor:03d}",
            name=str(step["name"]),
            arguments_raw=json.dumps(step["arguments"], sort_keys=True),
            arguments=dict(step["arguments"]),
        )
        return LLMResponse(
            tool_calls=(call,),
            finish_reason=FinishReason.TOOL_CALLS,
            model="fake",
            usage=self._usage(),
        )

    def _decide(self) -> LLMResponse:
        # Scripted policy: keep calling tools until the plan is spent, then finish. Deliberately
        # simple -- DECIDE's real work (evaluating a success criterion against evidence) is the
        # loop's, and duplicating judgement here would test the fake instead of the brain.
        exhausted = self._tool_cursor >= max(len(_INFORMED_PLAN), len(_NAIVE_PLAN))
        return self._json(
            {
                "next": "finish" if exhausted else "continue",
                "criterion": "The current step produced the evidence it was for",
                "passed": exhausted,
                "evidence": "Tool results returned without error",
                "reason": "Plan steps exhausted" if exhausted else "More plan steps remain",
            }
        )

    def _finish(self) -> LLMResponse:
        informed = self._plan_choice == "informed"
        if informed:
            answer = (
                "checkout-api is recovered. Error rate is back to 0.11% and all replicas are "
                "ready, verified by a fresh health check after the change.\n\n"
                "Root cause: deploy v2.31.0 (dep-8841, 2026-03-10) lowered db_pool_max from 60 to "
                "10 while raising worker concurrency, so the connection pool saturated under the "
                "morning peak and requests timed out waiting for a connection.\n\n"
                "Action taken: rolled checkout-api back off v2.31.0 rather than restarting it. A "
                "restart was rejected as the first move because this exact signature has already "
                "recurred after a restart on this service.\n\n"
                "Still open: the pool sizing decision itself. A follow-up ticket records that "
                "db_pool_max=10 is below peak concurrency, so a future deploy can reintroduce this."
            )
        else:
            answer = (
                "checkout-api was restarted and its error rate has dropped.\n\n"
                "Observed: connection-pool timeouts with all connections active and requests "
                "queuing. A replica was cycled, which cleared the condition.\n\n"
                "Not established: why the pool exhausted. No change boundary was checked, so if "
                "this was caused by a recent deploy the condition is expected to return. "
                "Recommend checking deploy history and opening a follow-up ticket."
            )
        return self._json(
            {
                "status": "completed",
                "answer": answer,
                "blocker": None,
                "next_action": None,
            }
        )

    def _retain(self, prompt_text: str) -> LLMResponse:
        informed = self._informed(prompt_text)
        if informed:
            memories = [
                {
                    "kind": "outcome",
                    "text": (
                        "On checkout-api, rolling back the deploy that lowered db_pool_max "
                        "resolved connection pool exhaustion; the error rate returned below 1% "
                        "and was confirmed by a health check."
                    ),
                    "entities": ["checkout-api", "rollback_deploy", "db_pool_max"],
                    "confidence": 0.85,
                }
            ]
        else:
            memories = [
                {
                    "kind": "outcome",
                    "text": (
                        "Restarting a checkout-api replica cleared connection-pool timeouts, but "
                        "the underlying cause was not established."
                    ),
                    "entities": ["checkout-api", "restart_service"],
                    "confidence": 0.5,
                }
            ]
        return self._json(
            {
                "memories": memories,
                "skipped": [
                    {
                        "candidate": "The incident happened on a Thursday morning.",
                        "reason": "horizon_test",
                    }
                ],
            }
        )

    # ------------------------------------------------------------------ helpers

    def _informed(self, prompt_text: str) -> bool:
        """Whether the pivotal memory is present in this prompt.

        Cached per instance because it must not change mid-run: a scripted agent that switched
        strategy halfway through would produce a trace that no real model could explain.
        """
        if self._memory_seen is None:
            self._memory_seen = PIVOTAL_MEMORY_ID in prompt_text or (
                "restarting checkout-api for database connection pool exhaustion resolved nothing"
                in prompt_text.lower()
            )
            self._plan_choice = "informed" if self._memory_seen else "naive"
        return self._memory_seen

    @staticmethod
    def _task_of(request: LLMRequest) -> str:
        for message in reversed(request.messages):
            if message.role in {"user", "system"}:
                match = _TASK_RE.search(message.content or "")
                if match:
                    return match.group(1)
        return "UNKNOWN"

    @staticmethod
    def _usage() -> TokenUsage:
        # An estimate, flagged as such, so the trace never presents a guess as a measurement.
        return TokenUsage(prompt_tokens=900, completion_tokens=180, total_tokens=1080, estimated=True)

    def _json(self, payload: Mapping[str, Any]) -> LLMResponse:
        return LLMResponse(
            content=json.dumps(payload),
            finish_reason=FinishReason.STOP,
            model="fake",
            usage=self._usage(),
        )


def build(settings: dict[str, Any], *, root: Path, impl: str | None = None) -> Any:
    """Factory. Reads a script file when one is configured and present, else uses the embedded
    devops script so that a fresh checkout runs without any fixture preparation."""
    script_path = settings.get("script")
    scenario = str(settings.get("scenario", "devops_pool_exhaustion"))
    if script_path:
        candidate = root / str(script_path)
        if candidate.exists():
            return FakeLLM.from_yaml(candidate, scenario=scenario)
    return FakeLLM(scenario=scenario, strict=bool(settings.get("strict", False)))
