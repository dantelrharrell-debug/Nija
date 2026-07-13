"""Converge NIJA's live trading cycle onto one account-safe execution path.

This repair is deliberately narrow:

* serialize the shared ``TradingStrategy`` object so broker/APEX context cannot
  bleed between platform and user threads;
* reject true same-thread re-entry instead of recursively running the scanner;
* hydrate APEX with the selected broker's own cached balance for every cycle;
* auto-promote user cycles to independent signal generation when copy trading is
  disabled;
* make position-adoption verification recover the broker used by adoption;
* emit one deterministic ``CYCLE_OUTCOME`` record for every cycle;
* cache broker balance reads so user capital authority does not depend on the
  platform-only aggregate capital snapshot.

The patch is installed from ``usercustomize.py`` after ``sitecustomize.py`` has
finished loading the existing runtime overlays, so this is the final convergence
layer rather than another competing execution route.
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
_TLS = threading.local()
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}
_MISSING = object()

_OUTCOME_PRIORITY = {
    "NO_SCAN_RESULT": 0,
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
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _safe_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
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
    if parsed < 0 or parsed != parsed:
        return None
    return parsed


def _cache_balance(broker: Any, raw: Any) -> Optional[float]:
    balance = _safe_float(raw)
    if balance is None or broker is None:
        return balance
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
            value = getattr(broker, attr, None)
        except Exception:
            continue
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _broker_label(broker: Any) -> str:
    if broker is None:
        return "unknown"
    account = ""
    venue = ""
    for attr in ("account_id", "_account_id", "user_id", "account_name", "label"):
        try:
            value = getattr(broker, attr, None)
        except Exception:
            value = None
        if value:
            account = str(value).strip()
            break
    for attr in ("broker_name", "exchange_name", "name", "exchange", "venue"):
        try:
            value = getattr(broker, attr, None)
        except Exception:
            value = None
        if value:
            venue = str(getattr(value, "value", value)).strip()
            break
    if not venue:
        venue = type(broker).__name__.replace("Broker", "").strip() or "broker"
    if not account:
        account = "platform_or_unlabeled"
    return f"{account}:{venue}".lower().replace(" ", "_")


def _current_context() -> Optional[dict[str, Any]]:
    value = getattr(_TLS, "cycle_context", None)
    return value if isinstance(value, dict) else None


def _set_outcome(outcome: str, **details: Any) -> None:
    context = _current_context()
    if context is None:
        return
    current = str(context.get("outcome") or "NO_SCAN_RESULT")
    if _OUTCOME_PRIORITY.get(outcome, 0) >= _OUTCOME_PRIORITY.get(current, 0):
        context["outcome"] = outcome
    if details:
        context.setdefault("details", {}).update(details)


def _reason_text(result: Any) -> str:
    pieces: list[str] = []
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
    if isinstance(result, dict):
        for name in names:
            if name in result:
                pieces.append(str(result.get(name)))
    else:
        for name in names:
            try:
                value = getattr(result, name, None)
            except Exception:
                value = None
            if value:
                pieces.append(str(value))
    return " ".join(pieces).lower()


def classify_scan_result(result: Any) -> str:
    """Map a core-loop result to one stable terminal outcome."""
    reason = _reason_text(result)
    if "max position" in reason or "position cap" in reason or "no slot" in reason:
        return "MAX_POSITIONS_REACHED"
    if any(token in reason for token in ("insufficient cash", "insufficient balance", "not enough cash", "underfunded")):
        return "INSUFFICIENT_CASH"
    if "risk" in reason and any(token in reason for token in ("reject", "block", "veto", "denied")):
        return "RISK_REJECTED"
    if "pending order" in reason or "symbol lock" in reason or "order lock" in reason:
        return "PENDING_ORDER_BLOCKED"
    if "market closed" in reason:
        return "MARKET_CLOSED"

    def _count(name: str) -> int:
        try:
            value = result.get(name, 0) if isinstance(result, dict) else getattr(result, name, 0)
            return int(value or 0)
        except Exception:
            return 0

    entries = _count("entries_taken")
    exits = _count("exits_taken")
    scored = _count("symbols_scored")
    blocked = _count("entries_blocked")

    if entries > 0:
        return "ORDER_SUBMITTED"
    if exits > 0:
        return "EXIT_EXECUTED"
    if scored <= 0:
        return "NO_MARKETS_OR_DATA"
    if blocked > 0:
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
    original = cls.__dict__.get("get_account_balance")
    if not callable(original) or getattr(original, "_nija_balance_cache_patch", False):
        return

    def get_account_balance(self: Any, *args: Any, **kwargs: Any):
        result = original(self, *args, **kwargs)
        _cache_balance(self, result)
        return result

    get_account_balance._nija_balance_cache_patch = True  # type: ignore[attr-defined]
    setattr(cls, "get_account_balance", get_account_balance)


def _patch_broker_module(module: ModuleType) -> None:
    for value in list(vars(module).values()):
        if isinstance(value, type) and "broker" in value.__name__.lower():
            _patch_balance_method(value)


def _patch_trading_strategy_class(cls: type) -> None:
    if getattr(cls, "_nija_trade_cycle_convergence_patched", False):
        return

    original_adopt = getattr(cls, "adopt_existing_positions", None)
    if callable(original_adopt) and not getattr(original_adopt, "_nija_adoption_broker_memory", False):
        def adopt_existing_positions(self: Any, *args: Any, **kwargs: Any):
            broker = kwargs.get("broker", args[0] if args else None)
            account_id = str(kwargs.get("account_id", "") or "")
            mapping = getattr(self, "_nija_adoption_brokers", None)
            if not isinstance(mapping, dict):
                mapping = {}
                setattr(self, "_nija_adoption_brokers", mapping)
            if account_id and broker is not None:
                mapping[account_id] = broker
            result = original_adopt(self, *args, **kwargs)
            if account_id and broker is not None:
                mapping[account_id] = broker
            return result

        adopt_existing_positions._nija_adoption_broker_memory = True  # type: ignore[attr-defined]
        setattr(cls, "adopt_existing_positions", adopt_existing_positions)

    original_verify = getattr(cls, "verify_position_adoption_status", None)
    if callable(original_verify) and not getattr(original_verify, "_nija_optional_broker_repair", False):
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
                logger.error(
                    "POSITION_ADOPTION_VERIFY_NO_BROKER account=%s broker_name=%s",
                    account_id,
                    broker_name,
                )
                return False
            return bool(
                original_verify(
                    self,
                    broker=broker,
                    broker_name=broker_name,
                    account_id=account_id,
                )
            )

        verify_position_adoption_status._nija_optional_broker_repair = True  # type: ignore[attr-defined]
        setattr(cls, "verify_position_adoption_status", verify_position_adoption_status)

    original_run_cycle = getattr(cls, "run_cycle", None)
    if not callable(original_run_cycle):
        return

    def run_cycle(self: Any, broker: Any = None, user_mode: bool = False, *args: Any, **kwargs: Any):
        selected_broker = broker if broker is not None else getattr(self, "broker", None)
        account = _broker_label(selected_broker)
        thread_id = threading.get_ident()

        cycle_lock = getattr(self, "_nija_cycle_convergence_lock", None)
        if cycle_lock is None:
            cycle_lock = threading.Lock()
            setattr(self, "_nija_cycle_convergence_lock", cycle_lock)
        state_lock = getattr(self, "_nija_cycle_convergence_state_lock", None)
        if state_lock is None:
            state_lock = threading.Lock()
            setattr(self, "_nija_cycle_convergence_state_lock", state_lock)

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
        acquired = cycle_lock.acquire(timeout=timeout_s)
        if not acquired:
            logger.critical(
                "CYCLE_OUTCOME=CYCLE_LOCK_TIMEOUT account=%s timeout_s=%.1f owner_account=%s",
                account,
                timeout_s,
                owner_account,
            )
            return int(float(os.environ.get("NIJA_CYCLE_LOCK_TIMEOUT_RETRY_S", "10") or "10"))

        previous_context = getattr(_TLS, "cycle_context", None)
        previous_broker = getattr(self, "broker", None)
        apex = getattr(self, "apex", None)
        previous_balance = getattr(apex, "_last_account_balance", _MISSING) if apex is not None else _MISSING
        context: dict[str, Any] = {
            "account": account,
            "outcome": "NO_SCAN_RESULT",
            "started_at": time.monotonic(),
            "execute_attempts": 0,
            "details": {},
        }
        _TLS.cycle_context = context

        with state_lock:
            setattr(self, "_nija_cycle_owner_thread", thread_id)
            setattr(self, "_nija_cycle_owner_account", account)

        effective_user_mode = bool(user_mode)
        if (
            effective_user_mode
            and _truthy("NIJA_INDEPENDENT_USER_TRADING", True)
            and not _truthy("NIJA_COPY_TRADE_ENABLED", False)
        ):
            effective_user_mode = False
            logger.warning(
                "USER_INDEPENDENT_AUTHORITY_AUTO_PROMOTED account=%s reason=copy_trading_disabled",
                account,
            )

        balance = _cached_balance(selected_broker)
        if balance is None and selected_broker is not None and _truthy("NIJA_CYCLE_BALANCE_REFRESH_IF_UNCACHED", True):
            getter = getattr(selected_broker, "get_account_balance", None)
            if callable(getter):
                try:
                    balance = _cache_balance(selected_broker, getter())
                except Exception as exc:
                    logger.warning("ACCOUNT_BALANCE_CONTEXT_REFRESH_FAILED account=%s err=%s", account, exc)

        if selected_broker is not None:
            try:
                setattr(self, "broker", selected_broker)
            except Exception:
                pass
            if apex is not None:
                updater = getattr(apex, "update_broker_client", None)
                if callable(updater):
                    try:
                        updater(selected_broker)
                    except Exception as exc:
                        logger.warning("APEX_BROKER_CONTEXT_UPDATE_FAILED account=%s err=%s", account, exc)
        if apex is not None and balance is not None:
            try:
                setattr(apex, "_last_account_balance", float(balance))
            except Exception:
                pass

        logger.critical(
            "CYCLE_SERIALIZATION_ACQUIRED account=%s balance=%s user_mode_requested=%s user_mode_effective=%s",
            account,
            f"${balance:.2f}" if balance is not None else "unknown",
            bool(user_mode),
            effective_user_mode,
        )
        logger.critical(
            "ACCOUNT_CAPITAL_AUTHORITY_ACTIVE account=%s source=broker_scoped_cache balance=%s",
            account,
            f"${balance:.2f}" if balance is not None else "unknown",
        )

        try:
            return original_run_cycle(
                self,
                broker=selected_broker,
                user_mode=effective_user_mode,
                *args,
                **kwargs,
            )
        except Exception as exc:
            _set_outcome("CYCLE_ERROR", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            elapsed = max(0.0, time.monotonic() - float(context["started_at"]))
            outcome = str(context.get("outcome") or "NO_SCAN_RESULT")
            details = context.get("details") if isinstance(context.get("details"), dict) else {}
            logger.critical(
                "CYCLE_OUTCOME=%s account=%s elapsed_s=%.3f execute_attempts=%d details=%s",
                outcome,
                account,
                elapsed,
                int(context.get("execute_attempts", 0) or 0),
                details,
            )

            if apex is not None and previous_balance is not _MISSING:
                try:
                    setattr(apex, "_last_account_balance", previous_balance)
                except Exception:
                    pass
            try:
                setattr(self, "broker", previous_broker)
            except Exception:
                pass
            if apex is not None and previous_broker is not None and previous_broker is not selected_broker:
                updater = getattr(apex, "update_broker_client", None)
                if callable(updater):
                    try:
                        updater(previous_broker)
                    except Exception as exc:
                        logger.warning("APEX_BROKER_CONTEXT_RESTORE_FAILED account=%s err=%s", account, exc)

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
        outcome = classify_scan_result(result)
        _set_outcome(
            outcome,
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
        context = _current_context()
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
        def _execute_trading_cycle(
            self: Any,
            broker_type: Any,
            broker: Any,
            broker_name: str,
            cycle_count: int,
            balance: float,
        ):
            _cache_balance(broker, balance)
            return original(self, broker_type, broker, broker_name, cycle_count, balance)

        _execute_trading_cycle._nija_cycle_balance_handoff = True  # type: ignore[attr-defined]
        setattr(cls, "_execute_trading_cycle", _execute_trading_cycle)
    cls._nija_cycle_balance_handoff_patched = True
    logger.warning("INDEPENDENT_TRADER_BALANCE_HANDOFF_PATCHED class=%s", cls.__name__)


def _patch_hardening_module(module: ModuleType) -> None:
    original = getattr(module, "normalize_live_execution_env", None)
    if not callable(original) or getattr(original, "_nija_independent_authority_preserved", False):
        return

    def normalize_live_execution_env() -> None:
        original()
        os.environ["NIJA_INDEPENDENT_USER_CAPITAL_AUTHORITY"] = "true"
        os.environ["NIJA_INDEPENDENT_USER_TRADING"] = "true"
        os.environ["NIJA_COPY_TRADE_ENABLED"] = "false"

    normalize_live_execution_env._nija_independent_authority_preserved = True  # type: ignore[attr-defined]
    setattr(module, "normalize_live_execution_env", normalize_live_execution_env)
    normalize_live_execution_env()
    logger.warning(
        "INDEPENDENT_ACCOUNT_CAPITAL_AUTHORITY_ENABLED platform_aggregate_separated=true broker_scoped_cycles=true"
    )


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
    elif name in {"bot.live_execution_runtime_hardening_patch", "live_execution_runtime_hardening_patch"}:
        _patch_hardening_module(module)

    _PATCHED_MODULES.add(key)


def _patch_loaded_modules() -> None:
    target_names = (
        "bot.live_execution_runtime_hardening_patch",
        "live_execution_runtime_hardening_patch",
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
    )
    for name in target_names:
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

    def import_hook(name: str, globals: Any = None, locals: Any = None, fromlist: tuple = (), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        _patch_loaded_modules()
        return module

    builtins.__import__ = import_hook  # type: ignore[assignment]
    _patch_loaded_modules()
    logger.warning(
        "TRADE_CYCLE_CONVERGENCE_REPAIR_INSTALLED serialization=global account_balance=broker_scoped outcomes=deterministic"
    )


__all__ = [
    "classify_scan_result",
    "install_import_hook",
]
