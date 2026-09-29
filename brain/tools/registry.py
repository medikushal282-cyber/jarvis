"""The tool registry: `config/tools/*.yaml` as an in-memory catalogue of `ToolSpec`s.

The registry is rebuilt from disk on reload, so adding a tool is adding a YAML file. It holds
no policy of its own -- permission *enforcement* lives in the loop's policy engine. What the
registry owns is the set of facts a tool declares: its schema, its tier, its retry policy, and
what it must redact.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from brain.config.loader import ConfigLoader
from brain.contracts import ToolSpec
from brain.errors import ConfigError

__all__ = ["ToolRegistry"]


class ToolRegistry:
    """A validated, immutable catalogue of the tools available to the brain."""

    def __init__(self, tools: Sequence[ToolSpec]) -> None:
        self._by_name: dict[str, ToolSpec] = {}
        for spec in tools:
            if spec.name in self._by_name:
                raise ConfigError(f"duplicate tool name {spec.name!r} in the registry")
            self._by_name[spec.name] = spec

    @classmethod
    def from_yaml_dir(cls, directory: Path, *, root: Path | None = None) -> ToolRegistry:
        """Load every ``*.yaml`` in ``directory``.

        Routed through `ConfigLoader` rather than parsing YAML here, so there is exactly one
        implementation of tool validation and therefore exactly one place where a rule about
        tools can be true.
        """
        directory = Path(directory)
        resolved_root = root if root is not None else directory.parent.parent
        return cls(ConfigLoader(resolved_root)._load_tools(directory))

    def get(self, name: str) -> ToolSpec | None:
        return self._by_name.get(name)

    def require(self, name: str) -> ToolSpec:
        spec = self._by_name.get(name)
        if spec is None:
            known = ", ".join(sorted(self._by_name)) or "(none)"
            raise ConfigError(f"unknown tool {name!r}; known tools: {known}")
        return spec

    def all(self) -> tuple[ToolSpec, ...]:
        return tuple(self._by_name[name] for name in sorted(self._by_name))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_name))

    def for_profile(self, include: Iterable[str]) -> tuple[ToolSpec, ...]:
        """The subset a profile exposes.

        An unknown name is an error rather than a silent skip: a typo in a profile should fail
        loudly instead of quietly shrinking the agent's capabilities.
        """
        wanted = set(include)
        unknown = sorted(wanted - set(self._by_name))
        if unknown:
            raise ConfigError(f"profile includes unknown tools: {unknown}")
        return tuple(self._by_name[name] for name in sorted(wanted))

    def api_schemas(self, names: Sequence[str] | None = None) -> list[dict]:
        """Tool definitions in the shape the provider's function-calling API expects."""
        chosen = [self.require(n) for n in names] if names is not None else list(self.all())
        return [spec.api_schema() for spec in chosen]

    def methods_by_provider(self) -> dict[str, tuple[str, ...]]:
        """provider -> the methods its tools declare. Used by the conformance suite to check a
        provider actually exposes everything the registry promises."""
        grouped: dict[str, set[str]] = {}
        for spec in self._by_name.values():
            grouped.setdefault(spec.provider, set()).add(spec.method)
        return {k: tuple(sorted(v)) for k, v in sorted(grouped.items())}

    def __len__(self) -> int:
        return len(self._by_name)

    def __contains__(self, name: object) -> bool:
        return name in self._by_name
