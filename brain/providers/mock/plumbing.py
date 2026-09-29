"""Loop plumbing mocks: clock, ids, human, artifacts.

These are not domain mocks -- they are the seams that make a run *reproducible*. A frozen clock
and sequential ids are what allow two runs of the same scenario to produce byte-comparable
traces, which is the precondition for the memory ON/OFF benchmark to mean anything.

``ScriptedHuman`` is the interesting one. An approval-gated agent is untestable if a person has
to be present, and untestable-approval is the usual reason safety features get quietly disabled
before a demo. Scripting the answers keeps the confirm tier live in every test and lets the
rejection path -- human says no, agent must not retry -- be exercised on demand.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from brain.contracts import (
    ApprovalDecision,
    ApprovalRequest,
    ClarificationAnswer,
    ClarificationRequest,
)


# ---------------------------------------------------------------------------- clocks


class SystemClock:
    """Real time. Timezone-aware UTC, so no consumer has to guess a naive datetime's zone."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        import time

        return time.monotonic()


class FrozenClock:
    """A clock that advances only when told to.

    Deliberately not auto-advancing: a run that advanced its own clock on every read would
    produce different durations depending on how many times the loop happened to call it, which
    would make traces and budget tests non-deterministic. Tests that need wall-clock time to
    pass call :meth:`advance` explicitly.
    """

    def __init__(self, at: datetime, *, auto_advance_s: float = 0.0) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._now = at
        self._auto = auto_advance_s
        self._mono = 0.0

    def now(self) -> datetime:
        current = self._now
        if self._auto:
            self._now = self._now + timedelta(seconds=self._auto)
            self._mono += self._auto
        return current

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)
        self._mono += seconds


def _parse_iso(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------- ids


class UuidIds:
    """Opaque, unpredictable ids for real runs."""

    def new(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"


class SequentialIds:
    """Deterministic ids, so two runs of the same scenario produce identical traces.

    Counts per prefix rather than globally: otherwise adding an unrelated event type would
    renumber every id and invalidate every stored trace.
    """

    def __init__(self) -> None:
        self._counters: dict[str, itertools.count[int]] = {}

    def new(self, prefix: str) -> str:
        counter = self._counters.setdefault(prefix, itertools.count(1))
        return f"{prefix}-{next(counter):04d}"

    def reset(self) -> None:
        self._counters.clear()


# ---------------------------------------------------------------------------- human


class ScriptedHuman:
    """Answers approvals and clarifications from a script.

    Rules are matched in order against the tool name; the first match wins. Anything unmatched
    falls back to ``default_answer``. A rule may set ``approve: false`` to exercise the refusal
    path, and ``answer`` to supply text for a clarification.
    """

    def __init__(
        self,
        rules: Sequence[Mapping[str, Any]] | None = None,
        *,
        default_answer: bool = True,
        latency_ms: float = 0.0,
    ) -> None:
        self._rules = list(rules or [])
        self._default = default_answer
        self._latency_ms = latency_ms
        #: Full record of what was asked and answered, for assertions and for the report.
        self.requests: list[dict[str, Any]] = []
        self.answers: list[str] = []

    def confirm(self, request: ApprovalRequest) -> ApprovalDecision:
        rule = self._match(request.tool)
        approved = bool(rule.get("approve", self._default)) if rule else self._default
        self.requests.append(
            {"request_id": request.request_id, "tool": request.tool, "approved": approved}
        )
        return ApprovalDecision(
            approved=approved,
            answered_by=str((rule or {}).get("by", "scripted-human")),
            answer=(rule or {}).get("answer"),
            latency_ms=self._latency_ms,
        )

    def ask(self, question: ClarificationRequest) -> ClarificationAnswer:
        rule = self._match("*")
        answer = (rule or {}).get("answer")
        if answer is None and question.options:
            answer = question.options[0]
        if answer is None:
            answer = "No further guidance available."
        self.answers.append(str(answer))
        return ClarificationAnswer(answer=str(answer), answered_by="scripted-human")

    def _match(self, name: str) -> Mapping[str, Any] | None:
        for rule in self._rules:
            if rule.get("tool") in (name, "*"):
                return rule
        return None


# ---------------------------------------------------------------------------- artifacts


class FilesystemArtifacts:
    """Writes artifacts under a root directory and returns a relative reference.

    References are relative rather than absolute so a trace recorded on one machine stays
    readable on another -- an absolute path in a stored event is a broken link waiting to happen.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def write(self, name: str, data: bytes) -> str:
        safe = name.replace("..", "_").lstrip("/\\")
        target = self.root / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target.relative_to(self.root)).replace("\\", "/")

    def read(self, ref: str) -> bytes:
        return (self.root / ref).read_bytes()


class NullArtifacts:
    """Discards artifacts. Selected when a deployment has nowhere to put them."""

    def write(self, name: str, data: bytes) -> str:
        return f"discarded:{name}"

    def read(self, ref: str) -> bytes:
        raise FileNotFoundError(f"artifact store is disabled; cannot read {ref!r}")


# ---------------------------------------------------------------------------- factory


def build(settings: dict[str, Any], *, root: Path, impl: str | None = None) -> Any:
    """Factory for clock, ids, human and artifacts.

    One module serves four capabilities, so ``settings["capability"]`` decides which object to
    return -- and for clock and ids, ``impl`` selects between two implementations.
    """
    capability = str(settings.get("capability", ""))
    chosen = impl or str(settings.get("impl", ""))

    if capability == "clock":
        if chosen == "frozen":
            at = _parse_iso(str(settings.get("frozen_at", "2026-03-14T09:12:00Z")))
            return FrozenClock(at, auto_advance_s=float(settings.get("auto_advance_s", 0.0)))
        return SystemClock()

    if capability == "ids":
        return SequentialIds() if chosen == "sequential" else UuidIds()

    if capability == "human":
        # `response_script` is what config/providers.yaml points at; `rules` is the inline form,
        # kept for tests that want to script an answer without touching disk.
        rules = settings.get("rules")
        script = settings.get("response_script")
        if rules is None and script:
            path = root / str(script)
            if path.exists():
                import yaml

                loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                rules = loaded.get("rules")
        return ScriptedHuman(
            rules,
            default_answer=bool(settings.get("default_answer", True)),
        )

    if capability == "artifacts":
        if chosen == "none":
            return NullArtifacts()
        return FilesystemArtifacts(root / str(settings.get("root", ".brain/artifacts")))

    raise ValueError(f"brain.providers.mock.plumbing cannot serve capability {capability!r}")
