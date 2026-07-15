"""Continuously prove that NIJA's mandatory live guards remain active."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Mapping

logger = logging.getLogger("nija.runtime_guard_audit")
_MARKER = "20260715-runtime-guard-audit-v1"
_LOCK = threading.RLock()
_STARTED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_REQUIRED = (
    "NIJA_SCAN_WRAPPER_HARD_CLAMP_INSTALLED",
    "NIJA_KRAKEN_VERIFIED_COST_BASIS_RECOVERY_INSTALLED",
    "NIJA_DAILY_GAIN_PROFIT_HARVEST_INSTALLED",
    "NIJA_KRAKEN_TPE_MIN_NOTIONAL_ALLOCATION_INSTALLED",
)


def _ready(env: Mapping[str, str] | None = None) -> tuple[bool, list[str]]:
    source = os.environ if env is None else env
    missing = [name for name in _REQUIRED if str(source.get(name, "") or "").strip().lower() not in _TRUE]
    return not missing, missing


def _emit() -> bool:
    ready, missing = _ready()
    commit = next((str(os.environ.get(name, "") or "").strip() for name in ("RENDER_GIT_COMMIT", "GIT_COMMIT", "SOURCE_VERSION") if str(os.environ.get(name, "") or "").strip()), "unknown")
    logger.critical(
        "RUNTIME_GUARD_AUDIT marker=%s ready=%s commit=%s scan_hard_clamp=%s verified_cost_basis=%s daily_gain_harvest=%s kraken_min_notional=%s missing=%s",
        _MARKER,
        str(ready).lower(),
        commit,
        os.environ.get(_REQUIRED[0], "0"),
        os.environ.get(_REQUIRED[1], "0"),
        os.environ.get(_REQUIRED[2], "0"),
        os.environ.get(_REQUIRED[3], "0"),
        ",".join(missing) or "none",
    )
    if not ready and str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).upper() == "LIVE_ACTIVE":
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
        logger.critical("RUNTIME_GUARD_AUDIT_INSTALLED marker=%s interval_s=%s", _MARKER, os.environ.get("NIJA_RUNTIME_GUARD_AUDIT_INTERVAL_S", "60"))
        return True


__all__ = ["install", "_ready", "_emit"]
