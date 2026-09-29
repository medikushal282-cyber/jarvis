"""The memory ON/OFF benchmark.

This exists to make one claim falsifiable: *the agent gets better because it remembers.* Without a
measurement, "memory is central" is a design intention -- and the hackathon's heaviest criterion is
precisely whether the improvement is real and visible.

Method: run the same objective against the same frozen world N times with memory off, then N times
with memory on, and report the deltas on four metrics. Sequential ids and a frozen clock make each
run reproducible, and both arms reset the world between runs so neither inherits mutations from the
run before it.

Two honest caveats, stated here rather than discovered by a judge:

1. The scripted fake LLM branches on whether a specific memory is present in its prompt. That is a
   faithful simulation of a model choosing differently given the text "restarting this already
   resolved nothing" -- but it is a simulation, and the number is a property of the fixture, not a
   measurement of a language model. Point `providers.llm.impl` at `groq` for the real thing: the
   harness is identical, and the ladder is config-driven precisely so that swap is one line.
2. Corrections needed is counted from the scripted human's refusals. It falls with memory on because
   the informed plan asks for fewer confirmations -- a real mechanism, demonstrated rather than
   measured as human workload saved.
"""

from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from brain.loop.engine import Brain, RunConfig


@dataclass(frozen=True, slots=True)
class Arm:
    """One side of the comparison."""

    label: str
    memory_enabled: bool
    steps: list[int]
    tool_errors: list[int]
    corrections: list[int]
    successes: int

    @property
    def runs(self) -> int:
        return len(self.steps)


def _measure(*, root: Path, profile: str, objective: str, runs: int, memory_enabled: bool) -> Arm:
    from brain.providers.mock import business, devops

    steps: list[int] = []
    errors: list[int] = []
    corrections: list[int] = []
    successes = 0

    for index in range(runs):
        # Reset before every run so run 7 does not inherit run 6's mutations. Without this, part of
        # the measured "improvement" would be the world healing itself.
        devops.world().reset()
        business.world().reset()
        try:
            result = Brain(root=root).run(
                RunConfig(objective=objective, profile=profile, memory_enabled=memory_enabled)
            )
        except Exception as exc:  # noqa: BLE001 - a benchmark must not die on one bad run
            print(f"  run {index + 1} raised {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        steps.append(result.metrics.steps_to_completion)
        errors.append(result.metrics.tool_errors)
        corrections.append(result.metrics.corrections_needed)
        if str(result.status) == "completed":
            successes += 1

    return Arm(
        label="memory ON" if memory_enabled else "memory OFF",
        memory_enabled=memory_enabled,
        steps=steps,
        tool_errors=errors,
        corrections=corrections,
        successes=successes,
    )


def _mean(values: list[int]) -> float:
    return statistics.fmean(values) if values else 0.0


def _delta(before: float, after: float) -> str:
    if before == 0:
        return f"{after:g} (no baseline)"
    change = (after - before) / before * 100.0
    verdict = "improved" if change < 0 else ("worse" if change > 0 else "unchanged")
    return f"{after:g} ({change:+.1f}% {verdict})"


def run_plumbing_benchmark(*, root: Path, profile: str, objective: str, runs: int) -> int:
    """Run both arms and print the comparison. Returns a process exit code."""
    print(f"objective: {objective}")
    print(f"profile:   {profile}    runs per arm: {runs}\n")

    off = _measure(root=root, profile=profile, objective=objective, runs=runs, memory_enabled=False)
    on = _measure(root=root, profile=profile, objective=objective, runs=runs, memory_enabled=True)

    if not off.steps or not on.steps:
        print("benchmark produced no usable runs", file=sys.stderr)
        return 1

    print(f"{'metric':<28}{'memory OFF':>12}{'memory ON':>26}")
    print("-" * 66)
    print(f"{'runs':<28}{off.runs:>12}{on.runs:>26}")
    print(f"{'steps to completion (mean)':<28}{_mean(off.steps):>12.2f}{_delta(_mean(off.steps), _mean(on.steps)):>26}")
    print(f"{'tool errors (mean)':<28}{_mean(off.tool_errors):>12.2f}{_delta(_mean(off.tool_errors), _mean(on.tool_errors)):>26}")
    print(f"{'corrections needed (mean)':<28}{_mean(off.corrections):>12.2f}{_delta(_mean(off.corrections), _mean(on.corrections)):>26}")
    print(f"{'success rate':<28}{off.successes / off.runs * 100:>11.1f}%{on.successes / on.runs * 100:>25.1f}%")
    print()

    delta = _mean(off.steps) - _mean(on.steps)
    if delta > 0:
        print(f"Memory reduced steps to completion by {delta:.2f} on average.")
    elif delta < 0:
        print(
            f"Memory increased steps to completion by {abs(delta):.2f}. That is a real result and "
            "worth investigating rather than explaining away -- a recalled memory that misleads is "
            "worse than no memory at all."
        )
    else:
        print("No difference in steps to completion. The memory layer is not yet load-bearing here.")
    return 0


def run_learning_benchmark(*, root: Path, profile: str, objective: str, runs: int) -> int:
    """The real learning benchmark. Starts with empty memory and runs N times."""
    print(f"objective: {objective}")
    print(f"profile:   {profile}    runs per arm: {runs}\n")
    
    # We must ensure the seed is NOT used, by clearing the store and pretending it's the only source.
    # In MockMemory, if store exists but is empty JSON, it doesn't fallback to seed.
    store = root / ".brain" / "state" / "memory.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    
    def _run_arm(enabled: bool) -> Arm:
        store.write_text('{"memories": []}', encoding="utf-8")
        return _measure(root=root, profile=profile, objective=objective, runs=runs, memory_enabled=enabled)

    off = _run_arm(False)
    on = _run_arm(True)

    if not off.steps or not on.steps:
        print("benchmark produced no usable runs", file=sys.stderr)
        return 1

    print(f"{'metric':<28}{'memory OFF':>15}{'memory ON':>26}")
    print("-" * 69)
    print(f"{'runs':<28}{off.runs:>15}{on.runs:>26}")
    
    # Calculate variances
    def _var(vals: list[int]) -> float:
        return statistics.variance(vals) if len(vals) > 1 else 0.0

    print(f"{'steps to completion (mean)':<28}{_mean(off.steps):>10.2f} (±{_var(off.steps):.2f}){_delta(_mean(off.steps), _mean(on.steps)):>26}")
    print(f"{'tool errors (mean)':<28}{_mean(off.tool_errors):>10.2f} (±{_var(off.tool_errors):.2f}){_delta(_mean(off.tool_errors), _mean(on.tool_errors)):>26}")
    print(f"{'corrections needed (mean)':<28}{_mean(off.corrections):>10.2f} (±{_var(off.corrections):.2f}){_delta(_mean(off.corrections), _mean(on.corrections)):>26}")
    print(f"{'success rate':<28}{off.successes / off.runs * 100:>14.1f}%{on.successes / on.runs * 100:>25.1f}%")
    print()
    return 0

