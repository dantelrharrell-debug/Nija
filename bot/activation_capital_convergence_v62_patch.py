"""Canonical activation/capital state convergence repair v62.

This repair closes two fail-closed startup races without manufacturing authority:

1. Compatibility activation requests can reach ``StartupCoordinator`` before its
   cached bootstrap/capital/readiness fields have been refreshed from the
   canonical FSMs. The coordinator then correctly rejects at ``capital.running``
   even though CapitalBootstrapStateMachine is already READY. Before evaluating a
   compatibility request, mirror the current canonical bootstrap, capital, and
   readiness snapshots into the coordinator using its normal ``record_*`` APIs.

2. ``three_venue_execution_readiness`` historically allowed environment handoff
   flags to override CapitalAuthority staleness. Replace that observer with a
   canonical check: hydrated authority, positive real capital, and a currently
   accepted, non-stale publication are all required.

No writer, nonce, kill-switch, dispatch-health, risk, or freshness gate is
bypassed. The coordinator's existing readiness proof remains the final authority.
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

LOGGER = logging.getLogger("nija.activation_capital_convergence_v62")
MARKER = "20260812-activation-capital-convergence-v62"
_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_ACTIVATION_CAPITAL_CONVERGENCE_V62_IMPORT_HOOK"
_COORD_PATCH = "_nija_activation_capital_convergence_v62"
_CAPITAL_PATCH = "_nija_canonical_capital_observer_v62"


def _state_value(module_name: str, getter_name: str) -> str:
    try:
        module = __import__(module_name, fromlist=[getter_name])
        getter = getattr(module, getter_name)
        state = getattr(getter(), "state", None)
        return str(getattr(state, "value", state) or "UNAVAILABLE")
    except Exception:
        return "UNAVAILABLE"


def _authority_snapshot() -> tuple[bool, float | None, bool]:
    """Return (hydrated, real_capital, stale_or_unaccepted) from CapitalAuthority."""
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        authority = get_capital_authority()
        if authority is None:
            return False, None, True

        hydrated_value = getattr(authority, "is_hydrated", False)
        hydrated = bool(
            hydrated_value() if callable(hydrated_value) else hydrated_value
        )

        capital_reader = getattr(authority, "get_real_capital", None)
        capital = float(capital_reader()) if callable(capital_reader) else float(
            getattr(authority, "total_capital", 0.0) or 0.0
        )

        stale = True
        publication_reader = getattr(authority, "get_snapshot_publication_status", None)
        if callable(publication_reader):
            try:
                publication = publication_reader()
                publication_stale = bool(getattr(publication, "stale", True))
                publication_accepted = bool(
                    getattr(publication, "accepted", not publication_stale)
                )
                stale = bool(publication_stale or not publication_accepted)
            except Exception:
                stale = True
        else:
            stale_reader = getattr(authority, "is_stale", None)
            if callable(stale_reader):
                try:
                    stale = bool(stale_reader())
                except TypeError:
                    stale = bool(stale_reader(ttl_s=90.0))
                except Exception:
                    stale = True

        return hydrated, capital, stale
    except Exception:
        return False, None, True


def _readiness_snapshot() -> tuple[int, dict[str, bool]]:
    try:
        try:
            from bot.readiness_table import snapshot_with_version
        except ImportError:
            from readiness_table import snapshot_with_version  # type: ignore[import]
        version, table = snapshot_with_version()
        return int(version or 0), dict(table or {})
    except Exception:
        return 0, {}


def _sync_coordinator_inputs(coordinator: Any) -> None:
    """Mirror canonical state into StartupCoordinator without granting authority."""
    bootstrap_state = _state_value(
        "bot.bootstrap_state_machine", "get_bootstrap_fsm"
    )
    capital_state = _state_value(
        "bot.capital_flow_state_machine", "get_capital_bootstrap_fsm"
    )
    hydrated, capital, stale = _authority_snapshot()
    readiness_version, readiness = _readiness_snapshot()

    coordinator.record_bootstrap_state(bootstrap_state)
    coordinator.record_capital_state(
        state=capital_state,
        hydrated=hydrated,
        balance=capital,
        stale=stale,
    )
    if readiness:
        readiness_table = readiness
        readiness_complete = bool(all(readiness.values()))
    else:
        # An empty/unavailable table must never satisfy
        # StartupConvergenceSnapshot.pending_readiness by vacuous truth.
        readiness_table = {"canonical_sync_available": False}
        readiness_complete = False
    coordinator.record_readiness(
        key="__canonical_sync__",
        value=readiness_complete,
        version=readiness_version,
        table=readiness_table,
    )
    LOGGER.info(
        "ACTIVATION_CAPITAL_CANONICAL_SYNC marker=%s bootstrap=%s capital=%s "
        "hydrated=%s balance=%s stale=%s readiness_v=%s pending=%s",
        MARKER,
        bootstrap_state,
        capital_state,
        hydrated,
        capital,
        stale,
        readiness_version,
        sorted(key for key, value in readiness_table.items() if not value),
    )


def _patch_startup_coordinator(module: ModuleType) -> bool:
    cls = getattr(module, "StartupCoordinator", None)
    original = getattr(cls, "force_activate_bypass", None) if isinstance(cls, type) else None
    if not callable(original):
        return False
    if getattr(original, _COORD_PATCH, False):
        return True

    @wraps(original)
    def force_activate_with_canonical_sync(self: Any, reason: str) -> int:
        _sync_coordinator_inputs(self)
        return original(self, reason)

    setattr(force_activate_with_canonical_sync, _COORD_PATCH, True)
    setattr(force_activate_with_canonical_sync, "__wrapped__", original)
    cls.force_activate_bypass = force_activate_with_canonical_sync
    LOGGER.critical(
        "ACTIVATION_COORDINATOR_CANONICAL_SYNC_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _canonical_capital_ready() -> bool:
    hydrated, capital, stale = _authority_snapshot()
    return bool(hydrated and capital is not None and capital > 0.0 and not stale)


def _patch_three_venue(module: ModuleType) -> bool:
    current = getattr(module, "_capital_ready", None)
    if not callable(current):
        return False
    if getattr(current, _CAPITAL_PATCH, False):
        return True

    @wraps(current)
    def canonical_capital_ready() -> bool:
        ready = _canonical_capital_ready()
        if not ready:
            hydrated, capital, stale = _authority_snapshot()
            LOGGER.warning(
                "THREE_VENUE_CANONICAL_CAPITAL_NOT_READY marker=%s hydrated=%s "
                "capital=%s stale_or_unaccepted=%s env_handoff_ignored=true",
                MARKER,
                hydrated,
                capital,
                stale,
            )
        return ready

    setattr(canonical_capital_ready, _CAPITAL_PATCH, True)
    setattr(canonical_capital_ready, "__wrapped__", current)
    module._capital_ready = canonical_capital_ready
    LOGGER.critical(
        "THREE_VENUE_CANONICAL_CAPITAL_OBSERVER_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in ("bot.startup_coordinator", "startup_coordinator"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_startup_coordinator(module) or changed
    for name in ("three_venue_execution_readiness", "bot.three_venue_execution_readiness"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_three_venue(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if (
                    "startup_coordinator" in str(name)
                    or "three_venue_execution_readiness" in str(name)
                ):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_ACTIVATION_CAPITAL_CONVERGENCE_V62_READY"] = "1"
        LOGGER.critical(
            "ACTIVATION_CAPITAL_CONVERGENCE_V62_INSTALLED marker=%s "
            "canonical_state_sync=true canonical_capital_freshness=true bypass=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_capital_ready",
    "_sync_coordinator_inputs",
]
