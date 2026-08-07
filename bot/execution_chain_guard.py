"""Chain-aware wrapper idempotency guard for NIJA execution pipeline.

Provides ``chain_has_attr`` — a drop-in replacement for
``getattr(func, attr, False)`` that walks the entire ``__wrapped__``
chain before concluding that a wrapper marker is absent.

This prevents duplicate wrapper installation when outer layers are
replaced by another patch (the old marker ends up deeper in the chain,
invisible to a shallow ``getattr`` check).

Usage
-----
Replace::

    if getattr(cls.execute, "_my_marker", False):
        return False   # already installed

with::

    from bot.execution_chain_guard import chain_has_attr
    if chain_has_attr(cls.execute, "_my_marker"):
        return False   # already installed
"""
from __future__ import annotations

from typing import Any

_MAX_CHAIN_DEPTH = 256


def chain_has_attr(func: Any, attr: str, *, max_depth: int = _MAX_CHAIN_DEPTH) -> bool:
    """Return True if *attr* is present (and truthy) anywhere in the wrapper chain.

    The chain is followed via ``__wrapped__`` links.  A cycle or depth
    exceeding *max_depth* causes the walk to stop and return the value
    found so far.
    """
    current = func
    seen: set[int] = set()
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen or depth > max_depth:
            break
        seen.add(ident)
        if getattr(current, attr, False):
            return True
        nxt = getattr(current, "__wrapped__", None)
        if not callable(nxt):
            break
        current = nxt
        depth += 1
    return False


def chain_depth(func: Any, *, max_depth: int = _MAX_CHAIN_DEPTH) -> tuple[int, bool]:
    """Return ``(depth, cycle_detected)`` for the ``__wrapped__`` chain."""
    current = func
    seen: set[int] = set()
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            return depth, True
        seen.add(ident)
        nxt = getattr(current, "__wrapped__", None)
        if not callable(nxt):
            return depth, False
        current = nxt
        depth += 1
        if depth > max_depth:
            return depth, False
    return depth, False


__all__ = ["chain_has_attr", "chain_depth"]
