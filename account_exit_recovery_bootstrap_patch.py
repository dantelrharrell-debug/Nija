"""Bootstrap the account-local exit recovery before LIVE_ACTIVE convergence.

The account exit-management recovery layer patches IndependentBrokerTrader, but its
supervisor originally started only from ``start_independent_trading``.  In a
fail-closed startup, that method is not reached until CapitalAuthority reports at
least one valid broker.  When broker reconnection itself depends on the supervisor,
startup deadlocks at ``LIVE_PENDING_CONFIRMATION`` with ``valid_brokers=0``.

This bridge patches ``IndependentBrokerTrader.__init__`` and schedules the existing
recovery supervisor immediately after construction.  It also refreshes
CapitalAuthority after each recovery pass.  It does not grant execution authority,
mark brokers connected, fabricate balances, bypass writer lineage, or submit orders.
"""

from __future__ import annotations

import gc
import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Mapping, Optional

logger = logging.getLogger("nija.account_exit_recovery_bootstrap")

_MARKER = "20260711m"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_CLASS_PATCHED_ATTR = "_nija_account_exit_bootstrap_20260711m"
_RETRY_PATCHED_ATTR = "_nija_account_exit_retry_capital_refresh_20260711m"
_INSTANCE_STARTED_ATTR = "_nija_account_exit_bootstrap_started_20260711m"
_INSTALL_LOCK = threading.RLock()
_WATCHDOG_STARTED = False


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _load_recovery_module() -> Optional[ModuleType]:
    for name in (
        "account_exit_management_recovery_patch",
        "bot.account_exit_management_recovery_patch",
    ):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
        try:
            imported = importlib.import_module(name)
            if isinstance(imported, ModuleType):
                return imported
        except Exception:
            continue
    return None


def _refresh_capital_authority(trader: Any, source: str) -> Mapping[str, Any]:
    manager = getattr(trader, "multi_account_manager", None)
    refresher = getattr(manager, "refresh_capital_authority", None)
    if not callable(refresher):
        return {}

    try:
        try:
            result = refresher(trigger=f"account_exit_recovery:{source}")
        except TypeError:
            result = refresher()
        payload = result if isinstance(result, Mapping) else {}
        logger.warning(
            "ACCOUNT_EXIT_RECOVERY_CAPITAL_REFRESH marker=%s source=%s "
            "ready=%s total=%s valid_brokers=%s",
            _MARKER,
            source,
            payload.get("ready"),
            payload.get("total_capital", payload.get("total")),
            payload.get("valid_brokers"),
        )
        return payload
    except Exception as exc:
        logger.warning(
            "ACCOUNT_EXIT_RECOVERY_CAPITAL_REFRESH_FAILED marker=%s source=%s error=%s",
            _MARKER,
            source,
            exc,
        )
        return {}


def _patch_recovery_retry(recovery: ModuleType) -> bool:
    original = getattr(recovery, "_retry_all_accounts", None)
    if not callable(original):
        return False
    if getattr(original, _RETRY_PATCHED_ATTR, False):
        return True

    def _retry_all_accounts(trader: Any) -> Any:
        result = original(trader)
        _refresh_capital_authority(trader, "retry_all_accounts")
        return result

    setattr(_retry_all_accounts, "__wrapped__", original)
    setattr(_retry_all_accounts, _RETRY_PATCHED_ATTR, True)
    recovery._retry_all_accounts = _retry_all_accounts
    logger.warning("ACCOUNT_EXIT_RECOVERY_CAPITAL_REFRESH_PATCHED marker=%s", _MARKER)
    return True


def _start_supervisor_async(trader: Any, source: str) -> bool:
    if trader is None or not _truthy("NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_ENABLED", "true"):
        return False
    if bool(getattr(trader, _INSTANCE_STARTED_ATTR, False)):
        return False
    setattr(trader, _INSTANCE_STARTED_ATTR, True)

    def _runner() -> None:
        recovery = _load_recovery_module()
        starter = getattr(recovery, "_start_supervisor", None) if recovery is not None else None
        if not callable(starter):
            setattr(trader, _INSTANCE_STARTED_ATTR, False)
            logger.warning(
                "ACCOUNT_EXIT_RECOVERY_EARLY_START_FAILED marker=%s source=%s reason=starter_missing",
                _MARKER,
                source,
            )
            return
        try:
            starter(trader)
            logger.critical(
                "ACCOUNT_EXIT_RECOVERY_EARLY_STARTED marker=%s source=%s "
                "entries_authority_unchanged=true",
                _MARKER,
                source,
            )
        except Exception as exc:
            setattr(trader, _INSTANCE_STARTED_ATTR, False)
            logger.exception(
                "ACCOUNT_EXIT_RECOVERY_EARLY_START_FAILED marker=%s source=%s error=%s",
                _MARKER,
                source,
                exc,
            )

    threading.Thread(
        target=_runner,
        name="AccountExitRecoveryEarlyBootstrap",
        daemon=True,
    ).start()
    return True


def _patch_class(cls: type) -> bool:
    if getattr(cls, _CLASS_PATCHED_ATTR, False):
        return True

    original_init = getattr(cls, "__init__", None)
    if not callable(original_init):
        return False

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        _start_supervisor_async(self, "independent_trader_init")

    setattr(__init__, "__wrapped__", original_init)
    cls.__init__ = __init__
    setattr(cls, _CLASS_PATCHED_ATTR, True)
    logger.warning(
        "ACCOUNT_EXIT_RECOVERY_BOOTSTRAP_CLASS_PATCHED marker=%s class=%s",
        _MARKER,
        cls.__name__,
    )

    try:
        for obj in gc.get_objects():
            try:
                if isinstance(obj, cls):
                    _start_supervisor_async(obj, "existing_instance")
            except Exception:
                continue
    except Exception as exc:
        logger.debug("ACCOUNT_EXIT_RECOVERY_EXISTING_SCAN_SKIPPED error=%s", exc)
    return True


def _patch_loaded() -> bool:
    patched = False
    recovery = _load_recovery_module()
    if recovery is not None:
        patched = _patch_recovery_retry(recovery) or patched

    for name in ("bot.independent_broker_trader", "independent_broker_trader"):
        module = sys.modules.get(name)
        cls = getattr(module, "IndependentBrokerTrader", None) if isinstance(module, ModuleType) else None
        if isinstance(cls, type):
            patched = _patch_class(cls) or patched
    return patched


def _watchdog() -> None:
    timeout_s = max(
        30.0,
        float(os.environ.get("NIJA_ACCOUNT_EXIT_BOOTSTRAP_PATCH_TIMEOUT_S", "180") or 180.0),
    )
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if _patch_loaded():
                return
        except Exception as exc:
            logger.debug("ACCOUNT_EXIT_RECOVERY_BOOTSTRAP_PATCH_RETRY error=%s", exc)
        time.sleep(0.1)
    logger.critical(
        "ACCOUNT_EXIT_RECOVERY_BOOTSTRAP_PATCH_TIMEOUT marker=%s timeout_s=%.1f",
        _MARKER,
        timeout_s,
    )


def install_import_hook() -> None:
    global _WATCHDOG_STARTED
    with _INSTALL_LOCK:
        os.environ.setdefault("NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_ENABLED", "true")
        os.environ.setdefault("NIJA_ACCOUNT_EXIT_MANAGEMENT_INTERVAL_S", "15")
        os.environ.setdefault("NIJA_ACCOUNT_EXIT_BOOTSTRAP_PATCH_TIMEOUT_S", "180")
        _patch_loaded()
        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            threading.Thread(
                target=_watchdog,
                name="account-exit-recovery-bootstrap-watchdog",
                daemon=True,
            ).start()
        logger.warning(
            "ACCOUNT_EXIT_RECOVERY_BOOTSTRAP_INSTALL_REQUESTED marker=%s",
            _MARKER,
        )


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_patch_class",
    "_patch_loaded",
    "_patch_recovery_retry",
    "_refresh_capital_authority",
    "_start_supervisor_async",
]
