"""Configuration loading, layering and validation.

The layering rule is the feature: `config/` defaults are overridden per key by the selected
profile, then by a workspace override, then by a user override. Each layer is merged deeply,
so a workspace file that sets one nested budget does not erase its siblings -- which is the
bug that makes shallow overrides useless in practice.

Failure is always loud and never partial. A layer that does not validate raises
:class:`~brain.errors.ConfigError` naming the offending key path, and the previously loaded
good configuration stays in force. The alternative -- keeping the partially-applied result --
would leave the agent behaving according to no file on disk, which makes a trace
unattributable and a bug unreproducible.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from brain.contracts import (
    Autonomy,
    Budgets,
    MemoryKind,
    PermissionTier,
    RetryPolicy,
    SideEffects,
    ToolSpec,
)
from brain.errors import ConfigError, ErrorClass

#: Where an operator's overrides live, relative to the repo root. Kept out of `config/` so
#: that `config/` can stay purely version-controlled while these stay purely local.
WORKSPACE_DIR = Path(".brain/workspace")
USER_DIR = Path(".brain/user")

_ENV_PREFIX = "BRAIN_PROVIDER__"


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    """Memory policy for a run, resolved from the profile.

    ``always_recall_kinds`` exists because for some profiles a category of memory must be
    *visible* rather than merely available: an on-call agent should be shown the fixes that
    already failed here even if a relevance score would have ranked them lower.
    """

    enabled: bool = True
    recall_limit: int = 8
    retain_kinds: tuple[MemoryKind, ...] = (
        MemoryKind.OUTCOME,
        MemoryKind.FAILURE,
        MemoryKind.CORRECTION,
        MemoryKind.PREFERENCE,
        MemoryKind.ENTITY_FACT,
    )
    always_recall_kinds: tuple[MemoryKind, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """The effective configuration for a run, after merging every layer."""

    soul_markdown: str
    agents_markdown: str
    profile: str
    role: str
    autonomy: Autonomy
    budgets: Budgets
    memory: MemoryConfig
    policy: dict[str, Any]
    tools: tuple[ToolSpec, ...]
    providers: dict[str, dict[str, Any]]
    workflow: str
    profile_prompts: dict[str, str]
    soul_additions: str
    demo: dict[str, Any]
    fingerprint: str
    sources: dict[str, str] = field(default_factory=dict)

    def tool_names(self) -> tuple[str, ...]:
        return tuple(t.name for t in self.tools)


# ---------------------------------------------------------------------------- helpers


def load_yaml(path: Path) -> Any:
    """Read a YAML file, raising a `ConfigError` that names the file on any parse failure."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge ``overlay`` into ``base`` per key, recursively for nested mappings.

    Lists replace rather than concatenate. Concatenating would make a tool list or a retention
    list impossible to *narrow* in an override, and narrowing is the common case.
    """
    out = dict(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {path}") from exc


def canonical_fingerprint(payload: dict[str, Any]) -> str:
    """Stable hash of an effective configuration.

    Stamped into `run.started` so any trace can be tied to the exact soul, policies and tool
    set that produced it. Sorted keys and no whitespace, so the hash changes when a value
    changes and never because of formatting.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _require(mapping: Any, key: str, *, where: str, kind: type | tuple[type, ...]) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ConfigError(f"{where}: missing required key {key!r}")
    value = mapping[key]
    if not isinstance(value, kind):
        raise ConfigError(
            f"{where}.{key}: expected {getattr(kind, '__name__', kind)}, got {type(value).__name__}"
        )
    return value


# ---------------------------------------------------------------------------- loader


class ConfigLoader:
    """Loads, layers, validates and caches the effective configuration."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._current: ResolvedConfig | None = None
        self._last_args: dict[str, Any] = {}
        self._tool_schema = self._read_json_schema(
            self.root / "docs/brain/schemas/tool.schema.json"
        )

    # ------------------------------------------------------------------ public

    def load(
        self,
        profile: str = "devops",
        *,
        workspace: str | None = None,
        user: str | None = None,
    ) -> ResolvedConfig:
        """Resolve the configuration for ``profile``, applying any overlay layers."""
        self._last_args = {"profile": profile, "workspace": workspace, "user": user}

        soul = load_text(self.root / "config/soul.md")
        agents_md = load_text(self.root / "config/agents.md")

        profile_path = self.root / "config/profiles" / f"{profile}.yaml"
        if not profile_path.exists():
            available = ", ".join(
                sorted(p.stem for p in (self.root / "config/profiles").glob("*.yaml"))
            )
            raise ConfigError(f"unknown profile {profile!r}; available: {available}")
        raw = load_yaml(profile_path) or {}
        where = f"config/profiles/{profile}.yaml"

        # Overlay layers, in increasing precedence.
        for layer_dir, layer_name in ((WORKSPACE_DIR, workspace), (USER_DIR, user)):
            if not layer_name:
                continue
            layer_file = self.root / layer_dir / f"{layer_name}.yaml"
            if layer_file.exists():
                raw = deep_merge(raw, load_yaml(layer_file) or {})

        providers, sources = self._resolve_providers()
        tools = self._load_tools(self.root / "config/tools")

        include = (raw.get("agents", {}).get("tools", {}) or {}).get("include")
        if include is None:
            raise ConfigError(f"{where}: agents.tools.include is required")
        unknown = sorted(set(include) - {t.name for t in tools})
        if unknown:
            raise ConfigError(f"{where}: agents.tools.include names unknown tools: {unknown}")
        selected = tuple(t for t in tools if t.name in set(include))

        agents_block = raw.get("agents", {}) or {}
        budgets_raw = agents_block.get("budgets", {}) or {}
        budgets = Budgets(
            max_steps=int(budgets_raw.get("max_steps", 24)),
            max_tokens=int(budgets_raw.get("max_tokens", 120_000)),
            max_wall_clock_s=int(budgets_raw.get("max_wall_clock_s", 900)),
            max_tool_calls_per_step=int(budgets_raw.get("max_tool_calls_per_step", 3)),
            max_consecutive_failures=int(budgets_raw.get("max_consecutive_failures", 4)),
        )

        memory_raw = agents_block.get("memory", {}) or {}
        memory = MemoryConfig(
            enabled=bool(memory_raw.get("enabled", True)),
            recall_limit=int(memory_raw.get("recall_limit", 8)),
            retain_kinds=tuple(
                MemoryKind(k)
                for k in memory_raw.get("retain_kinds", [m.value for m in MemoryKind])
            ),
            always_recall_kinds=tuple(
                MemoryKind(k) for k in memory_raw.get("always_recall_kinds", [])
            ),
        )

        soul_block = raw.get("soul", {}) or {}
        resolved = ResolvedConfig(
            soul_markdown=soul,
            agents_markdown=agents_md,
            profile=profile,
            role=str(raw.get("role", profile)),
            autonomy=Autonomy(agents_block.get("autonomy", Autonomy.STANDARD)),
            budgets=budgets,
            memory=memory,
            policy=agents_block.get("policy", {}) or {},
            tools=selected,
            providers=providers,
            workflow=str(raw.get("workflow", "")),
            profile_prompts=agents_block.get("prompts", {}) or {},
            soul_additions=str(soul_block.get("additions", "")),
            demo=raw.get("demo", {}) or {},
            fingerprint="",
            sources={
                **sources,
                "soul": str(self.root / "config/soul.md"),
                "agents": str(self.root / "config/agents.md"),
                "profile": str(profile_path),
            },
        )
        resolved = self._with_fingerprint(resolved)
        self._current = resolved
        return resolved

    def reload(self) -> ResolvedConfig:
        """Re-resolve using the arguments from the last successful :meth:`load`.

        Raises before touching the cache if the new configuration is invalid, so the previous
        good configuration survives a bad edit. That is what makes hot-reload safe to expose
        over an API.
        """
        if not self._last_args:
            raise ConfigError("cannot reload: no configuration has been loaded yet")
        return self.load(**self._last_args)

    def current(self) -> ResolvedConfig | None:
        return self._current

    def list_profiles(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "config/profiles").glob("*.yaml"))

    def write_layer(self, layer: str, key: str, value: Any) -> Path:
        """Write one key into an override layer.

        Deliberately does not reload: a caller editing several keys should validate once, after
        the last write.
        """
        if layer not in {"workspace", "user"}:
            raise ConfigError(f"unknown config layer {layer!r}; expected 'workspace' or 'user'")
        base = self.root / (WORKSPACE_DIR if layer == "workspace" else USER_DIR)
        base.mkdir(parents=True, exist_ok=True)
        target = base / f"{self._last_args.get('profile', 'devops')}.yaml"
        existing = (load_yaml(target) if target.exists() else {}) or {}
        node = existing
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        target.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")
        return target

    # ------------------------------------------------------------------ internals

    def _with_fingerprint(self, resolved: ResolvedConfig) -> ResolvedConfig:
        payload = {
            "profile": resolved.profile,
            "role": resolved.role,
            "autonomy": str(resolved.autonomy),
            "budgets": resolved.budgets.as_event_data(),
            "memory": {
                "enabled": resolved.memory.enabled,
                "recall_limit": resolved.memory.recall_limit,
                "retain_kinds": [str(k) for k in resolved.memory.retain_kinds],
                "always_recall_kinds": [str(k) for k in resolved.memory.always_recall_kinds],
            },
            "policy": resolved.policy,
            "tools": sorted(t.name for t in resolved.tools),
            "soul_sha": hashlib.sha256(resolved.soul_markdown.encode()).hexdigest()[:12],
            "agents_sha": hashlib.sha256(resolved.agents_markdown.encode()).hexdigest()[:12],
        }
        return dataclasses.replace(resolved, fingerprint=canonical_fingerprint(payload))

    def _resolve_providers(self) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        raw = load_yaml(self.root / "config/providers.yaml") or {}
        block = raw.get("providers")
        if not isinstance(block, dict):
            raise ConfigError("config/providers.yaml: missing 'providers' mapping")

        out: dict[str, dict[str, Any]] = {}
        for capability, entry in block.items():
            if not isinstance(entry, dict):
                raise ConfigError(
                    f"config/providers.yaml: providers.{capability} must be a mapping"
                )
            impl = _require(entry, "impl", where=f"providers.{capability}", kind=str)
            # The one env override in the system, deliberately scoped to provider selection
            # only: it lets a demo flip one capability without editing a versioned file.
            override = os.environ.get(f"{_ENV_PREFIX}{capability.upper()}")
            out[capability] = {
                "impl": override or impl,
                "settings": entry.get("settings", {}) or {},
            }
        return out, {"providers": str(self.root / "config/providers.yaml")}

    def _load_tools(self, directory: Path) -> tuple[ToolSpec, ...]:
        """Build the tool catalogue, enforcing both the published JSON Schema and the
        cross-field invariants a schema cannot express."""
        if not directory.exists():
            raise ConfigError(f"tool directory not found: {directory}")

        specs: dict[str, ToolSpec] = {}
        for path in sorted(directory.glob("*.yaml")):
            raw = load_yaml(path) or {}
            entries = raw.get("tools")
            if not isinstance(entries, list) or not entries:
                raise ConfigError(f"{path.name}: 'tools' must be a non-empty list")
            for entry in entries:
                spec = self._build_spec(entry, path, raw.get("version"))
                if spec.name in specs:
                    raise ConfigError(
                        f"{path.name}: tool {spec.name!r} is already defined in "
                        f"{specs[spec.name].source}"
                    )
                specs[spec.name] = spec
        return tuple(specs[name] for name in sorted(specs))

    def _build_spec(self, entry: Any, path: Path, version: Any) -> ToolSpec:
        where = path.name
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: each tool must be a mapping")
        name = str(entry.get("name", "<unnamed>"))

        errors = self._schema_errors(entry) if self._tool_schema else []
        if errors:
            raise ConfigError(f"{where}: tool {name!r}: " + "; ".join(errors))

        side_effects = SideEffects(entry["side_effects"])
        permission = PermissionTier(entry["permission"])

        # The schema states this too, but it is re-checked here so that a caller without the
        # schema file present still gets the guard rather than silently losing it.
        if side_effects is SideEffects.DESTRUCTIVE and permission is PermissionTier.AUTO:
            raise ConfigError(
                f"{where}: tool {name!r} is destructive and must not be permission 'auto'; "
                "an irreversible action must reach a human"
            )

        retry_raw = entry.get("retry", {}) or {}
        retry = RetryPolicy(
            max_attempts=int(retry_raw.get("max_attempts", 1)),
            backoff=str(retry_raw.get("backoff", "exponential")),
            base_delay_s=float(retry_raw.get("base_delay_s", 0.5)),
            jitter=bool(retry_raw.get("jitter", True)),
            retry_on=tuple(ErrorClass(c) for c in retry_raw.get("retry_on", [])),
        )
        if permission is PermissionTier.DENY and retry.max_attempts != 1:
            raise ConfigError(f"{where}: tool {name!r} is 'deny' but declares retries")

        return ToolSpec(
            name=name,
            description=entry["description"],
            provider=entry["provider"],
            method=entry["method"],
            parameters=entry["parameters"],
            permission=permission,
            timeout_s=float(entry["timeout_s"]),
            idempotent=bool(entry["idempotent"]),
            side_effects=side_effects,
            retry=retry,
            returns=str(entry.get("returns", "")),
            redact=tuple(entry.get("redact", []) or ()),
            source=f"{path.name}#{version}",
        )

    def _schema_errors(self, entry: dict[str, Any]) -> list[str]:
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - only when deps are missing
            return []
        assert self._tool_schema is not None
        validator = jsonschema.Draft202012Validator(self._tool_schema["$defs"]["tool"])
        return [
            f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(entry), key=lambda e: list(e.absolute_path))
        ]

    @staticmethod
    def _read_json_schema(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
