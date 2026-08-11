"""Continuously prove that NIJA's mandatory live guards remain active."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Mapping

logger = logging.getLogger("nija.runtime_guard_audit")
_MARKER = "20260811-runtime-guard-audit-v4"
_LOCK = threading.RLock()
_STARTED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_REQUIRED = (
    "NIJA_SCAN_WRAPPER_HARD_CLAMP_INSTALLED",
    "NIJA_KRAKEN_VERIFIED_COST_BASIS_RECOVERY_INSTALLED",
    "NIJA_DAILY_GAIN_PROFIT_HARVEST_INSTALLED",
    "NIJA_KRAKEN_TPE_MIN_NOTIONAL_ALLOCATION_INSTALLED",
    "NIJA_OKX_FUNDING_WALLET_READINESS_INSTALLED",
    "NIJA_RUNTIME_POST_IMPORT_CONVERGENCE_INSTALLED",
)
_DYNAMIC_WRITER_REQUIRED = (
    "NIJA_WRITER_LEASE_ACQUIRED",
    "NIJA_WRITER_HEARTBEAT_ACTIVE",
)
_DYNAMIC_WRITER_ARM_FLAGS = (
    "NIJA_PREBOT_WRITER_AUTHORITY_READY",
    "NIJA_CANONICAL_WRITER_FIRST_V59_READY",
)


def _ready(env: Mapping[str, str] | None = None) -> tuple[bool, list[str]]:
    source = os.environ if env is None else env
    missing = [
        name
        for name in _REQUIRED
        if str(source.get(name, "") or "").strip().lower() not in _TRUE
    ]
    # These flags are intentionally optional during early startup.  Once they
    # exist, however, an explicit false value is terminal runtime truth and the
    # audit must not keep claiming ready merely because static patch modules
    # remain installed.
    writer_truth = {
        name: str(source.get(name, "") or "").strip().lower()
        for name in _DYNAMIC_WRITER_REQUIRED
    }
    writer_armed = bool(
        all(writer_truth[name] in _TRUE for name in _DYNAMIC_WRITER_REQUIRED)
        or any(
            str(source.get(name, "") or "").strip().lower() in _TRUE
            for name in _DYNAMIC_WRITER_ARM_FLAGS
        )
    )
    if writer_armed:
        missing.extend(
            name
            for name in _DYNAMIC_WRITER_REQUIRED
            if writer_truth[name] not in _TRUE
        )
    if (
        str(source.get("NIJA_RUNTIME_TRADING_STATE", "") or "").strip().upper()
        == "LIVE_ACTIVE"
        and str(source.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "") or "")
        .strip()
        .lower()
        not in _TRUE
    ):
        missing.append("NIJA_RUNTIME_EXECUTION_AUTHORITY")
    if (
        str(source.get("NIJA_RUNTIME_TRADING_STATE", "") or "").strip().upper()
        == "LIVE_ACTIVE"
        and str(source.get("NIJA_BROKER_RUNTIME_PREFLIGHT_READY", "") or "")
        .strip()
        .lower()
        not in _TRUE
    ):
        missing.append("NIJA_BROKER_RUNTIME_PREFLIGHT_READY")
    if (
        str(source.get("NIJA_RUNTIME_TRADING_STATE", "") or "").strip().upper()
        == "LIVE_ACTIVE"
        and str(source.get("NIJA_EXECUTION_LIFECYCLE_CANARY_PASSED", "") or "")
        .strip()
        .lower()
        not in _TRUE
    ):
        missing.append("NIJA_EXECUTION_LIFECYCLE_CANARY_PASSED")
    return not missing, missing


def _emit() -> bool:
    ready, missing = _ready()
    commit = next((str(os.environ.get(name, "") or "").strip() for name in ("RENDER_GIT_COMMIT", "GIT_COMMIT", "SOURCE_VERSION") if str(os.environ.get(name, "") or "").strip()), "unknown")
    emit = logger.info if ready else logger.critical
    emit(
        "RUNTIME_GUARD_AUDIT marker=%s ready=%s commit=%s scan_hard_clamp=%s verified_cost_basis=%s "
        "daily_gain_harvest=%s kraken_min_notional=%s okx_dual_wallet=%s post_import_convergence=%s "
        "authority_policy=%s authority_min_brokers=%s okx_balance_observed=%s okx_funding_status=%s "
        "okx_trading_spendable=%s okx_funding_spendable=%s "
        "writer_lease=%s writer_heartbeat=%s execution_authority=%s runtime_state=%s "
        "broker_runtime_preflight=%s lifecycle_canary=%s "
        "first_blocker=%s missing=%s",
        _MARKER,
        str(ready).lower(),
        commit,
        os.environ.get(_REQUIRED[0], "0"),
        os.environ.get(_REQUIRED[1], "0"),
        os.environ.get(_REQUIRED[2], "0"),
        os.environ.get(_REQUIRED[3], "0"),
        os.environ.get(_REQUIRED[4], "0"),
        os.environ.get(_REQUIRED[5], "0"),
        os.environ.get("NIJA_RUNTIME_AUTHORITY_BROKER_POLICY", "unknown"),
        os.environ.get("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS", "unknown"),
        os.environ.get("NIJA_OKX_BALANCE_OBSERVED", "0"),
        os.environ.get("NIJA_OKX_FUNDING_STATUS", "unobserved"),
        os.environ.get("NIJA_OKX_TRADING_SPENDABLE_QUOTE", "unknown"),
        os.environ.get("NIJA_OKX_FUNDING_SPENDABLE_QUOTE", "unknown"),
        os.environ.get("NIJA_WRITER_LEASE_ACQUIRED", "uninitialized"),
        os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE", "uninitialized"),
        os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "uninitialized"),
        os.environ.get("NIJA_RUNTIME_TRADING_STATE", "uninitialized"),
        os.environ.get("NIJA_BROKER_RUNTIME_PREFLIGHT_READY", "uninitialized"),
        os.environ.get("NIJA_EXECUTION_LIFECYCLE_CANARY_PASSED", "uninitialized"),
        missing[0] if missing else "none",
        ",".join(missing) or "none",
    )
    dynamic_writer_missing = any(name in missing for name in _DYNAMIC_WRITER_REQUIRED)
    if not ready and (
        dynamic_writer_missing
        or str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).upper()
        == "LIVE_ACTIVE"
    ):
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
        logger.critical("RUNTIME_GUARD_AUDIT_FAIL_CLOSED marker=%s missing=%s", _MARKER, ",".join(missing))
    return ready


def _watchdog() -> None:
    interval = max(15.0, float(os.environ.get("NIJA_RUNTIME_GUARD_AUDIT_INTERVAL_S", "60") or 60))
    while True:
        _emit()
        time.sleep(interval)


def install() -> bool:
    global _STARTED
    with _LOCK:
        if not _emit():
            raise RuntimeError("mandatory_runtime_guards_not_ready")
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="RuntimeGuardAudit", daemon=True).start()
        os.environ["NIJA_RUNTIME_GUARD_AUDIT_INSTALLED"] = "1"
        logger.info("RUNTIME_GUARD_AUDIT_INSTALLED marker=%s interval_s=%s", _MARKER, os.environ.get("NIJA_RUNTIME_GUARD_AUDIT_INTERVAL_S", "60"))
        return True


__all__ = ["install", "_ready", "_emit"]
