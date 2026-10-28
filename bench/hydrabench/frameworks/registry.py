"""Resolve a framework spec to an adapter: a built-in name, or ``module:Class`` for your own."""

from __future__ import annotations

import importlib

from .base import FrameworkAdapter

BUILTIN: dict[str, str] = {
    "openhydra": "bench.hydrabench.frameworks.openhydra_adapter:OpenHydraAdapter",
    "langgraph": "bench.hydrabench.frameworks.langgraph_adapter:LangGraphAdapter",
    "crewai": "bench.hydrabench.frameworks.crewai_adapter:CrewAIAdapter",
    "bare": "bench.hydrabench.frameworks.bare_agent_adapter:BareAgentAdapter",
}


def resolve_adapter(spec: str) -> FrameworkAdapter:
    """Return an adapter instance for ``spec``.

    ``spec`` is a built-in name (``openhydra``, ``langgraph``, ``crewai``, ``bare``) or
    ``module:Class``, where ``module`` is importable on ``PYTHONPATH`` and ``Class`` subclasses
    :class:`FrameworkAdapter` with a no-argument constructor.
    """
    target = BUILTIN.get(spec, spec)
    if ":" not in target:
        raise ValueError(
            f"unknown framework {spec!r}: use one of {sorted(BUILTIN)} or module:Class"
        )
    module_name, _, class_name = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ValueError(f"cannot import {module_name!r} for framework {spec!r}: {e}") from e
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ValueError(f"{module_name!r} has no class {class_name!r}")
    if not (isinstance(cls, type) and issubclass(cls, FrameworkAdapter)):
        raise TypeError(f"{target} is not a FrameworkAdapter subclass")
    return cls()
