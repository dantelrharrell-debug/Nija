"""Exit JIT conflict recovery v332.

v330 introduced exact just-in-time broker position proof for exits when the
shared v285 snapshot is missing, stale, or structurally invalid. Production
then exposed a second safe-to-reverify state: the shared snapshot can be recent
but incomplete relative to the tracker, yielding either
``symbol_absent_from_recent_authoritative_snapshot`` or
``authoritative_quantity_mismatch``. Those states must not be promoted to a
valid exit, but they also must not strand capital indefinitely.

v332 handles only those conflicts. It asks v330 for a fresh account-local JIT
quantity proof. For Kraken this can reuse a genuine short-TTL authenticated
v312 Balance observation; for other venues v330 schedules a bounded direct
position refresh. The exit becomes eligible only if the new broker quantity
exactly matches the already verified tracker quantity. Otherwise it remains
fail-closed and no order is submitted.

No snapshot TTL is extended. No position, cost basis, balance, price, order,
fill, profit, or readiness state is fabricated. v67 fill reconciliation, v68
all-in break-even economics, stop-loss, trailing exits, writer/nonce/risk,
kill-switch and minimum-order gates remain authoritative.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_exit_jit_conflict_recovery_v332")
MARKER = "20260831-exit-jit-conflict-recovery-v332"
RELEASE_ID = "20260831-runtime-convergence-v332"
_READY_FLAG = "NIJA_RUNTIME_EXIT_JIT_CONFLICT_RECOVERY_V332_READY"
_PATCH_ATTR = "_nija_exit_jit_conflict_recovery_v332"
_INSTALL_FLAG = "_NIJA_RUNTIME_EXIT_JIT_CONFLICT_RECOVERY_V332"
_LOCK = threading.RLock()
_CONFLICT_REASONS = {
    "symbol_absent_from_recent_authoritative_snapshot",
    "authoritative_quantity_mismatch",
}


def _patch_v323_conflicts() -> bool:
    v323 = importlib.import_module("bot.runtime_universal_exit_tracker_convergence_v323_patch")
    v330 = importlib.import_module("bot.runtime_capital_recycling_exit_v330_patch")
    current = getattr(v323, "_position_exit_proof", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def conflict_recovery(universal: ModuleType, broker: Any, pos: Mapping[str, Any]):
        safe, reason, details = current(universal, broker, pos)
        if safe or reason not in _CONFLICT_REASONS:
            return safe, reason, details

        symbol = universal.auto_exit._sym(pos.get("symbol"))
        tracker_qty = universal.auto_exit._quantity(dict(pos))
        if not symbol or tracker_qty <= 0.0:
            return False, reason, details

        ok, broker_qty, source, age = v330._jit_quantity(broker, symbol)
        merged = dict(details or {})
        merged.update({
            "tracker_quantity": tracker_qty,
            "jit_authoritative_quantity": broker_qty,
            "jit_source": source,
            "jit_age_s": age,
            "original_conflict_reason": reason,
        })
        if not ok:
            LOGGER.warning(
                "EXIT_JIT_CONFLICT_V332_DEFERRED marker=%s venue=%s account=%s symbol=%s "
                "reason=%s jit_source=%s exit_not_submitted=true fail_closed=true "
                "snapshot_ttl_unchanged=true safety_gates_bypassed=false",
                MARKER,
                universal.auto_exit._broker_label(broker),
                universal._account_label(broker),
                symbol,
                reason,
                source,
            )
            return False, f"{reason}+{source}", merged

        if not v330._quantity_matches(tracker_qty, broker_qty):
            LOGGER.warning(
                "EXIT_JIT_CONFLICT_V332_MISMATCH marker=%s venue=%s account=%s symbol=%s "
                "tracker_qty=%.12f broker_qty=%.12f source=%s exit_not_submitted=true "
                "ghost_or_stale_tracker_not_sold=true safety_gates_bypassed=false",
                MARKER,
                universal.auto_exit._broker_label(broker),
                universal._account_label(broker),
                symbol,
                tracker_qty,
                broker_qty,
                source,
            )
            return False, "jit_conflict_quantity_mismatch", merged

        LOGGER.critical(
            "EXIT_JIT_CONFLICT_V332_RECOVERED marker=%s venue=%s account=%s symbol=%s "
            "original_reason=%s tracker_qty=%.12f broker_qty=%.12f source=%s age_s=%.3f "
            "cost_basis_still_required=true fill_confirmation_required=true "
            "snapshot_ttl_unchanged=true position_fabricated=false safety_gates_bypassed=false",
            MARKER,
            universal.auto_exit._broker_label(broker),
            universal._account_label(broker),
            symbol,
            reason,
            tracker_qty,
            broker_qty,
            source,
            age,
        )
        return True, "verified_jit_conflict_recovery", merged

    setattr(conflict_recovery, _PATCH_ATTR, True)
    setattr(conflict_recovery, "__wrapped__", current)
    v323._position_exit_proof = conflict_recovery
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_exit_jit_conflict_recovery_v332"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            if os.environ.get("NIJA_RUNTIME_CAPITAL_RECYCLING_EXIT_V330_READY") != "1":
                raise RuntimeError("v330_not_ready")
            patched = _patch_v323_conflicts()
            manifest = _register_manifest()
            ready = bool(patched and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "EXIT_JIT_CONFLICT_V332_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true forced_exit=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_EXIT_JIT_CONFLICT_RECOVERY_V332_%s marker=%s ready=%s "
            "symbol_absence_reverified=true quantity_mismatch_reverified=true "
            "exact_jit_quantity_match_required=true v330_required=true v67_fill_confirmation_preserved=true "
            "v68_all_in_break_even_preserved=true snapshot_ttl_unchanged=true "
            "ghost_position_exit_blocked=true forced_loss_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook"]
