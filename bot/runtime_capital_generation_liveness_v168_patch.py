"""Bound retired capital generations without starving the canonical refresh lane.

Production after v167 proved the routine-demand and writer-ownership repairs, but
v142/v164 still had one liveness contradiction: v142 generation-fences a timed
out coordinator before requesting rollover, while v164 counts that retired
physical daemon against the same two-thread capacity used for new canonical
work. Two fenced daemons can therefore consume both slots forever and prevent a
fresh CapitalAuthority publication even though they no longer have publication
authority.

v168 separates physical quarantine from canonical ownership:

* at most two retired v142 runtime-refresh daemons may remain quarantined;
* one additional canonical recovery lane may exist, for an absolute maximum of
  three v142 runtime-refresh daemons;
* a rollover may bypass v164's legacy two-thread physical cap only when the
  coordinator being replaced is already generation-fenced and the absolute
  three-thread ceiling has not been reached;
* when three physical workers are alive, no fourth worker is permitted;
* v142/v162 late-publication and late-observation fences remain authoritative.

This patch does not extend capital freshness, promote stale observations,
fabricate balances, change writer/nonce authority, clear kill switches, weaken
risk/order gates, or force LIVE_ACTIVE.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_generation_liveness_v168")
MARKER = "20260820-runtime-capital-generation-liveness-v168"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_GENERATION_LIVENESS_V168_READY"
_PATCH_ATTR = "_nija_runtime_capital_generation_liveness_v168"
_LOCK = threading.RLock()
_THREAD_RE = re.compile(r"^capital-runtime-refresh-v142-g(?P<generation>[0-9]+)$")


def _v142() -> Any:
    return importlib.import_module("bot.capital_publication_liveness_v142_patch")


def _v164() -> Any:
    return importlib.import_module("bot.runtime_capital_publication_liveness_v164_patch")


def _quarantine_limit() -> int:
    raw = str(os.environ.get("NIJA_CAPITAL_RETIRED_GENERATION_QUARANTINE_MAX", "2") or "2").strip()
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = 2
    # Production contract: enough room for the two already-observed retired
    # generations, but never an unbounded daemon backlog.
    return max(1, min(value, 2))


def _absolute_runtime_thread_limit() -> int:
    return _quarantine_limit() + 1


def _thread_generation(thread: Any) -> int | None:
    name = str(getattr(thread, "name", "") or "")
    match = _THREAD_RE.match(name)
    if match is None:
        return None
    try:
        return int(match.group("generation"))
    except (TypeError, ValueError):
        return None


def _live_runtime_threads() -> list[Any]:
    live: list[Any] = []
    for thread in threading.enumerate():
        generation = _thread_generation(thread)
        if generation is None:
            continue
        alive = getattr(thread, "is_alive", None)
        try:
            if callable(alive) and bool(alive()):
                live.append(thread)
        except Exception:
            continue
    return live


def _generation_state() -> tuple[int, bool]:
    getter = getattr(_v142(), "_generation_state", None)
    if not callable(getter):
        return 0, False
    try:
        active, rolled = getter()
        return int(active or 0), bool(rolled)
    except Exception:
        return 0, False


def _coordinator_generation(coordinator: Any) -> int:
    try:
        return int(getattr(coordinator, "_nija_v142_flight_generation", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _capacity_snapshot(manager: Any = None) -> dict[str, Any]:
    threads = _live_runtime_threads()
    generations = [g for g in (_thread_generation(t) for t in threads) if g is not None]
    active_generation, rolled = _generation_state()
    coordinator = getattr(manager, "_capital_coordinator", None) if manager is not None else None
    coordinator_generation = _coordinator_generation(coordinator)

    retired = [g for g in generations if active_generation > 0 and g != active_generation]
    active_physical = [g for g in generations if active_generation > 0 and g == active_generation]
    if active_generation <= 0:
        retired = []
        active_physical = list(generations)

    return {
        "active_generation": active_generation,
        "rollover_occurred": rolled,
        "coordinator_generation": coordinator_generation,
        "live_generations": sorted(generations),
        "retired_generations": sorted(retired),
        "active_physical_generations": sorted(active_physical),
        "live_count": len(generations),
        "retired_count": len(retired),
        "quarantine_limit": _quarantine_limit(),
        "absolute_limit": _absolute_runtime_thread_limit(),
    }


def _already_generation_fenced(coordinator: Any) -> bool:
    generation = _coordinator_generation(coordinator)
    if generation <= 0:
        return False
    active_generation, rolled = _generation_state()
    return bool(rolled and active_generation > 0 and generation != active_generation)


def _legacy_v142_rollover(current: Any) -> Any:
    """Return the v142 rollover under the v164 containment wrapper when provable."""
    wrapped = getattr(current, "__wrapped__", None)
    if not callable(wrapped):
        return None
    # v164's wrapper directly wraps v142._rollover_coordinator. Do not peel
    # arbitrary wrapper chains: bypassing anything else could discard a safety
    # layer installed after v164.
    v164_marker = str(getattr(_v164(), "_PATCH_ATTR", "_nija_runtime_capital_publication_liveness_v164"))
    if not bool(getattr(current, v164_marker, False)):
        return None
    return wrapped


def _patch_rollover_capacity() -> bool:
    v142 = _v142()
    current = getattr(v142, "_rollover_coordinator", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    legacy = _legacy_v142_rollover(current)
    if not callable(legacy):
        LOGGER.error(
            "CAPITAL_V168_ROLLOVER_CHAIN_UNPROVEN marker=%s trading_fail_closed=true",
            MARKER,
        )
        return False

    @wraps(current)
    def rollover_v168(
        manager: Any,
        *,
        expected_old: Any = None,
        reason: str,
    ) -> Any:
        old = getattr(manager, "_capital_coordinator", None)
        if old is None or (expected_old is not None and old is not expected_old):
            return current(manager, expected_old=expected_old, reason=reason)

        capacity = _capacity_snapshot(manager)
        fenced = _already_generation_fenced(old)
        total = int(capacity["live_count"])
        absolute = int(capacity["absolute_limit"])

        # v142 retires the timed-out generation before invoking rollover. When
        # that is proven and there is room below the absolute ceiling, bypass
        # only v164's legacy two-physical-thread cap and invoke the underlying
        # v142 swap. The new coordinator object itself starts no worker; v137's
        # immediate retry may then occupy the one canonical recovery lane.
        if fenced and total < absolute:
            replacement = legacy(
                manager,
                expected_old=expected_old,
                reason=reason,
            )
            LOGGER.critical(
                "CAPITAL_V168_CANONICAL_LANE_RELEASED marker=%s reason=%s old_generation=%d "
                "active_generation=%d live_generations=%s retired_alive=%d quarantine_limit=%d "
                "absolute_limit=%d replacement=%s generation_fence_preserved=true "
                "publication_expiry_extended=false trading_fail_closed_until_fresh=true",
                MARKER,
                reason,
                _coordinator_generation(old),
                int(capacity["active_generation"]),
                capacity["live_generations"],
                int(capacity["retired_count"]),
                int(capacity["quarantine_limit"]),
                absolute,
                replacement is not None and replacement is not old,
            )
            return replacement

        if fenced and total >= absolute:
            LOGGER.critical(
                "CAPITAL_V168_ABSOLUTE_THREAD_CAP marker=%s reason=%s live_generations=%s "
                "retired_alive=%d absolute_limit=%d fourth_worker_blocked=true "
                "generation_fence_preserved=true trading_fail_closed=true",
                MARKER,
                reason,
                capacity["live_generations"],
                int(capacity["retired_count"]),
                absolute,
            )

        # For unproven/unretired ownership, preserve v164 exactly.
        return current(manager, expected_old=expected_old, reason=reason)

    setattr(rollover_v168, _PATCH_ATTR, True)
    # Preserve v164 marker so its periodic installer does not re-wrap over v168.
    v164_marker = str(getattr(_v164(), "_PATCH_ATTR", "_nija_runtime_capital_publication_liveness_v164"))
    setattr(rollover_v168, v164_marker, True)
    setattr(rollover_v168, "__wrapped__", current)
    v142._rollover_coordinator = rollover_v168
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_generation_liveness_v168"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        rollover_ok = _patch_rollover_capacity()
        manifest_ok = _patch_release_manifest()
        ready = bool(rollover_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_GENERATION_LIVENESS_V168_FAILED marker=%s rollover_ok=%s "
                "manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(rollover_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False

        manager = None
        try:
            mabm = importlib.import_module("bot.multi_account_broker_manager")
            getter = getattr(mabm, "get_broker_manager", None)
            manager = getter() if callable(getter) else None
        except Exception:
            manager = None
        capacity = _capacity_snapshot(manager)
        LOGGER.critical(
            "RUNTIME_CAPITAL_GENERATION_LIVENESS_V168 marker=%s ready=true quarantine_limit=%d "
            "canonical_recovery_lanes=1 absolute_runtime_thread_limit=%d live_generations=%s "
            "retired_alive=%d active_physical=%d late_publication_fence_preserved=true "
            "late_observation_fence_preserved=true publication_expiry_extended=false stale_promoted=false "
            "safety_gates_bypassed=false",
            MARKER,
            int(capacity["quarantine_limit"]),
            int(capacity["absolute_limit"]),
            capacity["live_generations"],
            int(capacity["retired_count"]),
            len(capacity["active_physical_generations"]),
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_quarantine_limit",
    "_absolute_runtime_thread_limit",
    "_thread_generation",
    "_live_runtime_threads",
    "_generation_state",
    "_coordinator_generation",
    "_capacity_snapshot",
    "_already_generation_fenced",
    "_patch_rollover_capacity",
]
