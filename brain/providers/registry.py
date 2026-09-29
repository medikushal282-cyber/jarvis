"""The provider registry: resolves a capability name to a live implementation.

This module is the reason the mock->real swap is one line of configuration. The reasoning loop
never imports a teammate's code; it asks for a capability and receives an object satisfying a
Protocol from :mod:`brain.contracts`. Because those are structural types, a bundled mock and a
real adapter are the same kind of thing, so swapping them cannot change the loop's behaviour by
accident.

Resolution order for a capability (first hit wins):

1. ``settings["factory"]`` as ``"module.path:function"`` -- an explicit escape hatch for an
   implementation that lives somewhere unusual.
2. ``brain.providers.<capability>.<impl>`` -- the documented convention, and what a teammate
   writing a real adapter should use.
3. The bundled mock module from ``_BUNDLED``, for our own offline implementations.

The bundled mocks deliberately share a world module per vertical rather than one module per
capability: they are fixtures for one scenario, and splitting them would spread a single
coherent synthetic estate across six files. The documented convention above is still tried
first, so a real ``brain/providers/observability/real.py`` overrides the bundle with no change
anywhere else.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain.errors import ConfigError

#: capability -> bundled mock module. Consulted only after the documented path misses.
_BUNDLED: dict[str, str] = {
    "clock": "brain.providers.mock.plumbing",
    "ids": "brain.providers.mock.plumbing",
    "human": "brain.providers.mock.plumbing",
    "artifacts": "brain.providers.mock.plumbing",
    "events": "brain.events.sinks",
    "memory": "brain.providers.mock.memory",
    "observability": "brain.providers.mock.devops",
    "incident": "brain.providers.mock.devops",
    "remediation": "brain.providers.mock.devops",
    "comms": "brain.providers.mock.devops",
    "crm": "brain.providers.mock.business",
    "support": "brain.providers.mock.business",
}


@dataclass(frozen=True, slots=True)
class ProviderChoice:
    """One capability's selection: which implementation, and with what settings."""

    capability: str
    impl: str
    settings: dict[str, Any]


class ProviderRegistry:
    """Builds and caches one instance per capability."""

    def __init__(
        self,
        choices: Mapping[str, ProviderChoice],
        *,
        root: Path,
        factories: Mapping[str, Callable[..., Any]] | None = None,
    ) -> None:
        self._choices = dict(choices)
        self._root = Path(root)
        self._factories = dict(factories or {})
        self._cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ construction

    @classmethod
    def from_config(
        cls,
        providers_cfg: Mapping[str, Any],
        *,
        root: Path,
        env: Mapping[str, str] | None = None,
        factories: Mapping[str, Callable[..., Any]] | None = None,
    ) -> ProviderRegistry:
        """Build from the ``providers:`` block of `config/providers.yaml`.

        ``env`` is injectable so a test can exercise the override path without mutating the
        process environment.
        """
        environ = env if env is not None else os.environ
        choices: dict[str, ProviderChoice] = {}
        for capability, entry in (providers_cfg or {}).items():
            if not isinstance(entry, Mapping):
                raise ConfigError(f"providers.{capability} must be a mapping")
            impl = str(entry.get("impl", "")).strip()
            if not impl:
                raise ConfigError(f"providers.{capability}: 'impl' is required")
            override = environ.get(f"BRAIN_PROVIDER__{capability.upper()}")
            choices[capability] = ProviderChoice(
                capability=capability,
                impl=override or impl,
                settings=dict(entry.get("settings", {}) or {}),
            )
        return cls(choices, root=root, factories=factories)

    def register(self, capability: str, factory: Callable[..., Any]) -> None:
        """Register a programmatic factory, overriding module resolution for that capability."""
        self._factories[capability] = factory
        self._cache.pop(capability, None)

    # ------------------------------------------------------------------ access

    def get(self, capability: str) -> Any:
        """Build (once) and return the implementation for ``capability``."""
        if capability in self._cache:
            return self._cache[capability]
        choice = self._choices.get(capability)
        if choice is None:
            known = ", ".join(sorted(self._choices)) or "(none)"
            raise ConfigError(f"no provider configured for {capability!r}; configured: {known}")
        built = self._build(choice)
        self._cache[capability] = built
        return built

    def choice(self, capability: str) -> ProviderChoice:
        choice = self._choices.get(capability)
        if choice is None:
            raise ConfigError(f"no provider configured for {capability!r}")
        return choice

    def capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self._choices))

    def describe(self) -> dict[str, str]:
        """capability -> impl, for `cli config show` and for the trace."""
        return {name: c.impl for name, c in sorted(self._choices.items())}

    # ------------------------------------------------------------------ typed accessors

    def llm(self) -> Any:
        return self.get("llm")

    def memory(self) -> Any:
        return self.get("memory")

    def human(self) -> Any:
        return self.get("human")

    def clock(self) -> Any:
        return self.get("clock")

    def ids(self) -> Any:
        return self.get("ids")

    def sink(self) -> Any:
        return self.get("events")

    def artifacts(self) -> Any:
        return self.get("artifacts")

    def tool_provider(self, capability: str) -> Any:
        """The adapter behind every tool whose ``provider:`` is ``capability``."""
        return self.get(capability)

    # ------------------------------------------------------------------ internals

    def _build(self, choice: ProviderChoice) -> Any:
        custom = self._factories.get(choice.capability)
        if custom is not None:
            return _call_factory(custom, choice, root=self._root)

        for module_path in self._candidate_modules(choice):
            module = _try_import(module_path)
            if module is None:
                continue
            factory = getattr(module, "build", None)
            if factory is None:
                continue
            return _call_factory(factory, choice, root=self._root)

        raise ConfigError(
            f"could not resolve provider {choice.capability!r} with impl {choice.impl!r}; "
            f"tried: {', '.join(self._candidate_modules(choice))}"
        )

    @staticmethod
    def _candidate_modules(choice: ProviderChoice) -> list[str]:
        candidates: list[str] = []
        settings_factory = choice.settings.get("factory")
        if isinstance(settings_factory, str) and ":" in settings_factory:
            candidates.append(settings_factory.split(":", 1)[0])
        candidates.append(f"brain.providers.{choice.capability}.{choice.impl}")
        if choice.capability == "llm":
            candidates.append(f"brain.providers.llm.{choice.impl}")
        bundled = _BUNDLED.get(choice.capability)
        if bundled:
            candidates.append(bundled)
        # De-duplicate while preserving order, so the error message names a real search path.
        seen: list[str] = []
        for candidate in candidates:
            if candidate not in seen:
                seen.append(candidate)
        return seen


def _call_factory(factory: Callable[..., Any], choice: ProviderChoice, *, root: Path) -> Any:
    """Call a factory, passing only the keyword arguments it actually accepts.

    Bundled factories take ``(settings, *, root)``; some take ``impl`` too, because one module
    serves several implementations of the same capability (clock, ids). Introspecting rather
    than mandating one signature keeps a teammate's adapter simple to write.
    """
    import inspect

    settings = dict(choice.settings)
    settings.setdefault("impl", choice.impl)
    settings.setdefault("capability", choice.capability)

    try:
        params = inspect.signature(factory).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins
        return factory(settings, root=root)

    kwargs: dict[str, Any] = {}
    if "root" in params:
        kwargs["root"] = root
    if "impl" in params:
        kwargs["impl"] = choice.impl
    if "capability" in params:
        kwargs["capability"] = choice.capability
    return factory(settings, **kwargs)


def _try_import(module_path: str) -> Any | None:
    try:
        return importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        # Only swallow the module being absent. A ModuleNotFoundError raised *inside* a module
        # that does exist means that module has a broken import, and hiding it would turn a
        # real bug into a confusing "could not resolve provider".
        if exc.name and module_path.startswith(exc.name):
            return None
        raise
    except ImportError:
        return None
