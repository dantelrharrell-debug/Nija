"""Converge proactive capital-publication scheduling with the effective pipeline deadline.

Production after v164 proved three-broker position sync, LIVE_ACTIVE, writer/core
registration, and live trade-cycle execution. It also exposed a remaining timing
contradiction: v137 computed pre-expiry headroom from the 50s broker-fetch budget,
while v158 correctly owns an 80s total runtime coordinator deadline inside the
90s immutable publication TTL. A refresh could therefore be legitimately in
flight when the older publication expired, briefly revoking otherwise fresh
3/3 capital.

v165 repairs scheduling only:
* v137 headroom is derived from the effective v142/v158 total pipeline deadline
  plus watchdog cadence, not merely the broker-fetch budget;
* the resulting headroom is still capped strictly inside the existing canonical
  freshness TTL, so publication expiry is never extended;
* v166 is installed from this already-required post-import convergence path so
  active-writer-only refresh ownership and tighter proactive bounds remain live;
* no balance, readiness, writer/nonce authority, kill switch, risk decision,
  activation state, or order permission is synthesized.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_publication_scheduling_v165")
MARKER = "20260819-runtime-capital-publication-scheduling-v165"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_PUBLICATION_SCHEDULING_V165_READY"
_PATCH_ATTR = "_nija_runtime_capital_publication_scheduling_v165"
_LOCK = threading.RLock()


def _v137() -> Any:
    return importlib.import_module("bot.capital_publication_deadline_v137_patch")


def _v142() -> Any:
    return importlib.import_module("bot.capital_publication_liveness_v142_patch")


def _effective_pipeline_deadline_seconds() -> float:
    v142 = _v142()
    getter = getattr(v142, "_runtime_pipeline_deadline_seconds", None)
    if not callable(getter):
        raise RuntimeError("runtime_pipeline_deadline_getter_missing")
    return max(10.0, float(getter()))


def _freshness_ttl_seconds() -> float:
    v137 = _v137()
    getter = getattr(v137, "_freshness_ttl_seconds", None)
    if not callable(getter):
        raise RuntimeError("freshness_ttl_getter_missing")
    return max(10.0, float(getter()))


def _watchdog_cadence_seconds(manager: Any) -> float:
    try:
        value = float(getattr(manager, "capital_watchdog_interval_s", 10.0) or 10.0)
    except (TypeError, ValueError):
        value = 10.0
    return max(1.0, min(10.0, value))


def _required_headroom_seconds(manager: Any) -> float:
    """Reserve enough validity for one worst-case coordinator run plus cadence."""
    ttl_s = _freshness_ttl_seconds()
    deadline_s = _effective_pipeline_deadline_seconds()
    cadence_s = _watchdog_cadence_seconds(manager)
    # Five seconds of immutable-validity margin remains non-negotiable. This
    # moves the refresh earlier; it never broadens publication lifetime.
    ceiling = max(5.0, ttl_s - 5.0)
    requested = deadline_s + cadence_s
    return max(5.0, min(requested, ceiling))


def _patch_v137_headroom() -> bool:
    v137 = _v137()
    current = getattr(v137, "_refresh_headroom_seconds", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def headroom_v165(manager: Any) -> float:
        return _required_headroom_seconds(manager)

    setattr(headroom_v165, _PATCH_ATTR, True)
    setattr(headroom_v165, "__wrapped__", original)
    v137._refresh_headroom_seconds = headroom_v165
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_publication_scheduling_v165"] = _READY_FLAG
        return True
    except Exception:
        return False


def _install_v166() -> bool:
    try:
        module = importlib.import_module("bot.runtime_capital_refresh_ownership_v166_patch")
        install_fn = getattr(module, "install", None)
        if not callable(install_fn):
            return False
        return bool(install_fn())
    except Exception as exc:
        LOGGER.error(
            "RUNTIME_CAPITAL_REFRESH_OWNERSHIP_V166_INSTALL_ERROR error=%s:%s trading_fail_closed=true",
            type(exc).__name__,
            exc,
        )
        return False


def install() -> bool:
    with _LOCK:
        headroom_ok = _patch_v137_headroom()
        manifest_ok = _patch_release_manifest()
        ready = bool(headroom_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_PUBLICATION_SCHEDULING_V165_FAILED marker=%s "
                "headroom_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(headroom_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        ttl_s = _freshness_ttl_seconds()
        deadline_s = _effective_pipeline_deadline_seconds()
        try:
            mabm = importlib.import_module("bot.multi_account_broker_manager")
            getter = getattr(mabm, "get_broker_manager", None)
            manager = getter() if callable(getter) else None
        except Exception:
            manager = None
        cadence_s = _watchdog_cadence_seconds(manager)
        headroom_s = _required_headroom_seconds(manager)
        LOGGER.critical(
            "RUNTIME_CAPITAL_PUBLICATION_SCHEDULING_V165 marker=%s ready=true "
            "freshness_ttl_s=%.1f effective_pipeline_deadline_s=%.1f watchdog_cadence_s=%.1f "
            "refresh_headroom_s=%.1f publication_expiry_extended=false safety_gates_bypassed=false",
            MARKER,
            ttl_s,
            deadline_s,
            cadence_s,
            headroom_s,
        )
        # v166 deliberately installs after v165 has published its base wrappers,
        # then replaces only the proactive runtime timing/ownership semantics.
        # Do not mark v165 unready when the optional follow-up import is still in
        # flight during the first import pass; the required v166 manifest flag
        # remains fail-closed until its own install completes.
        _install_v166()
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_effective_pipeline_deadline_seconds",
    "_freshness_ttl_seconds",
    "_watchdog_cadence_seconds",
    "_required_headroom_seconds",
    "_install_v166",
]
