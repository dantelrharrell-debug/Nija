"""Broker/account risk isolation v64.

Production on 2026-08-09 proved that a shared TradingStrategy/APEX instance was
bleeding broker-local state across independent broker threads.  A Coinbase
cycle with about $95 of equity was evaluated against an OKX-derived peak near
$145, so the system-wide drawdown breaker saw a false ~34% drawdown and wrote
EMERGENCY_STOP even though canonical CapitalAuthority held about $240 across
both funded platform brokers.

This patch is deliberately correctness-first:

* A shared TradingStrategy instance is serialized while one broker/account
  cycle owns its mutable APEX/CoreLoop state.  This prevents another broker
  thread from replacing ``apex.broker_client`` or ``_last_account_balance``
  halfway through a scan/order decision.
* The caller-selected broker is pinned before the cycle and its own hydrated
  balance is preferred over the shared APEX last-balance cache.
* Platform drawdown is evaluated only from a fresh canonical portfolio-equity
  snapshot from CapitalAuthority.  A broker-local balance is never compared to
  another platform broker's peak.
* User/account drawdown peaks are stored by canonical account identity and never
  fire the process-wide KillSwitch.  One user account cannot halt every other
  user or the NIJA platform account.
* Daily PnL used by the risk controller is isolated by the same account scope
  while the shared legacy APEX object remains in use.

The patch does NOT fabricate capital, clear an existing manual/drawdown kill
switch, bypass writer authority, relax risk thresholds, or force a trade.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Dict, Optional, Tuple

LOGGER = logging.getLogger("nija.broker_account_isolation_v64")
MARKER = "20260809-broker-account-risk-isolation-v64"

_INSTALL_LOCK = threading.RLock()
_CTX = threading.local()
_SCOPE_LOCK = threading.RLock()
_USER_SCOPE_STATE: Dict[str, Dict[str, float]] = {}
_SCOPE_DAILY_PNL: Dict[str, float] = {}
_PLATFORM_BREAKER: Any = None

_TS_PATCH_ATTR = "_nija_broker_account_isolation_v64"
_DRC_PATCH_ATTR = "_nija_scope_drawdown_isolation_v64"
_APEX_PATCH_ATTR = "_nija_scope_daily_pnl_isolation_v64"


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()


def _broker_name(broker: Any) -> str:
    if broker is None:
        return "unknown"
    broker_type = getattr(broker, "broker_type", None)
    raw = getattr(broker_type, "value", broker_type)
    name = _clean(raw)
    if name:
        return name
    return type(broker).__name__.replace("Broker", "").strip().lower() or "unknown"


def _account_id(broker: Any) -> str:
    for attr in ("account_identifier", "account_id", "user_id", "client_id"):
        raw = _clean(getattr(broker, attr, ""))
        if raw and raw not in {"none", "null"}:
            return raw
    return ""


def _scope_for_broker(broker: Any) -> Tuple[str, bool]:
    """Return (scope_id, is_platform_scope)."""
    name = _broker_name(broker)
    account = _account_id(broker)
    if not account or account in {"platform", name}:
        return "platform", True
    return f"account:{account}:{name}", False


def _finite_positive(value: Any) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return result if math.isfinite(result) and result > 0.0 else 0.0


def _canonical_platform_equity() -> Tuple[bool, float, int, str]:
    """Read fresh portfolio equity from canonical CapitalAuthority only."""
    module = None
    for name in ("bot.capital_authority", "capital_authority"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            break
    if not isinstance(module, ModuleType):
        try:
            module = importlib.import_module("bot.capital_authority")
        except Exception as exc:
            return False, 0.0, 0, f"capital_authority_unavailable:{type(exc).__name__}"

    getter = getattr(module, "get_capital_authority", None)
    if not callable(getter):
        return False, 0.0, 0, "capital_authority_getter_missing"
    try:
        authority = getter()
    except Exception as exc:
        return False, 0.0, 0, f"capital_authority_get_failed:{type(exc).__name__}"

    hydrated = bool(getattr(authority, "is_hydrated", False))
    stale = True
    stale_probe = getattr(authority, "is_stale", None)
    if callable(stale_probe):
        try:
            stale = bool(stale_probe())
        except Exception:
            stale = True
    else:
        stale = bool(getattr(authority, "stale", True))

    equity = 0.0
    real_capital = getattr(authority, "get_real_capital", None)
    if callable(real_capital):
        try:
            equity = _finite_positive(real_capital())
        except Exception:
            equity = 0.0
    if equity <= 0.0:
        for attr in ("real_capital", "total_capital", "total_balance", "balance"):
            equity = max(equity, _finite_positive(getattr(authority, attr, 0.0)))

    valid_brokers = 0
    for attr in ("registered_broker_count", "valid_broker_count"):
        try:
            valid_brokers = max(valid_brokers, int(getattr(authority, attr, 0) or 0))
        except (TypeError, ValueError):
            pass
    for attr in ("broker_balances", "_broker_balances", "balances"):
        values = getattr(authority, attr, None)
        if isinstance(values, dict):
            count = 0
            for value in values.values():
                if isinstance(value, dict):
                    candidates = (
                        value.get("trading_balance"),
                        value.get("total_funds"),
                        value.get("available"),
                        value.get("balance"),
                    )
                    amount = max((_finite_positive(v) for v in candidates), default=0.0)
                else:
                    amount = _finite_positive(value)
                if amount > 0.0:
                    count += 1
            valid_brokers = max(valid_brokers, count)

    if not hydrated:
        return False, equity, valid_brokers, "capital_not_hydrated"
    if stale:
        return False, equity, valid_brokers, "capital_snapshot_stale"
    if equity <= 0.0:
        return False, equity, valid_brokers, "capital_nonpositive"
    if valid_brokers <= 0:
        return False, equity, valid_brokers, "valid_broker_count_zero"
    return True, equity, valid_brokers, "canonical_capital_authority"


def _level_from_drawdown(drawdown_pct: float) -> Tuple[str, float, bool]:
    if drawdown_pct >= 20.0:
        return "HALT", 0.0, True
    if drawdown_pct >= 15.0:
        return "DANGER", 0.25, False
    if drawdown_pct >= 10.0:
        return "WARNING", 0.50, False
    if drawdown_pct >= 5.0:
        return "CAUTION", 0.75, False
    return "CLEAR", 1.0, False


def _user_scope_drawdown(scope: str, equity: float) -> Tuple[str, float, bool, str]:
    """Account-local drawdown.  Never activates the process-wide KillSwitch."""
    if equity <= 0.0:
        return "UNKNOWN", 0.0, True, f"account drawdown blocked: nonpositive equity scope={scope}"
    with _SCOPE_LOCK:
        state = _USER_SCOPE_STATE.setdefault(scope, {"peak": equity, "current": equity})
        peak = max(_finite_positive(state.get("peak")), equity)
        state["peak"] = peak
        state["current"] = equity
    drawdown_pct = max(0.0, ((peak - equity) / peak) * 100.0) if peak > 0.0 else 0.0
    level, mult, halted = _level_from_drawdown(drawdown_pct)
    if halted:
        LOGGER.critical(
            "ACCOUNT_DRAWDOWN_V64_HALT marker=%s scope=%s drawdown_pct=%.2f equity=%.2f peak=%.2f "
            "global_kill_switch=false isolated=true",
            MARKER,
            scope,
            drawdown_pct,
            equity,
            peak,
        )
    return level, mult, halted, (
        f"AccountDrawdown scope={scope} drawdown={drawdown_pct:.1f}%"
        if halted
        else ""
    )


def _platform_scope_drawdown(account_balance: float) -> Tuple[str, float, bool, str]:
    """Use canonical aggregate equity; never substitute one broker's balance."""
    global _PLATFORM_BREAKER
    ok, equity, valid_brokers, reason = _canonical_platform_equity()
    if not ok:
        LOGGER.error(
            "PLATFORM_DRAWDOWN_V64_BLOCKED marker=%s reason=%s broker_balance=%.2f "
            "canonical_equity=%.2f valid_brokers=%d action=block_entries_no_kill_switch",
            MARKER,
            reason,
            float(account_balance or 0.0),
            equity,
            valid_brokers,
        )
        return "UNKNOWN", 0.0, True, f"canonical portfolio equity unavailable:{reason}"

    with _SCOPE_LOCK:
        if _PLATFORM_BREAKER is None:
            try:
                module = importlib.import_module("bot.global_drawdown_circuit_breaker")
            except ImportError:
                module = importlib.import_module("global_drawdown_circuit_breaker")
            cls = getattr(module, "GlobalDrawdownCircuitBreaker")
            _PLATFORM_BREAKER = cls()
            _PLATFORM_BREAKER.initialise(starting_equity=equity)
        breaker = _PLATFORM_BREAKER

    decision = breaker.update_equity(equity)
    level = str(getattr(getattr(decision, "level", "CLEAR"), "value", getattr(decision, "level", "CLEAR")))
    level = level.split(".")[-1].upper()
    LOGGER.info(
        "PLATFORM_DRAWDOWN_V64_EVALUATED marker=%s canonical_equity=%.2f broker_balance_ignored=%.2f "
        "valid_brokers=%d level=%s drawdown_pct=%.2f",
        MARKER,
        equity,
        float(account_balance or 0.0),
        valid_brokers,
        level,
        float(getattr(decision, "drawdown_pct", 0.0) or 0.0),
    )
    if not bool(getattr(decision, "allow_new_entries", True)):
        return level, 0.0, True, (
            f"Platform portfolio drawdown halted: {float(getattr(decision, 'drawdown_pct', 0.0) or 0.0):.1f}%"
        )
    return level, float(getattr(decision, "position_size_multiplier", 1.0) or 1.0), False, ""


def _patch_drawdown_module(module: ModuleType) -> bool:
    cls = getattr(module, "DrawdownRiskController", None)
    if not isinstance(cls, type):
        return False
    original_layer = getattr(cls, "_layer_drawdown", None)
    original_pre = getattr(cls, "pre_entry_check", None)
    if not callable(original_layer) or not callable(original_pre):
        return False
    if getattr(original_layer, _DRC_PATCH_ATTR, False):
        return True

    @wraps(original_layer)
    def _layer_drawdown_scoped(self: Any, account_balance: float):
        scope = str(getattr(_CTX, "scope", "") or "").strip()
        if not scope:
            return original_layer(self, account_balance)
        if scope == "platform":
            return _platform_scope_drawdown(account_balance)
        return _user_scope_drawdown(scope, float(account_balance or 0.0))

    @wraps(original_pre)
    def _pre_entry_scoped(
        self: Any,
        account_balance: float,
        df: Any,
        indicators: Dict[str, Any],
        daily_pnl_usd: float = 0.0,
        regime: Any = None,
        daily_loss_limit_pct: Optional[float] = None,
    ):
        scope = str(getattr(_CTX, "scope", "") or "").strip()
        if scope:
            with _SCOPE_LOCK:
                daily_pnl_usd = float(_SCOPE_DAILY_PNL.get(scope, 0.0) or 0.0)
        return original_pre(
            self,
            account_balance=account_balance,
            df=df,
            indicators=indicators,
            daily_pnl_usd=daily_pnl_usd,
            regime=regime,
            daily_loss_limit_pct=daily_loss_limit_pct,
        )

    setattr(_layer_drawdown_scoped, _DRC_PATCH_ATTR, True)
    setattr(cls, "_layer_drawdown", _layer_drawdown_scoped)
    setattr(cls, "pre_entry_check", _pre_entry_scoped)
    LOGGER.critical(
        "BROKER_ACCOUNT_RISK_V64_DRAWDOWN_PATCHED marker=%s module=%s "
        "platform_equity=canonical user_kill_switch=false scope_daily_pnl=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_apex_module(module: ModuleType) -> bool:
    cls = getattr(module, "NIJAApexStrategyV71", None)
    if not isinstance(cls, type):
        return False
    method = getattr(cls, "_update_safe_profit_mode", None)
    if not callable(method) or getattr(method, _APEX_PATCH_ATTR, False):
        return bool(getattr(method, _APEX_PATCH_ATTR, False))

    @wraps(method)
    def _update_scope_profit(self: Any, trade_pnl_usd: float) -> None:
        scope = str(getattr(_CTX, "scope", "") or "").strip()
        if not scope:
            return method(self, trade_pnl_usd)
        with _SCOPE_LOCK:
            starting = float(_SCOPE_DAILY_PNL.get(scope, 0.0) or 0.0)
        previous = float(getattr(self, "_daily_pnl_usd", 0.0) or 0.0)
        setattr(self, "_daily_pnl_usd", starting)
        try:
            method(self, trade_pnl_usd)
            updated = float(getattr(self, "_daily_pnl_usd", starting) or starting)
            with _SCOPE_LOCK:
                _SCOPE_DAILY_PNL[scope] = updated
        finally:
            setattr(self, "_daily_pnl_usd", previous)

    setattr(_update_scope_profit, _APEX_PATCH_ATTR, True)
    setattr(cls, "_update_safe_profit_mode", _update_scope_profit)
    LOGGER.critical(
        "BROKER_ACCOUNT_RISK_V64_PNL_PATCHED marker=%s module=%s scope_daily_pnl=true",
        MARKER,
        module.__name__,
    )
    return True


def _broker_local_balance(strategy: Any, broker: Any) -> float:
    if broker is None:
        return 0.0
    helper = getattr(strategy, "_broker_entry_balance", None)
    if callable(helper):
        try:
            value = _finite_positive(helper(broker))
            if value > 0.0:
                return value
        except Exception:
            pass
    for attr in ("_last_known_balance", "last_known_balance", "cached_balance", "balance"):
        value = _finite_positive(getattr(broker, attr, 0.0))
        if value > 0.0:
            return value
    return 0.0


def _patch_trading_strategy_module(module: ModuleType) -> bool:
    cls = getattr(module, "TradingStrategy", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "run_cycle", None)
    if not callable(original) or getattr(original, _TS_PATCH_ATTR, False):
        return bool(getattr(original, _TS_PATCH_ATTR, False))

    @wraps(original)
    def _isolated_run_cycle(self: Any, broker: Any = None, user_mode: bool = False) -> int:
        lock = getattr(self, "_nija_shared_strategy_cycle_lock_v64", None)
        if lock is None:
            with _INSTALL_LOCK:
                lock = getattr(self, "_nija_shared_strategy_cycle_lock_v64", None)
                if lock is None:
                    lock = threading.RLock()
                    setattr(self, "_nija_shared_strategy_cycle_lock_v64", lock)

        wait_started = time.monotonic()
        with lock:
            wait_s = max(0.0, time.monotonic() - wait_started)
            scope, is_platform = _scope_for_broker(broker)
            previous_scope = getattr(_CTX, "scope", "")
            previous_broker = getattr(_CTX, "broker", None)
            _CTX.scope = scope
            _CTX.broker = broker

            apex = getattr(self, "apex", None)
            local_balance = _broker_local_balance(self, broker)
            previous_balance = getattr(apex, "_last_account_balance", None) if apex is not None else None
            previous_broker_client = getattr(apex, "broker_client", None) if apex is not None else None
            previous_strategy_broker = getattr(self, "broker", None)
            if broker is not None:
                setattr(self, "broker", broker)
            if apex is not None and broker is not None:
                updater = getattr(apex, "update_broker_client", None)
                if callable(updater):
                    updater(broker)
                else:
                    setattr(apex, "broker_client", broker)
                engine = getattr(apex, "execution_engine", None)
                if engine is not None and hasattr(engine, "broker_client"):
                    setattr(engine, "broker_client", broker)
            if apex is not None and local_balance > 0.0:
                setattr(apex, "_last_account_balance", local_balance)

            LOGGER.critical(
                "BROKER_ACCOUNT_CYCLE_V64_ENTER marker=%s scope=%s platform=%s broker=%s "
                "broker_balance=%.2f lock_wait_s=%.3f shared_strategy_serialized=true",
                MARKER,
                scope,
                str(is_platform).lower(),
                _broker_name(broker),
                local_balance,
                wait_s,
            )
            try:
                return int(original(self, broker=broker, user_mode=user_mode))
            finally:
                # Restore ambient mutable aliases so non-cycle background tasks do
                # not inherit the identity of the last account that happened to run.
                if apex is not None:
                    if previous_broker_client is not None:
                        updater = getattr(apex, "update_broker_client", None)
                        if callable(updater):
                            updater(previous_broker_client)
                        else:
                            setattr(apex, "broker_client", previous_broker_client)
                    if previous_balance is not None:
                        setattr(apex, "_last_account_balance", previous_balance)
                setattr(self, "broker", previous_strategy_broker)
                _CTX.scope = previous_scope
                _CTX.broker = previous_broker
                LOGGER.info(
                    "BROKER_ACCOUNT_CYCLE_V64_EXIT marker=%s scope=%s broker=%s",
                    MARKER,
                    scope,
                    _broker_name(broker),
                )

    setattr(_isolated_run_cycle, _TS_PATCH_ATTR, True)
    setattr(cls, "run_cycle", _isolated_run_cycle)
    LOGGER.critical(
        "BROKER_ACCOUNT_CYCLE_V64_PATCHED marker=%s module=%s shared_strategy_serialized=true "
        "broker_balance_source=broker_local",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        try:
            if name in {"bot.drawdown_risk_controller", "drawdown_risk_controller"}:
                changed = _patch_drawdown_module(module) or changed
            elif name in {"bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"}:
                changed = _patch_apex_module(module) or changed
            elif name in {"bot.trading_strategy", "trading_strategy"}:
                changed = _patch_trading_strategy_module(module) or changed
        except Exception as exc:
            LOGGER.warning(
                "BROKER_ACCOUNT_ISOLATION_V64_PATCH_ERROR marker=%s module=%s error=%s:%s",
                MARKER,
                name,
                type(exc).__name__,
                exc,
            )
    return changed


def install_import_hook() -> bool:
    with _INSTALL_LOCK:
        _patch_loaded()
        flag = "_NIJA_BROKER_ACCOUNT_ISOLATION_V64_IMPORT_HOOK"
        if getattr(builtins, flag, False):
            return True
        original_import = builtins.__import__

        @wraps(original_import)
        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            module = original_import(name, globals, locals, fromlist, level)
            if any(
                token in str(name)
                for token in ("trading_strategy", "nija_apex_strategy_v71", "drawdown_risk_controller")
            ):
                _patch_loaded()
            return module

        builtins.__import__ = guarded_import
        setattr(builtins, flag, True)
        os.environ["NIJA_BROKER_ACCOUNT_ISOLATION_V64_INSTALLED"] = "1"
        LOGGER.critical(
            "BROKER_ACCOUNT_ISOLATION_V64_INSTALLED marker=%s fail_closed=true "
            "platform_drawdown=canonical account_kill_switch=false shared_strategy_serialized=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_platform_equity",
    "_scope_for_broker",
    "_user_scope_drawdown",
    "_platform_scope_drawdown",
    "_patch_drawdown_module",
    "_patch_trading_strategy_module",
]
