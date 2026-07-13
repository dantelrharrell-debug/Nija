"""Final convergence repair for NIJA's shared live trading cycle.

The runtime uses one TradingStrategy/APEX object from multiple platform and user
threads. This patch serializes that mutable context, supplies broker-scoped
balance authority, repairs user position-adoption verification, and emits one
terminal CYCLE_OUTCOME record for every cycle without bypassing risk controls or
exchange constraints.
"""

from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.trade_cycle_convergence_repair")

_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED_MODULES: set[tuple[str, int]] = set()
_REGISTRY_GUARD = threading.Lock()
_TLS = threading.local()
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}
_MISSING = object()

_OUTCOME_PRIORITY = {
    "NO_SIGNAL": 10,
    "NO_MARKETS_OR_DATA": 20,
    "MARKET_CLOSED": 25,
    "ENTRY_BLOCKED": 30,
    "PENDING_ORDER_BLOCKED": 35,
    "MAX_POSITIONS_REACHED": 40,
    "INSUFFICIENT_CASH": 45,
    "RISK_REJECTED": 50,
    "EXIT_EXECUTED": 70,
    "ORDER_FAILED": 80,
    "SCAN_ERROR": 90,
    "CYCLE_ERROR": 95,
    "ORDER_SUBMITTED": 100,
}
_BALANCE_ATTRS = (
    "_nija_last_account_balance_usd",
    "_nija_cycle_balance_usd",
    "last_account_balance",
    "_last_account_balance",
    "available_balance",
    "usd_balance",
    "cash_balance",
    "balance",
)
_BALANCE_KEYS = (
    "total_balance",
    "balance",
    "usd_balance",
    "available_balance",
    "available_cash",
    "cash",
    "equity",
    "portfolio_value",
)


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else str(raw).strip().lower() in _TRUTHY


def _safe_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        for key in _BALANCE_KEYS:
            if key in value:
                parsed = _safe_float(value.get(key))
                if parsed is not None:
                    return parsed
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 and parsed == parsed else None


def _cache_balance(broker: Any, raw: Any) -> Optional[float]:
    balance = _safe_float(raw)
    if broker is not None and balance is not None:
        try:
            setattr(broker, "_nija_last_account_balance_usd", balance)
            setattr(broker, "_nija_last_account_balance_at", time.time())
        except Exception:
            pass
    return balance


def _cached_balance(broker: Any) -> Optional[float]:
    if broker is None:
        return None
    for attr in _BALANCE_ATTRS:
        try:
            parsed = _safe_float(getattr(broker, attr, None))
        except Exception:
            parsed = None
        if parsed is not None:
            return parsed
    return None


def _broker_label(broker: Any) -> str:
    if broker is None:
        return "unknown"
    account = ""
    venue = ""
    for attr in ("account_id", "_account_id", "user_id", "account_name", "label"):
        value = getattr(broker, attr, None)
        if value:
            account = str(value).strip()
            break
    for attr in ("broker_name", "exchange_name", "name", "exchange", "venue"):
        value = getattr(broker, attr, None)
        if value:
            venue = str(getattr(value, "value", value)).strip()
            break
    if not venue:
        venue = type(broker).__name__.replace("Broker", "").strip() or "broker"
    return f"{account or 'platform_or_unlabeled'}:{venue}".lower().replace(" ", "_")


def _context() -> Optional[dict[str, Any]]:
    value = getattr(_TLS, "cycle_context", None)
    return value if isinstance(value, dict) else None


def _set_outcome(outcome: str, **details: Any) -> None:
    context = _context()
    if context is None:
        return
    current = str(context.get("outcome") or "NO_SIGNAL")
    if _OUTCOME_PRIORITY.get(outcome, 0) >= _OUTCOME_PRIORITY.get(current, 0):
        context["outcome"] = outcome
    if details:
        context.setdefault("details", {}).update(details)


def _reason_text(result: Any) -> str:
    names = (
        "reason",
        "reasons",
        "block_reason",
        "block_reasons",
        "entry_block_reason",
        "last_block_reason",
        "diagnostics",
        "message",
    )
    values: list[str] = []
    if isinstance(result, dict):
        values.extend(str(result.get(name)) for name in names if name in result)
    else:
        for name in names:
            value = getattr(result, name, None)
            if value:
                values.append(str(value))
    return " ".join(values).lower()


def classify_scan_result(result: Any) -> str:
    """Map a core-loop result to one stable terminal outcome."""
    reason = _reason_text(result)
    if any(token in reason for token in ("max position", "position cap", "no slot")):
        return "MAX_POSITIONS_REACHED"
    if any(token in reason for token in ("insufficient cash", "insufficient balance", "not enough cash", "underfunded")):
        return "INSUFFICIENT_CASH"
    if "risk" in reason and any(token in reason for token in ("reject", "block", "veto", "denied")):
        return "RISK_REJECTED"
    if any(token in reason for token in ("pending order", "symbol lock", "order lock")):
        return "PENDING_ORDER_BLOCKED"
    if "market closed" in reason:
        return "MARKET_CLOSED"

    def count(name: str) -> int:
        try:
            value = result.get(name, 0) if isinstance(result, dict) else getattr(result, name, 0)
            return int(value or 0)
        except Exception:
            return 0

    if count("entries_taken") > 0:
        return "ORDER_SUBMITTED"
    if count("exits_taken") > 0:
        return "EXIT_EXECUTED"
    if count("symbols_scored") <= 0:
        return "NO_MARKETS_OR_DATA"
    if count("entries_blocked") > 0:
        return "ENTRY_BLOCKED"
    return "NO_SIGNAL"


def _execution_succeeded(result: Any) -> bool:
    if isinstance(result, dict):
        for key in ("success", "submitted", "accepted", "filled"):
            if key in result:
                return bool(result.get(key))
        return bool(result.get("order_id") or result.get("id") or result.get("txid"))
    return bool(result)


def _patch_balance_method(cls: type) -> None:
    original = getattr(cls, "get_account_balance", None)
    if not callable(original) or getattr(original, "_nija_balance_cache_patch", False):
        return

    def get_account_balance(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        _cache_balance(self, result)
        return result

    get_account_balance._nija_balance_cache_patch = True  # type: ignore[attr-defined]
    setattr(cls, "get_account_balance", get_account_balance)


def _patch_broker_module(module: ModuleType) -> None:
    for value in tuple(vars(module).values()):
        if isinstance(value, type) and "broker" in value.__name__.lower():
            _patch_balance_method(value)


def _get_cycle_locks(owner: Any) -> tuple[threading.Lock, threading.Lock]:
    with _REGISTRY_GUARD:
        cycle_lock = getattr(owner, "_nija_cycle_convergence_lock", None)
        if cycle_lock is None:
            cycle_lock = threading.Lock()
            setattr(owner, "_nija_cycle_convergence_lock", cycle_lock)
        state_lock = getattr(owner, "_nija_cycle_convergence_state_lock", None)
        if state_lock is None:
            state_lock = threading.Lock()
            setattr(owner, "_nija_cycle_convergence_state_lock", state_lock)
    return cycle_lock, state_lock


def _set_apex_broker(apex: Any, broker: Any) -> None:
    if apex is None:
        return
    updater = getattr(apex, "update_broker_client", None)
    if callable(updater):
        try:
            updater(broker)
            return
        except Exception as exc:
            logger.warning("APEX_BROKER_CONTEXT_UPDATE_FAILED broker=%s err=%s", _broker_label(broker), exc)
    for attr in ("broker_client", "broker", "active_broker"):
        if hasattr(apex, attr):
            try:
                setattr(apex, attr, broker)
            except Exception:
                pass


def _patch_trading_strategy_class(cls: type) -> None:
    if getattr(cls, "_nija_trade_cycle_convergence_patched", False):
        return

    original_adopt = getattr(cls, "adopt_existing_positions", None)
    if callable(original_adopt):
        def adopt_existing_positions(self: Any, *args: Any, **kwargs: Any):
            broker = kwargs.get("broker", args[0] if args else None)
            account_id = str(kwargs.get("account_id", "") or "")
            mapping = getattr(self, "_nija_adoption_brokers", None)
            if not isinstance(mapping, dict):
                mapping = {}
                setattr(self, "_nija_adoption_brokers", mapping)
            if account_id and broker is not None:
                mapping[account_id] = broker
            return original_adopt(self, *args, **kwargs)

        adopt_existing_positions._nija_adoption_broker_memory = True  # type: ignore[attr-defined]
        setattr(cls, "adopt_existing_positions", adopt_existing_positions)

    original_verify = getattr(cls, "verify_position_adoption_status", None)
    if callable(original_verify):
        def verify_position_adoption_status(
            self: Any,
            broker: Any = None,
            broker_name: str = "",
            account_id: str = "",
            *args: Any,
            **kwargs: Any,
        ) -> bool:
            if broker is None:
                mapping = getattr(self, "_nija_adoption_brokers", {})
                if isinstance(mapping, dict):
                    broker = mapping.get(account_id)
            if broker is None:
                broker = getattr(self, "broker", None)
            if broker is None:
                logger.error("POSITION_ADOPTION_VERIFY_NO_BROKER account=%s broker=%s", account_id, broker_name)
                return False
            return bool(original_verify(self, broker=broker, broker_name=broker_name, account_id=account_id))

        verify_position_adoption_status._nija_optional_broker_repair = True  # type: ignore[attr-defined]
        setattr(cls, "verify_position_adoption_status", verify_position_adoption_status)

    original_run_cycle = getattr(cls, "run_cycle", None)
    if not callable(original_run_cycle):
        return

    def run_cycle(self: Any, broker: Any = None, user_mode: bool = False, *args: Any, **kwargs: Any):
        selected_broker = broker if broker is not None else getattr(self, "broker", None)
        account = _broker_label(selected_broker)
        thread_id = threading.get_ident()
        cycle_lock, state_lock = _get_cycle_locks(self)

        with state_lock:
            owner_thread = getattr(self, "_nija_cycle_owner_thread", None)
            owner_account = getattr(self, "_nija_cycle_owner_account", "unknown")
        if owner_thread == thread_id:
            logger.critical(
                "CYCLE_OUTCOME=REENTRANT_SKIPPED account=%s owner_account=%s thread=%s",
                account,
                owner_account,
                thread_id,
            )
            return int(float(os.environ.get("NIJA_REENTRANT_CYCLE_RETRY_S", "5") or "5"))

        try:
            timeout_s = max(1.0, float(os.environ.get("NIJA_CYCLE_SERIALIZATION_TIMEOUT_S", "120") or "120"))
        except Exception:
            timeout_s = 120.0
        if not cycle_lock.acquire(timeout=timeout_s):
            logger.critical(
                "CYCLE_OUTCOME=CYCLE_LOCK_TIMEOUT account=%s timeout_s=%.1f owner_account=%s",
                account,
                timeout_s,
                owner_account,
            )
            return int(float(os.environ.get("NIJA_CYCLE_LOCK_TIMEOUT_RETRY_S", "10") or "10"))

        previous_context = getattr(_TLS, "cycle_context", None)
        previous_strategy_broker = getattr(self, "broker", None)
        apex = getattr(self, "apex", None)
        previous_apex_broker = getattr(apex, "broker_client", _MISSING) if apex is not None else _MISSING
        previous_balance = getattr(apex, "_last_account_balance", _MISSING) if apex is not None else _MISSING
        context: dict[str, Any] = {
            "account": account,
            "outcome": "NO_SIGNAL",
            "started_at": time.monotonic(),
            "execute_attempts": 0,
            "details": {},
        }
        _TLS.cycle_context = context
        with state_lock:
            setattr(self, "_nija_cycle_owner_thread", thread_id)
            setattr(self, "_nija_cycle_owner_account", account)

        effective_user_mode = bool(user_mode)
        if effective_user_mode and _truthy("NIJA_INDEPENDENT_USER_TRADING", True) and not _truthy("NIJA_COPY_TRADE_ENABLED", False):
            effective_user_mode = False
            logger.warning("USER_INDEPENDENT_AUTHORITY_AUTO_PROMOTED account=%s reason=copy_trading_disabled", account)

        balance = _cached_balance(selected_broker)
        if balance is None and selected_broker is not None and _truthy("NIJA_CYCLE_BALANCE_REFRESH_IF_UNCACHED", True):
            getter = getattr(selected_broker, "get_account_balance", None)
            if callable(getter):
                try:
                    balance = _cache_balance(selected_broker, getter())
                except Exception as exc:
                    logger.warning("ACCOUNT_BALANCE_CONTEXT_REFRESH_FAILED account=%s err=%s", account, exc)

        try:
            setattr(self, "broker", selected_broker)
            _set_apex_broker(apex, selected_broker)
            if apex is not None and balance is not None:
                setattr(apex, "_last_account_balance", float(balance))

            logger.critical(
                "CYCLE_SERIALIZATION_ACQUIRED account=%s balance=%s user_mode_requested=%s user_mode_effective=%s",
                account,
                f"${balance:.2f}" if balance is not None else "unknown",
                bool(user_mode),
                effective_user_mode,
            )
            logger.critical(
                "ACCOUNT_CAPITAL_AUTHORITY_ACTIVE account=%s source=broker_scoped balance=%s",
                account,
                f"${balance:.2f}" if balance is not None else "unknown",
            )
            return original_run_cycle(self, *args, broker=selected_broker, user_mode=effective_user_mode, **kwargs)
        except Exception as exc:
            _set_outcome("CYCLE_ERROR", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if context.get("outcome") == "NO_SIGNAL" and not (getattr(self, "symbols", None) or []):
                context["outcome"] = "NO_MARKETS_OR_DATA"
            elapsed = max(0.0, time.monotonic() - float(context["started_at"]))
            logger.critical(
                "CYCLE_OUTCOME=%s account=%s elapsed_s=%.3f execute_attempts=%d details=%s",
                context.get("outcome"),
                account,
                elapsed,
                int(context.get("execute_attempts", 0) or 0),
                context.get("details", {}),
            )

            if apex is not None and previous_balance is not _MISSING:
                try:
                    setattr(apex, "_last_account_balance", previous_balance)
                except Exception:
                    pass
            if previous_apex_broker is not _MISSING:
                _set_apex_broker(apex, previous_apex_broker)
            try:
                setattr(self, "broker", previous_strategy_broker)
            except Exception:
                pass
            _TLS.cycle_context = previous_context
            with state_lock:
                setattr(self, "_nija_cycle_owner_thread", None)
                setattr(self, "_nija_cycle_owner_account", "")
            cycle_lock.release()

    run_cycle._nija_trade_cycle_convergence = True  # type: ignore[attr-defined]
    setattr(cls, "run_cycle", run_cycle)
    cls._nija_trade_cycle_convergence_patched = True
    logger.warning("TRADING_STRATEGY_CYCLE_CONVERGENCE_PATCHED class=%s", cls.__name__)


def _patch_core_loop_class(cls: type) -> None:
    if getattr(cls, "_nija_cycle_outcome_patched", False):
        return
    original = getattr(cls, "run_scan_phase", None)
    if not callable(original):
        return

    def run_scan_phase(self: Any, *args: Any, **kwargs: Any):
        try:
            result = original(self, *args, **kwargs)
        except Exception as exc:
            _set_outcome("SCAN_ERROR", error=f"{type(exc).__name__}: {exc}")
            raise
        _set_outcome(
            classify_scan_result(result),
            symbols_scored=getattr(result, "symbols_scored", None),
            entries_taken=getattr(result, "entries_taken", None),
            entries_blocked=getattr(result, "entries_blocked", None),
            exits_taken=getattr(result, "exits_taken", None),
        )
        return result

    run_scan_phase._nija_cycle_outcome_patch = True  # type: ignore[attr-defined]
    setattr(cls, "run_scan_phase", run_scan_phase)
    cls._nija_cycle_outcome_patched = True
    logger.warning("CORE_LOOP_CYCLE_OUTCOME_PATCHED class=%s", cls.__name__)


def _patch_apex_class(cls: type) -> None:
    if getattr(cls, "_nija_execute_outcome_patched", False):
        return
    original = getattr(cls, "execute_action", None)
    if not callable(original):
        return

    def execute_action(self: Any, *args: Any, **kwargs: Any):
        context = _context()
        if context is not None:
            context["execute_attempts"] = int(context.get("execute_attempts", 0) or 0) + 1
        try:
            result = original(self, *args, **kwargs)
        except Exception as exc:
            _set_outcome("ORDER_FAILED", error=f"{type(exc).__name__}: {exc}")
            raise
        _set_outcome("ORDER_SUBMITTED" if _execution_succeeded(result) else "ORDER_FAILED")
        return result

    execute_action._nija_execute_outcome_patch = True  # type: ignore[attr-defined]
    setattr(cls, "execute_action", execute_action)
    cls._nija_execute_outcome_patched = True
    logger.warning("APEX_EXECUTE_OUTCOME_PATCHED class=%s", cls.__name__)


def _patch_independent_trader_class(cls: type) -> None:
    if getattr(cls, "_nija_cycle_balance_handoff_patched", False):
        return
    original = getattr(cls, "_execute_trading_cycle", None)
    if callable(original):
        def _execute_trading_cycle(self: Any, broker_type: Any, broker: Any, broker_name: str, cycle_count: int, balance: float):
            _cache_balance(broker, balance)
            return original(self, broker_type, broker, broker_name, cycle_count, balance)

        _execute_trading_cycle._nija_cycle_balance_handoff = True  # type: ignore[attr-defined]
        setattr(cls, "_execute_trading_cycle", _execute_trading_cycle)
    cls._nija_cycle_balance_handoff_patched = True
    logger.warning("INDEPENDENT_TRADER_BALANCE_HANDOFF_PATCHED class=%s", cls.__name__)


def _patch_module(module: ModuleType) -> None:
    name = str(getattr(module, "__name__", ""))
    key = (name, id(module))
    if key in _PATCHED_MODULES:
        return
    if name in {"bot.trading_strategy", "trading_strategy"}:
        cls = getattr(module, "TradingStrategy", None)
        if isinstance(cls, type):
            _patch_trading_strategy_class(cls)
    elif name in {"bot.nija_core_loop", "nija_core_loop"}:
        cls = getattr(module, "NijaCoreLoop", None)
        if isinstance(cls, type):
            _patch_core_loop_class(cls)
    elif name in {"bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"}:
        cls = getattr(module, "NIJAApexStrategyV71", None)
        if isinstance(cls, type):
            _patch_apex_class(cls)
    elif name in {"bot.independent_broker_trader", "independent_broker_trader"}:
        cls = getattr(module, "IndependentBrokerTrader", None)
        if isinstance(cls, type):
            _patch_independent_trader_class(cls)
    elif name in {"bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration"}:
        _patch_broker_module(module)
    _PATCHED_MODULES.add(key)


def _patch_loaded_modules() -> None:
    for name in (
        "bot.broker_manager",
        "broker_manager",
        "bot.broker_integration",
        "broker_integration",
        "bot.nija_apex_strategy_v71",
        "nija_apex_strategy_v71",
        "bot.nija_core_loop",
        "nija_core_loop",
        "bot.trading_strategy",
        "trading_strategy",
        "bot.independent_broker_trader",
        "independent_broker_trader",
    ):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("TRADE_CYCLE_CONVERGENCE_PATCH_FAILED module=%s err=%s", name, exc)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    os.environ["NIJA_INDEPENDENT_USER_CAPITAL_AUTHORITY"] = "true"
    os.environ["NIJA_INDEPENDENT_USER_TRADING"] = "true"
    os.environ["NIJA_COPY_TRADE_ENABLED"] = "false"
    os.environ.setdefault("NIJA_CYCLE_SERIALIZATION_TIMEOUT_S", "120")
    os.environ.setdefault("NIJA_CYCLE_BALANCE_REFRESH_IF_UNCACHED", "true")

    _patch_loaded_modules()
    if _ORIGINAL_IMPORT is not None:
        return
    _ORIGINAL_IMPORT = builtins.__import__
    hook_local = threading.local()

    def import_hook(name: str, globals: Any = None, locals: Any = None, fromlist: tuple = (), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        if getattr(hook_local, "active", False):
            return module
        hook_local.active = True
        try:
            _patch_loaded_modules()
        finally:
            hook_local.active = False
        return module

    builtins.__import__ = import_hook  # type: ignore[assignment]
    _patch_loaded_modules()
    logger.warning(
        "TRADE_CYCLE_CONVERGENCE_REPAIR_INSTALLED serialization=global account_balance=broker_scoped outcomes=deterministic"
    )


__all__ = ["classify_scan_result", "install_import_hook"]
