"""Bootstrap helper utilities."""

from __future__ import annotations

import importlib
from typing import Callable, Optional


def resolve_bootstrap_balance_probe() -> Optional[Callable[[], bool]]:
    """Return a callable that reports balance hydration, or None when unavailable."""
    for module_name in ("bot.bootstrap_state_machine", "bootstrap_state_machine"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        probe = getattr(module, "is_bootstrap_balance_hydrated", None)
        if callable(probe):
            return probe
    return None
