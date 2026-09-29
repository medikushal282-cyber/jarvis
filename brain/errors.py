"""Error taxonomy for the agent brain.

One vocabulary, shared by the LLM parser, the tool executor, the retry policy, the recovery
ladder and the event stream. A consumer can switch on ``error_class`` without knowing which
layer produced the failure, which is what keeps the recovery ladder simple and the trace
readable.

The taxonomy is part of the frozen contract (see ``docs/brain/CONTRACTS.md`` section 5).
Adding a member is a minor version bump; renaming or removing one is a major bump.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorClass(StrEnum):
    """Classification of a failure, used to choose a recovery strategy.

    The split that matters is transient vs. model-output vs. capability:

    * transient (``TIMEOUT``, ``RATE_LIMITED``, ``PROVIDER_5XX``) -- retrying the identical
      call is reasonable.
    * model-output (``MALFORMED_ARGS``, ``VALIDATION``, ``UNKNOWN_TOOL``) -- the call itself
      was wrong. Retrying it unchanged is a defect; the arguments must be repaired first.
    * capability (``NOT_FOUND``, ``PERMISSION``, ``PROVIDER_ERROR``) -- the call cannot
      succeed as posed. Substitute, replan, or escalate.
    """

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_5XX = "provider_5xx"
    MALFORMED_ARGS = "malformed_args"
    VALIDATION = "validation"
    UNKNOWN_TOOL = "unknown_tool"
    NOT_FOUND = "not_found"
    PERMISSION = "permission"
    PROVIDER_ERROR = "provider_error"


#: Classes for which an identical retry can plausibly succeed. Everything else needs the call
#: or the plan to change. Kept as a set rather than a method on the enum so that the policy is
#: visible in one place when it is reviewed.
RETRYABLE: frozenset[ErrorClass] = frozenset(
    {ErrorClass.TIMEOUT, ErrorClass.RATE_LIMITED, ErrorClass.PROVIDER_5XX}
)

#: Failures caused by the model's own output. The hackathon brief calls these out
#: specifically: they must always be repaired and retried at least once before the step is
#: allowed to fail.
MODEL_OUTPUT: frozenset[ErrorClass] = frozenset(
    {ErrorClass.MALFORMED_ARGS, ErrorClass.VALIDATION, ErrorClass.UNKNOWN_TOOL}
)


def is_retryable(error_class: ErrorClass) -> bool:
    """Whether a bare retry of the identical call is permitted."""
    return error_class in RETRYABLE


def is_model_output_error(error_class: ErrorClass) -> bool:
    """Whether the failure was produced by the model rather than by the world.

    These are the ones the repair ladder must attempt to fix before giving up on the step.
    """
    return error_class in MODEL_OUTPUT


class BrainError(Exception):
    """Base class for every error the brain raises deliberately.

    Carries an :class:`ErrorClass` so that callers never have to pattern-match on message
    text, and an optional ``details`` mapping that is emitted into the trace. Message text is
    for humans; ``error_class`` is for control flow.
    """

    error_class: ErrorClass = ErrorClass.PROVIDER_ERROR

    def __init__(
        self,
        message: str,
        *,
        error_class: ErrorClass | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if error_class is not None:
            self.error_class = error_class
        self.details: dict[str, Any] = details or {}

    @property
    def is_fatal(self) -> bool:
        """Whether this error should end the run rather than being recovered from.

        Default False: almost every failure is recoverable by some rung of the ladder. The
        subclasses that override this are configuration and contract violations, which mean
        the run's premise is broken rather than its current step.
        """
        return False

    def to_event_data(self) -> dict[str, Any]:
        """Render for an ``error.raised`` event payload."""
        return {
            "where": type(self).__name__,
            "message": self.message,
            "fatal": self.is_fatal,
            "error_class": str(self.error_class),
        }


class ConfigError(BrainError):
    """A configuration layer failed validation or could not be resolved.

    Fatal, and deliberately so: the contract says a bad layer is rejected and the previously
    good config stays in force. Continuing with a half-applied config would make the agent's
    behaviour unattributable to any file on disk.
    """

    error_class = ErrorClass.VALIDATION

    @property
    def is_fatal(self) -> bool:
        return True


class ToolError(BrainError):
    """A tool call failed.

    Expected failures should be returned as ``ToolResult(ok=False)`` instead; this is for
    failures the executor itself detects (timeout, unknown tool, schema violation, blocked by
    policy).
    """

    error_class = ErrorClass.PROVIDER_ERROR


class PolicyError(BrainError):
    """A call was refused by the permission model.

    Not a bug and not a crash: the loop catches this and routes to recovery or escalation.
    """

    error_class = ErrorClass.PERMISSION
    is_fatal = False


class LLMError(BrainError):
    """The model call failed or returned something unusable."""

    error_class = ErrorClass.PROVIDER_ERROR


class BudgetExhausted(BrainError):
    """A run budget (steps, tokens, wall clock) was exhausted.

    Signals a graceful partial finish rather than a crash: the loop catches this, stops
    starting new steps, and finishes with what it verified.
    """

    error_class = ErrorClass.PROVIDER_ERROR

    def __init__(self, kind: str, limit: float, used: float) -> None:
        super().__init__(f"{kind} budget exhausted: {used} of {limit}")
        self.kind = kind
        self.limit = limit
        self.used = used

    def to_event_data(self) -> dict[str, Any]:
        return {
            "where": "budget",
            "message": self.message,
            "fatal": False,
            "error_class": None,
        }


class ContractError(BrainError):
    """An implementation violated a frozen interface.

    Fatal: it means a mock and a real adapter disagree about the contract, which is exactly
    the class of bug the contract exists to catch early. Surfacing it loudly during
    development is cheaper than a subtly wrong trace during a demo.
    """

    error_class = ErrorClass.VALIDATION

    @property
    def is_fatal(self) -> bool:
        return True
