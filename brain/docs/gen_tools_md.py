"""Regenerate `config/tools.md` from the live registry, so the documentation cannot drift.

This is the whole point of the generator: a hand-maintained tool document is wrong the first time
someone adds a tool and forgets, and a wrong tool document is worse than none because it is
believed. Output is deterministic (stable ordering everywhere) so a test can assert the committed
file is current.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from brain.contracts import ToolSpec
from brain.tools.registry import ToolRegistry

HEADER = """<!-- GENERATED FILE - DO NOT EDIT BY HAND.
     Regenerate with:  python -m brain.docs.gen_tools_md
     Source of truth:  config/tools/*.yaml
     A test asserts this file matches the registry, so editing it by hand will fail the build. -->

# Tool registry

Every tool the brain can call, generated from `config/tools/*.yaml`. A profile exposes a subset of
these by name; availability is a profile decision and permission is a tool decision, and both must
pass before a call leaves the loop.

## Summary

| Tool | Provider | Permission | Side effects | Idempotent | Timeout | Retries |
|---|---|---|---|---|---|---|
"""


def render_tools_md(registry: ToolRegistry, *, profile: str | None = None) -> str:
    """Render the full catalogue as Markdown."""
    specs = list(registry.all())
    lines: list[str] = [HEADER]

    for spec in specs:
        lines.append(
            f"| `{spec.name}` | {spec.provider} | **{spec.permission}** | {spec.side_effects} "
            f"| {'yes' if spec.idempotent else 'no'} | {spec.timeout_s:g}s "
            f"| {spec.retry.max_attempts} |"
        )

    lines.append("")
    lines.append("## Permission tiers")
    lines.append("")
    lines.append("- **auto** -- runs unattended. Reads and memory operations only.")
    lines.append("- **confirm** -- needs per-call human approval, with a quantified blast radius.")
    lines.append(
        "- **deny** -- never runs, at any autonomy level. A restriction to report, not to route around."
    )
    lines.append("")

    by_provider: dict[str, list[ToolSpec]] = {}
    for spec in specs:
        by_provider.setdefault(spec.provider, []).append(spec)

    for provider in sorted(by_provider):
        lines.append(f"## Provider: `{provider}`")
        lines.append("")
        for spec in sorted(by_provider[provider], key=lambda s: s.name):
            lines.append(f"### `{spec.name}`")
            lines.append("")
            lines.append(spec.description.strip())
            lines.append("")

            params = spec.parameters or {}
            props = params.get("properties") or {}
            required = set(params.get("required") or [])
            if props:
                lines.append("| Argument | Type | Required | Constraints |")
                lines.append("|---|---|---|---|")
                for name in sorted(props):
                    sub = props[name] or {}
                    kind = sub.get("type", "any")
                    if isinstance(kind, list):
                        kind = " or ".join(str(k) for k in kind)
                    constraints: list[str] = []
                    if sub.get("enum"):
                        constraints.append("one of " + ", ".join(f"`{v}`" for v in sub["enum"]))
                    if sub.get("minimum") is not None:
                        constraints.append(f"min {sub['minimum']}")
                    if sub.get("maximum") is not None:
                        constraints.append(f"max {sub['maximum']}")
                    if sub.get("default") is not None:
                        constraints.append(f"default `{sub['default']}`")
                    lines.append(
                        f"| `{name}` | {kind} | {'yes' if name in required else 'no'} "
                        f"| {'; '.join(constraints) or '-'} |"
                    )
                lines.append("")

            if spec.returns:
                lines.append(f"Returns: {spec.returns.strip()}")
                lines.append("")
            if spec.redact:
                lines.append(f"Redacts: {', '.join(f'`{p}`' for p in spec.redact)}")
                lines.append("")
            retry_on = ", ".join(str(c) for c in spec.retry.retry_on) or "nothing"
            lines.append(
                f"Retry: {spec.retry.max_attempts} attempt(s), {spec.retry.backoff} backoff, "
                f"base {spec.retry.base_delay_s:g}s, jitter "
                f"{'on' if spec.retry.jitter else 'off'}, on {retry_on}."
            )
            lines.append("")

    return "\n".join(lines) + "\n"


def write_tools_md(registry: ToolRegistry, out: Path, *, profile: str | None = None) -> None:
    Path(out).write_text(render_tools_md(registry, profile=profile), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    root = Path(args[0]) if args else Path.cwd()
    registry = ToolRegistry.from_yaml_dir(root / "config/tools", root=root)
    out = root / "config/tools.md"
    write_tools_md(registry, out)
    print(f"wrote {out} ({len(registry)} tools)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
