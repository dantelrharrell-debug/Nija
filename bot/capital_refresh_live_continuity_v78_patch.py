"""Freshness-bounded slow-broker capital refresh continuity v78.

Capital refresh workers may legitimately take longer than the canonical capital
freshness TTL. Waiting synchronously for those workers beyond the TTL creates a
liveness contradiction: the refresh pipeline remains occupied while the last
accepted CapitalAuthority snapshot becomes stale, so activation must fail closed.

v78 keeps slow requests alive in their existing daemon workers but bounds the
*synchronous batch wait* so a refresh can publish from brokers that completed in
time. Late workers may populate the guard's observation cache for a later cycle;
that cache remains subject to the existing freshness checks.

Safety properties:
* the synchronous cycle deadline is always strictly inside the freshness TTL;
* no per-broker timeout is lengthened and no stale fallback is authorized;
* still-running workers are not cancelled or duplicated;
* optional slow venues cannot hold the whole capital publication path past TTL;
* the guard remains fail closed when no fresh broker result is available.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.capital_refresh_live_continuity_v78")
MARKER = "20260812-capital-refresh-freshness-bounded-v78"
_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_capital_refresh_live_continuity_v78"
_HOOK_FLAG = "_NIJA_CAPITAL_REFRESH_LIVE_CONTINUITY_V78_IMPORT_HOOK"
_GUARD_NAMES = (
    "nija_capital_refresh_stall_guard_v35_prebot",
    "bot.capital_refresh_stall_guard_v35",
    "capital_refresh_stall_guard_v35",
)


def _freshness_ttl_seconds() -> float:
    try:
        return max(
            10.0,
            float(os.environ.get("NIJA_CAPITAL_FRESHNESS_TTL_S", "90.0") or 90.0),
        )
    except (TypeError, ValueError):
        return 90.0


def fetch_budget_seconds() -> float:
    """Return a synchronous publish budget that cannot outlive capital freshness."""
    ttl_s = _freshness_ttl_seconds()
    try:
        requested = float(
            os.environ.get("NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS", "60.0")
            or 60.0
        )
    except (TypeError, ValueError):
        requested = 60.0

    try:
        margin_s = float(
            os.environ.get("NIJA_CAPITAL_REFRESH_PUBLISH_MARGIN_SECONDS", "15.0")
            or 15.0
        )
    except (TypeError, ValueError):
        margin_s = 15.0

    margin_s = max(5.0, min(margin_s, max(5.0, ttl_s / 2.0)))
    ceiling = max(5.0, ttl_s - margin_s)
    return max(5.0, min(requested, ceiling))


def _patch_guard(module: ModuleType) -> bool:
    batch_cls = getattr(module, "_BalanceFetchBatch", None)
    if not isinstance(batch_cls, type):
        return False
    original_init = getattr(batch_cls, "__init__", None)
    if not callable(original_init):
        return False
    if getattr(original_init, _PATCH_ATTR, False):
        return True

    @wraps(original_init)
    def init_v78(self: Any, broker_map: dict[str, Any]) -> None:
        original_init(self, broker_map)
        budget = fetch_budget_seconds()

        # v35/v36 use _batch_started; a few compatibility revisions used
        # _cycle_started. Support both without mutating immutable _Flight tuples.
        started = 0.0
        for attr in ("_batch_started", "_cycle_started"):
            try:
                candidate = float(getattr(self, attr, 0.0) or 0.0)
            except (TypeError, ValueError):
                candidate = 0.0
            if candidate > 0.0:
                started = candidate
                break

        if started > 0.0:
            current_deadline = float(getattr(self, "_cycle_deadline", 0.0) or 0.0)
            bounded_deadline = started + budget
            # Only shorten an overlong batch. Never lengthen a stricter deadline.
            if current_deadline <= 0.0 or current_deadline > bounded_deadline:
                setattr(self, "_cycle_deadline", bounded_deadline)

        LOGGER.info(
            "CAPITAL_REFRESH_V78_BATCH_BUDGET marker=%s budget_s=%.1f ttl_s=%.1f "
            "brokers=%s late_workers_async=true stale_fallback_extension=false",
            MARKER,
            budget,
            _freshness_ttl_seconds(),
            sorted(str(name).lower() for name in broker_map),
        )

    setattr(init_v78, _PATCH_ATTR, True)
    setattr(init_v78, "__wrapped__", original_init)
    batch_cls.__init__ = init_v78
    LOGGER.critical(
        "CAPITAL_REFRESH_V78_GUARD_PATCHED marker=%s module=%s "
        "freshness_bounded=true stale_fallback_extension=false",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in _GUARD_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_guard(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if "capital_refresh_stall_guard_v35" in str(name):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)
        os.environ["NIJA_CAPITAL_REFRESH_LIVE_CONTINUITY_V78_INSTALLED"] = "1"
        LOGGER.critical(
            "CAPITAL_REFRESH_LIVE_CONTINUITY_V78_INSTALLED marker=%s budget_s=%.1f "
            "ttl_s=%.1f freshness_bounded=true",
            MARKER,
            fetch_budget_seconds(),
            _freshness_ttl_seconds(),
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "fetch_budget_seconds",
    "install",
    "install_import_hook",
]
