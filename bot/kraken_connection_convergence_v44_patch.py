"""NIJA Kraken connection convergence v44.

Production after v42 showed Kraken credentials present and historical capital
available while the canonical platform broker remained ``connected=False``.
The authenticated recovery in canonical_broker_startup_convergence_v24 already
performs the correct real broker.connect()/supervisor path, but its one-shot
``_KRAKEN_RECOVERY_STARTED`` guard remains latched after a successful recovery.
A later disconnect can therefore leave Kraken permanently offline because every
subsequent trigger sees recovery as already started.

v44 adds a small writer-scoped watchdog around that existing recovery path.  It
never marks Kraken connected and never fabricates authentication.  It rearms the
canonical recovery only when all of these are true:

* Kraken credentials are configured and not explicitly disabled;
* verified writer lineage is present;
* the canonical Kraken broker exists and is actually ``connected=False``;
* the previous authenticated recovery had declared READY, proving the guard is
  a stale success latch rather than an active in-flight attempt.

If recovery is not currently started at all, the watchdog may invoke the
canonical v24 recovery directly.  Permanent-auth failures remain latched by the
existing reconnect supervisor and no execution/readiness gate is bypassed.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Optional

LOGGER = logging.getLogger("nija.kraken_connection_convergence_v44")
MARKER = "20260807-kraken-connection-convergence-v44"

_LOCK = threading.RLock()
_STOP = threading.Event()
_WATCHDOG_STARTED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

_V24_NAMES = (
    "nija_canonical_broker_startup_convergence_v24_prebot",
    "bot.canonical_broker_startup_convergence_v24",
    "canonical_broker_startup_convergence_v24",
)


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _v24() -> Optional[ModuleType]:
    for name in _V24_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    for name in ("bot.canonical_broker_startup_convergence_v24",):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        if isinstance(module, ModuleType):
            return module
    return None


def _manager() -> Any:
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        getter = getattr(module, "get_multi_account_broker_manager", None) if module else None
        if callable(getter):
            try:
                return getter()
            except Exception:
                pass
    try:
        module = importlib.import_module("bot.multi_account_broker_manager")
        getter = getattr(module, "get_multi_account_broker_manager", None)
        if callable(getter):
            return getter()
    except Exception:
        pass
    return None


def _canonical_kraken(manager: Any) -> Any:
    if manager is None:
        return None
    try:
        broker_module = importlib.import_module("bot.broker_manager")
    except Exception:
        return None
    broker_type = getattr(getattr(broker_module, "BrokerType", None), "KRAKEN", None)
    if broker_type is not None:
        broker = getattr(manager, "_platform_brokers", {}).get(broker_type)
        if broker is not None:
            return broker
    getter = getattr(broker_module, "get_platform_broker", None)
    if callable(getter):
        for key in ("kraken", broker_type):
            if key is None:
                continue
            try:
                broker = getter(key)
            except Exception:
                continue
            if broker is not None:
                return broker
    return None


def _lineage_ready(v24: ModuleType) -> tuple[bool, str]:
    probe = getattr(v24, "_writer_lineage", None)
    if not callable(probe):
        return False, "writer_lineage_probe_unavailable"
    try:
        ready, reason = probe()
        return bool(ready), str(reason or "")
    except Exception as exc:
        return False, f"writer_lineage_error:{type(exc).__name__}:{exc}"


def _credentials_ready(v24: ModuleType) -> bool:
    probe = getattr(v24, "_kraken_credentials_configured", None)
    if not callable(probe):
        return False
    try:
        return bool(probe())
    except Exception:
        return False


def _permanent_failure_latched() -> bool:
    for name in ("bot.kraken_reconnect_supervisor", "kraken_reconnect_supervisor"):
        module = sys.modules.get(name)
        probe = getattr(module, "is_permanent_failure_latched", None) if module else None
        if callable(probe):
            try:
                return bool(probe())
            except Exception:
                return True
    try:
        module = importlib.import_module("bot.kraken_reconnect_supervisor")
        probe = getattr(module, "is_permanent_failure_latched", None)
        if callable(probe):
            return bool(probe())
    except ImportError:
        return False
    except Exception:
        return True
    return False


def _rearm_if_stale_success(v24: ModuleType, broker: Any) -> bool:
    """Clear only the stale post-success guard; never interrupt in-flight recovery."""
    if broker is None or bool(getattr(broker, "connected", False)):
        return False
    if not bool(getattr(v24, "_KRAKEN_RECOVERY_STARTED", False)):
        return False
    if not _truthy("NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"):
        return False
    with _LOCK:
        if bool(getattr(broker, "connected", False)):
            return False
        if not bool(getattr(v24, "_KRAKEN_RECOVERY_STARTED", False)):
            return False
        if not _truthy("NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"):
            return False
        setattr(v24, "_KRAKEN_RECOVERY_STARTED", False)
        os.environ["NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"] = "0"
    LOGGER.critical(
        "KRAKEN_V44_STALE_SUCCESS_REARMED marker=%s connected=false previous_ready=true",
        MARKER,
    )
    return True


def reconcile_once() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "action": "none",
        "reason": "uninitialized",
        "connected": False,
    }
    v24 = _v24()
    if v24 is None:
        result["reason"] = "v24_unavailable"
        return result
    if not _credentials_ready(v24):
        result["reason"] = "credentials_not_configured_or_disabled"
        return result
    lineage_ok, lineage_reason = _lineage_ready(v24)
    if not lineage_ok:
        result["reason"] = lineage_reason or "writer_lineage_not_ready"
        return result
    if _permanent_failure_latched():
        result["reason"] = "permanent_auth_or_config_failure_latched"
        return result

    manager = _manager()
    if manager is None:
        result["reason"] = "canonical_manager_unavailable"
        return result
    broker = _canonical_kraken(manager)
    if broker is None:
        prepare = getattr(v24, "_prepare_canonical_manager", None)
        if callable(prepare):
            try:
                manager = prepare()
                broker = _canonical_kraken(manager)
            except Exception as exc:
                result["reason"] = f"canonical_prepare_failed:{type(exc).__name__}:{exc}"
                return result
    if broker is None:
        result["reason"] = "canonical_kraken_unavailable"
        return result

    connected = bool(getattr(broker, "connected", False))
    result["connected"] = connected
    if connected:
        result.update(ok=True, action="none", reason="already_connected")
        return result

    rearmed = _rearm_if_stale_success(v24, broker)
    starter = getattr(v24, "_start_kraken_authenticated_recovery", None)
    if not callable(starter):
        result["reason"] = "authenticated_recovery_unavailable"
        return result

    already_started = bool(getattr(v24, "_KRAKEN_RECOVERY_STARTED", False))
    if already_started and not rearmed:
        result["reason"] = "authenticated_recovery_in_flight"
        result["action"] = "observe"
        return result

    try:
        started = bool(starter(manager))
    except Exception as exc:
        result["reason"] = f"authenticated_recovery_start_failed:{type(exc).__name__}:{exc}"
        return result

    if started:
        result.update(
            ok=True,
            action="recovery_started",
            reason="stale_success_rearmed" if rearmed else "disconnected_recovery_started",
        )
        LOGGER.warning(
            "KRAKEN_V44_RECOVERY_STARTED marker=%s reason=%s writer_lineage=%s",
            MARKER,
            result["reason"],
            lineage_reason,
        )
    else:
        result["reason"] = "authenticated_recovery_not_started"
    return result


def _watchdog_loop() -> None:
    try:
        interval = max(
            5.0,
            float(os.environ.get("NIJA_KRAKEN_CONNECTION_WATCHDOG_INTERVAL_S", "15") or "15"),
        )
    except (TypeError, ValueError):
        interval = 15.0
    last_signature = ""
    while not _STOP.wait(interval):
        try:
            state = reconcile_once()
            signature = f"{state.get('action')}:{state.get('reason')}:{state.get('connected')}"
            if signature != last_signature:
                log = LOGGER.info if state.get("connected") else LOGGER.warning
                log(
                    "KRAKEN_V44_WATCHDOG marker=%s connected=%s action=%s reason=%s",
                    MARKER,
                    str(bool(state.get("connected"))).lower(),
                    state.get("action"),
                    state.get("reason"),
                )
                last_signature = signature
        except Exception as exc:
            LOGGER.warning(
                "KRAKEN_V44_WATCHDOG_ERROR marker=%s error=%s:%s",
                MARKER,
                type(exc).__name__,
                exc,
            )


def install() -> bool:
    global _WATCHDOG_STARTED
    with _LOCK:
        if _WATCHDOG_STARTED:
            os.environ["NIJA_KRAKEN_CONNECTION_CONVERGENCE_V44_INSTALLED"] = "1"
            return True
        _WATCHDOG_STARTED = True
        os.environ["NIJA_KRAKEN_CONNECTION_CONVERGENCE_V44_INSTALLED"] = "1"
        thread = threading.Thread(
            target=_watchdog_loop,
            name="KrakenConnectionConvergenceV44",
            daemon=True,
        )
        thread.start()
    # Run one reconciliation immediately so startup does not wait one interval.
    try:
        reconcile_once()
    except Exception:
        LOGGER.exception("KRAKEN_V44_INITIAL_RECONCILE_FAILED marker=%s", MARKER)
    LOGGER.critical(
        "KRAKEN_CONNECTION_CONVERGENCE_V44_INSTALLED marker=%s fail_closed=true fabricates_connected=false",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_rearm_if_stale_success",
]
