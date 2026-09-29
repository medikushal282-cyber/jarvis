"""JARVIS Agent Brain -- the reasoning loop, and the interfaces it consumes.

The public surface is :class:`~brain.loop.engine.Brain` and
:class:`~brain.loop.engine.RunConfig`. Everything else is implementation, and every external
capability is a Protocol in :mod:`brain.contracts` resolved through ``config/providers.yaml``,
so swapping a mock for a teammate's real adapter is a one-line configuration change.

The lookup here is deferred so that ``import brain`` stays cheap and never requires an optional
provider module to be importable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["Brain", "RunConfig", "__version__"]

__version__ = "1.0.0"


def __getattr__(name: str) -> Any:
    if name in {"Brain", "RunConfig"}:
        from brain.loop import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:  # pragma: no cover - typing only
    from brain.loop.engine import Brain, RunConfig
