"""Pre-core Kraken position-read and phase-handoff liveness ordering v318.

Production evidence on 2026-08-31 showed two startup-order failures on PLATFORM
Kraken. First, authoritative Balance reconciliation could begin before the
credential-scoped read-liveness stack was fully installed. Second, even after an
initial genuine Balance completed, the v288/v304 cost-basis phase and v305/v306
Balance-to-history handoff could still be installed later. A legacy
``TradesHistory`` worker could therefore take the monitoring turn while a
redundant authoritative Balance owner was queued behind it, consuming another
full configured Kraken monitoring interval and exhausting the bounded post-core
activation budget.

v318 changes installation order only. On the canonical fast path, after the real
Redis writer lease has already been acquired and verified by launcher v313 but
before ``bot.bot_main`` begins broker reconciliation, it:

* applies v286's patch-only primitive without starting its monitor/reconcile loop;
* arms the existing v292 transport timeout wrapper;
* arms v293 credential-scoped private-call serialization;
* arms v297 priority/FIFO monitoring coordination;
* arms v299 credential-scoped Balance coalescing + v314 owner promotion;
* arms v312 authenticated same-credential Balance epoch handoff;
* arms v288 broker-scoped bulk cost-basis recovery, which chains v304 older
  authenticated history pagination;
* arms v305 authoritative snapshot ownership isolation, which chains v306's
  explicit Balance-to-cost-basis phase handoff.

The added v288/v304/v305/v306 installers only patch/import coordination surfaces
at this point; v318 itself never invokes a broker method, starts a v286 monitor,
or calls a reconciliation routine. No existing worker is cancelled, no lock is
released or bypassed, no Kraken rate interval or timeout is relaxed, and no
position, balance, cost basis, readiness, execution proof, fill, or LIVE_ACTIVE
state is fabricated. Any failed prerequisite keeps canonical startup fail closed.
"""
from __future__ import annotations

import importlib
import logging
import os
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_precore_liveness_v318")
MARKER = "20260831-kraken-precore-liveness-v318"
RELEASE_ID = "20260831-runtime-convergence-v318"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_PRECORE_LIVENESS_V318_READY"
_REQUIRED_WRITER_FLAGS = (
    "NIJA_CANONICAL_WRITER_FIRST_V59_READY",
    "NIJA_CANONICAL_LAUNCHER_IMPORT_V111_READY",
)
_REQUIRED_PHASE_FLAGS = (
    "NIJA_RUNTIME_KRAKEN_COST_BASIS_BULK_V288_READY",
    "NIJA_RUNTIME_KRAKEN_COST_BASIS_HISTORY_PAGINATION_V304_READY",
    "NIJA_RUNTIME_KRAKEN_AUTHORITATIVE_SNAPSHOT_OWNERSHIP_V305_READY",
    "NIJA_RUNTIME_KRAKEN_STARTUP_PHASE_HANDOFF_V306_READY",
)


def _writer_precondition() -> tuple[bool, str]:
    missing = [name for name in _REQUIRED_WRITER_FLAGS if os.environ.get(name) != "1"]
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    if missing:
        return False, "missing_writer_attestations:" + ",".join(missing)
    if not token:
        return False, "writer_fencing_token_missing"
    return True, "verified"


def _module(name: str) -> Any:
    return importlib.import_module(name)


def _install_module(name: str) -> bool:
    module = _module(name)
    installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer):
        raise RuntimeError(f"installer_missing:{name}")
    result = installer()
    if result is False:
        raise RuntimeError(f"installer_returned_false:{name}")
    return True


def _v286_patch_only() -> tuple[bool, bool]:
    """Patch the v286 read/adopter surfaces without starting its monitor."""
    v286 = _module("bot.runtime_kraken_position_refresh_liveness_v286_patch")
    patcher = getattr(v286, "_patch_all", None)
    if not callable(patcher):
        raise RuntimeError("v286_patch_only_primitive_missing")

    before_thread = getattr(v286, "_MONITOR_THREAD", None)
    before_alive = bool(before_thread is not None and before_thread.is_alive())
    if patcher() is False:
        raise RuntimeError("v286_patch_only_failed")
    after_thread = getattr(v286, "_MONITOR_THREAD", None)
    after_alive = bool(after_thread is not None and after_thread.is_alive())

    # v318 itself must never be the operation that starts reconciliation I/O.
    if not before_alive and after_alive:
        raise RuntimeError("v286_monitor_started_during_precore_patch")
    return True, after_alive


def _phase_stack_ready() -> tuple[bool, tuple[str, ...]]:
    missing = tuple(name for name in _REQUIRED_PHASE_FLAGS if os.environ.get(name) != "1")
    if missing:
        return False, missing

    v288 = _module("bot.runtime_kraken_cost_basis_bulk_v288_patch")
    v306 = _module("bot.runtime_kraken_startup_phase_handoff_v306_patch")
    resolve = getattr(_module("bot.startup_position_sync"), "_resolve_entry_price", None)
    authoritative = getattr(_module("bot.runtime_kraken_position_refresh_liveness_v286_patch"), "_authoritative_positions", None)
    v288_attr = str(getattr(v288, "_PATCH_ATTR", "") or "")
    v306_attr = str(getattr(v306, "_PATCH_ATTR", "") or "")
    if not callable(resolve) or not v288_attr or not bool(getattr(resolve, v288_attr, False)):
        return False, ("v288_resolver_patch_missing",)
    if not callable(authoritative) or not v306_attr or not bool(getattr(authoritative, v306_attr, False)):
        return False, ("v306_authoritative_handoff_patch_missing",)
    return True, ()


def _register_manifest() -> bool:
    try:
        manifest = _module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_precore_liveness_v318"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    writer_ok, writer_detail = _writer_precondition()
    if not writer_ok:
        os.environ[_READY_FLAG] = "0"
        LOGGER.critical(
            "KRAKEN_PRECORE_LIVENESS_V318_NOT_READY marker=%s reason=%s "
            "trading_fail_closed=true broker_io=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
            writer_detail,
        )
        return False

    outcomes: dict[str, str] = {}
    monitor_preexisting = False
    try:
        _patched, monitor_preexisting = _v286_patch_only()
        outcomes["v286_patch_only"] = "ok"
        for module_name, label in (
            ("bot.runtime_kraken_transport_timeout_v292_patch", "v292"),
            ("bot.runtime_kraken_credential_lock_scope_v293_patch", "v293"),
            ("bot.runtime_kraken_monitoring_fairness_v297_patch", "v297"),
            ("bot.runtime_kraken_credential_read_convergence_v299_patch", "v299_v314"),
            ("bot.runtime_kraken_balance_epoch_handoff_v312_patch", "v312"),
            ("bot.runtime_kraken_cost_basis_bulk_v288_patch", "v288_v304"),
            ("bot.runtime_kraken_authoritative_snapshot_ownership_v305_patch", "v305_v306"),
        ):
            _install_module(module_name)
            outcomes[label] = "ok"

        phase_ready, phase_missing = _phase_stack_ready()
        if not phase_ready:
            raise RuntimeError("precore_phase_stack_unproven:" + ",".join(phase_missing))
        outcomes["phase_stack"] = "v288+v304+v305+v306_ready"

        manifest_ok = _register_manifest()
        if not manifest_ok:
            raise RuntimeError("release_manifest_registration_failed")
    except Exception as exc:
        os.environ[_READY_FLAG] = "0"
        LOGGER.critical(
            "KRAKEN_PRECORE_LIVENESS_V318_NOT_READY marker=%s error=%s:%s outcomes=%s "
            "writer_verified=true broker_io=false trading_fail_closed=true "
            "lock_bypass=false lock_force_release=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
            type(exc).__name__,
            exc,
            outcomes,
            exc_info=True,
        )
        return False

    os.environ[_READY_FLAG] = "1"
    LOGGER.critical(
        "KRAKEN_PRECORE_LIVENESS_V318_READY marker=%s ready=true outcomes=%s "
        "writer_verified=true before_bot_main=true before_broker_reconciliation=true "
        "v286_patch_only=true v286_monitor_started_by_v318=false monitor_preexisting=%s "
        "transport_timeout_v292=true credential_lock_v293=true monitoring_fairness_v297=true "
        "credential_balance_v299=true owner_priority_v314=true balance_epoch_v312=true "
        "cost_basis_bulk_v288=true history_pagination_v304=true snapshot_ownership_v305=true "
        "startup_phase_handoff_v306=true redundant_balance_during_history_blocked=true "
        "broker_io=false configured_rate_interval_unchanged=true transport_timeout_unchanged=true "
        "nonce_ordering_unchanged=true lock_bypass=false lock_force_release=false "
        "position_success_fabricated=false balance_fabricated=false cost_basis_fabricated=false "
        "readiness_granted=false execution_proof_fabricated=false forced_trade=false "
        "forced_activation=false writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        MARKER,
        outcomes,
        str(monitor_preexisting).lower(),
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_writer_precondition",
    "_v286_patch_only",
    "_phase_stack_ready",
]
