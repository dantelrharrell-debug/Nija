"""Slow-broker capital refresh continuity v78.

A healthy Coinbase authenticated balance read has been observed taking longer
than the historical 180 second capital-refresh deadline.  v37 correctly refuses
to reuse an observation after the normal freshness TTL, but the short live-fetch
deadline can therefore collapse a healthy multi-broker snapshot to one venue.

v78 changes the *live request budget*, not the capital freshness contract:
* increase the bounded per-broker/cycle fetch budget to a configurable 420s;
* reuse a still-running in-flight request within that bounded cycle rather than
  starting a second request;
* preserve v37's existing fresh-observation fallback exactly as-is;
* never convert timeout to zero unless both live fetch and fresh fallback fail;
* never extend the freshness TTL or authorize trading from stale balances.

The guard remains fail closed after the extended bounded deadline.
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
MARKER = "20260809-capital-refresh-live-continuity-v78"
_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_capital_refresh_live_continuity_v78"
_HOOK_FLAG = "_NIJA_CAPITAL_REFRESH_LIVE_CONTINUITY_V78_IMPORT_HOOK"
_GUARD_NAMES = (
    "nija_capital_refresh_stall_guard_v35_prebot",
    "bot.capital_refresh_stall_guard_v35",
    "capital_refresh_stall_guard_v35",
)


def fetch_budget_seconds() -> float:
    try:
        value = float(os.environ.get("NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS", "420") or 420.0)
    except (TypeError, ValueError):
        value = 420.0
    return max(180.0, min(600.0, value))


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
        budget = fetch_budget_seconds()
        # v35/v36 read their timeout configuration while constructing the batch.
        # Set only the dedicated capital-refresh variable and restore the caller's
        # environment immediately after construction.
        key = "NIJA_CAPITAL_REFRESH_BROKER_TIMEOUT_SECONDS"
        previous = os.environ.get(key)
        try:
            os.environ[key] = str(budget)
            original_init(self, broker_map)
        finally:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous

        # Some historical guard revisions materialize timeout values before
        # consulting the environment. Raise only values that are clearly the
        # old <=180s default; never shorten a stricter operator configuration.
        for flight in dict(getattr(self, "_flights", {}) or {}).values():
            try:
                current = float(getattr(flight, "timeout_s", 0.0) or 0.0)
            except (TypeError, ValueError):
                current = 0.0
            if current <= 180.0:
                try:
                    setattr(flight, "timeout_s", budget)
                except Exception:
                    pass
        try:
            cycle_started = float(getattr(self, "_cycle_started", 0.0) or 0.0)
            cycle_deadline = float(getattr(self, "_cycle_deadline", 0.0) or 0.0)
            if cycle_started > 0.0 and cycle_deadline - cycle_started <= 180.0:
                setattr(self, "_cycle_deadline", cycle_started + budget)
        except Exception:
            pass
        LOGGER.info(
            "CAPITAL_REFRESH_V78_BATCH_BUDGET marker=%s budget_s=%.1f brokers=%s freshness_ttl_unchanged=true",
            MARKER,
            budget,
            sorted(str(name).lower() for name in broker_map),
        )

    setattr(init_v78, _PATCH_ATTR, True)
    setattr(init_v78, "__wrapped__", original_init)
    batch_cls.__init__ = init_v78
    LOGGER.critical(
        "CAPITAL_REFRESH_V78_GUARD_PATCHED marker=%s module=%s max_budget_s=600 stale_fallback_extension=false",
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
            "CAPITAL_REFRESH_LIVE_CONTINUITY_V78_INSTALLED marker=%s budget_s=%.1f freshness_ttl_unchanged=true",
            MARKER,
            fetch_budget_seconds(),
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "fetch_budget_seconds", "install", "install_import_hook"]
