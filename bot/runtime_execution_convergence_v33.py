"""Bound-method safety hotfix for runtime execution convergence v32.

The v32 reconnect deduplication correctly unwraps decorated callbacks, but a
bound broker method may expose an unbound function through ``__wrapped__``.
Registering that function loses ``self`` and causes reconnect attempts such as
``CoinbaseBroker.connect() missing 1 required positional argument: 'self'``.

This prebootstrap hotfix replaces only v32's callable unwrapping helper. It
preserves the original bound instance while retaining cycle-safe unwrapping.
"""
from __future__ import annotations

import logging
import os
import sys
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_execution_convergence_v33")
MARKER = "20260727-runtime-execution-convergence-v33"
_TARGETS = (
    "nija_runtime_execution_convergence_v32_prebot",
    "bot.runtime_execution_convergence_v32",
)


def _bound_safe_unwrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Unwrap decorators without discarding a bound method's instance."""

    bound_self = getattr(fn, "__self__", None)
    current: Callable[..., Any] = fn
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        wrapped = getattr(current, "__wrapped__", None)
        if not callable(wrapped):
            break
        current = wrapped

    if bound_self is not None and getattr(current, "__self__", None) is None:
        descriptor = getattr(current, "__get__", None)
        if callable(descriptor):
            rebound = descriptor(bound_self, type(bound_self))
            if callable(rebound):
                current = rebound
    return current


def install() -> bool:
    patched = False
    for name in _TARGETS:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        setattr(module, "_unwrap_callable", _bound_safe_unwrap)
        setattr(module, "BOUND_METHOD_HOTFIX_MARKER", MARKER)
        patched = True

    if not patched:
        LOGGER.critical(
            "RUNTIME_EXECUTION_CONVERGENCE_V33_DEFERRED marker=%s reason=v32_not_loaded",
            MARKER,
        )
        return False

    os.environ["NIJA_RUNTIME_EXECUTION_CONVERGENCE_V33_INSTALLED"] = "1"
    LOGGER.critical(
        "RUNTIME_EXECUTION_CONVERGENCE_V33_INSTALLED marker=%s bound_method_preserved=true",
        MARKER,
    )
    return True


install_import_hook = install
