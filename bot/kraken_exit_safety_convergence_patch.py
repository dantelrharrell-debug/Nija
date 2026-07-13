"""Final convergence for account-local Kraken exits.

Loaded after ``kraken_all_account_exit_runtime_patch``. It supplies explicit
pipeline exit context, keeps recovery cycles position-management-only, preserves
legacy non-Kraken exit monitoring, and allows a private-authenticated reduce-only
margin close during low/critical margin health. It never bypasses Kraken
permission or private API failures.
"""

from __future__ import annotations

import builtins
import logging
import sys
import threading
from contextvars import ContextVar
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.kraken_exit_safety_convergence")
_MARKER = "20260713-kraken-exit-safety-v1"
_ORIGINAL_IMPORT = None
_LOCK = threading.RLock()
_PATCHED: set[tuple[str, int]] = set()
_EXIT_MANAGEMENT_SCOPE: ContextVar[bool] = ContextVar("nija_exit_management_scope", default=False)


def _is_kraken(broker: Any) -> bool:
    if broker is None:
        return False
    values = (
        type(broker).__name__,
        getattr(broker, "NAME", ""),
        getattr(getattr(broker, "broker_type", None), "value", getattr(broker, "broker_type", "")),
    )
    return any("kraken" in str(value or "").lower() for value in values)


def _canonical_account_id(identity: Any, broker: Any = None) -> str:
    text = str(identity or "").strip().lower().replace("/", ":")
    parts = [part for part in text.split(":") if part]
    if parts:
        if parts[0] == "platform":
            return "platform"
        if parts[0] == "user" and len(parts) >= 2:
            return parts[1]
    if text.startswith("user_"):
        text = text[5:]
    if text.endswith("_kraken"):
        text = text[:-7]
    if text and text not in {"kraken", "none", "default"}:
        return text
    for attr in ("account_identifier", "account_id", "user_id", "owner_id"):
        value = str(getattr(broker, attr, "") or "").strip().lower()
        if value.startswith("user:"):
            return value.split(":", 1)[1]
        if value.startswith("user_"):
            value = value[5:]
        if value.endswith("_kraken"):
            value = value[:-7]
        if value and value not in {"kraken", "none", "default"}:
            return "platform" if value.startswith("platform") else value
    return "platform"


def _patch_all_account_exit(module: ModuleType) -> bool:
    current = getattr(module, "_submit_exit", None)
    if not callable(current) or getattr(current, "_nija_explicit_exit_context_v1", False):
        return False

    def submit_exit(
        broker: Any,
        account: str,
        pair: str,
        quantity: float,
        reason: str,
    ) -> Mapping[str, Any]:
        account_id = _canonical_account_id(account, broker)
        try:
            from bot.pipeline_order_submitter import submit_market_order_via_pipeline
            result = submit_market_order_via_pipeline(
                broker=broker,
                symbol=pair,
                side="sell",
                quantity=quantity,
                size_type="base",
                strategy=f"KrakenAccountExit:{reason}",
                intent_type="exit",
                account_id_override=account_id,
                reduce_only_override=None,
                position_effect="close",
                metadata_override={
                    "closing_position": True,
                    "exit_reason": reason,
                    "account_exit_supervisor": True,
                    "supervisor_identity": account,
                },
            )
            logger.critical(
                "KRAKEN_EXIT_ACCOUNT_CONTEXT marker=%s supervisor=%s account_id=%s pair=%s reason=%s",
                _MARKER, account, account_id, pair, reason,
            )
            return result if isinstance(result, Mapping) else {
                "status": "error", "error": str(result),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    submit_exit._nija_explicit_exit_context_v1 = True  # type: ignore[attr-defined]
    submit_exit.__wrapped__ = current  # type: ignore[attr-defined]
    module._submit_exit = submit_exit
    logger.warning("KRAKEN_EXPLICIT_EXIT_CONTEXT_PATCHED marker=%s", _MARKER)
    return True


def _patch_recovery_scope(module: ModuleType) -> bool:
    current = getattr(module, "_adopt_and_manage", None)
    if not callable(current) or getattr(current, "_nija_exit_management_scope_v1", False):
        return False

    @wraps(current)
    def adopt_and_manage(trader: Any, identity: str, broker: Any):
        token = _EXIT_MANAGEMENT_SCOPE.set(True)
        try:
            logger.info(
                "EXIT_ONLY_MANAGEMENT_SCOPE_ENTER marker=%s account=%s",
                _MARKER, identity,
            )
            return current(trader, identity, broker)
        finally:
            _EXIT_MANAGEMENT_SCOPE.reset(token)

    adopt_and_manage._nija_exit_management_scope_v1 = True  # type: ignore[attr-defined]
    module._adopt_and_manage = adopt_and_manage
    logger.warning("ACCOUNT_EXIT_MANAGEMENT_SCOPE_PATCHED marker=%s", _MARKER)
    return True


def _patch_trade_cycle_truth(module: ModuleType) -> bool:
    current = getattr(module, "_truthy", None)
    if not callable(current) or getattr(current, "_nija_exit_scope_truth_v1", False):
        return False

    @wraps(current)
    def truthy(name: str, default: bool = False) -> bool:
        if _EXIT_MANAGEMENT_SCOPE.get() and name == "NIJA_INDEPENDENT_USER_TRADING":
            logger.info(
                "EXIT_ONLY_USER_MODE_PRESERVED marker=%s auto_promotion_blocked=true",
                _MARKER,
            )
            return False
        return bool(current(name, default))

    truthy._nija_exit_scope_truth_v1 = True  # type: ignore[attr-defined]
    module._truthy = truthy
    logger.warning("TRADE_CYCLE_EXIT_SCOPE_PROMOTION_GUARD_PATCHED marker=%s", _MARKER)
    return True


def _patch_margin_engine(module: ModuleType) -> bool:
    cls = getattr(module, "KrakenMarginEngine", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "is_margin_trade_allowed", None)
    if not callable(current) or getattr(current, "_nija_reduce_only_health_escape_v1", False):
        return False

    @wraps(current)
    def is_margin_trade_allowed(
        self: Any,
        *,
        is_reducing: bool = False,
        adapter: Any = None,
    ) -> tuple[bool, str]:
        allowed, reason = current(self, is_reducing=is_reducing, adapter=adapter)
        reason_text = str(reason or "")
        if (
            is_reducing
            and not allowed
            and (
                reason_text.startswith("critical_margin:")
                or reason_text.startswith("maintenance_low:")
            )
        ):
            logger.critical(
                "KRAKEN_MARGIN_RISK_REDUCING_EXIT_ALLOWED marker=%s account=%s reason=%s",
                _MARKER, getattr(self, "account_id", "default"), reason_text,
            )
            return True, f"risk_reducing_exit:{reason_text}"
        return allowed, reason

    is_margin_trade_allowed._nija_reduce_only_health_escape_v1 = True  # type: ignore[attr-defined]
    cls.is_margin_trade_allowed = is_margin_trade_allowed
    logger.warning("KRAKEN_MARGIN_REDUCE_ONLY_HEALTH_ESCAPE_PATCHED marker=%s", _MARKER)
    return True


def _patch_legacy_auto_exit(module: ModuleType) -> bool:
    changed = False
    starter = getattr(module, "_start_monitor", None)
    if callable(starter) and getattr(starter, "_nija_account_local_disabled_v1", False):
        original = getattr(starter, "__wrapped__", None)
        if callable(original):
            module._start_monitor = original
            changed = True
            logger.warning("NON_KRAKEN_GLOBAL_AUTO_EXIT_RESTORED marker=%s", _MARKER)

    current_scan = getattr(module, "_scan_once", None)
    if callable(current_scan) and not getattr(current_scan, "_nija_kraken_account_local_owner_v1", False):
        @wraps(current_scan)
        def scan_once(engine: Any) -> int:
            broker = getattr(engine, "broker_client", None)
            if _is_kraken(broker):
                logger.debug(
                    "GLOBAL_KRAKEN_AUTO_EXIT_SCAN_SKIPPED marker=%s reason=account_local_supervisor_owns_scan",
                    _MARKER,
                )
                return 0
            return int(current_scan(engine) or 0)

        scan_once._nija_kraken_account_local_owner_v1 = True  # type: ignore[attr-defined]
        module._scan_once = scan_once
        for candidate in ("bot.execution_engine", "execution_engine"):
            loaded = sys.modules.get(candidate)
            cls = getattr(loaded, "ExecutionEngine", None) if isinstance(loaded, ModuleType) else None
            if isinstance(cls, type):
                cls.scan_stop_loss_take_profit_once = scan_once
                break
        changed = True
        logger.warning("KRAKEN_GLOBAL_AUTO_EXIT_SCAN_REDIRECTED marker=%s", _MARKER)
    return changed


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    if key in _PATCHED:
        return True
    name = str(getattr(module, "__name__", ""))
    changed = False
    if name.endswith("kraken_all_account_exit_runtime_patch"):
        changed = _patch_all_account_exit(module) or changed
    if name.endswith("account_exit_management_recovery_patch"):
        changed = _patch_recovery_scope(module) or changed
    if name.endswith("trade_cycle_convergence_repair_patch"):
        changed = _patch_trade_cycle_truth(module) or changed
    if name.endswith("kraken_margin_engine"):
        changed = _patch_margin_engine(module) or changed
    if name.endswith("auto_exit_sl_tp_runtime_patch"):
        changed = _patch_legacy_auto_exit(module) or changed
    if changed:
        _PATCHED.add(key)
    return changed


def _patch_loaded() -> None:
    for module in tuple(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception:
                continue


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _patch_loaded()
    with _LOCK:
        if _ORIGINAL_IMPORT is not None:
            return
        _ORIGINAL_IMPORT = builtins.__import__
        local = threading.local()

        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
            if getattr(local, "active", False):
                return module
            local.active = True
            try:
                _patch_loaded()
            finally:
                local.active = False
            return module

        builtins.__import__ = guarded_import  # type: ignore[assignment]
    _patch_loaded()
    logger.critical("KRAKEN_EXIT_SAFETY_CONVERGENCE_INSTALLED marker=%s", _MARKER)


__all__ = [
    "install_import_hook",
    "_canonical_account_id",
    "_patch_all_account_exit",
    "_patch_recovery_scope",
    "_patch_trade_cycle_truth",
    "_patch_margin_engine",
    "_patch_legacy_auto_exit",
]
