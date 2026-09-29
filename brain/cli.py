"""Command-line entry point.

    python -m brain.cli run --profile devops --objective "checkout-api is throwing 5xx"
    python -m brain.cli run --profile devops --objective "..." --no-memory
    python -m brain.cli run --profile devops --objective "..." --trace
    python -m brain.cli tools
    python -m brain.cli config show --profile devops
    python -m brain.cli config reload
    python -m brain.cli benchmark --runs 20

Kept deliberately thin. Everything it does is reachable from the library too, because a CLI that
can do something the library cannot is a CLI that grows a second implementation of it.

Exit codes:
  0: Run completed successfully
  1: Unexpected error or interrupt
  2: Run ended in a partial, escalated, or failed state, or configuration error
  3: BrainError (application logic error)
"""

from __future__ import annotations

import argparse
import json
import sys
import os
import dotenv
dotenv.load_dotenv(override=True)
from collections.abc import Sequence
from pathlib import Path

from brain.errors import BrainError, ConfigError


def _cmd_run(args: argparse.Namespace) -> int:
    from brain.events.sinks import MemorySink, MultiSink, StdoutSink, JsonlSink
    from brain.loop.engine import Brain, RunConfig

    root = Path(args.root)
    sink = MemorySink()
    if args.trace:
        live = MultiSink(StdoutSink(compact=not args.verbose), JsonlSink(root / ".brain/state/events.jsonl"), sink)
    else:
        live = sink
    brain = Brain(root=root, sink=live)

    result = brain.run(
        RunConfig(
            objective=args.objective,
            profile=args.profile,
            memory_enabled=False if args.no_memory else None,
        )
    )

    print()
    print(f"status: {result.status}")
    print(
        f"steps:  {result.metrics.steps_to_completion}   "
        f"tool_errors: {result.metrics.tool_errors}   "
        f"plans_revised: {result.metrics.plans_revised}"
    )
    print(
        f"memory: {result.metrics.memory_items_used} used, "
        f"{result.metrics.memory_items_written} written"
    )
    print()
    print(result.answer)
    if result.blocker:
        print()
        print(f"blocked: {result.blocker}")
    if result.next_action:
        print(f"next:    {result.next_action}")

    if args.trace:
        trace_path = Path(args.trace_out)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("w", encoding="utf-8") as fh:
            for event in sink.events:
                fh.write(event.to_json() + "\n")
        print(f"\ntrace: {trace_path} ({len(sink.events)} events)")

    if str(result.status) == "completed":
        return 0
    return 2


def _cmd_tools(args: argparse.Namespace) -> int:
    from brain.tools.registry import ToolRegistry

    root = Path(args.root)
    registry = ToolRegistry.from_yaml_dir(root / "config/tools", root=root)
    print(f"{len(registry)} tools\n")
    for spec in registry.all():
        print(f"  {spec.name:<28} {spec.permission:<8} {spec.side_effects:<12} {spec.provider}")
    return 0


def _cmd_config_show(args: argparse.Namespace) -> int:
    from brain.config.loader import ConfigLoader

    config = ConfigLoader(Path(args.root)).load(args.profile)
    print(
        json.dumps(
            {
                "profile": config.profile,
                "role": config.role,
                "autonomy": str(config.autonomy),
                "fingerprint": config.fingerprint,
                "budgets": config.budgets.as_event_data(),
                "memory": {
                    "enabled": config.memory.enabled,
                    "recall_limit": config.memory.recall_limit,
                    "retain_kinds": [str(k) for k in config.memory.retain_kinds],
                    "always_recall_kinds": [str(k) for k in config.memory.always_recall_kinds],
                },
                "workflow": config.workflow,
                "tools": list(config.tool_names()),
                "providers": {k: v["impl"] for k, v in sorted(config.providers.items())},
                "sources": config.sources,
                "soul_bytes": len(config.soul_markdown),
                "agents_bytes": len(config.agents_markdown),
            },
            indent=2,
        )
    )
    return 0


def _cmd_config_reload(args: argparse.Namespace) -> int:
    from brain.config.loader import ConfigLoader

    loader = ConfigLoader(Path(args.root))
    loader.load(args.profile)
    before = loader.current()
    try:
        after = loader.reload()
    except ConfigError as exc:
        # The contract is that a bad edit is rejected and the previous configuration stays in
        # force, so this is a clean failure rather than a half-applied state.
        print(f"reload rejected: {exc}", file=sys.stderr)
        if before is not None:
            print(f"still using fingerprint {before.fingerprint}", file=sys.stderr)
        return 2
    print(f"reloaded: fingerprint {after.fingerprint}")
    return 0


def _cmd_benchmark(args: argparse.Namespace) -> int:
    from brain.bench import run_plumbing_benchmark, run_learning_benchmark

    if getattr(args, "learning", False):
        return run_learning_benchmark(
            root=Path(args.root),
            profile=args.profile,
            objective=args.objective,
            runs=args.runs,
        )
    return run_plumbing_benchmark(
        root=Path(args.root),
        profile=args.profile,
        objective=args.objective,
        runs=args.runs,
    )


def _cmd_conformance(args: argparse.Namespace) -> int:
    from brain.tools.conformance import run_conformance

    return run_conformance(args)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brain", description="JARVIS agent brain")
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one objective")
    run.add_argument("--objective", required=True)
    run.add_argument("--profile", default="devops")
    run.add_argument("--no-memory", action="store_true", help="disable memory for this run")
    run.add_argument("--trace", action="store_true", help="print events as they are emitted")
    run.add_argument("--trace-out", default=".brain/state/trace.jsonl")
    run.add_argument("--verbose", action="store_true", help="full event payloads, not one line")
    run.set_defaults(func=_cmd_run)

    tools = sub.add_parser("tools", help="list the loaded tool registry")
    tools.set_defaults(func=_cmd_tools)

    config = sub.add_parser("config", help="inspect or reload configuration")
    config_sub = config.add_subparsers(dest="action", required=True)
    show = config_sub.add_parser("show")
    show.add_argument("--profile", default="devops")
    show.set_defaults(func=_cmd_config_show)
    reload_p = config_sub.add_parser("reload")
    reload_p.add_argument("--profile", default="devops")
    reload_p.set_defaults(func=_cmd_config_reload)

    bench = sub.add_parser("benchmark", help="compare memory OFF vs ON over N runs")
    bench.add_argument("--runs", type=int, default=20)
    bench.add_argument("--profile", default="devops")
    bench.add_argument(
        "--objective",
        default=(
            "checkout-api is returning 5xx errors since this morning. "
            "Find out why and fix it if you can."
        ),
    )
    bench.add_argument("--learning", action="store_true", help="run the true learning benchmark (starts empty)")
    bench.set_defaults(func=_cmd_benchmark)

    conf = sub.add_parser("conformance", help="run the provider conformance suite")
    conf.add_argument("--provider", required=True, help="capability name (e.g., observability)")
    conf.add_argument("--impl", required=True, help="implementation name (e.g., real)")
    conf.set_defaults(func=_cmd_conformance)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except BrainError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
