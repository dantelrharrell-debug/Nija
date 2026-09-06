"""Kraken margin protective-exit authority scoping v368.

v367 correctly stopped treating configured protection as exchange proof, but its
software-protection readiness probe called v337 outside the exact-broker context
installed by v339. In production this caused a false negative while the Kraken
margin monitor was alive: the global dispatch-health aggregate was still false
although the exact Kraken protective-close path could be re-proven independently.

v368 fixes only that authority-scoping mismatch. It does not promote global
execution readiness, bypass broker health, create fills, or force exits.

The patch:
* carries the exact Kraken broker through margin coverage using a ContextVar;
* reuses v339's broker-local proof path when v337 reports global dispatch health
  not ready;
* allows the dedicated margin monitor to keep observing an authenticated Kraken
  account during transient stale ``connected`` bookkeeping, but only after a real
  authenticated OpenOrders read succeeds; terminal submit gates remain unchanged;
* preserves fail-closed behavior whenever exact broker, writer, nonce, kill switch,
  circuit, fencing, or terminal execution requirements are not proven.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from contextvars import ContextVar
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_margin_protection_authority_v368")
MARKER = "20260904-runtime-kraken-margin-protection-authority-v368"
RELEASE_ID = "20260904-runtime-convergence-v368"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_AUTHORITY_V368_READY"
_PATCH_ATTR = "_nija_v368_kraken_margin_protection_authority"
_LOCK = threading.RLock()
_BROKER_SCOPE: ContextVar[Any] = ContextVar("nija_v368_margin_coverage_broker", default=None)


def _v367():
    return importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch")


def _v366():
    return importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")


def _exact_scoped_authority(broker: Any) -> tuple[bool, str]:
    """Re-prove hard exit authority inside v339's exact broker scope."""
    if broker is None:
        return False, "exact_broker_missing"
    try:
        v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
        v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
        probe = getattr(v337, "_hard_exit_authority_proof", None)
        broker_var = getattr(v339, "_BROKER", None)
        if not callable(probe) or broker_var is None:
            return False, "exact_broker_authority_surface_unavailable"
        token = broker_var.set(broker)
        try:
            ok, reason, _snapshot = probe()
        finally:
            broker_var.reset(token)
        return bool(ok), str(reason or "unproven")
    except Exception as exc:
        return False, f"exact_broker_authority_exception:{type(exc).__name__}"


def _patch_software_protection_status() -> bool:
    v367 = _v367()
    current = getattr(v367, "_software_protection_status", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def scoped_software_status():
        # Preserve v367's monitor/wiring requirements first.
        if not bool(getattr(v367, "_monitor_alive", lambda: False)()):
            return False, "margin_monitor_not_alive"
        if not bool(getattr(v367, "_margin_scan_wiring_ready", lambda: False)()):
            return False, "margin_scan_wiring_unproven"

        broker = _BROKER_SCOPE.get()
        if broker is None:
            return current()

        ok, reason = _exact_scoped_authority(broker)
        if not ok:
            return False, f"hard_exit_authority_unproven:{reason}"
        return True, "dedicated_margin_monitor_and_exact_broker_hard_exit_authority_ready"

    setattr(scoped_software_status, _PATCH_ATTR, True)
    setattr(scoped_software_status, "__wrapped__", current)
    v367._software_protection_status = scoped_software_status
    return True


def _patch_margin_coverage_broker_scope() -> bool:
    v366 = _v366()
    current = getattr(v366, "margin_coverage_rows", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def margin_coverage_v368(account: str, broker: Any):
        token = _BROKER_SCOPE.set(broker)
        try:
            return current(account, broker)
        finally:
            _BROKER_SCOPE.reset(token)

    setattr(margin_coverage_v368, _PATCH_ATTR, True)
    setattr(margin_coverage_v368, "__wrapped__", current)
    v366.margin_coverage_rows = margin_coverage_v368
    return True


def _patch_account_brokers_authenticated_read_fallback() -> bool:
    """Keep the monitor observing Kraken during stale connection bookkeeping.

    This fallback grants *read/scan participation only*. It requires a successful
    authenticated OpenOrders call through v367. It does not declare execution
    health and does not alter any terminal order-submit gate.
    """
    v367 = _v367()
    current = getattr(v367, "_account_brokers", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def account_brokers_v368():
        rows = list(current() or [])
        seen = {str(account) for account, _broker in rows}
        try:
            v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
            manager = v281._canonical_manager()
            expected = v281._expected_accounts(manager)
        except Exception:
            return rows

        for account, broker in dict(expected or {}).items():
            account_s = str(account)
            if account_s in seen or broker is None:
                continue
            try:
                if not _v366().is_kraken_account(account, broker):
                    continue
                native_ok, _orders, reason = v367._native_protection(account_s, broker)
            except Exception:
                continue
            if not native_ok:
                continue
            rows.append((account_s, broker))
            seen.add(account_s)
            LOGGER.warning(
                "KRAKEN_MARGIN_MONITOR_V368_AUTHENTICATED_READ_FALLBACK marker=%s account=%s "
                "openorders_authenticated=true reason=%s execution_health_promoted=false "
                "terminal_submit_gates_unchanged=true safety_gates_bypassed=false",
                MARKER, account_s, reason,
            )
        return rows

    setattr(account_brokers_v368, _PATCH_ATTR, True)
    setattr(account_brokers_v368, "__wrapped__", current)
    v367._account_brokers = account_brokers_v368
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_margin_protection_authority_v368"] = _READY_FLAG
        return True
    except Exception:
        return False


def _install_v372() -> bool:
    """Install the post-v368 read-only execution-proof liveness repair.

    v372 does not grant execution readiness. It only makes v367 reuse v366's
    authenticated OpenPositions observation so exact QueryOrders proof can reach
    the existing v328/v346 verifier after a clean redeploy.
    """
    try:
        module = importlib.import_module("bot.runtime_kraken_margin_execution_proof_liveness_v372_patch")
        install = getattr(module, "install_import_hook", None)
        ready = bool(install()) if callable(install) else False
    except Exception as exc:
        ready = False
        LOGGER.exception(
            "KRAKEN_MARGIN_EXECUTION_PROOF_V372_INSTALL_DEFERRED marker=%s error=%s:%s "
            "trading_fail_closed=true execution_proof_fabricated=false safety_gates_bypassed=false",
            MARKER, type(exc).__name__, exc,
        )
    return ready


def _wake_runtime() -> None:
    # Re-run only existing read-only/protection reconciliation surfaces.
    try:
        _v367().recover_execution_proof_once()
    except Exception:
        LOGGER.debug("v368 execution proof wake deferred", exc_info=True)
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        audit = getattr(v281, "audit_once", None)
        if callable(audit):
            audit()
    except Exception:
        LOGGER.debug("v368 coverage wake deferred", exc_info=True)


def install_import_hook() -> bool:
    with _LOCK:
        try:
            if os.environ.get("NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_TRUTH_V367_READY") != "1":
                raise RuntimeError("v367_not_ready")
            software = _patch_software_protection_status()
            coverage = _patch_margin_coverage_broker_scope()
            readers = _patch_account_brokers_authenticated_read_fallback()
            manifest = _register_manifest()
            ready = bool(software and coverage and readers and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_KRAKEN_MARGIN_PROTECTION_AUTHORITY_V368_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true global_execution_ready_unchanged=true safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )

        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_KRAKEN_MARGIN_PROTECTION_AUTHORITY_V368_%s marker=%s ready=%s "
            "exact_broker_scope=true v339_broker_local_reproof=true authenticated_read_fallback=true "
            "global_dispatch_health_not_promoted=true execution_ready_unchanged=true "
            "writer_nonce_killswitch_seak_circuit_fencing_terminal_gates_preserved=true "
            "forced_trade=false forced_exit=false execution_proof_fabricated=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        if ready:
            v372_ready = _install_v372()
            LOGGER.info(
                "KRAKEN_MARGIN_EXECUTION_PROOF_V372_INSTALL_RESULT marker=%s ready=%s "
                "v368_ready_unchanged=true trading_fail_closed_if_false=true",
                MARKER, str(v372_ready).lower(),
            )
            _wake_runtime()
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_exact_scoped_authority"]
